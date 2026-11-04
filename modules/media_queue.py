"""
PC Control — Управление живой очередью треков YouTube Music (до 200 треков), плейлистами и кешированием метаданных.
"""
import asyncio
import base64
import hashlib
import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

from core.config import BASE_DIR, is_safe_test_mode
from core.logger import log_action, log_error
from modules.media_api import (
    _extract_search_tracks,
    _find_video_ids,
    _parse_ytm_panel_items,
    _search_ytm_tracks,
)
from modules.media_history import (
    _load_listening_history_impl,
    _record_listening_history_locked_impl,
    _listening_history,
    LISTENING_HISTORY_MAX,
)
from modules.media_keys import (
    _navigate_chrome_or_launch as _navigate_chrome_impl,
    _send_media_click_or_key,
    _send_media_key,
)
from modules.media_uia import (
    _get_chrome_ytm_url,
    _norm_title,
    _parse_dur_to_seconds,
    _read_ytm_live_dom,
    _uia_invoke_ytm_queue_play,
    invalidate_dom_cache,
)
from modules.media_volume import _get_player_audio_volume

QUEUE_LIMIT = 200

_queue_lock = threading.RLock()
_queue_items: list[dict] = []
_queue_current_idx: int = 0
_queue_source_name: str = ""
_queue_fetching_for: str = ""
_queue_fetch_in_progress: bool = False
_last_synced_title: str = ""
_playback_track_title: str = ""
_cached_thumb_key: tuple[str, str] = ("", "")
_cached_thumb_data: str | None = None
_ytm_cache: dict[str, list[dict]] = {}
_track_meta_cache: dict[str, dict] = {}
_negative_meta_cache: set[str] = set()
_fetched_playlist_keys: set[str] = set()
_meta_resolve_in_progress: bool = False
_active_page_video_id: str = ""
_active_page_playlist_id: str = ""
_force_queue_refresh: bool = False

_media_mode = {"mode": "normal"}  # "normal" | "repeat" | "shuffle"
_repeat_locked_title: str = ""
_last_auto_action: float = 0.0
_last_manual_skip: float = 0.0


def _navigate_chrome_or_launch(url: str) -> bool:
    def _update_ids(v: str, p: str):
        global _active_page_video_id, _active_page_playlist_id
        if v:
            _active_page_video_id = v
        if p:
            _active_page_playlist_id = p

    return _navigate_chrome_impl(url, update_page_ids_fn=_update_ids)


def _fmt_dur(sec: float) -> str:
    if not sec or sec <= 0:
        return ""
    total = int(round(sec))
    return f"{total // 60}:{total % 60:02d}"


def _clean_thumb(url: str | None) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://") or url.startswith("data:image/"):
        return url
    return ""


def _cache_track_meta(title: str, artist: str, video_id: str, thumbnail: str, duration: str = ""):
    nt = _norm_title(title)
    if not nt:
        return
    na = _norm_title(artist)
    clean_th = _clean_thumb(thumbnail)
    entry = _track_meta_cache.get(nt, {})
    merged = {
        "video_id": video_id or entry.get("video_id", ""),
        "thumbnail": clean_th or entry.get("thumbnail", ""),
        "duration": duration or entry.get("duration", ""),
        "artist": artist or entry.get("artist", ""),
    }
    _track_meta_cache[nt] = merged
    if na:
        _track_meta_cache[f"{nt}|{na}"] = dict(merged)


def _lookup_track_meta(title: str, artist: str = "") -> dict:
    nt = _norm_title(title)
    if not nt:
        return {}
    na = _norm_title(artist)
    if na and f"{nt}|{na}" in _track_meta_cache:
        return _track_meta_cache[f"{nt}|{na}"]
    if nt in _track_meta_cache:
        return _track_meta_cache[nt]
    return {}


def _load_listening_history():
    _load_listening_history_impl(cache_meta_fn=_cache_track_meta)


def _record_listening_history_locked(
    title: str,
    artist: str = "",
    duration_str: str = "",
    thumbnail: str = "",
    video_id: str = "",
):
    _record_listening_history_locked_impl(
        title=title,
        artist=artist,
        duration_str=duration_str,
        thumbnail=thumbnail,
        video_id=video_id,
        norm_title_fn=_norm_title,
        clean_thumb_fn=_clean_thumb,
        lookup_meta_fn=_lookup_track_meta,
    )


_load_listening_history()


def _compute_queue_version() -> str:
    import hashlib
    with _queue_lock:
        parts = [
            str(_queue_current_idx),
            str(_media_mode.get("mode", "normal")),
            str(_queue_source_name),
            str(len(_queue_items)),
        ]
        for it in _queue_items[:QUEUE_LIMIT]:
            parts.append(
                f"{it.get('title','')}|{it.get('artist','')}|{it.get('duration','')}|{1 if it.get('thumbnail') else 0}|{it.get('video_id','')}"
            )
        raw = "\n".join(parts).encode("utf-8", errors="ignore")
        return hashlib.md5(raw).hexdigest()[:12]



def _fetch_ytm_playlist(
    vid: str = "",
    pid: str = "",
    limit: int = QUEUE_LIMIT,
    title_fallback: str = "",
    artist_fallback: str = "",
) -> tuple[list[dict], int]:
    """Получает полную очередь YouTube Music из контекста/плейлиста браузера (без обрезки до 30 треков)
    и наполняет кэш метаданных (обложки и video_id) для всех треков плейлиста."""
    vid_clean = (vid or "").strip()
    pid_clean = (pid or "").strip()
    t_fallback = (title_fallback or "").strip()
    a_fallback = (artist_fallback or "").strip()

    ctx = {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": "1.20240918.01.00",
                "hl": "en",
                "gl": "UA",
            }
        }
    }
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

    # Если vid и pid не переданы, сначала пробуем прочитать их из открытой вкладки YouTube Music
    if not vid_clean and not pid_clean:
        try:
            u_vid, u_pid = _get_chrome_ytm_url(force=False)
            vid_clean = u_vid or vid_clean
            pid_clean = u_pid or pid_clean
        except Exception:
            pass

    if not vid_clean and t_fallback:
        search_tracks = _search_ytm_tracks(f"{t_fallback} {a_fallback}".strip(), limit=5)
        norm_target = _norm_title(t_fallback)
        for item in search_tracks:
            if norm_target and _norm_title(item.get("title", "")) == norm_target:
                vid_clean = item.get("videoId", "")
                break
        if not vid_clean and search_tracks:
            vid_clean = search_tracks[0].get("videoId", "")

    if not vid_clean and not pid_clean:
        return [], 0

    try:
        # Если заданы и vid_clean, и pid_clean, сначала один раз прогреваем кэш начала плейлиста (треки 0..49),
        # так как youtubei/v1/next с videoId возвращает окно из 100 треков вокруг активного трека.
        if vid_clean and pid_clean and f"head|{pid_clean}" not in _fetched_playlist_keys and not pid_clean.startswith("RD"):
            _fetched_playlist_keys.add(f"head|{pid_clean}")
            try:
                req_head = urllib.request.Request(
                    "https://music.youtube.com/youtubei/v1/next?prettyPrint=false",
                    data=json.dumps({
                        **ctx,
                        "videoId": "",
                        "playlistId": pid_clean,
                        "enablePersistentPlaylistPanel": True,
                        "isAudioOnly": True,
                    }).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req_head, timeout=5) as r_head:
                    d_head = json.loads(r_head.read().decode("utf-8", errors="ignore"))
                h_contents = (
                    d_head.get("contents", {})
                    .get("singleColumnMusicWatchNextResultsRenderer", {})
                    .get("tabbedRenderer", {})
                    .get("watchNextTabbedResultsRenderer", {})
                    .get("tabs", [{}])[0]
                    .get("tabRenderer", {})
                    .get("content", {})
                    .get("musicQueueRenderer", {})
                    .get("content", {})
                    .get("playlistPanelRenderer", {})
                    .get("contents", [])
                )
                for h_it in h_contents:
                    h_ren = h_it.get("playlistPanelVideoRenderer")
                    if not h_ren:
                        continue
                    h_title = "".join(x.get("text", "") for x in h_ren.get("title", {}).get("runs", []))
                    h_artist = "".join(x.get("text", "") for x in h_ren.get("shortBylineText", {}).get("runs", []))
                    h_dur = "".join(x.get("text", "") for x in h_ren.get("lengthText", {}).get("runs", []))
                    h_thumbs = h_ren.get("thumbnail", {}).get("thumbnails", [])
                    h_thumb = h_thumbs[-1].get("url", "") if h_thumbs else ""
                    h_vid = h_ren.get("videoId", "")
                    if h_title:
                        _cache_track_meta(h_title, h_artist, h_vid, h_thumb, h_dur)
            except Exception:
                pass

        req_next = urllib.request.Request(
            "https://music.youtube.com/youtubei/v1/next?prettyPrint=false",
            data=json.dumps({
                **ctx,
                "videoId": vid_clean,
                "playlistId": pid_clean or (f"RDAMVM{vid_clean}" if vid_clean else ""),
                "enablePersistentPlaylistPanel": True,
                "isAudioOnly": True,
            }).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req_next, timeout=7) as r_next:
            data = json.loads(r_next.read().decode("utf-8", errors="ignore"))

        ppr = (
            data.get("contents", {})
            .get("singleColumnMusicWatchNextResultsRenderer", {})
            .get("tabbedRenderer", {})
            .get("watchNextTabbedResultsRenderer", {})
            .get("tabs", [{}])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("musicQueueRenderer", {})
            .get("content", {})
            .get("playlistPanelRenderer", {})
        )
        contents = ppr.get("contents", [])
        all_tracks: list[dict] = []
        active_idx = None
        norm_fallback = _norm_title(t_fallback)

        for it in contents:
            renderer = it.get("playlistPanelVideoRenderer")
            if not renderer:
                continue
            title = "".join(x.get("text", "") for x in renderer.get("title", {}).get("runs", [])) or "Без названия"
            artist = "".join(x.get("text", "") for x in renderer.get("shortBylineText", {}).get("runs", []))
            dur = "".join(x.get("text", "") for x in renderer.get("lengthText", {}).get("runs", []))
            thumbs = renderer.get("thumbnail", {}).get("thumbnails", [])
            thumb_url = thumbs[-1].get("url", "") if thumbs else ""
            item_vid = renderer.get("videoId", "")
            selected = bool(renderer.get("selected", False))

            _cache_track_meta(title, artist, item_vid, thumb_url, dur)

            idx = len(all_tracks)
            if selected or (item_vid and item_vid == vid_clean):
                active_idx = idx
            elif active_idx is None and norm_fallback and _norm_title(title) == norm_fallback:
                active_idx = idx

            all_tracks.append({
                "index": idx,
                "title": title,
                "artist": artist,
                "duration": dur,
                "thumbnail": thumb_url,
                "video_id": item_vid,
                "active": False,
            })

        if not all_tracks:
            return [], 0

        if active_idx is None:
            active_idx = 0

        # Если запрошен limit меньше общего числа треков, сохраняем окно вокруг активного трека,
        # но по умолчанию QUEUE_LIMIT=200 вмещает весь плейлист целиком.
        eff_limit = max(1, int(limit or QUEUE_LIMIT))
        if len(all_tracks) > eff_limit:
            half = eff_limit // 2
            start = max(0, min(active_idx - half, len(all_tracks) - eff_limit))
            sliced = all_tracks[start : start + eff_limit]
            active_idx = active_idx - start
            for new_i, tr in enumerate(sliced):
                tr["index"] = new_i
                tr["active"] = (new_i == active_idx)
            all_tracks = sliced
        else:
            for new_i, tr in enumerate(all_tracks):
                tr["index"] = new_i
                tr["active"] = (new_i == active_idx)

        if pid_clean:
            _fetched_playlist_keys.add(pid_clean)
        if vid_clean:
            _fetched_playlist_keys.add(f"{vid_clean}|{pid_clean}")

        return all_tracks, active_idx
    except Exception:
        return [], 0


def _fetch_ytm_automix(
    title: str = "",
    artist: str = "",
    video_id: str = "",
    playlist_id: str = "",
    limit: int = QUEUE_LIMIT,
    force_fresh: bool = False,
) -> list[dict]:
    """Совместимая обёртка для подгрузки очереди треков."""
    tracks, _ = _fetch_ytm_playlist(
        vid=video_id,
        pid=playlist_id,
        limit=limit,
        title_fallback=title,
        artist_fallback=artist,
    )
    return tracks


def _resolve_missing_track_meta_bg():
    """Фоновое дообогащение обложек и video_id для треков, вручную добавленных пользователем в очередь на сайте."""
    global _meta_resolve_in_progress
    if _meta_resolve_in_progress:
        return
    _meta_resolve_in_progress = True

    def _worker():
        global _meta_resolve_in_progress
        try:
            missing: list[tuple[str, str]] = []
            with _queue_lock:
                # В первую очередь проверяем активный трек и ближайшие к нему
                order = list(range(len(_queue_items)))
                order.sort(key=lambda idx: (0 if idx == _queue_current_idx else 1, abs(idx - _queue_current_idx)))
                for idx in order:
                    it = _queue_items[idx]
                    t = it.get("title", "")
                    a = it.get("artist", "")
                    nt = _norm_title(t)
                    if not nt or nt in _negative_meta_cache:
                        continue
                    if not it.get("thumbnail") or not it.get("video_id"):
                        cached = _lookup_track_meta(t, a)
                        if cached.get("thumbnail") and cached.get("video_id"):
                            it["thumbnail"] = it.get("thumbnail") or cached["thumbnail"]
                            it["video_id"] = it.get("video_id") or cached["video_id"]
                        else:
                            missing.append((t, a))
                            if len(missing) >= 15:
                                break

            for t, a in missing:
                nt = _norm_title(t)
                results = _search_ytm_tracks(f"{t} {a}".strip(), limit=3)
                matched = None
                for r in results:
                    if _norm_title(r.get("title", "")) == nt:
                        matched = r
                        break
                if not matched and results:
                    matched = results[0]
                if matched:
                    _cache_track_meta(
                        t,
                        a,
                        matched.get("videoId", ""),
                        matched.get("thumbnail", ""),
                        matched.get("duration", ""),
                    )
                    with _queue_lock:
                        for it in _queue_items:
                            if _norm_title(it.get("title", "")) == nt:
                                if not it.get("video_id"):
                                    it["video_id"] = matched.get("videoId", "")
                                if not it.get("thumbnail"):
                                    it["thumbnail"] = matched.get("thumbnail", "")
                else:
                    _negative_meta_cache.add(nt)
        except Exception:
            pass
        finally:
            _meta_resolve_in_progress = False

    threading.Thread(target=_worker, name="ytm-meta-resolver", daemon=True).start()



def _sync_ytm_live_session(force: bool = False) -> dict:
    """Синхронизирует очередь и состояние плеера напрямую с живым DOM вкладки YouTube Music
    и обогащает метаданными (обложками и video_id) из Innertube."""
    global _queue_current_idx, _queue_source_name, _active_page_video_id, _active_page_playlist_id
    global _queue_fetch_in_progress, _force_queue_refresh, _last_synced_title, _playback_track_title

    dom = _read_ytm_live_dom(force=force or _force_queue_refresh, current_idx=_queue_current_idx)
    if not dom.get("found"):
        return dom

    vid = dom.get("vid", "")
    pid = dom.get("pid", "")
    if vid:
        _active_page_video_id = vid
    if pid:
        _active_page_playlist_id = pid
    if dom.get("queue_source"):
        _queue_source_name = dom["queue_source"]

    pb = dom.get("player_bar", {})
    pb_title = pb.get("title", "")
    pb_artist = pb.get("artist", "")
    dom_queue = dom.get("dom_queue", [])
    active_idx = dom.get("active_idx", 0)

    # Проверяем, нужно ли подгрузить метаданные плейлиста (video_id и обложки) из youtubei/v1/next
    need_playlist_meta = False
    if vid or pid:
        key_check = pid if pid else f"{vid}|"
        if force or _force_queue_refresh or (key_check and key_check not in _fetched_playlist_keys):
            need_playlist_meta = True
        elif dom_queue:
            # Если более чем у 3 треков нет обложек в кэше
            missing_cnt = sum(1 for it in dom_queue[:20] if not _lookup_track_meta(it["title"], it["artist"]).get("thumbnail"))
            if missing_cnt > 3 and f"{vid}|{pid}" not in _fetched_playlist_keys:
                need_playlist_meta = True

    if need_playlist_meta and not _queue_fetch_in_progress:
        if force or not _queue_items:
            _queue_fetch_in_progress = True
            try:
                _fetch_ytm_playlist(
                    vid=vid,
                    pid=pid,
                    limit=QUEUE_LIMIT,
                    title_fallback=pb_title,
                    artist_fallback=pb_artist,
                )
            finally:
                _queue_fetch_in_progress = False
        else:
            _queue_fetch_in_progress = True
            def _bg_meta(v=vid, p=pid, t=pb_title, a=pb_artist):
                global _queue_fetch_in_progress
                try:
                    _fetch_ytm_playlist(vid=v, pid=p, limit=QUEUE_LIMIT, title_fallback=t, artist_fallback=a)
                    # После загрузки метаданных сразу обогащаем текущую очередь
                    with _queue_lock:
                        for q_it in _queue_items:
                            m = _lookup_track_meta(q_it.get("title", ""), q_it.get("artist", ""))
                            if m.get("thumbnail") and not q_it.get("thumbnail"):
                                q_it["thumbnail"] = m["thumbnail"]
                            if m.get("video_id") and not q_it.get("video_id"):
                                q_it["video_id"] = m["video_id"]
                finally:
                    _queue_fetch_in_progress = False
            threading.Thread(target=_bg_meta, name="ytm-playlist-meta", daemon=True).start()

    _force_queue_refresh = False

    if dom_queue:
        new_items: list[dict] = []
        has_missing_meta = False
        for idx_q, d_it in enumerate(dom_queue[:QUEUE_LIMIT]):
            t_title = d_it.get("title", "Без названия")
            t_artist = d_it.get("artist", "")
            t_dur = d_it.get("duration", "")
            meta = _lookup_track_meta(t_title, t_artist)
            t_vid = meta.get("video_id", "")
            t_thumb = meta.get("thumbnail", "")
            if idx_q == active_idx and vid:
                t_vid = vid
                if t_thumb:
                    _cache_track_meta(t_title, t_artist, vid, t_thumb, t_dur)
            if not t_thumb or not t_vid:
                has_missing_meta = True
            new_items.append({
                "index": idx_q,
                "title": t_title,
                "artist": t_artist or meta.get("artist", ""),
                "duration": t_dur or meta.get("duration", ""),
                "thumbnail": t_thumb,
                "video_id": t_vid,
                "active": (idx_q == active_idx),
            })

        with _queue_lock:
            _queue_items.clear()
            _queue_items.extend(new_items)
            _queue_current_idx = active_idx if 0 <= active_idx < len(new_items) else 0
            if 0 <= _queue_current_idx < len(_queue_items):
                act_tr = _queue_items[_queue_current_idx]
                _playback_track_title = act_tr.get("title", pb_title)
                _last_synced_title = _norm_title(_playback_track_title)
                _record_listening_history_locked(
                    act_tr.get("title", pb_title),
                    act_tr.get("artist") or pb_artist,
                    act_tr.get("duration") or pb.get("duration_str", ""),
                    act_tr.get("thumbnail", ""),
                    act_tr.get("video_id") or vid,
                )

        if has_missing_meta:
            _resolve_missing_track_meta_bg()

    return dom


def _sync_queue_with_playing(title: str, artist: str, album: str, duration: float, thumbnail: str | None):
    """Синхронизирует очередь и историю прослушивания с текущим треком.
    В первую очередь использует живую синхронизацию с открытой вкладкой YouTube Music."""
    global _queue_current_idx, _repeat_locked_title, _active_page_video_id, _active_page_playlist_id
    global _force_queue_refresh, _last_synced_title, _queue_fetch_in_progress

    dom = _sync_ytm_live_session(force=_force_queue_refresh)
    if dom.get("found") and dom.get("dom_queue"):
        with _queue_lock:
            if _media_mode.get("mode") == "repeat" and not _repeat_locked_title and title:
                _repeat_locked_title = title
            if 0 <= _queue_current_idx < len(_queue_items):
                cur_it = _queue_items[_queue_current_idx]
                if thumbnail and not cur_it.get("thumbnail"):
                    cur_it["thumbnail"] = thumbnail
        return

    norm_t = _norm_title(title)
    if not norm_t:
        return

    dur_str = _fmt_dur(duration)
    art_str = artist or album or ""

    # Пробуем получить реальные vid и pid из браузера
    browser_vid, browser_pid = _get_chrome_ytm_url(force=False)
    if browser_vid:
        _active_page_video_id = browser_vid
    if browser_pid:
        _active_page_playlist_id = browser_pid

    if norm_t == _last_synced_title and _queue_items and not _force_queue_refresh:
        with _queue_lock:
            if 0 <= _queue_current_idx < len(_queue_items):
                cur_it = _queue_items[_queue_current_idx]
                if thumbnail and not cur_it.get("thumbnail"):
                    cur_it["thumbnail"] = thumbnail
                if dur_str and not cur_it.get("duration"):
                    cur_it["duration"] = dur_str
        return

    _last_synced_title = norm_t

    found_idx = None
    with _queue_lock:
        if _media_mode.get("mode") == "repeat" and not _repeat_locked_title:
            _repeat_locked_title = title

        for i, it in enumerate(_queue_items):
            it_norm = _norm_title(it.get("title", ""))
            if it_norm == norm_t or (len(norm_t) >= 4 and len(it_norm) >= 4 and (norm_t in it_norm or it_norm in norm_t)):
                found_idx = i
                break

        if found_idx is not None and not _force_queue_refresh:
            _queue_current_idx = found_idx
            for i, it in enumerate(_queue_items):
                it["active"] = (i == found_idx)
            cur_it = _queue_items[found_idx]
            if thumbnail and not cur_it.get("thumbnail"):
                cur_it["thumbnail"] = thumbnail
            if dur_str and not cur_it.get("duration"):
                cur_it["duration"] = dur_str
            if cur_it.get("video_id"):
                _active_page_video_id = cur_it["video_id"]

            _record_listening_history_locked(
                cur_it.get("title", title),
                cur_it.get("artist") or art_str,
                cur_it.get("duration") or dur_str,
                cur_it.get("thumbnail") or thumbnail or "",
                cur_it.get("video_id") or _active_page_video_id,
            )
            return

        _force_queue_refresh = False

        meta = _lookup_track_meta(title, art_str)
        _queue_items.clear()
        _queue_items.append({
            "index": 0,
            "title": title,
            "artist": art_str or meta.get("artist", ""),
            "duration": dur_str or meta.get("duration", ""),
            "thumbnail": meta.get("thumbnail") or thumbnail or "",
            "video_id": browser_vid or meta.get("video_id", ""),
            "active": True,
        })
        _queue_current_idx = 0

        _record_listening_history_locked(
            title,
            art_str,
            dur_str,
            meta.get("thumbnail") or thumbnail or "",
            browser_vid or meta.get("video_id", ""),
        )

    if not _queue_fetch_in_progress:
        _queue_fetch_in_progress = True

        def _bg_fetch():
            global _queue_fetch_in_progress, _active_page_video_id, _queue_current_idx
            try:
                v_use, p_use = _get_chrome_ytm_url(force=True)
                tracks, act_idx = _fetch_ytm_playlist(
                    vid=v_use or _active_page_video_id,
                    pid=p_use or _active_page_playlist_id,
                    limit=QUEUE_LIMIT,
                    title_fallback=title,
                    artist_fallback=art_str,
                )
                if tracks:
                    with _queue_lock:
                        _queue_items.clear()
                        _queue_items.extend(tracks)
                        _queue_current_idx = act_idx
                        if 0 <= act_idx < len(tracks):
                            t_act = tracks[act_idx]
                            _active_page_video_id = t_act.get("video_id", "") or _active_page_video_id
                            _record_listening_history_locked(
                                t_act.get("title", title),
                                t_act.get("artist", art_str),
                                t_act.get("duration", dur_str),
                                t_act.get("thumbnail", thumbnail or ""),
                                t_act.get("video_id", _active_page_video_id),
                            )
            except Exception:
                pass
            finally:
                _queue_fetch_in_progress = False

        threading.Thread(target=_bg_fetch, name="ytm-queue-fetch", daemon=True).start()


async def _read_media_info():
    global _cached_thumb_key, _cached_thumb_data, _playback_track_title
    import datetime
    import modules.media as _media_mod
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions

    # Сначала синхронизируем живое состояние YouTube Music DOM (занимает ~0мс при кэше или ~150мс при обновлении)
    dom_state = _sync_ytm_live_session(force=False)
    dom_found = bool(dom_state.get("found"))
    dom_pb = dom_state.get("player_bar", {}) if dom_found else {}

    # 1. Пробуем WinRT SMTC с коротким таймаутом
    try:
        scored = await _media_mod._get_scored_media_sessions()
        if scored:
            status_map = {
                PlaybackStatus.PLAYING: "playing",
                PlaybackStatus.PAUSED: "paused",
                PlaybackStatus.STOPPED: "stopped",
                PlaybackStatus.CLOSED: "closed",
                PlaybackStatus.CHANGING: "changing",
                PlaybackStatus.OPENED: "opened",
            }

            for _, session, playback, status_val in scored[:3]:
                props = None
                try:
                    props = await asyncio.wait_for(session.try_get_media_properties_async(), timeout=0.5)
                except Exception:
                    props = None

                status = status_map.get(status_val, "unknown")
                title_str = (props.title or "") if props else ""
                artist_str = (props.artist or "") if props else ""
                album_str = (props.album_title or "") if props else ""

                if not title_str and status in ("closed", "stopped", "unknown"):
                    continue

                try:
                    app_id = session.source_app_user_model_id or ""
                except Exception:
                    app_id = ""

                is_chrome_ytm = dom_found and ("chrome" in app_id.lower() or not app_id)
                if is_chrome_ytm and dom_pb.get("title"):
                    title_str = dom_pb["title"]
                    artist_str = dom_pb.get("artist") or artist_str
                    album_str = dom_pb.get("album") or album_str or "YouTube Music"
                    if dom_pb.get("status") in ("playing", "paused"):
                        status = dom_pb["status"]

                thumbnail_data_url = None
                # Сначала проверяем высококачественную обложку из синхронизированной очереди YouTube Music
                meta_info = _lookup_track_meta(title_str, artist_str)
                if meta_info.get("thumbnail"):
                    thumbnail_data_url = meta_info["thumbnail"]

                if not thumbnail_data_url:
                    thumb_ref = props.thumbnail if props else None
                    track_key = (title_str, artist_str)
                    if track_key == _cached_thumb_key and _cached_thumb_data:
                        thumbnail_data_url = _cached_thumb_data
                    elif thumb_ref:
                        try:
                            stream = await asyncio.wait_for(thumb_ref.open_read_async(), timeout=0.5)
                            size = int(stream.size)
                            if size > 0:
                                buf = Buffer(size)
                                await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
                                reader = DataReader.from_buffer(buf)
                                raw = bytearray(buf.length)
                                reader.read_bytes(raw)
                                mime = getattr(stream, "content_type", None) or "image/jpeg"
                                thumbnail_data_url = f"data:{mime};base64," + base64.b64encode(bytes(raw)).decode("ascii")
                                _cached_thumb_key = track_key
                                _cached_thumb_data = thumbnail_data_url
                        except Exception:
                            _cached_thumb_key = track_key
                            _cached_thumb_data = None

                position = 0.0
                duration = 0.0
                if is_chrome_ytm and dom_pb.get("duration", 0) > 0:
                    duration = round(float(dom_pb["duration"]), 1)
                    position = round(max(0.0, min(float(dom_pb.get("position", 0.0)), duration)), 1)
                else:
                    try:
                        tl = session.get_timeline_properties()
                        if tl:
                            dur = tl.end_time.total_seconds() if tl.end_time else 0.0
                            pos = tl.position.total_seconds() if tl.position else 0.0
                            if status == "playing" and tl.last_updated_time and tl.last_updated_time.year > 1970:
                                now_utc = datetime.datetime.now(datetime.timezone.utc)
                                elapsed = (now_utc - tl.last_updated_time).total_seconds()
                                if 0 < elapsed < 3600:
                                    pos += elapsed
                            if dur > 0:
                                duration = round(dur, 1)
                                time_since_skip = time.time() - _last_manual_skip
                                if time_since_skip < 5.0 and pos >= dur - 1.5:
                                    position = round(min(time_since_skip, dur), 1)
                                else:
                                    position = round(max(0.0, min(pos, dur)), 1)
                    except Exception:
                        pass

                p_vol, p_muted = _get_player_audio_volume(app_id)

                if title_str and not dom_found:
                    try:
                        _sync_queue_with_playing(title_str, artist_str, album_str, duration, thumbnail_data_url)
                    except Exception:
                        pass

                if not thumbnail_data_url:
                    with _queue_lock:
                        if 0 <= _queue_current_idx < len(_queue_items):
                            thumbnail_data_url = _queue_items[_queue_current_idx].get("thumbnail") or None

                _playback_track_title = title_str
                return {
                    "available": True,
                    "status": status,
                    "title": title_str,
                    "artist": artist_str,
                    "album": album_str,
                    "thumbnail": thumbnail_data_url,
                    "app": app_id,
                    "position": position,
                    "duration": duration,
                    "volume": p_vol,
                    "muted": p_muted,
                    "mode": _media_mode["mode"],
                    "queue_version": _compute_queue_version(),
                    "queue_current_index": _queue_current_idx,
                    "queue_total": len(_queue_items),
                    "queue_source": _queue_source_name,
                    "video_id": _active_page_video_id,
                }
    except Exception as e:
        log_error("media_info_smtc", e)

    # 2. Если вкладка YouTube Music открыта в Chrome и прочитана через UIA DOM (даже если SMTC не ответил)
    if dom_found and dom_pb.get("title"):
        p_vol, p_muted = _get_player_audio_volume("chrome")
        t_str = dom_pb["title"]
        a_str = dom_pb.get("artist", "YouTube Music")
        al_str = dom_pb.get("album", "YouTube Music")
        meta_info = _lookup_track_meta(t_str, a_str)
        thumb_url = meta_info.get("thumbnail") or None
        if not thumb_url:
            with _queue_lock:
                if 0 <= _queue_current_idx < len(_queue_items):
                    thumb_url = _queue_items[_queue_current_idx].get("thumbnail") or None
        _playback_track_title = t_str
        return {
            "available": True,
            "status": dom_pb.get("status", "paused"),
            "title": t_str,
            "artist": a_str,
            "album": al_str,
            "thumbnail": thumb_url,
            "app": "Google Chrome",
            "position": round(float(dom_pb.get("position", 0.0)), 1),
            "duration": round(float(dom_pb.get("duration", 0.0)), 1),
            "volume": p_vol,
            "muted": p_muted,
            "mode": _media_mode["mode"],
            "queue_version": _compute_queue_version(),
            "queue_current_index": _queue_current_idx,
            "queue_total": len(_queue_items),
            "queue_source": _queue_source_name,
            "video_id": _active_page_video_id,
        }

    # 3. Фоллбэк по заголовкам окон + WASAPI
    try:
        fallback = _media_mod._extract_media_from_window_titles()
        if fallback.get("available"):
            if fallback.get("title"):
                try:
                    _sync_queue_with_playing(
                        fallback["title"],
                        fallback["artist"],
                        fallback.get("album", ""),
                        fallback.get("duration", 0.0),
                        fallback.get("thumbnail"),
                    )
                except Exception:
                    pass
            fallback["queue_version"] = _compute_queue_version()
            fallback["queue_current_index"] = _queue_current_idx
            fallback["queue_total"] = len(_queue_items)
            fallback["queue_source"] = _queue_source_name
            fallback["video_id"] = _active_page_video_id
            return fallback
    except Exception as e:
        log_error("media_info_fallback", e)

    return {"available": False}




def _get_queue_payload() -> dict:
    with _queue_lock:
        items = []
        for i, it in enumerate(_queue_items[:QUEUE_LIMIT]):
            items.append({
                "index": i,
                "title": it.get("title", "Без названия"),
                "artist": it.get("artist", ""),
                "duration": it.get("duration", ""),
                "thumbnail": it.get("thumbnail", ""),
                "video_id": it.get("video_id", ""),
                "active": bool(i == _queue_current_idx),
            })
        history_out = []
        for h_idx, h in enumerate(_listening_history[:LISTENING_HISTORY_MAX]):
            h_norm = _norm_title(h.get("title", ""))
            q_match = None
            for qi, qit in enumerate(items):
                qn = _norm_title(qit.get("title", ""))
                if qn == h_norm or (len(h_norm) >= 4 and len(qn) >= 4 and (h_norm in qn or qn in h_norm)):
                    q_match = qi
                    break
            history_out.append({
                "h_index": h_idx,
                "queue_index": q_match,
                "title": h.get("title", "Без названия"),
                "artist": h.get("artist", ""),
                "duration": h.get("duration", ""),
                "thumbnail": h.get("thumbnail", ""),
                "video_id": h.get("video_id", ""),
                "ts": h.get("ts", 0),
                "active": bool(h_idx == 0 and _playback_track_title and _norm_title(h.get("title", "")) == _norm_title(_playback_track_title)),
            })
        return {
            "current_index": _queue_current_idx,
            "queue_version": _compute_queue_version(),
            "queue_source": _queue_source_name,
            "playlist_id": _active_page_playlist_id,
            "video_id": _active_page_video_id,
            "tracks": items,
            "history": history_out,
            "mode": _media_mode.get("mode", "normal"),
        }




def _seek_tracked_position(pos: float):
    try:
        import modules.media as _media_mod
        _media_mod._seek_tracked_position(pos)
    except Exception:
        pass


async def _play_queue_index(
    target_idx: int | None = None,
    title: str = "",
    artist: str = "",
    video_id: str = "",
) -> tuple[bool, str]:
    """Переключает воспроизведение на выбранный трек в очереди.
    1) Сначала кликает по треку напрямую в DOM очереди YouTube Music через UIA (мгновенно, без перезагрузки страницы).
    2) При недоступности DOM использует бесшовный SMTC skip или переход по URL с сохранением плейлиста."""
    global _queue_current_idx, _last_manual_skip, _repeat_locked_title, _playback_track_title
    global _active_page_video_id, _active_page_playlist_id
    import modules.media as _media_mod

    if target_idx is not None and target_idx < 0:
        return False, "Некорректный индекс трека"

    actual_idx = None
    target_track = None
    with _queue_lock:
        if target_idx is not None and 0 <= target_idx < len(_queue_items):
            actual_idx = target_idx
            target_track = dict(_queue_items[target_idx])

        if target_track is None and video_id:
            for i, it in enumerate(_queue_items):
                if it.get("video_id") == video_id:
                    actual_idx = i
                    target_track = dict(it)
                    break

        if target_track is None and title:
            nt = _norm_title(title)
            for i, it in enumerate(_queue_items):
                it_norm = _norm_title(it.get("title", ""))
                if it_norm == nt or (len(nt) >= 4 and len(it_norm) >= 4 and (nt in it_norm or it_norm in nt)):
                    actual_idx = i
                    target_track = dict(it)
                    break

        if target_track is None:
            if title or video_id:
                target_track = {"title": title, "artist": artist, "video_id": video_id}
            else:
                return False, "Трек не найден в очереди"

        delta = (actual_idx - _queue_current_idx) if actual_idx is not None else None

    if is_safe_test_mode():
        return True, f"Воспроизводится: {target_track.get('title', '')}"

    # Случай 1: Нажат тот же самый трек -> перемотка в 0:00
    if delta == 0 and actual_idx is not None:
        try:
            session = await _media_mod._select_media_session()
            if session is not None:
                await session.try_change_playback_position_async(0)
                await session.try_play_async()
        except Exception:
            pass
        return True, f"Воспроизводится: {target_track.get('title', '')}"

    # Случай 2: Прямой клик по треку в живом DOM очереди YouTube Music (работает для любого индекса 0..200!)
    if actual_idx is not None or target_track.get("title"):
        if _uia_invoke_ytm_queue_play(actual_idx, target_track.get("title", "")):
            _last_manual_skip = time.time()
            _playback_track_title = target_track.get("title", "")
            _seek_tracked_position(0.0)
            with _queue_lock:
                if actual_idx is not None and 0 <= actual_idx < len(_queue_items):
                    _queue_current_idx = actual_idx
                    for i, tr in enumerate(_queue_items):
                        tr["active"] = (i == actual_idx)
                if target_track.get("video_id"):
                    _active_page_video_id = target_track["video_id"]
                _record_listening_history_locked(
                    target_track.get("title", ""),
                    target_track.get("artist", ""),
                    target_track.get("duration", ""),
                    target_track.get("thumbnail", ""),
                    target_track.get("video_id", ""),
                )
            invalidate_dom_cache()
            return True, f"Воспроизводится: {target_track.get('title', '')}"

    # Случай 3: Бесшовный пропуск по очереди через SMTC (|delta| <= 8)
    if delta is not None and 0 < abs(delta) <= 8:
        _last_manual_skip = time.time()
        _playback_track_title = target_track.get("title", "")
        _seek_tracked_position(0.0)

        session = await _media_mod._select_media_session()
        if delta < 0:
            if session:
                try:
                    await session.try_change_playback_position_async(0)
                except Exception:
                    pass
            for _ in range(abs(delta)):
                if session:
                    await session.try_skip_previous_async()
                else:
                    _send_media_click_or_key("prev")
                await asyncio.sleep(0.08)
        else:
            for _ in range(delta):
                if session:
                    await session.try_skip_next_async()
                else:
                    _send_media_key("next")
                await asyncio.sleep(0.06)

        with _queue_lock:
            _queue_current_idx = actual_idx
            for i, tr in enumerate(_queue_items):
                tr["active"] = (i == actual_idx)
            if target_track.get("video_id"):
                _active_page_video_id = target_track["video_id"]

        _record_listening_history_locked(
            target_track.get("title", ""),
            target_track.get("artist", ""),
            target_track.get("duration", ""),
            target_track.get("thumbnail", ""),
            target_track.get("video_id", ""),
        )
        return True, f"Воспроизводится: {target_track.get('title', '')}"

    # Случай 4: Переход по URL с сохранением плейлиста
    _last_manual_skip = time.time()
    _playback_track_title = target_track.get("title", "")
    _seek_tracked_position(0.0)

    vid = target_track.get("video_id") or video_id
    if not vid:
        found = _search_ytm_tracks(f"{target_track.get('title', '')} {target_track.get('artist', '')}".strip(), limit=3)
        if found:
            vid = found[0].get("videoId", "")
            target_track["video_id"] = vid

    with _queue_lock:
        if actual_idx is not None:
            _queue_current_idx = actual_idx
            for i, tr in enumerate(_queue_items):
                tr["active"] = (i == actual_idx)

    pid = _active_page_playlist_id
    if vid:
        _active_page_video_id = vid
        url = f"https://music.youtube.com/watch?v={vid}" + (f"&list={pid}" if pid else "")
        if _navigate_chrome_or_launch(url):
            return True, f"Воспроизводится: {target_track.get('title', '')}"

    query = f"{target_track.get('title', '')} {target_track.get('artist', '')}".strip()
    if query:
        search_url = f"https://music.youtube.com/search?q={urllib.parse.quote(query)}"
        if _navigate_chrome_or_launch(search_url):
            return True, f"Поиск трека: {query}"

    return True, f"Выбран трек: {target_track.get('title', '')}"


async def _play_history_track(h_index: int | None, title: str = "", artist: str = "", video_id: str = "") -> tuple[bool, str]:
    """Воспроизводит выбранный трек из истории прослушивания.
    Если этот трек есть в текущей очереди — переключается на него без сброса очереди!"""
    global _playback_track_title, _last_manual_skip, _active_page_video_id, _active_page_playlist_id
    global _queue_current_idx

    _load_listening_history()
    target_entry = None
    with _queue_lock:
        if h_index is not None and 0 <= h_index < len(_listening_history):
            target_entry = dict(_listening_history[h_index])
        elif title:
            nt = _norm_title(title)
            for it in _listening_history:
                if _norm_title(it.get("title", "")) == nt:
                    target_entry = dict(it)
                    break

    if target_entry is None:
        if title or video_id:
            target_entry = {"title": title, "artist": artist, "video_id": video_id}
        else:
            return False, "Трек не найден в истории"

    # Сначала проверяем, есть ли этот трек уже в активной очереди
    t_norm = _norm_title(target_entry.get("title", ""))
    q_match_idx = None
    with _queue_lock:
        for i, q_it in enumerate(_queue_items):
            if _norm_title(q_it.get("title", "")) == t_norm:
                q_match_idx = i
                break

    if q_match_idx is not None:
        return await _play_queue_index(
            target_idx=q_match_idx,
            title=target_entry.get("title", ""),
            artist=target_entry.get("artist", ""),
            video_id=target_entry.get("video_id", ""),
        )

    if is_safe_test_mode():
        return True, f"Воспроизводится: {target_entry.get('title', '')}"

    _last_manual_skip = time.time()
    _playback_track_title = target_entry.get("title", "")
    _seek_tracked_position(0.0)

    vid = video_id or target_entry.get("video_id", "")
    if not vid:
        found = _search_ytm_tracks(f"{target_entry.get('title', '')} {target_entry.get('artist', '')}".strip(), limit=3)
        if found and found[0].get("videoId"):
            vid = found[0]["videoId"]
            target_entry["video_id"] = vid

    if vid:
        _active_page_video_id = vid
        pid = _active_page_playlist_id or f"RDAMVM{vid}"
        url = f"https://music.youtube.com/watch?v={vid}&list={pid}"
        if _navigate_chrome_or_launch(url):
            return True, f"Воспроизводится: {target_entry.get('title', '')}"

    query = f"{target_entry.get('title', '')} {target_entry.get('artist', '')}".strip()
    if query:
        search_url = f"https://music.youtube.com/search?q={urllib.parse.quote(query)}"
        if _navigate_chrome_or_launch(search_url):
            return True, f"Поиск трека: {query}"

    return False, "Не удалось запустить трек из истории"


