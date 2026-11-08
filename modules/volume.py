"""
PC Control — Модуль управления системной громкостью и аудио-микшером приложений.
"""

import math
import threading
import time
from flask import Blueprint, jsonify, request
from core.auth import check_token
from core.config import is_safe_test_mode
from core.logger import log_action, log_error

volume_bp = Blueprint("volume", __name__)

_vol_retry_lock = threading.Lock()
_vol_cache = {"percent": None, "muted": None, "ts": 0.0}
_vol_cache_ttl = 0.35  # кэш на 350мс для ускорения повторных запросов громкости
_safe_vol_state = {"percent": 50, "muted": False}
_com_tls = threading.local()


def _ensure_com():
    import comtypes

    if not getattr(_com_tls, "initialized", False):
        try:
            # Режим из sys.coinit_flags (в сервере — MTA): потоки запросов не должны становиться
            # STA без цикла сообщений (см. server.py)
            comtypes.CoInitializeEx()
        except OSError as e:
            if getattr(e, "winerror", None) != -2147417850:  # RPC_E_CHANGED_MODE
                raise
        _com_tls.initialized = True


def _get_audio_sessions():
    from pycaw.pycaw import AudioUtilities

    _ensure_com()
    try:
        return list(AudioUtilities.GetAllSessions())
    except Exception:
        return []


def _volume_interface():
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    _ensure_com()
    device = AudioUtilities.GetSpeakers()
    if hasattr(device, "EndpointVolume"):
        return device.EndpointVolume
    interface = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


def _with_volume_retry(fn):
    with _vol_retry_lock:
        try:
            return fn(_volume_interface())
        except Exception:
            time.sleep(0.1)
            return fn(_volume_interface())


def _get_cached_volume():
    if is_safe_test_mode():
        return _safe_vol_state["percent"], _safe_vol_state["muted"]
    now = time.time()
    if _vol_cache["percent"] is not None and (now - _vol_cache["ts"]) < _vol_cache_ttl:
        return _vol_cache["percent"], _vol_cache["muted"]

    def read(vol):
        return round(vol.GetMasterVolumeLevelScalar() * 100), bool(vol.GetMute())

    percent, is_muted = _with_volume_retry(read)
    _vol_cache["percent"] = percent
    _vol_cache["muted"] = is_muted
    _vol_cache["ts"] = now
    return percent, is_muted


def _invalidate_volume_cache():
    _vol_cache["ts"] = 0.0


@volume_bp.route("/volume", methods=["GET"])
def get_volume_route():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    try:
        percent, is_muted = _get_cached_volume()
        return jsonify({"percent": percent, "muted": is_muted})
    except Exception as e:
        log_error("get_volume", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@volume_bp.route("/volume", methods=["POST"])
def set_volume_route():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    try:
        raw_val = data.get("percent", 50)
        if raw_val is None:
            return jsonify({"message": "Некорректное значение громкости"}), 400
        v = float(raw_val)
        if math.isnan(v) or math.isinf(v):
            return jsonify({"message": "Некорректное значение громкости"}), 400
        percent = max(0, min(100, int(round(v))))
    except (ValueError, TypeError, OverflowError):
        return jsonify({"message": "Некорректное значение громкости"}), 400
    try:
        if is_safe_test_mode():
            _safe_vol_state["percent"] = percent
        else:
            _with_volume_retry(lambda vol: vol.SetMasterVolumeLevelScalar(percent / 100, None))
            _invalidate_volume_cache()
        log_action("set_volume", {"percent": percent})
        return jsonify({"message": f"Громкость: {percent}%"})
    except Exception as e:
        log_error("set_volume", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@volume_bp.route("/mute", methods=["POST"])
def mute():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    state = 1 if data.get("mute", True) else 0
    try:
        if is_safe_test_mode():
            _safe_vol_state["muted"] = bool(state)
        else:
            _with_volume_retry(lambda vol: vol.SetMute(state, None))
            _invalidate_volume_cache()
        log_action("mute" if state else "unmute")
        return jsonify({"message": "Звук выключен" if state else "Звук включён"})
    except Exception as e:
        log_error("mute", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@volume_bp.route("/app_volumes")
def app_volumes():
    """Список аудио-сессий приложений с их индивидуальной громкостью."""
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    try:
        sessions = _get_audio_sessions()
        result = []
        seen_pids = set()
        for s in sessions:
            if not s.Process:
                continue
            pid = s.Process.pid
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            vol = s.SimpleAudioVolume
            result.append({
                "pid": pid,
                "name": s.Process.name(),
                "percent": round(vol.GetMasterVolume() * 100),
                "muted": bool(vol.GetMute()),
            })
        result.sort(key=lambda p: p["name"].lower())
        return jsonify(result)
    except Exception as e:
        log_error("app_volumes", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@volume_bp.route("/app_volume", methods=["POST"])
def set_app_volume():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_pid = data.get("pid")
    if raw_pid is None or isinstance(raw_pid, bool):
        return jsonify({"message": "Некорректный PID"}), 400
    try:
        pid = int(raw_pid)
    except (ValueError, TypeError, OverflowError):
        return jsonify({"message": "Некорректный PID"}), 400
    try:
        raw_val = data.get("percent", 50)
        if raw_val is None:
            return jsonify({"message": "Некорректное значение громкости"}), 400
        v = float(raw_val)
        if math.isnan(v) or math.isinf(v):
            return jsonify({"message": "Некорректное значение громкости"}), 400
        percent = max(0, min(100, int(round(v))))
    except (ValueError, TypeError, OverflowError):
        return jsonify({"message": "Некорректное значение громкости"}), 400
    try:
        for s in _get_audio_sessions():
            if s.Process and s.Process.pid == pid:
                if not is_safe_test_mode():
                    s.SimpleAudioVolume.SetMasterVolume(percent / 100, None)
                log_action("set_app_volume", {"pid": pid, "name": s.Process.name(), "percent": percent})
                return jsonify({"message": f"{s.Process.name()}: {percent}%"})
        return jsonify({"message": "Приложение не найдено среди аудио-сессий"}), 404
    except Exception as e:
        log_error("set_app_volume", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@volume_bp.route("/app_volume/mute", methods=["POST"])
def mute_app_volume():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_pid = data.get("pid")
    if raw_pid is None or isinstance(raw_pid, bool):
        return jsonify({"message": "Некорректный PID"}), 400
    try:
        pid = int(raw_pid)
    except (ValueError, TypeError, OverflowError):
        return jsonify({"message": "Некорректный PID"}), 400
    state = 1 if data.get("mute", True) else 0
    try:
        for s in _get_audio_sessions():
            if s.Process and s.Process.pid == pid:
                if not is_safe_test_mode():
                    s.SimpleAudioVolume.SetMute(state, None)
                log_action("mute_app" if state else "unmute_app", {"pid": pid, "name": s.Process.name()})
                return jsonify({"message": f"{s.Process.name()}: {'выключен' if state else 'включён'}"})
        return jsonify({"message": "Приложение не найдено среди аудио-сессий"}), 404
    except Exception as e:
        log_error("mute_app_volume", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500
