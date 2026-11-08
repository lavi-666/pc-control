"""
PC Control — Модуль интеграции с Windows Media (SMTC), YouTube Music, очередью треков и историей.
"""

import asyncio
import base64
import datetime
import json
import math
import os
import platform
import random
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from flask import Blueprint, jsonify, request

from core.auth import check_token
from core.config import BASE_DIR, CHROME, NO_WINDOW, is_safe_test_mode
from core.logger import log_action, log_error
from modules.system import _attach_input_desktop
from modules.volume import _ensure_com, _with_volume_retry
from modules.media_history import (
    LISTENING_HISTORY_FILE,
    LISTENING_HISTORY_MAX,
    _listening_history,
    _load_listening_history_impl,
    _save_listening_history_locked_impl,
    _record_listening_history_locked_impl,
)
from modules.media_api import (
    _find_video_ids,
    _extract_search_tracks as _extract_search_tracks_api,
    _search_ytm_tracks as _search_ytm_tracks_api,
    _parse_ytm_panel_items as _parse_ytm_panel_items_api,
)

media_bp = Blueprint("media", __name__)

# ---------- Медиаплеер (System Media Transport Controls — та же "сейчас играет",
# что показывает шторка громкости Windows; ловит YouTube/YouTube Music и т.п.
# из вкладки Chrome, если именно она сейчас активный источник) ----------

_media_manager = None
_last_mgr_attempt = 0.0

from modules.media_keys import (
    _send_media_key,
    _find_media_window,
    _send_media_click_or_key,
    _navigate_chrome_or_launch as _navigate_chrome_impl,
)


def _navigate_chrome_or_launch(url: str) -> bool:
    def _update_ids(v, p):
        global _active_page_video_id, _active_page_playlist_id
        if v:
            _active_page_video_id = v
        if p:
            _active_page_playlist_id = p

    return _navigate_chrome_impl(url, update_page_ids_fn=_update_ids)



_active_media_pname: str = "chrome"
_active_media_pid: int = 0
_playback_track_title: str = ""
_playback_track_pos: float = 0.0
_playback_last_tick: float = 0.0
_playback_last_media: dict = {}
_playback_last_sound_time: float = 0.0

def _norm_title_early(s: str) -> str:
    return "".join(ch.lower() for ch in (s or "") if ch.isalnum())

def _parse_dur_to_seconds(dur_val) -> float:
    if dur_val is None:
        return 0.0
    if isinstance(dur_val, (int, float)):
        return float(dur_val)
    s = str(dur_val).strip()
    if not s:
        return 0.0
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return float(int(parts[0]) * 60 + float(parts[1]))
        elif len(parts) == 3:
            return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2]))
        return float(s)
    except (ValueError, TypeError):
        return 0.0

def _lookup_track_duration(track_title: str) -> float:
    norm = _norm_title_early(track_title)
    if not norm:
        return 0.0
    try:
        with _queue_lock:
            for it in _queue_items:
                if _norm_title_early(it.get("title", "")) == norm or (len(norm) >= 5 and norm in _norm_title_early(it.get("title", ""))):
                    d = _parse_dur_to_seconds(it.get("duration"))
                    if d > 0:
                        return d
    except Exception:
        pass
    try:
        _load_listening_history()
        for h in _listening_history:
            if _norm_title_early(h.get("title", "")) == norm or (len(norm) >= 5 and norm in _norm_title_early(h.get("title", ""))):
                d = _parse_dur_to_seconds(h.get("duration"))
                if d > 0:
                    return d
    except Exception:
        pass
    try:
        for k, tlist in _ytm_cache.items():
            for t in tlist:
                if _norm_title_early(t.get("title", "")) == norm:
                    d = _parse_dur_to_seconds(t.get("duration"))
                    if d > 0:
                        return d
    except Exception:
        pass
    return 0.0

def _get_tracked_position(title: str, status: str, duration: float) -> float:
    global _playback_track_title, _playback_track_pos, _playback_last_tick
    now = time.time()
    norm = _norm_title_early(title)
    norm_prev = _norm_title_early(_playback_track_title or _mq._playback_track_title)
    if norm != norm_prev:
        _playback_track_title = title
        _mq._playback_track_title = title
        _playback_track_pos = 0.0
        _playback_last_tick = now
        return 0.0

    time_since_skip = now - _mq._last_manual_skip
    if time_since_skip < 5.0:
        _playback_track_pos = min(time_since_skip, duration) if duration > 0 else time_since_skip
        _playback_last_tick = now
        return round(_playback_track_pos, 1)

    if _playback_last_tick > 0 and status == "playing":
        dt = now - _playback_last_tick
        if 0 < dt < 15.0:
            _playback_track_pos += dt
            if duration > 0 and _playback_track_pos >= duration:
                _playback_track_pos = 0.0
    _playback_last_tick = now
    return round(_playback_track_pos, 1)

def _seek_tracked_position(pos: float):
    global _playback_track_pos, _playback_last_tick
    _playback_track_pos = max(0.0, float(pos))
    _playback_last_tick = time.time()

def _extract_media_from_window_titles() -> dict:
    global _active_media_pid, _active_media_pname, _playback_last_media, _playback_last_sound_time
    import ctypes
    from ctypes import wintypes
    import re
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

    user32 = ctypes.windll.user32
    _attach_input_desktop()

    windows = []
    def callback(hwnd, extra):
        if user32.IsWindow(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                windows.append((pid.value, buf.value))
        return True

    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    cb_win_ref = CMPFUNC(callback)
    user32.EnumWindows(cb_win_ref, 0)

    chrome_peak = 0.0
    chrome_vol = 100
    chrome_muted = False
    spotify_peak = 0.0
    spotify_vol = 100
    spotify_muted = False
    try:
        _ensure_com()
        audio_sessions = AudioUtilities.GetAllSessions()
        for s in audio_sessions:
            if not s.Process:
                continue
            try:
                pname = s.Process.name().lower()
                vol = s.SimpleAudioVolume
                v = round(vol.GetMasterVolume() * 100) if vol else 100
                m = bool(vol.GetMute()) if vol else False
                meter = s._ctl.QueryInterface(IAudioMeterInformation)
                pk = meter.GetPeakValue() if meter else 0.0
                if "chrome" in pname or "msedge" in pname or "firefox" in pname or "brave" in pname:
                    if pk > chrome_peak or (pk > 0.0001 and chrome_peak == 0):
                        chrome_vol = v
                        chrome_muted = m
                        _active_media_pid = s.ProcessId
                        _active_media_pname = pname
                        set_active_media_process(_active_media_pid, _active_media_pname)
                    elif chrome_peak == 0.0:
                        chrome_vol = v
                        chrome_muted = m
                    chrome_peak = max(chrome_peak, pk)
                elif "spotify" in pname:
                    if pk > spotify_peak or (pk > 0.0001 and spotify_peak == 0):
                        spotify_vol = v
                        spotify_muted = m
                        _active_media_pid = s.ProcessId
                        _active_media_pname = pname
                        set_active_media_process(_active_media_pid, _active_media_pname)
                    elif spotify_peak == 0.0:
                        spotify_vol = v
                        spotify_muted = m
                    spotify_peak = max(spotify_peak, pk)
            except Exception:
                pass
    except Exception:
        pass

    if chrome_peak > 0.0001:
        _playback_last_sound_time = time.time()

    for pid, title in windows:
        # YouTube Music in browser
        m_ytm = re.search(r"^(.*?)(?:\s+[\|\-–—]\s+YouTube Music)(?:\s+[\|\-–—]\s+.*)?$", title, re.IGNORECASE)
        if m_ytm:
            raw = m_ytm.group(1).strip()
            if raw and raw.lower() != "youtube music":
                track = raw
                artist = ""
                thumb = None
                norm_tr = _norm_title_early(raw)
                try:
                    with _queue_lock:
                        for qitem in _queue_items:
                            if _norm_title_early(qitem.get("title", "")) == norm_tr:
                                track = qitem.get("title") or raw
                                artist = qitem.get("artist") or ""
                                thumb = qitem.get("thumbnail") or None
                                break
                except Exception:
                    pass
                if not artist:
                    if " - " in raw:
                        parts = raw.split(" - ", 1)
                        artist, track = parts[0].strip(), parts[1].strip()
                    else:
                        artist = "YouTube Music"

                status = "playing" if chrome_peak > 0.0001 else "paused"
                dur = _lookup_track_duration(track)
                pos = _get_tracked_position(track, status, dur)

                res = {
                    "available": True,
                    "status": status,
                    "title": track,
                    "artist": artist,
                    "album": "YouTube Music",
                    "app": "Google Chrome",
                    "thumbnail": thumb,
                    "position": pos,
                    "duration": dur,
                    "volume": chrome_vol,
                    "muted": chrome_muted,
                    "mode": _media_mode["mode"],
                }
                _playback_last_media = dict(res)
                return res

        # Regular YouTube
        m_yt = re.search(r"^(.*?)(?:\s+[\|\-–—]\s+YouTube)(?:\s+[\|\-–—]\s+.*)?$", title, re.IGNORECASE)
        if m_yt:
            raw = re.sub(r"^\(\d+\)\s*", "", m_yt.group(1).strip())
            if raw and raw.lower() != "youtube":
                if " - " in raw:
                    parts = raw.split(" - ", 1)
                    artist, track = parts[0].strip(), parts[1].strip()
                else:
                    track = raw
                    artist = "YouTube"
                status = "playing" if chrome_peak > 0.0001 else "paused"
                dur = _lookup_track_duration(track)
                pos = _get_tracked_position(track, status, dur)
                res = {
                    "available": True,
                    "status": status,
                    "title": track,
                    "artist": artist,
                    "album": "YouTube",
                    "app": "Google Chrome",
                    "thumbnail": None,
                    "position": pos,
                    "duration": dur,
                    "volume": chrome_vol,
                    "muted": chrome_muted,
                    "mode": _media_mode["mode"],
                }
                _playback_last_media = dict(res)
                return res

        # Spotify
        if "spotify" in title.lower():
            clean = re.sub(r"^Spotify(?:\s+(?:Free|Premium))?\s*[-–—]\s*", "", title, flags=re.IGNORECASE).strip()
            if clean and clean.lower() != "spotify":
                if " - " in clean:
                    parts = clean.split(" - ", 1)
                    artist, track = parts[0].strip(), parts[1].strip()
                else:
                    artist = "Spotify"
                    track = clean
                status = "playing" if spotify_peak > 0.0001 else "paused"
                dur = _lookup_track_duration(track)
                pos = _get_tracked_position(track, status, dur)
                res = {
                    "available": True,
                    "status": status,
                    "title": track,
                    "artist": artist,
                    "album": "Spotify",
                    "app": "Spotify",
                    "thumbnail": None,
                    "position": pos,
                    "duration": dur,
                    "volume": spotify_vol,
                    "muted": spotify_muted,
                    "mode": _media_mode["mode"],
                }
                _playback_last_media = dict(res)
                return res

        # Yandex Music
        m_ym = re.search(r"^(.*?)(?:\s+[\|\-–—]\s+Яндекс\s*Музыка.*)?$", title, re.IGNORECASE)
        if m_ym and ("яндекс" in title.lower() and "музыка" in title.lower()):
            raw = m_ym.group(1).strip()
            if " - " in raw:
                parts = raw.split(" - ", 1)
                artist, track = parts[0].strip(), parts[1].strip()
            else:
                track = raw
                artist = "Яндекс Музыка"
            status = "playing" if chrome_peak > 0.0001 else "paused"
            dur = _lookup_track_duration(track)
            pos = _get_tracked_position(track, status, dur)
            res = {
                "available": True,
                "status": status,
                "title": track,
                "artist": artist,
                "album": "Яндекс Музыка",
                "app": "Яндекс Музыка",
                "thumbnail": None,
                "position": pos,
                "duration": dur,
                "volume": chrome_vol,
                "muted": chrome_muted,
                "mode": _media_mode["mode"],
            }
            _playback_last_media = dict(res)
            return res

    # If YouTube Music window is present (even if paused/title is just "YouTube Music - Google Chrome")
    has_ytm_window = any("youtube music" in t.lower() for _, t in windows)
    cur_pb_title = _playback_track_title or _mq._playback_track_title
    if has_ytm_window:
        if cur_pb_title:
            status = "playing" if chrome_peak > 0.0001 else "paused"
            dur = _lookup_track_duration(cur_pb_title)
            pos = _get_tracked_position(cur_pb_title, status, dur)
            target_artist = "YouTube Music"
            target_thumb = None
            with _queue_lock:
                for it in _queue_items:
                    if _norm_title(it.get("title", "")) == _norm_title(cur_pb_title):
                        target_artist = it.get("artist") or target_artist
                        target_thumb = it.get("thumbnail") or target_thumb
                        break
                if not target_thumb:
                    for it in _listening_history:
                        if _norm_title(it.get("title", "")) == _norm_title(cur_pb_title):
                            target_artist = it.get("artist") or target_artist
                            target_thumb = it.get("thumbnail") or target_thumb
                            break
            info = {
                "available": True,
                "status": status,
                "title": cur_pb_title,
                "artist": target_artist,
                "album": "YouTube Music",
                "app": "Google Chrome",
                "thumbnail": target_thumb,
                "position": pos,
                "duration": dur,
                "volume": chrome_vol,
                "muted": chrome_muted,
                "mode": _media_mode["mode"],
            }
            _playback_last_media = dict(info)
            return info
        if _playback_last_media and _playback_last_media.get("title"):
            info = dict(_playback_last_media)
            info["status"] = "playing" if chrome_peak > 0.0001 else "paused"
            info["volume"] = chrome_vol
            info["muted"] = chrome_muted
            info["available"] = True
            dur = info.get("duration") or _lookup_track_duration(info.get("title", ""))
            info["duration"] = dur
            info["position"] = _get_tracked_position(info.get("title", ""), info["status"], dur)
            return info
        with _queue_lock:
            if _queue_items and 0 <= _mq._queue_current_idx < len(_queue_items):
                qitem = _queue_items[_mq._queue_current_idx]
                status = "playing" if chrome_peak > 0.0001 else "paused"
                dur = _lookup_track_duration(qitem.get("title", ""))
                pos = _get_tracked_position(qitem.get("title", ""), status, dur)
                info = {
                    "available": True,
                    "status": status,
                    "title": qitem.get("title", ""),
                    "artist": qitem.get("artist", "") or "YouTube Music",
                    "album": "YouTube Music",
                    "app": "Google Chrome",
                    "thumbnail": qitem.get("thumbnail"),
                    "position": pos,
                    "duration": dur,
                    "volume": chrome_vol,
                    "muted": chrome_muted,
                    "mode": _media_mode["mode"],
                }
                _playback_last_media = dict(info)
                return info

    # If Chrome audio is actively playing or was recently playing in background
    if chrome_peak > 0.0001 or (time.time() - _playback_last_sound_time < 60.0 and _active_media_pid):
        if _playback_last_media and _playback_last_media.get("title"):
            info = dict(_playback_last_media)
            info["status"] = "playing" if chrome_peak > 0.0001 else "paused"
            info["volume"] = chrome_vol
            info["muted"] = chrome_muted
            info["available"] = True
            dur = info.get("duration") or _lookup_track_duration(info.get("title", ""))
            info["duration"] = dur
            info["position"] = _get_tracked_position(info.get("title", ""), info["status"], dur)
            return info
        with _queue_lock:
            if _queue_items and 0 <= _mq._queue_current_idx < len(_queue_items):
                qitem = _queue_items[_mq._queue_current_idx]
                status = "playing" if chrome_peak > 0.0001 else "paused"
                dur = _lookup_track_duration(qitem.get("title", ""))
                pos = _get_tracked_position(qitem.get("title", ""), status, dur)
                info = {
                    "available": True,
                    "status": status,
                    "title": qitem.get("title", ""),
                    "artist": qitem.get("artist", "") or "YouTube Music",
                    "album": "YouTube Music",
                    "app": "Google Chrome",
                    "thumbnail": qitem.get("thumbnail"),
                    "position": pos,
                    "duration": dur,
                    "volume": chrome_vol,
                    "muted": chrome_muted,
                    "mode": _media_mode["mode"],
                }
                _playback_last_media = dict(info)
                return info

    return {"available": False}


async def _get_media_manager():
    global _media_manager, _last_mgr_attempt
    if _media_manager is not None:
        return _media_manager
    now = time.time()
    if (now - _last_mgr_attempt) < 5.0:
        return None
    _last_mgr_attempt = now
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
        _media_manager = await asyncio.wait_for(MediaManager.request_async(), timeout=0.5)
        return _media_manager
    except Exception:
        return None


_last_controlled_app_id: str = ""

async def _get_scored_media_sessions():
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )

    global _media_manager, _last_controlled_app_id
    manager = await _get_media_manager()
    if manager is None:
        return []

    try:
        sessions = list(manager.get_sessions())
    except Exception:
        _media_manager = None
        return []

    candidates = []
    try:
        cur = manager.get_current_session()
        if cur:
            candidates.append(cur)
    except Exception:
        pass

    for s in sessions:
        if s not in candidates:
            candidates.append(s)

    scored = []
    for s in candidates:
        try:
            pb = s.get_playback_info()
            if pb is None:
                continue
            status_val = getattr(pb, "playback_status", None)
        except Exception:
            continue

        try:
            app_id = (s.source_app_user_model_id or "").lower()
        except Exception:
            app_id = ""

        is_browser = ("chrome" in app_id or "msedge" in app_id or "firefox" in app_id or "brave" in app_id or "opera" in app_id)

        score = 0
        if status_val == PlaybackStatus.PLAYING:
            score += 1000
        elif status_val == PlaybackStatus.PAUSED:
            score += 300
        elif status_val in (PlaybackStatus.CHANGING, PlaybackStatus.OPENED):
            score += 100

        # Сессионный аффинитет: если пользователь недавно управлял этим плеером, отдаем ему приоритет
        if _last_controlled_app_id and _last_controlled_app_id in app_id:
            score += 250

        if is_browser:
            score += 50

        scored.append((score, s, pb, status_val))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


async def _select_media_session():
    scored = await _get_scored_media_sessions()
    if not scored:
        return None
    return scored[0][1]




_cached_thumb_key: tuple[str, str] = ("", "")
_cached_thumb_data: str | None = None



# ---------- Декомпозированные специализированные модули ----------
from modules.media_keys import (
    _send_media_key,
    _find_media_window,
    _send_media_click_or_key,
    _attach_input_desktop,
)
from modules.media_history import (
    _load_listening_history_impl,
    _save_listening_history_locked_impl,
    _record_listening_history_locked_impl,
    LISTENING_HISTORY_FILE,
    LISTENING_HISTORY_MAX,
    _listening_history,
)
from modules.media_api import (
    _find_video_ids,
    _extract_search_tracks,
    _search_ytm_tracks,
    _parse_ytm_panel_items,
)
from modules.media_uia import (
    _norm_title,
    _find_ytm_chrome_hwnds,
    _wake_chrome_a11y,
    _parse_url_vid_pid,
    _read_ytm_live_dom,
    _get_chrome_ytm_url,
    _uia_invoke_ytm_player_bar_button,
    _uia_invoke_ytm_queue_play,
    _uia_invoke_ytm_queue_menu,
    invalidate_dom_cache,
)
from modules.media_volume import (
    _match_player_process,
    _get_player_audio_volume,
    _set_player_audio_volume,
    set_active_media_process,
)
import modules.media_queue as _mq
from modules.media_queue import (
    QUEUE_LIMIT,
    _fmt_dur,
    _clean_thumb,
    _cache_track_meta,
    _lookup_track_meta,
    _compute_queue_version,
    _fetch_ytm_playlist,
    _fetch_ytm_automix,
    _resolve_missing_track_meta_bg,
    _sync_ytm_live_session,
    _sync_queue_with_playing,
    _read_media_info,
    _get_queue_payload,
    _play_queue_index,
    _play_history_track,
    _queue_lock,
    _queue_items,
    _queue_current_idx,
    _queue_source_name,
    _queue_fetching_for,
    _ytm_cache,
    _track_meta_cache,
    _negative_meta_cache,
    _fetched_playlist_keys,
    _meta_resolve_in_progress,
    _active_page_video_id,
    _active_page_playlist_id,
    _force_queue_refresh,
    _media_mode,
    _repeat_locked_title,
    _last_auto_action,
    _last_manual_skip,
    _navigate_chrome_or_launch,
    _load_listening_history,
)


def _save_listening_history_locked():
    _save_listening_history_locked_impl()


def _record_listening_history_locked(
    title: str,
    artist: str = "",
    duration_str: str = "",
    thumbnail: str | None = "",
    video_id: str | None = "",
    album: str = "",
):
    dur_val = _fmt_dur(duration_str) if isinstance(duration_str, (int, float)) else str(duration_str or "")
    _mq._record_listening_history_locked(
        title=title,
        artist=artist or album,
        duration_str=dur_val,
        thumbnail=thumbnail or "",
        video_id=video_id or "",
    )


async def _control_media(action: str, position: float | None = None):
    # _last_controlled_app_id раньше не был объявлен global: присваивание создавало локальную
    # переменную, и приоритет «последнего управляемого плеера» никогда не запоминался.
    global _last_manual_skip, _last_controlled_app_id
    if is_safe_test_mode():
        return True, None
    try:
        session = await _select_media_session()
        if session is not None:
            if action in ("playpause", "play_pause"):
                ok = await asyncio.wait_for(session.try_toggle_play_pause_async(), timeout=1.0)
            elif action == "play":
                ok = await asyncio.wait_for(session.try_play_async(), timeout=1.0)
            elif action == "pause":
                ok = await asyncio.wait_for(session.try_pause_async(), timeout=1.0)
            elif action == "next":
                _mq._last_manual_skip = time.time()
                _last_manual_skip = _mq._last_manual_skip
                ok = await asyncio.wait_for(session.try_skip_next_async(), timeout=1.0)
            elif action in ("prev", "previous"):
                _mq._last_manual_skip = time.time()
                _last_manual_skip = _mq._last_manual_skip
                ok = await asyncio.wait_for(session.try_skip_previous_async(), timeout=1.0)
            elif action == "seek" and position is not None:
                ticks = max(0, int(float(position) * 10_000_000))
                ok = await asyncio.wait_for(session.try_change_playback_position_async(ticks), timeout=1.0)
            else:
                ok = False
            if ok:
                if action == "seek" and position is not None:
                    _seek_tracked_position(float(position))
                try:
                    _last_controlled_app_id = (session.source_app_user_model_id or "").lower()
                except Exception:
                    pass
                invalidate_dom_cache()
                return True, None
    except Exception:
        pass

    _mq._last_manual_skip = time.time()
    _last_manual_skip = _mq._last_manual_skip
    invalidate_dom_cache()
    if action == "seek":
        # Раньше здесь возвращался «успех», хотя перемотка не выполнялась (менялась только
        # расчётная позиция на сервере) — телефон показывал новую позицию, а трек играл дальше.
        return False, "Перемотка не выполнена: плеер на ПК её не поддерживает или не найден"
    if _uia_invoke_ytm_player_bar_button(action):
        return True, None
    if _send_media_click_or_key(action):
        return True, None

    return False, "Не найдено активного плеера (открой вкладку с музыкой)"


def _read_media_info_safe(timeout: float = 3.0) -> dict:
    try:
        return asyncio.run(_read_media_info()) or {"available": False}
    except Exception as e:
        log_error("read_media_info", e)
        return {"available": False, "message": str(e)}


def _control_media_safe(action: str, position: float | None = None, timeout: float = 3.0) -> tuple[bool, str | None]:
    try:
        res = asyncio.run(_control_media(action, position))
        return res if res else (False, "Ошибка выполнения команды")
    except Exception as e:
        log_error("control_media", e)
        return False, str(e)



_latest_media_info: dict = {"available": False}
_media_info_lock = threading.Lock()
_media_wake_event = threading.Event()


def _update_latest_media_info(info: dict):
    global _latest_media_info
    if not isinstance(info, dict):
        return
    with _media_info_lock:
        _latest_media_info = dict(info)


def _media_monitor_worker():
    """Фоновый поток, непрерывно синхронизирующий медиа-сессию и живую очередь YouTube Music 24/7."""
    global _last_auto_action, _repeat_locked_title
    # Поток живёт всё время работы сервера и не обрабатывает оконные сообщения, поэтому COM
    # здесь — MTA (так Microsoft рекомендует для клиентов UI Automation): вызовы UIA и
    # аудиосессий не ждут прокачки очереди сообщений однопоточного апартамента.
    try:
        import comtypes
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except Exception:
        pass
    while True:
        try:
            info = asyncio.run(_read_media_info())
            _update_latest_media_info(info)

            mode = _media_mode.get("mode", "normal")
            if info.get("available") and mode != "normal" and not is_safe_test_mode():
                dur = float(info.get("duration") or 0)
                pos = float(info.get("position") or 0)
                title = info.get("title") or ""
                now = time.time()

                if mode == "repeat":
                    if not _mq._repeat_locked_title and title:
                        _mq._repeat_locked_title = title
                        _repeat_locked_title = title
                    if dur > 5 and pos >= dur - 1.8 and (now - _mq._last_auto_action) > 2.5:
                        _mq._last_auto_action = now
                        _last_auto_action = now
                        asyncio.run(_control_media("seek", 0))
                        asyncio.run(_control_media("play"))
                    elif (
                        _mq._repeat_locked_title
                        and title
                        and _norm_title(title) != _norm_title(_mq._repeat_locked_title)
                        and (now - _mq._last_manual_skip) > 4.0
                        and (now - _mq._last_auto_action) > 3.0
                    ):
                        _mq._last_auto_action = now
                        _last_auto_action = now
                        asyncio.run(_control_media("prev"))
                        time.sleep(0.15)
                        asyncio.run(_control_media("seek", 0))

                elif mode == "shuffle":
                    if dur > 6 and pos >= dur - 1.8 and (now - _mq._last_auto_action) > 4.0:
                        _mq._last_auto_action = now
                        _last_auto_action = now
                        with _queue_lock:
                            q_len = len(_queue_items)
                        if q_len > 2:
                            rand_idx = random.randint(0, q_len - 1)
                            asyncio.run(_play_queue_index(target_idx=rand_idx))
                        else:
                            hops = random.randint(1, 3)
                            for _ in range(hops):
                                asyncio.run(_control_media("next"))
                                time.sleep(0.14)
        except Exception:
            pass

        _media_wake_event.wait(timeout=0.75)
        _media_wake_event.clear()


threading.Thread(target=_media_monitor_worker, name="media-mode-monitor", daemon=True).start()


@media_bp.route("/media/now")
def media_now():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"available": False, "message": "Доступно только на Windows"}), 400
    with _media_info_lock:
        info = dict(_latest_media_info)
    if info.get("available"):
        info["queue_version"] = _compute_queue_version()
        info["queue_current_index"] = _mq._queue_current_idx
        info["queue_total"] = len(_queue_items)
    return jsonify(info)


@media_bp.route("/media/control", methods=["POST"])
def media_control():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"message": "Доступно только на Windows"}), 400
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    action = str(data.get("action", "")).strip().lower()
    valid_actions = {"play", "pause", "playpause", "play_pause", "next", "prev", "previous", "stop", "seek"}
    if action not in valid_actions:
        return jsonify({"message": "Неизвестное действие медиаплеера"}), 400
    position = data.get("position")
    if action == "seek":
        if position is None or isinstance(position, bool):
            return jsonify({"message": "Некорректная позиция перемотки"}), 400
        try:
            pos_f = float(position)
            if math.isnan(pos_f) or math.isinf(pos_f):
                return jsonify({"message": "Некорректная позиция перемотки"}), 400
            position = max(0.0, pos_f)
        except (ValueError, TypeError, OverflowError):
            return jsonify({"message": "Некорректная позиция перемотки"}), 400
    try:
        ok, err = _control_media_safe(action, position, timeout=2.0)
        if err:
            return jsonify({"message": err}), 400
        _media_wake_event.set()
        log_action("media_" + action)
        return jsonify({"message": "ok" if ok else "Команда не выполнена (сессия могла закрыться)"})
    except Exception as e:
        log_error("media_control", e)
        return jsonify({"message": f"Ошибка: {e}"}), 400


@media_bp.route("/media/volume", methods=["POST"])
def media_volume():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    pct = data.get("percent")
    mute_val = data.get("mute")
    parsed_pct = None
    if pct is not None:
        if isinstance(pct, bool):
            return jsonify({"message": "Некорректный процент громкости плеера"}), 400
        try:
            v = float(pct)
            if math.isnan(v) or math.isinf(v):
                return jsonify({"message": "Некорректный процент громкости плеера"}), 400
            parsed_pct = max(0, min(100, int(round(v))))
        except (ValueError, TypeError, OverflowError):
            return jsonify({"message": "Некорректный процент громкости плеера"}), 400
    try:
        new_pct, new_mute = _set_player_audio_volume(
            percent=parsed_pct,
            mute=bool(mute_val) if mute_val is not None else None,
            app_hint=_active_media_pname or "chrome",
        )
        _media_wake_event.set()
        log_action("media_volume", {"percent": new_pct, "muted": new_mute})
        return jsonify({"percent": new_pct, "muted": new_mute, "message": f"Громкость плеера: {new_pct}%"})
    except Exception as e:
        log_error("media_volume", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@media_bp.route("/media/mode", methods=["POST"])
def media_mode():
    global _repeat_locked_title
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not data or not isinstance(data, dict) or "mode" not in data:
        return jsonify({"message": "Не передан параметр mode"}), 400
    mode = str(data.get("mode", "")).strip().lower()
    if mode not in ("normal", "repeat", "shuffle"):
        return jsonify({"message": "Неизвестный режим"}), 400
    _media_mode["mode"] = mode
    _mq._repeat_locked_title = ""
    _repeat_locked_title = ""
    _media_wake_event.set()
    labels = {
        "normal": "Обычный порядок воспроизведения",
        "repeat": "Повтор текущего трека включён",
        "shuffle": "Перемешивание треков включено",
    }
    log_action("media_mode", {"mode": mode})
    return jsonify({"mode": mode, "message": labels.get(mode, f"Режим установлен: {mode}")})


@media_bp.route("/media/queue")
def media_queue():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    return jsonify(_get_queue_payload())


@media_bp.route("/media/queue/refresh", methods=["POST"])
def media_queue_refresh():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    global _force_queue_refresh, _queue_current_idx, _active_page_video_id, _active_page_playlist_id
    _mq._force_queue_refresh = True
    _force_queue_refresh = True
    dom = _sync_ytm_live_session(force=True)
    if not (dom.get("found") and dom.get("dom_queue")):
        vid, pid = _get_chrome_ytm_url(force=True)
        if vid:
            _mq._active_page_video_id = vid
            _active_page_video_id = vid
        if pid:
            _mq._active_page_playlist_id = pid
            _active_page_playlist_id = pid
        cur_t = _playback_track_title or _mq._playback_track_title
        cur_art = ""
        with _queue_lock:
            if 0 <= _mq._queue_current_idx < len(_queue_items):
                it = _queue_items[_mq._queue_current_idx]
                cur_t = cur_t or it.get("title", "")
                cur_art = it.get("artist", "")
        tracks, act_idx = _fetch_ytm_playlist(
            vid=_mq._active_page_video_id,
            pid=_mq._active_page_playlist_id,
            limit=QUEUE_LIMIT,
            title_fallback=cur_t,
            artist_fallback=cur_art,
        )
        if tracks:
            with _queue_lock:
                _queue_items.clear()
                _queue_items.extend(tracks)
                _mq._queue_current_idx = act_idx
                _queue_current_idx = act_idx
    _media_wake_event.set()
    log_action("media_queue_refresh", {"video_id": _mq._active_page_video_id, "playlist_id": _mq._active_page_playlist_id})
    return jsonify(_get_queue_payload())


@media_bp.route("/media/queue/play", methods=["POST"])
def media_queue_play():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_idx = data.get("index")
    try:
        idx = int(raw_idx) if (raw_idx is not None and not isinstance(raw_idx, bool)) else None
    except (ValueError, TypeError, OverflowError):
        idx = None
    title = str(data.get("title", "")).strip()
    artist = str(data.get("artist", "")).strip()
    video_id = str(data.get("video_id", "")).strip()
    try:
        ok, msg = asyncio.run(asyncio.wait_for(
            _play_queue_index(target_idx=idx, title=title, artist=artist, video_id=video_id),
            timeout=8.0
        ))
        if not ok:
            return jsonify({"message": msg}), 400
        _media_wake_event.set()
        log_action("media_queue_play", {"index": idx, "title": title, "video_id": video_id})
        return jsonify({"message": msg, "current_index": _mq._queue_current_idx, "queue_version": _compute_queue_version()})
    except Exception as e:
        log_error("media_queue_play", e)
        return jsonify({"message": f"Ошибка: {e}"}), 400


@media_bp.route("/media/queue/remove", methods=["POST"])
def media_queue_remove():
    global _queue_current_idx
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_idx = data.get("index")
    try:
        idx = int(raw_idx) if (raw_idx is not None and not isinstance(raw_idx, bool)) else None
    except (ValueError, TypeError, OverflowError):
        idx = None
    title = str(data.get("title", "")).strip()
    if idx is None or idx < 0:
        return jsonify({"message": "Некорректный индекс трека"}), 400

    with _queue_lock:
        if idx >= len(_queue_items):
            return jsonify({"message": "Трек вне диапазона очереди"}), 400
        if idx == _mq._queue_current_idx:
            return jsonify({"message": "Нельзя удалить текущий воспроизводимый трек"}), 400
        removed_title = _queue_items[idx].get("title", title)

    ok_uia = _uia_invoke_ytm_queue_menu(
        idx,
        removed_title,
        ("Remove from queue", "Удалить из очереди", "Вилучити з черги"),
    )
    with _queue_lock:
        if 0 <= idx < len(_queue_items):
            _queue_items.pop(idx)
            if idx < _mq._queue_current_idx:
                _mq._queue_current_idx = max(0, _mq._queue_current_idx - 1)
                _queue_current_idx = _mq._queue_current_idx
            for new_i, tr in enumerate(_queue_items):
                tr["index"] = new_i
                tr["active"] = (new_i == _mq._queue_current_idx)

    _media_wake_event.set()
    log_action("media_queue_remove", {"index": idx, "title": removed_title, "uia": ok_uia})
    return jsonify({
        "message": f"Удалено из очереди: {removed_title}",
        **_get_queue_payload(),
    })


@media_bp.route("/media/queue/play_next", methods=["POST"])
def media_queue_play_next():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_idx = data.get("index")
    try:
        idx = int(raw_idx) if (raw_idx is not None and not isinstance(raw_idx, bool)) else None
    except (ValueError, TypeError, OverflowError):
        idx = None
    title = str(data.get("title", "")).strip()
    if idx is None or idx < 0:
        return jsonify({"message": "Некорректный индекс трека"}), 400

    with _queue_lock:
        if idx >= len(_queue_items):
            return jsonify({"message": "Трек вне диапазона очереди"}), 400
        src_track = dict(_queue_items[idx])

    ok_uia = _uia_invoke_ytm_queue_menu(
        idx,
        src_track.get("title", title),
        ("Play next", "Включить следующим", "Відтворити наступним"),
    )
    if ok_uia:
        time.sleep(0.35)
        _sync_ytm_live_session(force=True)
    else:
        with _queue_lock:
            insert_pos = min(len(_queue_items), _mq._queue_current_idx + 1)
            copy_tr = dict(src_track)
            copy_tr["active"] = False
            _queue_items.insert(insert_pos, copy_tr)
            for new_i, tr in enumerate(_queue_items):
                tr["index"] = new_i
                tr["active"] = (new_i == _mq._queue_current_idx)

    _media_wake_event.set()
    log_action("media_queue_play_next", {"index": idx, "title": src_track.get("title", "")})
    return jsonify({
        "message": f"Включится следующим: {src_track.get('title', '')}",
        **_get_queue_payload(),
    })


@media_bp.route("/media/search")
def media_search():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    q = str(request.args.get("q", "")).strip()
    if not q:
        return jsonify({"tracks": []})
    tracks = _search_ytm_tracks(q, limit=12)
    return jsonify({"tracks": tracks})


@media_bp.route("/media/queue/add", methods=["POST"])
def media_queue_add():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    query = str(data.get("query", "")).strip()
    title = str(data.get("title", "")).strip()
    artist = str(data.get("artist", "")).strip()
    video_id = str(data.get("video_id", "")).strip()
    duration = str(data.get("duration", "")).strip()
    thumbnail = str(data.get("thumbnail", "")).strip()
    play_now = bool(data.get("play_now", False))

    if not title and not video_id and query:
        found = _search_ytm_tracks(query, limit=3)
        if not found:
            return jsonify({"message": "Трек не найден в YouTube Music"}), 404
        top = found[0]
        title = top.get("title", query)
        artist = top.get("artist", "")
        video_id = top.get("videoId", "")
        duration = top.get("duration", "")
        thumbnail = top.get("thumbnail", "")
    elif not video_id and title:
        found = _search_ytm_tracks(f"{title} {artist}".strip(), limit=3)
        if found:
            top = found[0]
            video_id = top.get("videoId", "")
            duration = duration or top.get("duration", "")
            thumbnail = thumbnail or top.get("thumbnail", "")
            artist = artist or top.get("artist", "")

    if not title:
        return jsonify({"message": "Укажите название трека или поисковый запрос"}), 400

    _cache_track_meta(title, artist, video_id, thumbnail, duration)

    # Проверяем, есть ли этот трек уже в очереди YouTube Music — если есть, используем 'Play next' через UIA!
    existing_idx = None
    with _queue_lock:
        nt = _norm_title(title)
        for i, it in enumerate(_queue_items):
            if _norm_title(it.get("title", "")) == nt:
                existing_idx = i
                break

    if play_now:
        ok, msg = asyncio.run(_play_queue_index(target_idx=existing_idx, title=title, artist=artist, video_id=video_id))
        _media_wake_event.set()
        return jsonify({"message": msg, **_get_queue_payload()})

    if existing_idx is not None:
        ok_uia = _uia_invoke_ytm_queue_menu(
            existing_idx,
            title,
            ("Play next", "Включить следующим", "Відтворити наступним"),
        )
        if ok_uia:
            time.sleep(0.35)
            _sync_ytm_live_session(force=True)
            _media_wake_event.set()
            return jsonify({
                "message": f"Добавлено следующим в очередь: {title}",
                **_get_queue_payload(),
            })

    with _queue_lock:
        insert_pos = min(len(_queue_items), _mq._queue_current_idx + 1) if _queue_items else 0
        new_item = {
            "index": insert_pos,
            "title": title,
            "artist": artist,
            "duration": duration,
            "thumbnail": thumbnail,
            "video_id": video_id,
            "active": (len(_queue_items) == 0),
        }
        _queue_items.insert(insert_pos, new_item)
        for new_i, tr in enumerate(_queue_items):
            tr["index"] = new_i
            tr["active"] = (new_i == _mq._queue_current_idx)

    _media_wake_event.set()
    log_action("media_queue_add", {"title": title, "video_id": video_id})
    return jsonify({
        "message": f"Добавлено в очередь: {title}",
        **_get_queue_payload(),
    })


@media_bp.route("/media/history/play", methods=["POST"])
def media_history_play():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_h_idx = data.get("h_index")
    parsed_h_idx = None
    if raw_h_idx is not None:
        if isinstance(raw_h_idx, bool):
            return jsonify({"message": "Некорректный индекс истории"}), 400
        try:
            parsed_h_idx = int(raw_h_idx)
        except (ValueError, TypeError, OverflowError):
            return jsonify({"message": "Некорректный индекс истории"}), 400
    title = str(data.get("title", ""))
    artist = str(data.get("artist", ""))
    video_id = str(data.get("video_id", ""))
    try:
        ok, msg = asyncio.run(
            asyncio.wait_for(
                _play_history_track(
                    parsed_h_idx,
                    title=title,
                    artist=artist,
                    video_id=video_id,
                ),
                timeout=6.0,
            )
        )
        if not ok:
            return jsonify({"message": msg}), 400
        _media_wake_event.set()
        log_action("media_history_play", {"title": title[:60]})
        return jsonify({"message": msg})
    except Exception as e:
        log_error("media_history_play", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500
