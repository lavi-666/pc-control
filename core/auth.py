"""
PC Control — Аутентификация, rate-limiting и защита от перебора паролей.
"""

import ipaddress
import json
import secrets
import threading
import time
from pathlib import Path
from flask import request
from core.config import LOGS_DIR, get_auth_token, is_safe_test_mode, load_app_config
from core.logger import log_action

I18N_MESSAGES = {
    "ru": {
        "auth_required": "Требуется авторизация",
        "invalid_token": "Неверный пароль доступа",
        "locked_out": "Слишком много неверных попыток. Доступ заблокирован на {sec} сек.",
        "login_success": "Авторизация успешна",
        "token_rotated": "Токен доступа успешно обновлён",
        "cors_forbidden": "Доступ с этого источника (Origin) запрещён политикой CORS",
        "null_byte": "Недопустимый запрос: содержит null-байт",
        "path_traversal": "Недопустимый запрос: обнаружен path traversal ('..')",
        "internal_error": "Внутренняя ошибка сервера",
        "bad_request": "Ошибка запроса",
        "apk_not_built": "APK-файл ещё не собран",
        "apk_auth_required": "Необходима авторизация для скачивания приложения",
        "file_not_found": "Файл не найден",
        "qr_error": "Ошибка генерации QR-кода",
        "invalid_limit": "Некорректный параметр limit",
        "server_stopping": "Сервер останавливается. Автоперезапуск отключён.",
        "safe_mode_on": "включён",
        "safe_mode_off": "выключен",
        "safe_mode_msg": "Безопасный режим: {status}",
    },
    "en": {
        "auth_required": "Authentication required",
        "invalid_token": "Invalid access token",
        "locked_out": "Too many failed attempts. Access locked for {sec}s.",
        "login_success": "Authentication successful",
        "token_rotated": "Access token rotated successfully",
        "cors_forbidden": "Access from this Origin is forbidden by CORS policy",
        "null_byte": "Invalid request: contains null byte",
        "path_traversal": "Invalid request: path traversal detected ('..')",
        "internal_error": "Internal server error",
        "bad_request": "Bad request",
        "apk_not_built": "APK file has not been built yet",
        "apk_auth_required": "Authentication required to download application",
        "file_not_found": "File not found",
        "qr_error": "QR code generation error",
        "invalid_limit": "Invalid limit parameter",
        "server_stopping": "Server is stopping. Auto-restart disabled.",
        "safe_mode_on": "enabled",
        "safe_mode_off": "disabled",
        "safe_mode_msg": "Safe mode: {status}",
    },
    "uk": {
        "auth_required": "Потрібна авторизація",
        "invalid_token": "Невірний пароль доступу",
        "locked_out": "Забагато невдалих спроб. Доступ заблоковано на {sec} с.",
        "login_success": "Авторизація успішна",
        "token_rotated": "Токен доступу успішно оновлено",
        "cors_forbidden": "Доступ із цього джерела (Origin) заборонено політикою CORS",
        "null_byte": "Неприпустимий запит: містить null-байт",
        "path_traversal": "Неприпустимий запит: виявлено path traversal ('..')",
        "internal_error": "Внутрішня помилка сервера",
        "bad_request": "Помилка запиту",
        "apk_not_built": "APK-файл ще не зібрано",
        "apk_auth_required": "Потрібна авторизація для завантаження додатка",
        "file_not_found": "Файл не знайдено",
        "qr_error": "Помилка генерації QR-коду",
        "invalid_limit": "Некоректний параметр limit",
        "server_stopping": "Сервер зупиняється. Автоперезапуск вимкнено.",
        "safe_mode_on": "увімкнено",
        "safe_mode_off": "вимкнено",
        "safe_mode_msg": "Безпечний режим: {status}",
    }
}


def detect_language(req=None) -> str:
    r = req or (request if request else None)
    if r:
        try:
            lang_param = (r.args.get("lang") or "").strip().lower()
            if lang_param in ("ru", "en", "uk"):
                return lang_param
            accept = (r.headers.get("Accept-Language") or "").lower()
            if "uk" in accept:
                return "uk"
            if "ru" in accept:
                return "ru"
            if "en" in accept:
                return "en"
        except Exception:
            pass
    try:
        cfg = load_app_config() or {}
        cfg_lang = str(cfg.get("language", "ru")).lower()
        if cfg_lang in ("ru", "en", "uk"):
            return cfg_lang
    except Exception:
        pass
    return "ru"


def get_msg(key: str, lang: str | None = None, **kwargs) -> str:
    target_lang = lang or detect_language()
    dict_lang = I18N_MESSAGES.get(target_lang, I18N_MESSAGES["ru"])
    raw = dict_lang.get(key) or I18N_MESSAGES["en"].get(key, key)
    try:
        return raw.format(**kwargs)
    except Exception:
        return raw

LOCKOUT_FILE = LOGS_DIR / "lockouts.json"
LOCKOUT_WINDOW = 120        # окно для подсчета неудач (сек)
LOCKOUT_MAX_ATTEMPTS = 5    # лимит для внешних публичных сетей
LOCKOUT_DURATION = 180      # длительность блокировки публичных сетей (сек)
LOCKOUT_LAN_MAX = 15        # лимит для локальных сетей (защита от багов/опечаток)
LOCKOUT_LAN_DURATION = 30   # длительность блокировки локальных сетей (сек)

# Tailscale CGNAT подсеть (100.64.0.0/10)
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")

_failed_attempts: dict[str, list[float]] = {}   # ip -> [timestamps неудач]
_locked_until: dict[str, float] = {}            # ip -> unix timestamp разблокировки
_lock_guard = threading.Lock()


def _load_persisted_lockouts():
    try:
        if LOCKOUT_FILE.exists():
            data = json.loads(LOCKOUT_FILE.read_text(encoding="utf-8"))
            now = time.time()
            with _lock_guard:
                for ip, until in data.get("locked_until", {}).items():
                    if float(until) > now:
                        _locked_until[ip] = float(until)
    except Exception:
        pass


def _save_persisted_lockouts():
    try:
        import os
        now = time.time()
        with _lock_guard:
            active_locks = {ip: until for ip, until in _locked_until.items() if until > now}
            tmp_file = LOCKOUT_FILE.with_suffix(".json.tmp")
            tmp_file.write_text(json.dumps({"locked_until": active_locks}), encoding="utf-8")
            os.replace(tmp_file, LOCKOUT_FILE)
    except Exception:
        pass


_load_persisted_lockouts()


def is_private_ip(ip: str) -> bool:
    """Определяет доверенные локальные и защищенные VPN-сети (RFC 1918 + Tailscale 100.64.0.0/10).
    Использует строгую проверку через ipaddress вместо ненадежных префиксов."""
    if not ip or ip in ("127.0.0.1", "::1", "localhost", "unknown"):
        return True
    try:
        addr = ipaddress.ip_address(ip.strip())
        return addr.is_loopback or addr.is_private or (addr in TAILSCALE_NET)
    except ValueError:
        return False


def get_lockout_remaining(ip: str) -> int:
    with _lock_guard:
        until = _locked_until.get(ip)
        if until is None:
            return 0
        rem = int(until - time.time())
        return max(0, rem)


def is_locked(ip: str) -> bool:
    with _lock_guard:
        until = _locked_until.get(ip)
        if until is None:
            return False
        if time.time() >= until:
            _locked_until.pop(ip, None)
            _failed_attempts.pop(ip, None)
            return False
        return True


def register_failure(ip: str):
    with _lock_guard:
        now = time.time()
        if len(_failed_attempts) > 500:
            expired_ips = [
                k for k, ts_list in _failed_attempts.items()
                if not ts_list or (now - ts_list[-1] >= LOCKOUT_WINDOW and _locked_until.get(k, 0) <= now)
            ]
            for k in expired_ips:
                _failed_attempts.pop(k, None)
                _locked_until.pop(k, None)

        is_priv = is_private_ip(ip)
        max_att = LOCKOUT_LAN_MAX if is_priv else LOCKOUT_MAX_ATTEMPTS
        duration = LOCKOUT_LAN_DURATION if is_priv else LOCKOUT_DURATION

        attempts = [t for t in _failed_attempts.get(ip, []) if now - t < LOCKOUT_WINDOW]
        attempts.append(now)
        _failed_attempts[ip] = attempts
        if len(attempts) >= max_att:
            _locked_until[ip] = now + duration
            log_action("token_lockout", {"ip": ip, "duration": duration})
    _save_persisted_lockouts()


def clear_lockout(ip: str | None = None):
    changed = False
    with _lock_guard:
        if ip:
            if ip in _locked_until:
                _locked_until.pop(ip, None)
                changed = True
            _failed_attempts.pop(ip, None)
        else:
            if _locked_until:
                changed = True
            _locked_until.clear()
            _failed_attempts.clear()
    if changed:
        _save_persisted_lockouts()


def check_token(allow_stream_query: bool = False) -> bool:
    """Проверка токена из безопасных источников (X-Auth-Token, Authorization, Cookie, JSON body).
    Использует secrets.compare_digest для защиты от атак по времени (timing attacks).
    Клиентский заголовок X-Safe-Mode полностью удалён и не может влиять на аутентификацию.
    Query-параметр (?token=) по умолчанию запрещён для предотвращения утечек в URL и логи."""
    ip = request.remote_addr or "unknown"
    safe_test = is_safe_test_mode()

    if is_locked(ip):
        if safe_test and ip in ("127.0.0.1", "::1", "localhost"):
            clear_lockout(ip)
        else:
            return False

    token = None
    # 1. Заголовок X-Auth-Token
    token = request.headers.get("X-Auth-Token")
    # 2. Заголовок Authorization: Bearer <token>
    if not token:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()
    # 3. Cookie сессии
    if not token:
        token = request.cookies.get("pc_token") or request.cookies.get("token")
    # 4. JSON body (для POST запросов)
    if not token:
        json_body = request.get_json(silent=True)
        if isinstance(json_body, dict):
            token = json_body.get("token") or json_body.get("password")

    # 5. Исключение для мультимедиа стриминга (<audio>, <img>), где браузер не может передать заголовки
    if not token and allow_stream_query:
        token = request.args.get("token") or request.args.get("ticket")

    # 6. Поддержка тестов на loopback (127.0.0.1) в safe_test_mode
    if not token and safe_test and ip in ("127.0.0.1", "::1", "localhost"):
        token = request.args.get("token")

    if not token:
        return False

    expected = get_auth_token()
    token_str = str(token)
    if expected and secrets.compare_digest(token_str.encode("utf-8"), expected.encode("utf-8")):
        clear_lockout(ip)
        return True
    token_str = token_str.strip('"').strip("'")
    if "%" in token_str:
        try:
            import urllib.parse
            token_str = urllib.parse.unquote(token_str)
            if expected and secrets.compare_digest(token_str.encode("utf-8"), expected.encode("utf-8")):
                clear_lockout(ip)
                return True
            token_str = token_str.strip('"').strip("'")
        except Exception:
            pass

    is_valid = bool(expected) and secrets.compare_digest(token_str.encode("utf-8"), expected.encode("utf-8"))

    if is_valid:
        clear_lockout(ip)
        return True

    if not safe_test:
        register_failure(ip)

    return False
