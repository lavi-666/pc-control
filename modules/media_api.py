"""
PC Control — Модуль взаимодействия с API YouTube Music (Innertube / Search / Playlist).
"""

import json
import urllib.parse
import urllib.request


def _find_video_ids(obj, out: list[str]):
    if isinstance(obj, dict):
        vid = obj.get("videoId")
        if isinstance(vid, str) and len(vid) == 11:
            out.append(vid)
        for v in obj.values():
            _find_video_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _find_video_ids(v, out)


def _extract_search_tracks(d: dict, cache_meta_fn=None, parse_dur_fn=None) -> list[dict]:
    results = []

    def _walk(obj):
        if isinstance(obj, dict):
            if "musicResponsiveListItemRenderer" in obj:
                ren = obj["musicResponsiveListItemRenderer"]
                vid = ren.get("playlistItemData", {}).get("videoId")
                flex = ren.get("flexColumns", [])
                if not vid:
                    for fc in flex:
                        runs = fc.get("musicResponsiveListItemFlexColumnRenderer", {}).get("text", {}).get("runs", [])
                        for run in runs:
                            ep = run.get("navigationEndpoint", {})
                            we = ep.get("watchEndpoint", {})
                            if we.get("videoId"):
                                vid = we.get("videoId")
                                break
                        if vid:
                            break
                title = ""
                artist = ""
                duration = ""
                if len(flex) > 0:
                    runs = flex[0].get("musicResponsiveListItemFlexColumnRenderer", {}).get("text", {}).get("runs", [])
                    if runs:
                        title = "".join(r.get("text", "") for r in runs)
                if len(flex) > 1:
                    runs = flex[1].get("musicResponsiveListItemFlexColumnRenderer", {}).get("text", {}).get("runs", [])
                    if runs:
                        parts = [r.get("text", "") for r in runs if r.get("text", "").strip() not in ("•", "·", "")]
                        clean_parts = [p.strip() for p in parts if p.strip()]
                        if clean_parts:
                            if clean_parts[0].lower() in ("трек", "песня", "song", "video", "видео", "сингл") and len(clean_parts) > 1:
                                artist = clean_parts[1]
                            else:
                                artist = clean_parts[0]
                            for cp in reversed(clean_parts):
                                if ":" in cp and (parse_dur_fn(cp) > 0 if parse_dur_fn else True):
                                    duration = cp
                                    break
                thumbs = (
                    ren.get("thumbnail", {})
                    .get("musicThumbnailRenderer", {})
                    .get("thumbnail", {})
                    .get("thumbnails", [])
                )
                thumb_url = thumbs[-1].get("url", "") if thumbs else ""
                if vid and title:
                    if cache_meta_fn:
                        cache_meta_fn(title, artist, vid, thumb_url, duration)
                    results.append({
                        "videoId": vid,
                        "video_id": vid,
                        "title": title,
                        "artist": artist,
                        "duration": duration,
                        "thumbnail": thumb_url,
                    })
                return
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for it in obj:
                _walk(it)

    _walk(d)
    return results


def _search_ytm_tracks(query: str, limit: int = 10, cache_meta_fn=None, parse_dur_fn=None) -> list[dict]:
    """Выполняет прямой поиск треков через веб-клиент YouTube Music (Innertube API)."""
    q = (query or "").strip()
    if not q:
        return []
    url = "https://music.youtube.com/youtubei/v1/search?alt=json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://music.youtube.com/",
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "67",
        "X-YouTube-Client-Version": "1.20241001.01.00",
    }
    payload = {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": "1.20241001.01.00",
                "hl": "ru",
                "gl": "RU",
            }
        },
        "query": q,
        "params": "Eg-KAQwIABAAGAAgACgB",
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tracks = _extract_search_tracks(data, cache_meta_fn=cache_meta_fn, parse_dur_fn=parse_dur_fn)
            seen = set()
            unique = []
            for t in tracks:
                vid = t.get("videoId") or t.get("video_id")
                if vid and vid not in seen:
                    seen.add(vid)
                    unique.append(t)
                    if len(unique) >= limit:
                        break
            return unique
    except Exception:
        return []


def _parse_ytm_panel_items(contents: list, tracks: list[dict], limit: int, cache_meta_fn=None):
    for item in contents:
        if len(tracks) >= limit:
            break
        ren = item.get("playlistPanelVideoRenderer")
        if not ren:
            continue
        t_runs = ren.get("title", {}).get("runs", [])
        a_runs = ren.get("longBylineText", {}).get("runs", []) or ren.get("shortBylineText", {}).get("runs", [])
        l_runs = ren.get("lengthText", {}).get("runs", [])
        thumbs = ren.get("thumbnail", {}).get("thumbnails", [])
        t_title = "".join(x.get("text", "") for x in t_runs) if t_runs else ""
        t_artist = "".join(x.get("text", "") for x in a_runs) if a_runs else ""
        t_dur = "".join(x.get("text", "") for x in l_runs) if l_runs else ""
        t_thumb = thumbs[-1].get("url", "") if thumbs else ""
        t_vid = ren.get("videoId", "")
        if t_title:
            if cache_meta_fn:
                cache_meta_fn(t_title, t_artist, t_vid, t_thumb, t_dur)
            tracks.append({
                "title": t_title,
                "artist": t_artist,
                "duration": t_dur,
                "thumbnail": t_thumb,
                "video_id": t_vid,
            })
