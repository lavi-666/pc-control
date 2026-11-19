"""
PC Control — Сервер дистанционного управления ПК с телефона.
Запускать на компьютере, который нужно контролировать удалённо.
"""

import sys

# COM в режиме MTA — ДО первого импорта comtypes (он инициализирует COM в импортирующем потоке).
# Раньше comtypes впервые импортировался в рабочем потоке (медиамонитор/запрос), и тот по умолчанию
# становился ГЛАВНЫМ STA процесса без цикла сообщений. Вызовы объектов COM/UIA/WinRT из других
# потоков ставились в его очередь, которую никто не разбирал, и навсегда занимали потоки пула
# Windows: сервер терял до ~45 потоков в минуту (сотни за час). В MTA для объектов, которым нужен
# STA, COM сам создаёт служебный поток с циклом сообщений.
sys.coinit_flags = 0  # COINIT_MULTITHREADED

import json
import hashlib
import logging
import os
import platform
import secrets
import socket
import threading
import time
import sys
from pathlib import Path
from flask import Flask, Request, Response, jsonify, request, send_file, make_response, send_from_directory, g, has_request_context
import collections
import re

from core.config import (
    BASE_DIR,
    LOGS_DIR,
    WEB_INDEX_FILE,
    is_safe_test_mode,
    set_safe_test_mode,
    get_auth_token,
    load_app_config,
    update_auth_token,
    get_cors_allowed_origins,
    update_cors_origins,
    cors_pattern_too_broad,
)
from core.auth import (
    check_token,
    is_locked,
    get_lockout_remaining,
    register_failure,
    clear_lockout,
    is_private_ip,
    get_msg,
    detect_language,
    create_pairing_ticket,
    redeem_pairing_ticket,
    is_valid_pairing_ticket,
    current_session_id,
    legacy_password_allowed,
    password_matches,
)
from core import sessions
from core.logger import get_history, log_action, log_error
from modules.system import system_bp, _attach_input_desktop
from modules.volume import volume_bp
from modules.power import power_bp
from modules.streaming import streaming_bp
# Медиаплеер: новый движок (tools/media_helper.exe + расширение Chrome) или прежний modules/media.py
from modules.player import select_media_blueprint
media_bp = select_media_blueprint()
from modules.presets import presets_bp
from modules.input_controller import input_bp

# Безопасный парсинг JSON с защитой от UTF-8 BOM и обрывов соединения
_orig_get_json = Request.get_json
def _safe_get_json(self, *args, **kwargs):
    from werkzeug.exceptions import RequestEntityTooLarge
    silent = kwargs.get("silent", False)
    try:
        res = _orig_get_json(self, *args, **kwargs)
    except RequestEntityTooLarge:
        raise
    except Exception:
        if silent:
            return None
        raise
    if res is None:
        try:
            raw = self.get_data()
            if raw and raw.startswith(b"\xef\xbb\xbf"):
                return json.loads(raw.decode("utf-8-sig"))
        except Exception:
            pass
    return res
Request.get_json = _safe_get_json

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024


class _RedactSecretsFilter(logging.Filter):
    """Маскирует пароль в журнале запросов: видео/звук передают ?token=… в URL, и werkzeug
    записывал пароль открытым текстом в logs/server_stderr.log."""
    # Также внутри вложенной ссылки (/api/qr?url=…%3Ftoken%3D<пароль>%26…): раньше там пароль
    # оставался в журнале открытым текстом.
    _re = re.compile(r"((?:token|ticket|password)(?:=|%3D|%253D))(.+?)(?=&|%26|%2526|\s|\"|'|$)", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            red = self._re.sub(r"\1***", msg)
            if red != msg:
                record.msg = red
                record.args = ()
        except Exception:
            pass
        return True


logging.getLogger("werkzeug").addFilter(_RedactSecretsFilter())

# Measurements (QA): every request with its duration in ms → logs/requests.log (rotated 3 × 2 MB).
# Passwords / tickets in URLs are masked by _RedactSecretsFilter; headers are not logged.
_req_log = logging.getLogger("pcc.requests")
_req_log.propagate = False
_req_log.setLevel(logging.INFO)
_req_log.addFilter(_RedactSecretsFilter())
try:
    from logging.handlers import RotatingFileHandler
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _rh = RotatingFileHandler(LOGS_DIR / "requests.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    _rh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", "%Y-%m-%d %H:%M:%S"))
    _req_log.addHandler(_rh)
except Exception:
    pass


@app.before_request
def _request_timer_start():
    g.pcc_t0 = time.perf_counter()


def _log_request(resp):
    try:
        t0 = getattr(g, "pcc_t0", None)
        ms = (time.perf_counter() - t0) * 1000 if t0 is not None else -1
        rid = request.headers.get("X-Request-Id") or "-"
        qs = request.query_string.decode("utf-8", "replace") if request.query_string else ""
        _req_log.info("%s %s %s%s %s %.1fms rid=%s%s", request.remote_addr, request.method, request.path,
                      ("?" + qs) if qs else "", resp.status_code, ms, rid[:64],
                      " streamed" if resp.is_streamed else "")
    except Exception:
        pass

# Регистрация функциональных модулей через Blueprints
app.register_blueprint(volume_bp)
app.register_blueprint(power_bp)
app.register_blueprint(system_bp)
app.register_blueprint(streaming_bp)
app.register_blueprint(media_bp)
app.register_blueprint(presets_bp)
app.register_blueprint(input_bp)


@app.errorhandler(Exception)
def handle_any_error(e):
    """Подстраховка на случай необработанного исключения в любом роуте —
    возвращаем понятный JSON вместо стандартной HTML-страницы Flask."""
    from werkzeug.exceptions import HTTPException

    if isinstance(e, HTTPException):
        return jsonify({"message": e.description or get_msg("bad_request")}), e.code

    log_error("unhandled", e)
    return jsonify({"message": get_msg("internal_error")}), 500


def _is_origin_allowed(origin: str, remote_addr: str) -> bool:
    if not origin:
        return True
    origin_clean = origin.strip().lower()
    # QA R-2: "null" / "file://" / "capacitor://localhost" / "http://pccontrol.local" were always
    # allowed (a WebView legacy; the native app sends no Origin). Any site could read the replies of
    # private-network endpoints from a sandboxed iframe (Origin: null) — they are refused now.

    # 1. Проверяем гибкий список разрешённых origins из config.json
    import fnmatch
    allowed_patterns = get_cors_allowed_origins()
    try:
        import ipaddress
        from urllib.parse import urlparse
        parsed = urlparse(origin_clean)
        host = (parsed.hostname or "").strip().lower()
        if (not host or parsed.scheme not in ("http", "https") or parsed.username
                or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            return False
        # Same-origin requests must keep working even with an empty CORS list.
        if origin_clean.rstrip("/") == request.host_url.rstrip("/").lower():
            return True
        for pattern in allowed_patterns:
            pat_clean = pattern.strip().lower()
            if cors_pattern_too_broad(pat_clean):
                continue  # QA R-17: "*" would allow every site together with credentials
            pattern_host = urlparse(pat_clean if "://" in pat_clean else "http://" + pat_clean).hostname or ""
            # A numeric wildcard is an IP pattern, never a domain prefix.
            if re.match(r"^\d+\.", pattern_host) and "*" in pattern_host:
                try:
                    ipaddress.IPv4Address(host)
                except ValueError:
                    continue
            target = origin_clean if "://" in pat_clean else host
            if pat_clean and fnmatch.fnmatchcase(target, pat_clean):
                return True
    except Exception:
        pass
    return False


# X-Request-Id: веб-пульт (app.js) добавляет его к каждому POST для защиты от повторов.
# Без него в списке браузер/WebView отменял ВСЕ POST с другого origin (APK, Tailscale):
# preflight OPTIONS проходил, а сама команда (плеер, громкость, /action) не отправлялась.
_CORS_ALLOW_HEADERS = "Content-Type, X-Auth-Token, Authorization, X-Request-Id"


def _apply_cors_and_security_headers(resp):
    origin = request.headers.get("Origin")
    if origin:
        if _is_origin_allowed(origin, request.remote_addr):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = _CORS_ALLOW_HEADERS
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Max-Age"] = "600"
            resp.vary.add("Origin")
    else:
        if request.remote_addr in ("127.0.0.1", "::1"):  # QA A-9: not for every client in test mode
            resp.headers["Access-Control-Allow-Origin"] = "*"
        else:
            resp.headers["Access-Control-Allow-Origin"] = request.host_url.rstrip("/")
        resp.headers["Access-Control-Allow-Headers"] = _CORS_ALLOW_HEADERS
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

    # Защитные заголовки
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # Встраивать страницу может только сам сервер и панель управления на этом ПК (127.0.0.1/localhost).
    # Шаблоны «http://192.168.*» и т. п. недопустимы в CSP (браузер их игнорировал и писал 4 ошибки
    # в консоль на каждой загрузке страницы) — убраны, поведение не меняется.
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*;"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@app.before_request
def _ensure_interactive_desktop():
    if request.is_json:
        payload = request.get_json(silent=True)
        if payload is not None and not isinstance(payload, dict):
            return jsonify({"message": get_msg("bad_request")}), 400
    raw_query = request.query_string.decode("utf-8", errors="ignore") if request.query_string else ""
    if "\x00" in request.path or "\x00" in raw_query or "%00" in raw_query.lower() or "%00" in request.path.lower():
        return jsonify({"message": get_msg("null_byte")}), 400
    if ".." in request.path or "%2e%2e" in request.path.lower():
        return jsonify({"message": get_msg("path_traversal")}), 404

    if platform.system() == "Windows":
        _attach_input_desktop()

    # Дедупликация повторных POST/PUT запросов с тем же X-Request-Id (только для мутирующих команд)
    # ИСКЛЮЧЕНЫ: WebRTC, видео/аудио стримы, высокочастотные события мыши и клавиатуры
    req_id = request.headers.get("X-Request-Id")
    if req_id and request.method in ("POST", "PUT", "DELETE", "PATCH"):
        p = request.path
        if not p.startswith(("/webrtc/", "/screen/", "/audio", "/api/mouse", "/api/keyboard", "/keyboard/", "/api/mic")):
            cached = check_idempotency_request(req_id)
            if cached is not None:
                if cached.get("error"):
                    return jsonify({"ok": False, "message": cached["message"]}), cached["status"]
                c_resp = make_response(cached["body"], cached["status"])
                c_resp.headers["Content-Type"] = cached.get("content_type", "application/json")
                c_resp.headers["X-Idempotent-Replay"] = "1"
                return _apply_cors_and_security_headers(c_resp)

    if request.method == "OPTIONS":
        origin = request.headers.get("Origin")
        if origin and not _is_origin_allowed(origin, request.remote_addr):
            resp = Response(
                json.dumps({"message": get_msg("cors_forbidden")}),
                status=403,
                mimetype="application/json"
            )
            return resp
        resp = Response(status=204)
        return _apply_cors_and_security_headers(resp)


def _translate_json_reply(resp):
    """QA T-1: user-facing message fields of JSON replies in the client's language (core/server_i18n.py)."""
    try:
        if resp.is_streamed or resp.mimetype != "application/json" or resp.content_length is None \
                or resp.content_length > 256 * 1024:
            return
        lang = detect_language()
        if lang == "ru":
            return
        data = resp.get_json(silent=True)
        if not isinstance(data, dict):
            return
        from core.server_i18n import translate_reply
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        translate_reply(data, lang)
        if json.dumps(data, ensure_ascii=False, sort_keys=True) != before:
            resp.set_data(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


@app.after_request
def _add_cors_headers(resp):
    _translate_json_reply(resp)
    _log_request(resp)
    primary_key = getattr(g, "idempotency_cache_key", None)
    if primary_key:
        content_type = resp.headers.get("Content-Type", "application/json")
        store_idempotency_completion(primary_key, resp.status_code, resp.get_data(), content_type)
    return _apply_cors_and_security_headers(resp)


@app.teardown_request
def _cleanup_failed_idempotency(exc=None):
    if exc is not None:
        primary_key = getattr(g, "idempotency_cache_key", None)
        if primary_key:
            store_idempotency_completion(primary_key, 500, b"", "application/json")


PAGE = WEB_INDEX_FILE.read_text(encoding="utf-8") if WEB_INDEX_FILE.exists() else "<h1>PC Control Server Online</h1>"


@app.route("/")
def index():
    if WEB_INDEX_FILE.exists():
        content = WEB_INDEX_FILE.read_text(encoding="utf-8")
    else:
        content = PAGE

    cfg = load_app_config() or {}
    port = cfg.get("port", 5000)
    relay_port = cfg.get("relay_port", 5050)
    lan_ip = cfg.get("lan_ip") or get_local_ip()
    vpn_ip = cfg.get("vpn_ip", "")
    wol_relay_ip = cfg.get("wol_relay_ip", "")
    mac_addr = cfg.get("mac_address", "")

    # Динамическая подстановка ТОЛЬКО сетевых адресов сервера из config.json.
    # Пароль (DEFAULT_APP_TOKEN) НИКОГДА не вставляется в открытый HTML ради безопасности.
    try:
        content = re.sub(
            r"const\s+DEFAULT_APP_TOKEN\s*=\s*['\"][^'\"]*['\"];",
            "const DEFAULT_APP_TOKEN = '';",
            content,
            count=1
        )
        if lan_ip:
            lan_url = f"http://{lan_ip}:{port}"
            content = re.sub(
                r"const\s+DEFAULT_LAN_HOST\s*=\s*['\"][^'\"]*['\"];",
                f"const DEFAULT_LAN_HOST = {json.dumps(lan_url)};",
                content,
                count=1
            )
        if vpn_ip:
            vpn_url = f"http://{vpn_ip}:{port}"
            content = re.sub(
                r"const\s+DEFAULT_VPN_HOST\s*=\s*['\"][^'\"]*['\"];",
                f"const DEFAULT_VPN_HOST = {json.dumps(vpn_url)};",
                content,
                count=1
            )
        if wol_relay_ip:
            relay_url = f"http://{wol_relay_ip}:{relay_port}"
            content = re.sub(
                r"const\s+DEFAULT_WOL_RELAY\s*=\s*['\"][^'\"]*['\"];",
                f"const DEFAULT_WOL_RELAY = {json.dumps(relay_url)};",
                content,
                count=1
            )
        if mac_addr:
            content = re.sub(
                r"const\s+PC_MAC_ADDRESS\s*=\s*['\"][^'\"]*['\"];",
                f"const PC_MAC_ADDRESS = {json.dumps(mac_addr)};",
                content,
                count=1
            )
    except Exception:
        pass

    resp = make_response(content)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    # Никакой автоматической установки cookie с паролем без авторизации!
    return resp


def _local_test_mode() -> bool:
    """Тестовый режим ослабляет проверку пароля только для запросов с этого же ПК.
    Раньше при включённом тестовом режиме (его включает POST /api/safe_mode) любое устройство
    сети без пароля скачивало APK (в нём пароль), QR-код и сетевые данные ПК."""
    return is_safe_test_mode() and request.remote_addr in ("127.0.0.1", "::1")


def get_local_ip() -> str:
    try:
        from scripts.network_setup import get_best_lan_ip
        best = get_best_lan_ip()
        if best and best != "127.0.0.1":
            return best
    except Exception:
        pass
    for target in ('10.255.255.255', '192.168.1.1', '192.168.0.1', '172.16.0.1'):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 1))
                ip = s.getsockname()[0]
                if ip and ip != "127.0.0.1":
                    return ip
        except Exception:
            pass
    return ""


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Безопасная точка входа для авторизации с защитой от перебора (rate-limiting)."""
    ip = request.remote_addr or "unknown"
    if is_locked(ip):
        rem = get_lockout_remaining(ip)
        return jsonify({
            "ok": False,
            "message": get_msg("locked_out", sec=rem),
            "retry_after": rem
        }), 429

    data = request.get_json(silent=True) or {}
    pwd = str(data.get("password") or data.get("token") or "").strip()
    if not pwd:
        # Также проверяем заголовок X-Auth-Token
        pwd = (request.headers.get("X-Auth-Token") or "").strip()

    if password_matches(pwd):
        clear_lockout(ip)
        # Plan 5.2: every login gets its own revocable device token ("session"). "token" still
        # echoes the password for old clients that store it (they keep sending the password,
        # accepted while legacy_password_auth is on).
        session_token, rec = sessions.create(_device_name(data), ip, "password")
        log_action("session_created", {"id": rec["id"], "name": rec["name"], "kind": "password"})
        resp = jsonify({
            "ok": True,
            "message": get_msg("login_success"),
            "token": pwd,
            "session": session_token,
            "session_id": rec["id"],
            "expires_in": sessions.IDLE_EXPIRY,
        })
        resp.set_cookie(
            "pc_token",
            session_token,
            max_age=sessions.IDLE_EXPIRY,
            path="/",
            httponly=True,
            samesite="Strict"
        )
        return resp

    register_failure(ip)
    rem = get_lockout_remaining(ip)
    if rem > 0:
        return jsonify({
            "ok": False,
            "message": get_msg("locked_out", sec=rem),
            "retry_after": rem
        }), 429
    return jsonify({"ok": False, "message": get_msg("invalid_token")}), 401


@app.route("/api/auth/verify", methods=["GET", "POST"])
def api_auth_verify():
    """Проверка валидности текущей сессии/токена."""
    if check_token():
        return jsonify({"authenticated": True, "status": "ok"})
    return jsonify({"authenticated": False, "message": get_msg("auth_required")}), 401


@app.route("/api/auth/rotate", methods=["POST"])
def api_auth_rotate():
    """Ротация токена доступа. Требует авторизации с текущим токеном."""
    if not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401

    data = request.get_json(silent=True) or {}
    custom_token = str(data.get("new_token") or "").strip()
    if custom_token:
        from core.auth import MIN_PASSWORD_LEN
        if len(custom_token) < MIN_PASSWORD_LEN:  # QA A-8: was 4
            return jsonify({"ok": False, "message": f"Токен должен содержать минимум {MIN_PASSWORD_LEN} символов"}), 400
        new_token = custom_token
    else:
        new_token = secrets.token_hex(8)

    ok = update_auth_token(new_token)
    if not ok:
        return jsonify({"ok": False, "message": get_msg("internal_error")}), 500

    revoked = sessions.revoke(all_sessions=True) if data.get("revoke_sessions") else 0
    log_action("token_rotate", {"by": request.remote_addr or "local", "sessions_revoked": revoked})

    resp = jsonify({
        "ok": True,
        "token": new_token,
        "message": get_msg("token_rotated")
    })
    resp.set_cookie(
        "pc_token",
        new_token,
        max_age=31536000,
        path="/",
        httponly=True,
        samesite="Strict"
    )
    return resp


@app.route("/api/pair/ticket", methods=["GET", "POST"])
def api_pair_ticket():
    """Выпуск одноразового билета сопряжения для QR-кодов и ссылок (срок жизни 5 минут)."""
    # Только для авторизованных клиентов. Раньше билет выдавался ЛЮБОМУ адресу из локальной
    # сети/Tailscale без пароля, а /api/pair/exchange меняет билет на сам пароль — любое
    # устройство в той же Wi-Fi сети получало полный доступ к ПК двумя запросами.
    # Без исключения для тестового режима: билет меняется на НАСТОЯЩИЙ пароль (/api/pair/exchange),
    # а тестовый режим включается запросом POST /api/safe_mode.
    if not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401

    ticket = create_pairing_ticket(ttl=300)
    return jsonify({
        "ok": True,
        "ticket": ticket,
        "expires_in": 300,
    })


@app.route("/api/pair/exchange", methods=["POST"])
def api_pair_exchange():
    """Безопасный обмен одноразового билета сопряжения на сессионную cookie без передачи токена в открытом URL."""
    data = request.get_json(silent=True) or {}
    ticket = str(data.get("ticket") or "").strip()
    if not ticket:
        ticket = str(request.args.get("ticket") or "").strip()

    if not redeem_pairing_ticket(ticket):
        return jsonify({"ok": False, "message": "Недействительный или истёкший билет сопряжения (Invalid or expired pairing ticket)"}), 401

    # Plan 5.2: the QR ticket no longer hands out the password. "token" is a device session token:
    # old APKs / the web app store whatever comes in "token" and send it back, which works because
    # check_token() accepts session tokens.
    token, rec = sessions.create(_device_name(data, "QR"), request.remote_addr or "", "pairing")
    log_action("session_created", {"id": rec["id"], "name": rec["name"], "kind": "pairing"})
    resp = jsonify({
        "ok": True,
        "message": get_msg("login_success"),
        "token": token,
        "session": token,
        "session_id": rec["id"],
        "expires_in": sessions.IDLE_EXPIRY,
    })
    resp.set_cookie(
        "pc_token",
        token,
        max_age=sessions.IDLE_EXPIRY,
        path="/",
        httponly=True,
        samesite="Strict",
    )
    resp.set_cookie(
        "token",
        token,
        max_age=sessions.IDLE_EXPIRY,
        path="/",
        httponly=True,  # QA A-10: page scripts never read it; HttpOnly keeps it from injected JS
        samesite="Lax",
    )
    return resp


def _device_name(data: dict, default: str = "") -> str:
    name = str((data or {}).get("device_name") or "").strip()
    if not name:
        ua = request.headers.get("User-Agent") or ""
        if "Android" in ua and "Mobile" not in ua and "PCControl" not in ua:
            name = "Android"
        elif ua.startswith(("Dalvik", "PCControl")) or "okhttp" in ua.lower():
            name = "Android app"
        elif ua:
            name = "Browser"
    return sessions.clean_name(name or default or "Device")


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    """Clears the login cookies (they are HttpOnly, page scripts cannot remove them) and revokes the
    device session of this request, if it used one."""
    if check_token(count_failure=False):
        sid = current_session_id()
        if sid:
            sessions.revoke(sid)
    resp = jsonify({"ok": True})
    resp.delete_cookie("pc_token", path="/")
    resp.delete_cookie("token", path="/")
    return resp


@app.route("/api/auth/sessions", methods=["GET"])
def api_auth_sessions():
    """Device sessions (no tokens / hashes): id, name, created, last_seen, last_ip, state."""
    if not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401
    include_dead = request.args.get("all") in ("1", "true")
    return jsonify({"ok": True, "current": current_session_id(), "idle_expiry_days": sessions.IDLE_EXPIRY_DAYS,
                    "legacy_password_auth": legacy_password_allowed(),
                    "sessions": sessions.list_sessions(include_dead=include_dead)})


@app.route("/api/auth/sessions/revoke", methods=["POST"])
def api_auth_sessions_revoke():
    """{"id": "..."} revokes one device, {"all": true} every device (open streams are closed)."""
    if not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401
    data = request.get_json(silent=True) or {}
    if data.get("all") is True:
        n = sessions.revoke(all_sessions=True)
    else:
        sid = str(data.get("id") or "").strip()
        if not sid or len(sid) > 64:
            return jsonify({"ok": False, "message": get_msg("bad_request")}), 400
        n = sessions.revoke(sid)
    log_action("session_revoked", {"count": n, "by": request.remote_addr or "local"})
    return jsonify({"ok": True, "revoked": n})


@app.route("/api/cors", methods=["GET", "POST"])
def api_cors_settings():
    """Получение и настройка гибкого списка разрешённых Origin для CORS."""
    if not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        origins = data.get("origins")
        if not isinstance(origins, list):
            return jsonify({"ok": False, "message": get_msg("bad_request")}), 400
        ok = update_cors_origins(origins)
        if ok:
            return jsonify({"ok": True, "origins": get_cors_allowed_origins()})
        return jsonify({"ok": False, "message": get_msg("internal_error")}), 500

    return jsonify({"ok": True, "origins": get_cors_allowed_origins()})


# ---------- Надежная дедупликация и защита от повторного выполнения неидемпотентных команд (X-Request-Id) ----------
class IdempotencyRecord:
    def __init__(self, token_hash: str, method: str, path: str, body_hash: str, req_id: str):
        self.token_hash = token_hash
        self.method = method
        self.path = path
        self.body_hash = body_hash
        self.req_id = req_id
        self.status = "IN_PROGRESS"  # IN_PROGRESS, COMPLETED, FAILED
        self.created_at = time.time()
        self.completed_at = 0.0
        self.response = None  # dict with body, status, content_type

_idempotency_cache: collections.OrderedDict[str, IdempotencyRecord] = collections.OrderedDict()
_idempotency_lock = threading.Lock()
_IDEMPOTENCY_MAX_ENTRIES = 300
_IDEMPOTENCY_TTL_SEC = 15.0


def _get_request_identity() -> str:
    """Возвращает безопасный хэш текущего авторизованного контекста."""
    if has_request_context():
        token = request.headers.get("X-Auth-Token") or request.cookies.get("pc_token") or get_auth_token() or ""
    else:
        token = get_auth_token() or "test_default"
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


def check_idempotency_request(req_id: str):
    """
    Проверяет идемпотентность перед выполнением запроса.
    Требования:
    1. Авторизация должна быть предварительно подтверждена (неавторизованные запросы не получают кэш).
    2. Ключ кэша жестко привязан к: токену, методу, маршруту и хэшу тела запроса.
    3. Повторный ID с другим телом или маршрутом немедленно отклоняется (409 Conflict).
    4. Конкурентные запросы с одним ID атомарно переводятся в IN_PROGRESS.
    """
    if not req_id or len(req_id) > 128:
        return None

    if has_request_context():
        is_safe = _local_test_mode()
        # Мутирующие операции требуют обязательной проверки авторизации до доступа к кэшу!
        if not is_safe and not check_token():
            return None
        method = request.method
        path = request.path
        raw_body = request.get_data() or b""
    else:
        method = "POST"
        path = "/test"
        raw_body = b""

    body_hash = hashlib.sha256(raw_body).hexdigest()
    token_hash = _get_request_identity()

    primary_key = f"{token_hash}:{req_id}"
    now = time.time()

    with _idempotency_lock:
        # Очистка устаревших записей по TTL
        expired_keys = [k for k, rec in _idempotency_cache.items() if (now - rec.created_at) > _IDEMPOTENCY_TTL_SEC]
        for k in expired_keys:
            _idempotency_cache.pop(k, None)

        if primary_key in _idempotency_cache:
            rec = _idempotency_cache[primary_key]
            # Проверяем совпадение контекста: метод, маршрут и тело запроса
            if rec.method != method or rec.path != path or rec.body_hash != body_hash:
                return {
                    "error": "conflict",
                    "status": 409,
                    "message": "Idempotency key reused with different request payload or target endpoint"
                }

            if rec.status == "COMPLETED" and rec.response:
                return {
                    "body": rec.response["body"],
                    "status": rec.response["status"],
                    "content_type": rec.response.get("content_type", "application/json"),
                    "replay": True
                }
            elif rec.status == "IN_PROGRESS":
                return {
                    "error": "in_progress",
                    "status": 409,
                    "message": "Operation with this request ID is currently being processed"
                }
            elif rec.status == "FAILED":
                rec.status = "IN_PROGRESS"
                rec.created_at = now
                rec.response = None
                return None

        # Создаем новую запись IN_PROGRESS
        new_rec = IdempotencyRecord(token_hash, method, path, body_hash, req_id)
        if len(_idempotency_cache) >= _IDEMPOTENCY_MAX_ENTRIES:
            _idempotency_cache.popitem(last=False)
        _idempotency_cache[primary_key] = new_rec
        if has_request_context():
            g.idempotency_cache_key = primary_key
        return None


def store_idempotency_completion(primary_key: str, status_code: int, response_bytes: bytes, content_type: str):
    if not primary_key:
        return
    with _idempotency_lock:
        if primary_key in _idempotency_cache:
            rec = _idempotency_cache[primary_key]
            if status_code in (200, 201, 202):
                rec.status = "COMPLETED"
                rec.completed_at = time.time()
                rec.response = {
                    "body": response_bytes,
                    "status": status_code,
                    "content_type": content_type or "application/json"
                }
            else:
                rec.status = "FAILED"
                rec.completed_at = time.time()


# Совместимость с внешними вызовами тестов
def check_idempotency(req_id: str):
    if not has_request_context():
        token_hash = _get_request_identity()
        primary_key = f"{token_hash}:{req_id}"
        with _idempotency_lock:
            if primary_key in _idempotency_cache:
                rec = _idempotency_cache[primary_key]
                if rec.status == "COMPLETED" and rec.response:
                    return {
                        "body": rec.response["body"],
                        "status": rec.response["status"],
                        "content_type": rec.response.get("content_type", "application/json"),
                        "replay": True
                    }
            return None
    res = check_idempotency_request(req_id)
    if res and not res.get("error"):
        return res
    return None


def store_idempotency_result(req_id: str, result_data):
    token_hash = _get_request_identity()
    key = f"{token_hash}:{req_id}"
    with _idempotency_lock:
        if key not in _idempotency_cache:
            _idempotency_cache[key] = IdempotencyRecord(token_hash, "POST", "/test", hashlib.sha256(b"").hexdigest(), req_id)
    if isinstance(result_data, dict):
        store_idempotency_completion(
            key,
            result_data.get("status", 200),
            result_data.get("body", b""),
            result_data.get("content_type", "application/json")
        )


@app.route("/api/network/diagnose")
def api_network_diagnose():
    """Безопасная диагностика сетевых интерфейсов и доступности LAN без раскрытия секретов."""
    # QA R-1: no free pass for private / loopback addresses any more — over the USB cable (adb reverse)
    # every app on the phone looks like 127.0.0.1. The web UI calls this after login (token).
    if not _local_test_mode() and not check_token(allow_stream_query=True):
        return jsonify({"message": get_msg("auth_required")}), 401
    try:
        from scripts.network_setup import get_network_diagnostics
        diag = get_network_diagnostics()
        cfg = load_app_config() or {}
        diag["port"] = int(cfg.get("port", 5000))
        return jsonify(diag)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/lan_info")
def api_lan_info():
    # QA R-1: no free pass for private / loopback addresses any more — over the USB cable (adb reverse)
    # every app on the phone looks like 127.0.0.1. The web UI calls this after login (token).
    if not _local_test_mode() and not check_token(allow_stream_query=True):
        return jsonify({"message": get_msg("auth_required")}), 401
    cfg = load_app_config() or {}
    lan_ip = cfg.get("lan_ip") or get_local_ip()
    vpn_ip = cfg.get("vpn_ip", "")
    port = cfg.get("port", 5000)
    alt_ips = []
    is_wifi = False
    try:
        from scripts.network_setup import get_network_diagnostics
        diag = get_network_diagnostics()
        alt_ips = diag.get("alternative_ips", [])
        phys = diag.get("physical_interfaces") or []
        is_wifi = bool(phys and phys[0].get("is_wifi"))
    except Exception:
        pass
    return jsonify({
        "ip": lan_ip,
        "vpn_ip": vpn_ip,
        "mac_address": cfg.get("mac_address", ""),
        "web_url": f"http://{lan_ip}:{port}" if lan_ip else "",
        "vpn_url": f"http://{vpn_ip}:{port}" if vpn_ip else "",
        "apk_url": f"http://{lan_ip}:{port}/download/apk" if lan_ip else "",
        "alternative_ips": alt_ips,
        "is_wifi": is_wifi,
        "has_lan": bool(lan_ip),
    })


@app.route("/api/qr")
@app.route("/qr/apk")
def get_qr_image():
    if not _local_test_mode() and not is_private_ip(request.remote_addr) and not check_token(allow_stream_query=True):
        return jsonify({"message": get_msg("auth_required")}), 401
    import io
    target_url = request.args.get("url")
    if not target_url:
        cfg = load_app_config() or {}
        lan_ip = cfg.get("lan_ip") or get_local_ip()
        port = cfg.get("port", 5000)
        target_url = f"http://{lan_ip}:{port}/download/apk"
    elif len(target_url) > 2048:
        return jsonify({"message": "URL too long"}), 400
    try:
        import qrcode
        img = qrcode.make(target_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except Exception as e:
        log_error("qr_generation", e)
        return jsonify({"message": get_msg("qr_error")}), 500


@app.route("/download/apk")
def download_apk():
    # Только с паролем (cookie / заголовок) или действующим одноразовым билетом из QR-кода.
    # Раньше любое устройство локальной сети скачивало APK без пароля, а персональный APK
    # (его собирает мастер настройки) содержит пароль доступа — гость той же Wi-Fi сети
    # мог достать его из APK и получить полное управление ПК.
    if not _local_test_mode() and not is_valid_pairing_ticket(str(request.args.get("ticket") or "")) \
            and not check_token(allow_stream_query=True):
        return jsonify({"message": get_msg("apk_auth_required")}), 401
    apk_path = BASE_DIR / "PC_Control.apk"
    if not apk_path.exists():
        return jsonify({"message": get_msg("apk_not_built")}), 404
    return send_file(
        str(apk_path),
        mimetype="application/vnd.android.package-archive",
        as_attachment=True,
        download_name="PC_Control.apk",
    )


@app.route("/api/apk/info")
def api_apk_info():
    """Версия PC_Control.apk на этом ПК — для пункта «Обновление приложения» в настройках APK.
    Версия читается из самого APK (двоичный манифест), sha256 — для проверки скачанного файла."""
    if not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401
    from core.apk_info import get_apk_info
    resp = jsonify(get_apk_info(BASE_DIR / "PC_Control.apk"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/download/wol_relay.py")
def download_wol_relay():
    # Защита от несанкционированного скачивания из внешних публичных сетей
    # QA R-1: no free pass for private / loopback addresses any more — over the USB cable (adb reverse)
    # every app on the phone looks like 127.0.0.1. The web UI calls this after login (token).
    if not _local_test_mode() and not check_token(allow_stream_query=True):
        return jsonify({"message": get_msg("auth_required")}), 401
    relay_path = BASE_DIR / "scripts" / "wol_relay.py"
    if not relay_path.exists():
        relay_path = BASE_DIR / "wol_relay.py"
    if not relay_path.exists():
        return jsonify({"message": get_msg("file_not_found")}), 404
    import io
    cfg = load_app_config()
    source = relay_path.read_text(encoding="utf-8")
    source = re.sub(r'^DEFAULT_MAC = .*$', lambda _: 'DEFAULT_MAC = ' + json.dumps(cfg.get("mac_address", "AA-BB-CC-DD-EE-FF")), source, count=1, flags=re.MULTILINE)
    source = re.sub(r'^PORT = \d+$', lambda _: 'PORT = ' + str(int(cfg.get("relay_port", 5050))), source, count=1, flags=re.MULTILINE)
    return send_file(
        io.BytesIO(source.encode("utf-8")),
        mimetype="text/x-python",
        as_attachment=True,
        download_name="wol_relay.py",
    )


@app.route("/favicon.ico")
def favicon():
    ico_path = os.path.join(BASE_DIR, "pc_control.ico")
    if os.path.exists(ico_path):
        with open(ico_path, "rb") as f:
            return Response(f.read(), mimetype="image/x-icon")
    return Response(status=204)


@app.route("/logo.png")
def logo_png():
    logo_path = os.path.join(BASE_DIR, "web", "logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            return Response(f.read(), mimetype="image/png")
    return Response(status=404)


@app.route("/css/<path:filename>")
def serve_css(filename):
    css_dir = os.path.join(BASE_DIR, "web", "css")
    resp = send_from_directory(css_dir, filename)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/js/<path:filename>")
def serve_js(filename):
    js_dir = os.path.join(BASE_DIR, "web", "js")
    resp = send_from_directory(js_dir, filename)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/api/safe_mode", methods=["GET", "POST"])
def api_safe_mode():
    auth_ok = check_token()
    if not auth_ok:
        return jsonify({"message": get_msg("invalid_token")}), 401

    if request.method == "POST":
        # QA A-9: test mode weakens password checks — it may only be switched from this PC, and an
        # API-enabled test mode switches itself off after 10 minutes.
        if request.remote_addr not in ("127.0.0.1", "::1"):
            return jsonify({"message": get_msg("auth_required")}), 403
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            data = {}
        val = bool(data.get("enabled", True))
        was_on = is_safe_test_mode()
        set_safe_test_mode(val)
        if val and not was_on:
            t = threading.Timer(600, lambda: set_safe_test_mode(False))
            t.daemon = True
            t.start()
        status_str = get_msg("safe_mode_on" if val else "safe_mode_off")
        return jsonify({"safe_mode": val, "message": get_msg("safe_mode_msg", status=status_str)})
    return jsonify({"safe_mode": is_safe_test_mode()})


@app.route("/status")
def status():
    from core import route_auth
    data = {"status": "online"}
    instance = route_auth.instance_id()
    if request.remote_addr in ("127.0.0.1", "::1") or is_private_ip(request.remote_addr):
        data["instance"] = instance
    # ?nonce=… — the app checks that this is ITS server before sending the password
    # (automatic USB / tethering / LAN / Tailscale route choice, see core/route_auth.py).
    nonce = str(request.args.get("nonce") or "")
    if route_auth.valid_nonce(nonce):
        proof = route_auth.proof(nonce, instance)
        if proof:
            data["instance"] = instance
            data["proof"] = proof
    # QA R-1: the PC name only to a client with the password / a device token (no failure counting:
    # watchdog and route probes call /status without a token).
    if _local_test_mode() or check_token(count_failure=False):
        data["hostname"] = platform.node()
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/route/key")
def api_route_key():
    """Key for verifying this server on automatic routes (only to a client that knows the password)."""
    if not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401
    from core import route_auth
    resp = jsonify({"ok": True, "route_key": route_auth.route_key(), "instance": route_auth.instance_id()})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/usb/status")
def api_usb_status():
    """Phones connected by cable (adb reverse) — for diagnostics in the app / web UI."""
    if not _local_test_mode() and not check_token():
        return jsonify({"ok": False, "message": get_msg("auth_required")}), 401
    from core import usb_link
    svc = usb_link.get_service()
    return jsonify({"ok": True, **(svc.snapshot() if svc else {"adb": "disabled", "devices": []})})


@app.route("/history")
def history():
    if not check_token():
        return jsonify({"message": get_msg("invalid_token")}), 401
    limit_str = request.args.get("limit")
    limit = 500
    if limit_str is not None:
        try:
            limit = max(0, min(1000, int(limit_str)))
        except (ValueError, TypeError, OverflowError):
            return jsonify({"message": get_msg("invalid_limit")}), 400
    return jsonify(get_history(limit))


def _ensure_watchdog():
    """Запускает фоновый сторожевой процесс (watchdog.pyw), если он ещё не запущен,
    и сбрасывает флаг ручной остановки."""
    if os.environ.get("PC_CONTROL_TEST_MODE") == "1":
        return
    try:
        flag_path = LOGS_DIR / "manual_stop.flag"
        if flag_path.exists():
            try:
                flag_path.unlink()
            except Exception:
                pass
        watchdog_path = BASE_DIR / "scripts" / "watchdog.pyw"
        if watchdog_path.exists():
            py = sys.executable
            if py.lower().endswith("python.exe"):
                pyw = py[:-10] + "pythonw.exe"
                if os.path.exists(pyw):
                    py = pyw
            import subprocess
            subprocess.Popen([py, "-E", "-s", str(watchdog_path)], cwd=str(BASE_DIR), creationflags=0x08000000)
    except Exception:
        pass


@app.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    """Полная ручная остановка сервера. Устанавливает флаг, чтобы сторожевой процесс
    не перезапускал сервер до следующего явного ручного запуска."""
    if not check_token():
        return jsonify({"message": get_msg("invalid_token")}), 401
    flag_path = LOGS_DIR / "manual_stop.flag"
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text("manual_stop", encoding="utf-8")
    log_action("server_stop_manual")

    def _shutdown_worker():
        time.sleep(0.3)
        try:  # os._exit skips atexit: remove our adb reverse rules first
            from core import usb_link
            svc = usb_link.get_service()
            if svc is not None:
                svc.stop()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_shutdown_worker, daemon=True).start()
    return jsonify({"message": get_msg("server_stopping")})


_GUARD_WARN_THREADS = 400
_GUARD_RESTART_THREADS = 1500


def _resource_guard(port: int):
    """Сторож ресурсов процесса: раз в минуту проверяет число потоков ОС.

    Нативные библиотеки Windows (UI Automation/COM при чтении вкладки YouTube Music) в отдельных
    состояниях Chrome оставляли висящие рабочие потоки — сервер дорастал до сотен потоков.
    Причины по COM исправлены, но для гарантии стабильности при аномальном росте сторож пишет
    предупреждение в журнал, а при аварийном уровне перезапускает сервер через watchdog —
    только когда к серверу никто не подключён (трансляция не обрывается)."""
    import psutil
    proc = psutil.Process()
    warned = False
    while True:
        time.sleep(60)
        try:
            n = proc.num_threads()
            if n >= _GUARD_WARN_THREADS and not warned:
                warned = True
                log_action("resource_guard_warning", {"threads": n, "handles": proc.num_handles(),
                                                      "rss_mb": round(proc.memory_info().rss / 2**20)})
            if n >= _GUARD_RESTART_THREADS:
                remote = [c for c in proc.net_connections(kind="tcp")
                          if c.status == psutil.CONN_ESTABLISHED and c.laddr and c.laddr.port == port
                          and c.raddr and c.raddr.ip not in ("127.0.0.1", "::1")]
                if not remote:
                    log_action("resource_guard_restart", {"threads": n})
                    os._exit(3)  # watchdog перезапустит сервер (флага ручной остановки нет)
        except Exception:
            pass


if __name__ == "__main__":
    _ensure_watchdog()
    _cfg = load_app_config() or {}
    _port = int(_cfg.get("port", 5000))
    threading.Thread(target=_resource_guard, args=(_port,), name="resource-guard", daemon=True).start()
    print("=" * 65)
    print("                    PC CONTROL SERVER                    ")
    print("=" * 65)
    print(f"  Local URL:        http://{get_local_ip()}:{_port}")
    # Тестовый сервер (PC_CONTROL_TEST_MODE=1, tests/conftest.py) слушает только этот ПК: в тестовом
    # режиме часть проверок пароля ослаблена для 127.0.0.1, сеть к нему доступа не получает.
    _host = os.environ.get("PC_CONTROL_BIND_HOST") or ("127.0.0.1" if is_safe_test_mode() else "0.0.0.0")
    print(f"  Port:             {_port} ({'accessible on all interfaces' if _host == '0.0.0.0' else 'bound to ' + _host})")
    print("=" * 65)
    # USB cable: adb reverse for the phone + discovery beacon for USB tethering (core/usb_link.py).
    # The test server (PC_CONTROL_TEST_MODE=1) starts it only on request (PC_CONTROL_USB_LINK=1).
    if os.environ.get("PC_CONTROL_USB_LINK", "0" if is_safe_test_mode() else "1") == "1":
        try:
            from core import usb_link, route_auth
            usb_link.start_service(_port, route_auth.instance_id(), _cfg)
        except Exception as _e:
            log_error("usb_link_start", _e)
    # Production WSGI server with connection / thread limits (QA A-13, core/wsgi_server.py);
    # falls back to the Werkzeug server if the private runtime has no cheroot yet.
    from core import wsgi_server
    sessions.start_watcher()  # revocations made in the control panel close open streams

    def _log_backend(name, limits):
        print(f"  HTTP server:      {name}" + (f" {limits}" if limits else " (fallback, no connection limits)"), flush=True)
        log_action("http_server", {"backend": name, **limits})

    try:
        wsgi_server.serve(app, _host, _port, _cfg, log=_log_backend)
    except OSError as _e:
        print(f"Cannot listen on {_host}:{_port}: {_e}", file=sys.stderr, flush=True)
        log_error("http_server_bind", _e)
        sys.exit(1)
