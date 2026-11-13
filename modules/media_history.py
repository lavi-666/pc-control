"""
PC Control — Модуль персистентной истории прослушивания медиа.
"""

import json
import re
import time
from pathlib import Path

from core.config import BASE_DIR, DATA_DIR

LISTENING_HISTORY_FILE = DATA_DIR / "listening_history.json"
LISTENING_HISTORY_MAX = 100

_listening_history: list[dict] = []


def get_listening_history() -> list[dict]:
    return _listening_history


_YT_THUMB_ID_RE = re.compile(r"/vi(?:_webp)?/([A-Za-z0-9_-]{11})/")


def _sanitize_history(items: list[dict]) -> list[dict]:
    """Чинит записи, испорченные прежними версиями:
      * обложки data:URL (до ~100 КБ каждая) — ответ /media/queue раздувался до 2 МБ;
      * чужой video_id: запись наследовала его от «похожего» названия («Серия 1» → «Серия 10»),
        и «Играть из истории» включало другой трек. Если ссылка на обложку YouTube указывает
        на другой ролик — верим обложке; если один video_id у разных названий и обложка его
        не подтверждает — сбрасываем (трек найдётся поиском по названию)."""
    out = []
    for x in items:
        if not isinstance(x, dict) or not x.get("title"):
            continue
        h = dict(x)
        thumb = str(h.get("thumbnail") or "")
        if not thumb.startswith("http"):
            h["thumbnail"] = ""
        m = _YT_THUMB_ID_RE.search(thumb)
        if m and h.get("video_id") != m.group(1):
            h["video_id"] = m.group(1)
        out.append(h)
    titles_by_vid: dict[str, set] = {}
    for h in out:
        vid = h.get("video_id") or ""
        if vid:
            titles_by_vid.setdefault(vid, set()).add(str(h.get("title", "")).strip().lower())
    for h in out:
        vid = h.get("video_id") or ""
        if vid and len(titles_by_vid.get(vid, ())) > 1 and f"/{vid}/" not in str(h.get("thumbnail") or ""):
            h["video_id"] = ""
    return out


def _load_listening_history_impl(cache_meta_fn=None):
    global _listening_history
    if not LISTENING_HISTORY_FILE.exists():
        return
    try:
        data = json.loads(LISTENING_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _listening_history[:] = _sanitize_history(data)[:LISTENING_HISTORY_MAX]
            if cache_meta_fn:
                for h in _listening_history:
                    cache_meta_fn(
                        h.get("title", ""),
                        h.get("artist", ""),
                        h.get("video_id", ""),
                        h.get("thumbnail", ""),
                        h.get("duration", ""),
                    )
    except Exception:
        pass


def _save_listening_history_locked_impl():
    try:
        import os
        payload = json.dumps(_listening_history[:LISTENING_HISTORY_MAX], ensure_ascii=False, indent=2)
        tmp_file = LISTENING_HISTORY_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(payload, encoding="utf-8")
        os.replace(tmp_file, LISTENING_HISTORY_FILE)
    except Exception:
        pass


def _record_listening_history_locked_impl(
    title: str,
    artist: str = "",
    duration_str: str = "",
    thumbnail: str = "",
    video_id: str = "",
    norm_title_fn=None,
    clean_thumb_fn=None,
    lookup_meta_fn=None,
):
    norm_t = norm_title_fn(title) if norm_title_fn else title.strip().lower()
    if not norm_t:
        return

    clean_t = clean_thumb_fn(thumbnail) if clean_thumb_fn else thumbnail
    if clean_t and clean_t.startswith("data:") and lookup_meta_fn:
        meta = lookup_meta_fn(title, artist)
        if meta.get("thumbnail", "").startswith("http"):
            clean_t = meta["thumbnail"]
    if clean_t and not clean_t.startswith("http"):
        clean_t = ""  # data:URL в файл истории не пишем (каждая до ~100 КБ)

    if _listening_history:
        top_norm = norm_title_fn(_listening_history[0].get("title", "")) if norm_title_fn else _listening_history[0].get("title", "").strip().lower()
        if top_norm == norm_t:
            top = _listening_history[0]
            changed = False
            if artist and (not top.get("artist") or top.get("artist") == "YouTube Music"):
                top["artist"] = artist
                changed = True
            if duration_str and not top.get("duration"):
                top["duration"] = duration_str
                changed = True
            if clean_t and (not top.get("thumbnail") or (top.get("thumbnail", "").startswith("data:") and clean_t.startswith("http"))):
                top["thumbnail"] = clean_t
                changed = True
            if video_id and not top.get("video_id"):
                top["video_id"] = video_id
                changed = True
            if changed:
                _save_listening_history_locked_impl()
            return

    # Прежняя запись того же трека — только при точном совпадении названия. Раньше хватало
    # вхождения строки («Серия 1» внутри «Серия 10», «Intro» внутри «Intro (Live)»): чужая запись
    # удалялась, а новая наследовала её video_id — «Играть из истории» включало другой трек.
    prev_entry = None
    for idx in range(len(_listening_history) - 1, -1, -1):
        it = _listening_history[idx]
        it_norm = norm_title_fn(it.get("title", "")) if norm_title_fn else it.get("title", "").strip().lower()
        if it_norm == norm_t:
            prev_vid = it.get("video_id") or ""
            if video_id and prev_vid and prev_vid != video_id:
                continue  # то же название, другой ролик — это другая запись
            prev_entry = _listening_history.pop(idx)
            break

    entry = {
        "title": title,
        "artist": artist or (prev_entry.get("artist", "") if prev_entry else ""),
        "duration": duration_str or (prev_entry.get("duration", "") if prev_entry else ""),
        "thumbnail": clean_t or (prev_entry.get("thumbnail", "") if prev_entry else ""),
        "video_id": video_id or (prev_entry.get("video_id", "") if prev_entry else ""),
        "ts": int(time.time()),
    }
    _listening_history.insert(0, entry)
    if len(_listening_history) > LISTENING_HISTORY_MAX:
        del _listening_history[LISTENING_HISTORY_MAX:]
    _save_listening_history_locked_impl()
