"""
PC Control — Модуль управления громкостью медиаплееров через WASAPI (pycaw).
"""
import platform
import threading
import time
from core.config import is_safe_test_mode
from modules.volume import _with_volume_retry

_cached_pvol_time: float = 0.0
_cached_pvol_res: tuple[int, bool] = (100, False)
_active_media_pid: int = 0
_active_media_pname: str = "chrome"


def set_active_media_process(pid: int, pname: str):
    global _active_media_pid, _active_media_pname
    if pid:
        _active_media_pid = int(pid)
    if pname:
        _active_media_pname = str(pname)


_com_init_tls = threading.local()


def _co_init_safe() -> bool:
    """Инициализирует COM на текущем потоке ОДИН раз и оставляет его инициализированным.

    Всегда возвращает False, чтобы вызывающий код не делал CoUninitialize: раньше COM
    деинициализировался в конце каждого вызова, пока COM-объекты (сессии pycaw, элементы UIA)
    ещё были живы и освобождались уже после этого. Рабочие потоки COM/UIA оставались висеть —
    сервер терял ~40 потоков ОС в минуту, сотни за час."""
    if getattr(_com_init_tls, "done", False):
        return False
    import comtypes
    try:
        # Режим берётся из sys.coinit_flags (в сервере — MTA, см. server.py)
        comtypes.CoInitializeEx()
    except OSError as e:
        if getattr(e, "winerror", None) != -2147417850:  # RPC_E_CHANGED_MODE: поток уже инициализирован
            raise
    _com_init_tls.done = True
    return False


def _match_player_process(proc_name: str, app_hint: str) -> bool:
    p = proc_name.lower()
    h = (app_hint or "").lower()
    if "chrome" in h and "chrome" in p:
        return True
    if "msedge" in h and "msedge" in p:
        return True
    if "spotify" in h and "spotify" in p:
        return True
    if "firefox" in h and "firefox" in p:
        return True
    return p in ("chrome.exe", "msedge.exe", "spotify.exe", "firefox.exe", "opera.exe", "brave.exe", "vlc.exe")


def _get_player_audio_volume(app_hint: str = "") -> tuple[int, bool]:
    """Читает громкость аудио-сессии активного медиаплеера (например, Chrome с YouTube Music)
    или системную громкость, если сессия ещё не создана. Использует кэширование (2 сек)."""
    global _cached_pvol_time, _cached_pvol_res
    now = time.time()
    if (now - _cached_pvol_time) < 2.0:
        return _cached_pvol_res
    if platform.system() != "Windows":
        return 100, False
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities

        did_init = _co_init_safe()
        try:
            sessions = AudioUtilities.GetAllSessions()
            fallback = None
            for s in sessions:
                if not s.Process:
                    continue
                try:
                    name = s.Process.name()
                except Exception:
                    continue
                if _match_player_process(name, app_hint):
                    vol = s.SimpleAudioVolume
                    pct = round(vol.GetMasterVolume() * 100)
                    muted = bool(vol.GetMute())
                    if app_hint and app_hint.lower()[:5] in name.lower():
                        _cached_pvol_time = now
                        _cached_pvol_res = (pct, muted)
                        return pct, muted
                    if fallback is None:
                        fallback = (pct, muted)
            if fallback is not None:
                _cached_pvol_time = now
                _cached_pvol_res = fallback
                return fallback
            res = _with_volume_retry(lambda v: (round(v.GetMasterVolumeLevelScalar() * 100), bool(v.GetMute())))
            _cached_pvol_time = now
            _cached_pvol_res = res
            return res
        finally:
            if did_init:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass
    except Exception:
        return _cached_pvol_res


def _set_player_audio_volume(percent: int | None = None, mute: bool | None = None, app_hint: str = "") -> tuple[int, bool]:
    """Меняет громкость/mute аудио-сессий медиаплеера (например, вкладки Chrome с музыкой)."""
    global _active_media_pid, _active_media_pname, _cached_pvol_time, _cached_pvol_res
    if is_safe_test_mode():
        pct = max(0, min(100, int(percent))) if percent is not None else _cached_pvol_res[0]
        mt = bool(mute) if mute is not None else _cached_pvol_res[1]
        return pct, mt
    if platform.system() != "Windows":
        return 100, False
    import comtypes
    from pycaw.pycaw import AudioUtilities

    did_init = _co_init_safe()
    try:
        sessions = AudioUtilities.GetAllSessions()
        matched = []
        hint = (app_hint or _active_media_pname or "chrome").lower()

        if _active_media_pid:
            for s in sessions:
                if s.Process and s.ProcessId == _active_media_pid:
                    matched.append(s)

        for s in sessions:
            if not s.Process or s in matched:
                continue
            try:
                name = s.Process.name().lower()
            except Exception:
                continue
            if hint in name or _match_player_process(name, hint):
                matched.append(s)

        if matched:
            res_pct, res_mute = 100, False
            for s in matched:
                try:
                    vol = s.SimpleAudioVolume
                    if percent is not None:
                        clamped = max(0, min(100, int(percent)))
                        vol.SetMasterVolume(clamped / 100.0, None)
                    if mute is not None:
                        vol.SetMute(1 if mute else 0, None)
                    res_pct = round(vol.GetMasterVolume() * 100)
                    res_mute = bool(vol.GetMute())
                except Exception:
                    pass
            _cached_pvol_time = time.time()
            _cached_pvol_res = (res_pct, res_mute)
            return res_pct, res_mute

        def _apply(v):
            if percent is not None:
                v.SetMasterVolumeLevelScalar(max(0, min(100, int(percent))) / 100.0, None)
            if mute is not None:
                v.SetMute(1 if mute else 0, None)
            return round(v.GetMasterVolumeLevelScalar() * 100), bool(v.GetMute())

        res = _with_volume_retry(_apply)
        _cached_pvol_time = time.time()
        _cached_pvol_res = res
        return res
    finally:
        if did_init:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass

