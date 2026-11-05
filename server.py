"""
PC Control — Сервер дистанционного управления ПК с телефона.
Запускать на компьютере, который нужно контролировать удалённо.
"""

import json
import hashlib
import os
import platform
import secrets
import socket
import threading
import time
import sys
from pathlib import Path
from flask import Flask, Request, Response, jsonify, request, send_file, make_response, send_from_directory
import re

from core.config import (
    BASE_DIR,
    WEB_INDEX_FILE,
    is_safe_test_mode,
    set_safe_test_mode,
    get_auth_token,
    load_app_config,
    update_auth_token,
    get_cors_allowed_origins,
    update_cors_origins
)
from core.auth import (
    check_token,
    is_locked,
    get_lockout_remaining,
    register_failure,
    clear_lockout,
    is_private_ip,
    get_msg,
    detect_language
)
from core.logger import get_history, log_action, log_error
from modules.system import system_bp, _attach_input_desktop
from modules.volume import volume_bp
from modules.power import power_bp
from modules.streaming import streaming_bp
from modules.media import media_bp
from modules.presets import presets_bp

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

# Регистрация функциональных модулей через Blueprints
app.register_blueprint(volume_bp)
app.register_blueprint(power_bp)
app.register_blueprint(system_bp)
app.register_blueprint(streaming_bp)
app.register_blueprint(media_bp)
app.register_blueprint(presets_bp)


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
    if origin_clean in ("null", "file://", "capacitor://localhost", "http://pccontrol.local"):
        return True

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


def _apply_cors_and_security_headers(resp):
    origin = request.headers.get("Origin")
    if origin:
        if _is_origin_allowed(origin, request.remote_addr):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Auth-Token, Authorization"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
    else:
        if is_safe_test_mode() or request.remote_addr in ("127.0.0.1", "::1"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
        else:
            resp.headers["Access-Control-Allow-Origin"] = request.host_url.rstrip("/")
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Auth-Token, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

    # Защитные заголовки
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' http://127.0.0.1:* http://localhost:* http://192.168.* http://100.* http://10.*;"
    )
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


@app.after_request
def _add_cors_headers(resp):
    return _apply_cors_and_security_headers(resp)


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


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


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

    expected = get_auth_token()
    if pwd and expected and secrets.compare_digest(pwd.encode("utf-8"), expected.encode("utf-8")):
        clear_lockout(ip)
        resp = jsonify({
            "ok": True,
            "message": get_msg("login_success"),
            "token": pwd
        })
        resp.set_cookie(
            "pc_token",
            pwd,
            max_age=31536000,
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
        if len(custom_token) < 4:
            return jsonify({"ok": False, "message": "Токен должен содержать минимум 4 символа"}), 400
        new_token = custom_token
    else:
        new_token = secrets.token_hex(8)

    ok = update_auth_token(new_token)
    if not ok:
        return jsonify({"ok": False, "message": get_msg("internal_error")}), 500

    log_action("token_rotate", {"by": request.remote_addr or "local"})

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


@app.route("/api/lan_info")
def api_lan_info():
    if not is_safe_test_mode() and not is_private_ip(request.remote_addr) and not check_token(allow_stream_query=True):
        return jsonify({"message": get_msg("auth_required")}), 401
    cfg = load_app_config() or {}
    lan_ip = cfg.get("lan_ip") or get_local_ip()
    vpn_ip = cfg.get("vpn_ip", "")
    port = cfg.get("port", 5000)
    return jsonify({
        "ip": lan_ip,
        "vpn_ip": vpn_ip,
        "mac_address": cfg.get("mac_address", ""),
        "web_url": f"http://{lan_ip}:{port}",
        "vpn_url": f"http://{vpn_ip}:{port}" if vpn_ip else "",
        "apk_url": f"http://{lan_ip}:{port}/download/apk",
    })


@app.route("/api/qr")
@app.route("/qr/apk")
def get_qr_image():
    if not is_safe_test_mode() and not is_private_ip(request.remote_addr) and not check_token(allow_stream_query=True):
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
    # Защита от несанкционированного скачивания из внешних публичных сетей
    if not is_safe_test_mode() and not is_private_ip(request.remote_addr) and not check_token(allow_stream_query=True):
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


@app.route("/download/wol_relay.py")
def download_wol_relay():
    # Защита от несанкционированного скачивания из внешних публичных сетей
    if not is_safe_test_mode() and not is_private_ip(request.remote_addr) and not check_token(allow_stream_query=True):
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
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            data = {}
        val = bool(data.get("enabled", True))
        set_safe_test_mode(val)
        status_str = get_msg("safe_mode_on" if val else "safe_mode_off")
        return jsonify({"safe_mode": val, "message": get_msg("safe_mode_msg", status=status_str)})
    return jsonify({"safe_mode": is_safe_test_mode()})


@app.route("/status")
def status():
    data = {"status": "online"}
    if request.remote_addr in ("127.0.0.1", "::1"):
        data["instance"] = hashlib.sha256(str(BASE_DIR.resolve()).lower().rstrip("\\/").encode("utf-8")).hexdigest()
    if is_private_ip(request.remote_addr) or check_token() or is_safe_test_mode():
        data["hostname"] = platform.node()
    return jsonify(data)


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
    try:
        flag_path = BASE_DIR / "logs" / "manual_stop.flag"
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
            subprocess.Popen([py, str(watchdog_path)], cwd=str(BASE_DIR), creationflags=0x08000000)
    except Exception:
        pass


@app.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    """Полная ручная остановка сервера. Устанавливает флаг, чтобы сторожевой процесс
    не перезапускал сервер до следующего явного ручного запуска."""
    if not check_token():
        return jsonify({"message": get_msg("invalid_token")}), 401
    flag_path = BASE_DIR / "logs" / "manual_stop.flag"
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text("manual_stop", encoding="utf-8")
    log_action("server_stop_manual")

    def _shutdown_worker():
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_shutdown_worker, daemon=True).start()
    return jsonify({"message": get_msg("server_stopping")})


if __name__ == "__main__":
    _ensure_watchdog()
    _cfg = load_app_config() or {}
    _port = int(_cfg.get("port", 5000))
    print("=" * 65)
    print("                    PC CONTROL SERVER                    ")
    print("=" * 65)
    print(f"  Local URL:        http://{get_local_ip()}:{_port}")
    print(f"  Port:             {_port} (accessible on all interfaces)")
    print("=" * 65)
    app.run(host="0.0.0.0", port=_port, threaded=True)
