"""
PC Control — медиаплеер (новый движок).

Источники:
  * tools/media_helper.exe (Rust): медиасессии Windows — любой плеер (Chrome, Spotify, Яндекс
    Музыка, AIMP, «Медиаплеер»…), громкость именно этого приложения;
  * расширение Chrome «PC Control — YouTube Music» (через helper): точное состояние YouTube
    Music, очередь, повтор/перемешивание, громкость плеера на странице.

Адреса и формат ответов — те же, что у прежнего modules/media.py, поэтому веб-пульт и APK
работают без изменений. Прежний движок остаётся запасным: "media_engine": "legacy" в config.json.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import threading
import time

from flask import Blueprint, g, has_request_context, jsonify, request

from core.auth import check_token
from core.config import BASE_DIR, is_safe_test_mode, load_app_config
from core.logger import log_action, log_error
from modules.media_api import _search_ytm_tracks
from modules.media_history import (
    LISTENING_HISTORY_MAX,
    _listening_history,
    _load_listening_history_impl,
    _record_listening_history_locked_impl,
)
from modules.player_helper import MediaHelper

HELPER_EXE = BASE_DIR / "tools" / "media_helper.exe"
DEFAULT_BRIDGE_PORT = 5017
BROWSER_IDS = ("chrome", "msedge", "edge", "firefox", "brave", "opera", "vivaldi", "yandex", "308046b0af4a39cb")
EXTENSION_HINT = "Для очереди YouTube Music установите расширение «PC Control — YouTube Music» (папка chrome_extension)"

player_bp = Blueprint("media", __name__)  # имя "media" — как у прежнего blueprint'а
_helper: MediaHelper | None = None
_hist_lock = threading.Lock()
_last_hist_key = {"key": ""}
_ytm_shuffle = {"on": False}


# ---------- выбор движка ----------
def _bridge_port() -> int:
    try:
        port = int((load_app_config() or {}).get("media_bridge_port") or DEFAULT_BRIDGE_PORT)
        return port if 1024 <= port <= 65535 else DEFAULT_BRIDGE_PORT
    except Exception:
        return DEFAULT_BRIDGE_PORT


def native_engine_reason() -> str | None:
    """None — новый движок можно включать; иначе причина, почему остаётся прежний."""
    if platform.system() != "Windows":
        return "not windows"
    if is_safe_test_mode():
        return "safe test mode"
    try:
        if str((load_app_config() or {}).get("media_engine", "native")).lower() == "legacy":
            return "config media_engine=legacy"
    except Exception:
        pass
    if not HELPER_EXE.exists():
        return f"{HELPER_EXE.name} not found"
    return None


def select_media_blueprint():
    """Возвращает blueprint медиаплеера: новый (helper + расширение) или прежний."""
    global _helper
    reason = native_engine_reason()
    if reason is not None:
        from modules.media import media_bp as legacy_bp
        print(f"[media] legacy engine ({reason})")
        return legacy_bp
    _load_listening_history_impl()
    _helper = MediaHelper(HELPER_EXE, _bridge_port())
    _helper.add_listener(_on_state_change)
    _helper.start()
    print(f"[media] native engine: {HELPER_EXE.name}, extension bridge ws://127.0.0.1:{_helper.ws_port}")
    return player_bp


# ---------- общее ----------
def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", " ", (s or "").lower()).strip()


def _is_browser(app_id: str | None) -> bool:
    a = (app_id or "").lower()
    return any(b in a for b in BROWSER_IDS)


def _app_label(app_id: str) -> str:
    a = (app_id or "").strip()
    if "!" in a:
        a = a.split("!")[-1]
    a = a.rsplit("\\", 1)[-1]
    if a.lower().endswith(".exe"):
        a = a[:-4]
    if re.fullmatch(r"[0-9A-Fa-f]{16}", a):
        return "Firefox"
    return a.split(".")[-1] if "." in a else a


def _live_pos(pos, dur, playing: bool, since: float) -> float:
    p = float(pos or 0)
    if playing and since:
        p += max(0.0, time.time() - since)
    d = float(dur or 0)
    if d > 0:
        p = min(p, d)
    return round(max(0.0, p), 1)


def _vol(v) -> int:
    """Громкость 0–100 из состояния вкладки/helper'а. Значение приходит со страницы YouTube Music:
    NaN/строка раньше давали ValueError — /media/now отвечал 500 на каждом опросе."""
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return 100
        return max(0, min(100, int(round(f))))
    except (TypeError, ValueError):
        return 100


def _parse_dur(s) -> float:
    """«3:05» / «1:02:03» → секунды (0 — не удалось)."""
    try:
        parts = [int(p) for p in str(s or "").strip().split(":")]
    except ValueError:
        return 0.0
    if not 2 <= len(parts) <= 3 or any(p < 0 for p in parts):
        return 0.0
    total = 0
    for p in parts:
        total = total * 60 + p
    return float(total)


# Состояние играющей вкладки свежее, если пришло за последние 8 с (иначе позиция/трек могли
# уйти). На паузе состояние не меняется, а Chrome сильно замедляет таймеры фоновой вкладки
# (раз в минуту) — раньше через 8 с паузы пульт терял YouTube Music: пропадали очередь,
# индекс трека и режимы, команды уходили не туда.
YTM_FRESH_PLAYING = 8.0
YTM_FRESH_PAUSED = 600.0


def _sources():
    """(snap, ytm|None, gs|None, use_ytm)"""
    snap = _helper.snapshot()
    now = time.time()
    gs = snap["gsmtc"] if snap["gsmtc"].get("available") else None
    ytm = snap["ytm"]
    if ytm:
        max_age = YTM_FRESH_PLAYING if ytm.get("status") == "playing" else YTM_FRESH_PAUSED
        if not (snap["ext_connected"] and now - snap["ytm_at"] < max_age and ytm.get("title")):
            ytm = None
    # YouTube Music на паузе, а браузер играет ДРУГОЕ (ролик YouTube в соседней вкладке) —
    # показываем и переключаем то, что реально звучит
    gs_is_ytm = bool(ytm) and gs is not None and _is_browser(gs.get("app_id")) and (
        not gs.get("title") or _norm(gs.get("title")) == _norm(ytm.get("title")))
    use_ytm = bool(ytm) and (
        ytm.get("status") == "playing" or gs is None or gs.get("status") != "playing" or gs_is_ytm
    )
    # QA P-2: when nothing plays, Play/Pause must resume what played LAST. Before, pausing a YouTube
    # video in Chrome and pressing Play started YouTube Music (paused YTM always won).
    ytm_playing = bool(ytm) and ytm.get("status") == "playing"
    gs_playing = gs is not None and gs.get("status") == "playing"
    if ytm_playing:
        _last_active["src"] = "ytm"
    elif gs_playing and not gs_is_ytm:
        _last_active["src"] = "gs"
    if use_ytm and not ytm_playing and not gs_playing and gs is not None and not gs_is_ytm \
            and _last_active["src"] == "gs":
        use_ytm = False
    return snap, ytm, gs, use_ytm


_last_active = {"src": ""}  # source that played last: "ytm" / "gs" (QA P-2)


def _ytm_duration(ytm: dict, queue: list) -> float:
    """Длительность трека YouTube Music. Плеер на странице, пока трек не загрузился целиком,
    отдаёт растущее значение (у трека 2:53 видели 1:49 → 2:19 → 2:52): ползунок «прыгал»,
    а в историю записывалась неверная длительность. Длительность из очереди — точная."""
    d = float(ytm.get("duration") or 0)
    cur = ytm.get("queue_current_index", -1)
    if isinstance(cur, int) and not isinstance(cur, bool) and 0 <= cur < len(queue):
        item = queue[cur] if isinstance(queue[cur], dict) else {}
        vid = item.get("video_id") or ""
        if not vid or not ytm.get("video_id") or vid == ytm.get("video_id"):
            qd = _parse_dur(item.get("duration"))
            if qd > d + 1.5:
                d = qd
    return round(d, 1)


def _queue_version(snap: dict, ytm: dict | None) -> str:
    ids = "|".join(str(t.get("video_id") or t.get("title") or "") for t in snap["ytm_queue"])
    cur = ytm.get("queue_current_index", -1) if ytm else -1
    return hashlib.md5(f"{ids}#{cur}".encode("utf-8", "ignore")).hexdigest()[:12]


def _current() -> dict:
    snap, ytm, gs, use_ytm = _sources()
    if use_ytm:
        playing = ytm.get("status") == "playing"
        rep = ytm.get("repeat")
        mode = "repeat" if rep == "one" else ("shuffle" if _ytm_shuffle["on"] else "normal")
        ad = bool(ytm.get("ad"))
        # Во время рекламы длительность — у рекламы, не у трека из очереди
        dur = round(float(ytm.get("duration") or 0), 1) if ad else _ytm_duration(ytm, snap["ytm_queue"])
        return {
            "available": True,
            "source": "youtube-music",
            "app": "YouTube Music",
            "ad": ad,
            "title": ytm.get("title") or "",
            "artist": "Реклама" if ad else (ytm.get("artist") or ""),
            "album": ytm.get("album") or "",
            "thumbnail": ytm.get("thumbnail") or "",
            "video_id": ytm.get("video_id") or "",
            "status": "playing" if playing else "paused",
            "position": _live_pos(ytm.get("position"), dur, playing, snap["ytm_at"]),
            "duration": dur,
            "volume": _vol(ytm.get("volume")),
            "muted": bool(ytm.get("muted")),
            "volume_ok": True,
            "mode": mode,
            "mode_backend": "youtube-music",
            "queue_version": _queue_version(snap, ytm),
            "queue_current_index": ytm.get("queue_current_index", -1),
            "queue_total": len(snap["ytm_queue"]),
            "extension_connected": True,
        }
    if gs:
        playing = gs.get("status") == "playing"
        modes = gs.get("modes") or {}
        if modes.get("repeat") == "one":
            mode = "repeat"
        elif modes.get("shuffle"):
            mode = "shuffle"
        else:
            mode = "normal"
        return {
            "available": True,
            "source": "windows",
            "app": _app_label(gs.get("app_id") or ""),
            "app_id": gs.get("app_id") or "",
            "title": gs.get("title") or "",
            "artist": gs.get("artist") or "",
            "album": gs.get("album") or "",
            "thumbnail": snap["thumbnail"] or "",
            "status": "playing" if playing else "paused",
            "position": _live_pos(gs.get("position"), gs.get("duration"), playing, snap["gsmtc_at"]),
            "duration": round(float(gs.get("duration") or 0), 1),
            "volume": _vol(gs.get("volume")),
            "muted": bool(gs.get("muted")),
            "volume_ok": bool(gs.get("volume_ok")),
            "mode": mode,
            "mode_backend": "smtc" if (modes.get("shuffle_enabled") or modes.get("repeat_enabled")) else "none",
            "can_seek": bool(modes.get("can_seek")),
            "queue_version": _queue_version(snap, None),
            "queue_current_index": -1,
            "queue_total": len(snap["ytm_queue"]) if snap["ext_connected"] else 0,
            "extension_connected": bool(snap["ext_connected"]),
        }
    return {"available": False, "extension_connected": bool(snap["ext_connected"])}


HIST_MIN_LISTEN = 10.0           # трек попадает в историю, когда реально прослушан (а не пролистан)
HIST_MAX_BROWSER_VIDEO = 20 * 60  # фильмы/серии в браузере (не музыка) в историю не пишем


def _on_state_change() -> None:
    """История прослушивания: запись играющего трека, когда он прослушан хотя бы 10 с.
    Раньше записывалось всё подряд в момент смены трека: пролистанные треки, рекламные ролики
    браузера, серии с сайтов — и с длительностью, которую плеер ещё не успел узнать."""
    try:
        st = _current()
        if not (st.get("available") and st.get("status") == "playing" and st.get("title")) or st.get("ad"):
            return
        key = _norm(st["title"]) + "|" + _norm(st.get("artist", ""))
        if key == _last_hist_key["key"]:
            return
        dur = float(st.get("duration") or 0)
        if st.get("source") == "windows" and _is_browser(st.get("app_id")) and dur > HIST_MAX_BROWSER_VIDEO:
            return
        need = min(HIST_MIN_LISTEN, dur * 0.5) if dur > 0 else HIST_MIN_LISTEN
        if float(st.get("position") or 0) < need:
            return
        _last_hist_key["key"] = key
        dur_str = f"{int(dur // 60)}:{int(dur % 60):02d}" if dur > 0 else ""
        thumb = st.get("thumbnail") or ""
        with _hist_lock:
            _record_listening_history_locked_impl(
                title=st["title"],
                artist=st.get("artist") or st.get("album") or "",
                duration_str=dur_str,
                thumbnail=thumb if thumb.startswith("http") else "",
                video_id=st.get("video_id") or "",
                norm_title_fn=_norm,
            )
    except Exception as e:
        log_error("media_history", e)


# Заголовок панели очереди YouTube Music — «Playing from» / «Воспроизводится из» без названия
# плейлиста (расширение 1.0.0 брало его вместо названия): показывали «Playing from · 65 / 99»
_GENERIC_QUEUE_LABELS = {"playing from", "воспроизводится из", "источник", "відтворюється з", "up next", "далее"}


def _queue_source_label(s) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if not s or s.lower().rstrip(":") in _GENERIC_QUEUE_LABELS:
        return ""
    return s[:120]


def _queue_payload() -> dict:
    snap, ytm, _gs, _use = _sources()
    queue = snap["ytm_queue"] if snap["ext_connected"] else []
    cur = ytm.get("queue_current_index", -1) if ytm else -1
    tracks = [
        {
            "index": i,
            "title": t.get("title") or "Без названия",
            "artist": t.get("artist") or "",
            "duration": t.get("duration") or "",
            "thumbnail": t.get("thumbnail") or "",
            "video_id": t.get("video_id") or "",
            "active": i == cur,
        }
        for i, t in enumerate(queue[:500])
    ]
    cur_state = _current()
    now_title = _norm(cur_state.get("title", "")) if cur_state.get("available") else ""
    by_title: dict[str, int] = {}
    for t in tracks:
        by_title.setdefault(_norm(t["title"]), t["index"])
    history = []
    with _hist_lock:
        hist = list(_listening_history[:LISTENING_HISTORY_MAX])
    for h_idx, h in enumerate(hist):
        hn = _norm(h.get("title", ""))
        thumb = str(h.get("thumbnail") or "")
        history.append({
            "h_index": h_idx,
            "queue_index": by_title.get(hn),
            "title": h.get("title", "Без названия"),
            "artist": h.get("artist", ""),
            "duration": h.get("duration", ""),
            # data:URL прежних версий раздували ответ до 2 МБ (его запрашивают при каждой смене трека)
            "thumbnail": thumb if thumb.startswith("http") else "",
            "video_id": h.get("video_id", ""),
            "ts": h.get("ts", 0),
            "active": h_idx == 0 and bool(now_title) and hn == now_title,
        })
    return {
        "current_index": cur,
        "queue_version": _queue_version(snap, ytm),
        "queue_source": _queue_source_label((ytm or {}).get("queue_source")) or ("YouTube Music" if tracks else ""),
        "playlist_id": (ytm or {}).get("playlist_id", ""),
        "video_id": (ytm or {}).get("video_id", ""),
        "tracks": tracks,
        "history": history,
        "mode": cur_state.get("mode", "normal"),
        "extension_connected": bool(snap["ext_connected"]),
    }


def _json_body() -> dict:
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _int_or_none(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return None


_BAD = object()


def _parse_mute(v):
    """mute: True/False/None (не указан) или _BAD. Строка "false" раньше давала bool("false") → True."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
    return _BAD


def _ext_not_delivered(msg: str, res: dict | None = None) -> bool:
    """Команда точно не дошла до вкладки YouTube Music — можно выполнить её через Windows,
    не рискуя выполнить дважды (тайм-аут сюда не относится: команда могла сработать)."""
    # Расширение 1.1.2+ сообщает код: "not_delivered" — вкладке не отправлено; "interrupted"
    # (вкладку закрыли посреди команды) и "timeout" — команда могла выполниться
    code = (res or {}).get("code") if isinstance(res, dict) else None
    if code:
        return code == "not_delivered"
    # Старое расширение / helper: по тексту. «Вкладка … недоступна» старое расширение отвечало
    # и когда вкладку закрыли посреди команды — безопаснее не повторять через Windows
    m = (msg or "").lower()
    return any(s in m for s in ("не подключено", "отключилось", "не открыта", "не запущен"))


def _ytm_or_error(payload: dict, timeout: float = 5.0):
    """Команда расширению. Возвращает (ok, message, result)."""
    # Момент ОТПРАВКИ: вкладка присылает новое состояние иногда раньше, чем ответ на команду
    # доходит до сервера — ожидание «состояния новее ответа» тогда зря длилось весь тайм-аут
    if has_request_context():
        g.ytm_sent_at = time.time()
    res = _helper.ytm_command(payload, timeout=timeout)
    return bool(res.get("ok")), str(res.get("message") or ""), res


def _wait_new_state(timeout: float) -> bool:
    """Ждёт состояние вкладки, пришедшее после отправки последней команды этого запроса."""
    since = getattr(g, "ytm_sent_at", None) if has_request_context() else None
    return _helper.wait_ytm_state(time.time() if since is None else since, timeout=timeout)


def _open_in_browser(video_id: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id or ""):
        return False
    try:
        os.startfile(f"https://music.youtube.com/watch?v={video_id}")  # noqa: S606 — фиксированный https-адрес
        return True
    except Exception as e:
        log_error("media_open_browser", e)
        return False


def _unauthorized():
    return jsonify({"message": "Неверный пароль"}), 401


# ---------- маршруты ----------
@player_bp.route("/media/now")
def media_now():
    if not check_token():
        return _unauthorized()
    return jsonify(_current())


@player_bp.route("/media/status")
def media_engine_status():
    if not check_token():
        return _unauthorized()
    snap = _helper.snapshot()
    ext_ver = str((snap["ytm"] or {}).get("ext_version") or "") if snap["ext_connected"] else ""
    expected = _extension_disk_version()
    return jsonify({
        "engine": "native",
        "helper_running": _helper.running,
        "helper_version": _helper.version,
        "helper_restarts": _helper.restarts,
        "helper_last_error": _helper.last_error,
        "extension_connected": snap["ext_connected"],
        # Версия загруженного в Chrome расширения (1.0.0 её не сообщает) и версия в папке
        # chrome_extension: если отличаются — расширение нужно перезагрузить в chrome://extensions
        "extension_version": ext_ver,
        "extension_expected_version": expected,
        "extension_outdated": bool(snap["ext_connected"] and expected and ext_ver != expected),
        # Диагностика: давность последнего состояния вкладки YouTube Music и её статус
        "extension_state_age": round(time.time() - snap["ytm_at"], 1) if snap["ytm"] else None,
        "extension_tab_status": str((snap["ytm"] or {}).get("status") or ""),
        "extension_tab_has_title": bool((snap["ytm"] or {}).get("title")),
        "bridge_port": _helper.ws_port,
        "windows_session": (snap["gsmtc"] or {}).get("app_id", ""),
    })


def _extension_disk_version() -> str:
    try:
        return str(json.loads((BASE_DIR / "chrome_extension" / "manifest.json").read_text(encoding="utf-8")).get("version") or "")
    except Exception:
        return ""


VALID_ACTIONS = {"play", "pause", "playpause", "play_pause", "next", "prev", "previous", "stop", "seek"}


@player_bp.route("/media/control", methods=["POST"])
def media_control():
    if not check_token():
        return _unauthorized()
    data = _json_body()
    action = str(data.get("action", "")).strip().lower()
    if action not in VALID_ACTIONS:
        return jsonify({"message": "Неизвестное действие медиаплеера"}), 400
    position = None
    if action == "seek":
        raw = data.get("position")
        try:
            position = float(raw) if raw is not None and not isinstance(raw, bool) else None
        except (TypeError, ValueError, OverflowError):
            position = None
        if position is None or math.isnan(position) or math.isinf(position):
            return jsonify({"message": "Некорректная позиция перемотки"}), 400
        position = max(0.0, position)

    _snap, _ytm, _gs, use_ytm = _sources()
    if use_ytm:
        ok, msg, res = _ytm_or_error({"action": action, "position": position}, timeout=4.0)
        if ok:
            # Ответ — после нового состояния вкладки: пульт сразу запрашивает /media/now и раньше
            # ещё ~2,5 с показывал прежний трек/статус после «Далее» и «Пауза»
            _wait_new_state(0.8)
            log_action("media_" + action, {"via": "youtube-music"})
            return jsonify({"message": "ok"})
        if not _ext_not_delivered(msg, res):
            return jsonify({"message": msg or "Команда не выполнена"}), 400
    res = _helper.request({"cmd": "control", "action": action, "position": position}, timeout=4.0)
    if res.get("ok"):
        log_action("media_" + action, {"via": "windows"})
        return jsonify({"message": "ok"})
    return jsonify({"message": res.get("message") or "Команда не выполнена"}), 400


@player_bp.route("/media/volume", methods=["POST"])
def media_volume():
    if not check_token():
        return _unauthorized()
    data = _json_body()
    pct = data.get("percent")
    parsed = None
    if pct is not None:
        try:
            if isinstance(pct, bool):
                raise ValueError
            v = float(pct)
            if math.isnan(v) or math.isinf(v):
                raise ValueError
            parsed = max(0, min(100, int(round(v))))
        except (TypeError, ValueError, OverflowError):
            return jsonify({"message": "Некорректный процент громкости плеера"}), 400
    mute = _parse_mute(data.get("mute"))
    if mute is _BAD:
        return jsonify({"message": "Некорректное значение mute (ожидается true/false)"}), 400
    if parsed is None and mute is None:
        return jsonify({"message": "Не указана громкость"}), 400

    _snap, _ytm, gs, use_ytm = _sources()
    if use_ytm:
        ok, msg, res = _ytm_or_error({"action": "volume", "percent": parsed, "mute": mute}, timeout=3.0)
        if ok:
            p, m = res.get("percent", parsed), bool(res.get("muted", mute))
            _wait_new_state(0.6)  # чтобы /media/now сразу показал новое значение
            log_action("media_volume", {"percent": p, "muted": m, "via": "youtube-music"})
            return jsonify({"percent": p, "muted": m, "message": f"Громкость YouTube Music: {p}%"})
        if not _ext_not_delivered(msg, res):
            return jsonify({"message": msg or "Громкость не изменена"}), 400
    res = _helper.request({"cmd": "volume", "percent": parsed, "mute": mute, "app": (gs or {}).get("app_id", "")}, timeout=3.0)
    if res.get("ok"):
        log_action("media_volume", {"percent": res.get("percent"), "muted": res.get("muted"), "via": "windows"})
        return jsonify({"percent": res.get("percent"), "muted": res.get("muted"), "message": res.get("message")})
    return jsonify({"message": res.get("message") or "Громкость не изменена"}), 400


@player_bp.route("/media/mode", methods=["POST"])
def media_mode():
    if not check_token():
        return _unauthorized()
    data = _json_body()
    mode = str(data.get("mode", "")).strip().lower()
    if mode not in ("normal", "repeat", "shuffle"):
        return jsonify({"message": "Неизвестный режим"}), 400
    labels = {
        "normal": "Обычный порядок воспроизведения",
        "repeat": "Повтор текущего трека включён",
        "shuffle": "Очередь перемешана",
    }
    _snap, _ytm, _gs, use_ytm = _sources()
    if use_ytm:
        if mode == "shuffle":
            ok, msg, _ = _ytm_or_error({"action": "shuffle"})
            if ok:
                _ytm_or_error({"action": "repeat", "mode": "none"})
        else:
            ok, msg, _ = _ytm_or_error({"action": "repeat", "mode": "one" if mode == "repeat" else "none"})
        if not ok:
            return jsonify({"message": msg or "Режим не изменён"}), 400
        _ytm_shuffle["on"] = mode == "shuffle"
        _wait_new_state(0.8)
        log_action("media_mode", {"mode": mode, "backend": "youtube-music"})
        return jsonify({"mode": mode, "backend": "youtube-music", "message": labels[mode] + " (в YouTube Music)"})
    res = _helper.request({"cmd": "mode", "mode": mode})
    if res.get("ok"):
        log_action("media_mode", {"mode": mode, "backend": "smtc"})
        return jsonify({"mode": mode, "backend": "smtc", "message": labels[mode] + " (в плеере)"})
    return jsonify({"mode": _current().get("mode", "normal"), "message": res.get("message") or "Режим не изменён"}), 400


@player_bp.route("/media/queue")
def media_queue():
    if not check_token():
        return _unauthorized()
    return jsonify(_queue_payload())


@player_bp.route("/media/queue/refresh", methods=["POST"])
def media_queue_refresh():
    if not check_token():
        return _unauthorized()
    if _helper.snapshot()["ext_connected"]:
        ok, _msg, _ = _ytm_or_error({"action": "refresh"}, timeout=3.0)
        # Состояние с очередью приходит отдельным сообщением через ~0,25 с после ответа
        # (раньше ждали 0,15 с и отдавали прежнюю очередь)
        if ok:
            _wait_new_state(1.0)
    return jsonify(_queue_payload())


def _queue_cmd(action: str, ok_text: str):
    data = _json_body()
    idx = _int_or_none(data.get("index"))
    if idx is None or idx < 0:
        return jsonify({"message": "Некорректный индекс трека"}), 400
    snap = _helper.snapshot()
    if not snap["ext_connected"]:
        return jsonify({"message": EXTENSION_HINT}), 400
    title = str(data.get("title", "")).strip()
    video_id = str(data.get("video_id", "")).strip()
    if not video_id and idx < len(snap["ytm_queue"]):
        # Веб-пульт/APK для «удалить» и «следующим» присылают только индекс и название —
        # по video_id расширение находит именно этот трек, даже если очередь успела сдвинуться
        item = snap["ytm_queue"][idx] if isinstance(snap["ytm_queue"][idx], dict) else {}
        if not title or _norm(item.get("title", "")) == _norm(title):
            video_id = str(item.get("video_id") or "")
            title = title or str(item.get("title") or "")
    ok, msg, _ = _ytm_or_error({
        "action": action,
        "index": idx,
        "video_id": video_id,
        "title": title,
    }, timeout=6.0)
    if not ok:
        return jsonify({"message": msg or "Не выполнено"}), 400
    _wait_new_state(1.2)
    log_action("media_" + action, {"index": idx, "title": title[:80]})
    payload = _queue_payload()
    payload["message"] = ok_text.format(title=title or "трек")
    return jsonify(payload)


@player_bp.route("/media/queue/play", methods=["POST"])
def media_queue_play():
    if not check_token():
        return _unauthorized()
    return _queue_cmd("queue_play", "Играет: {title}")


@player_bp.route("/media/queue/remove", methods=["POST"])
def media_queue_remove():
    if not check_token():
        return _unauthorized()
    return _queue_cmd("queue_remove", "Удалено из очереди: {title}")


@player_bp.route("/media/queue/play_next", methods=["POST"])
def media_queue_play_next():
    if not check_token():
        return _unauthorized()
    return _queue_cmd("queue_play_next", "Включится следующим: {title}")


@player_bp.route("/media/search")
def media_search():
    if not check_token():
        return _unauthorized()
    q = str(request.args.get("q", "")).strip()
    if not q:
        return jsonify({"tracks": []})
    return jsonify({"tracks": _search_ytm_tracks(q, limit=12)})


def _play_or_add(video_id: str, title: str, play: bool):
    """Играть сейчас / поставить следующим трек по video_id. Возвращает (ok, message)."""
    snap = _helper.snapshot()
    if snap["ext_connected"]:
        ok, msg, res = _ytm_or_error({"action": "add", "video_id": video_id, "position": "next", "play": play, "title": title}, timeout=8.0)
        if ok:
            return True, (f"Играет: {title}" if play else f"Включится следующим: {title}")
        # Тайм-аут/ошибка вкладки: команда могла выполниться — открывать трек ещё и в новой
        # вкладке браузера нельзя (раньше трек начинал играть дважды)
        if not play or not _ext_not_delivered(msg, res):
            return False, msg or "Не удалось добавить в очередь"
    if play and _open_in_browser(video_id):
        return True, f"Открыто в YouTube Music: {title}"
    return False, EXTENSION_HINT


@player_bp.route("/media/queue/add", methods=["POST"])
def media_queue_add():
    if not check_token():
        return _unauthorized()
    data = _json_body()
    query = str(data.get("query", "")).strip()
    title = str(data.get("title", "")).strip()
    artist = str(data.get("artist", "")).strip()
    video_id = str(data.get("video_id", "")).strip()
    play_now = bool(data.get("play_now", False))
    if not video_id:
        q = query or f"{title} {artist}".strip()
        if not q:
            return jsonify({"message": "Укажите название трека или поисковый запрос"}), 400
        found = _search_ytm_tracks(q, limit=3)
        if not found:
            return jsonify({"message": "Трек не найден в YouTube Music"}), 404
        top = found[0]
        video_id = top.get("video_id") or top.get("videoId") or ""
        title = title or top.get("title", q)
    ok, msg = _play_or_add(video_id, title or video_id, play_now)
    if not ok:
        return jsonify({"message": msg}), 400
    _wait_new_state(1.2)
    log_action("media_queue_add", {"title": title[:80], "video_id": video_id, "play_now": play_now})
    return jsonify({"message": msg, **_queue_payload()})


@player_bp.route("/media/history/play", methods=["POST"])
def media_history_play():
    if not check_token():
        return _unauthorized()
    data = _json_body()
    raw = data.get("h_index")
    h_idx = _int_or_none(raw)
    if raw is not None and h_idx is None:
        return jsonify({"message": "Некорректный индекс истории"}), 400
    title = str(data.get("title", "")).strip()
    artist = str(data.get("artist", "")).strip()
    video_id = str(data.get("video_id", "")).strip()
    with _hist_lock:
        if h_idx is not None and 0 <= h_idx < len(_listening_history):
            h = dict(_listening_history[h_idx])
            title = title or h.get("title", "")
            artist = artist or h.get("artist", "")
            video_id = video_id or h.get("video_id", "")
    if not title and not video_id:
        return jsonify({"message": "Трек не найден в истории"}), 400

    # Уже есть в очереди YouTube Music — просто переключаемся на него
    snap = _helper.snapshot()
    if snap["ext_connected"]:
        for i, t in enumerate(snap["ytm_queue"]):
            if (video_id and t.get("video_id") == video_id) or (not video_id and _norm(t.get("title", "")) == _norm(title)):
                ok, msg, res = _ytm_or_error({"action": "queue_play", "index": i, "video_id": t.get("video_id", ""), "title": title}, timeout=6.0)
                if ok:
                    log_action("media_history_play", {"title": title[:60]})
                    return jsonify({"message": f"Играет: {title}"})
                if not _ext_not_delivered(msg, res):
                    # Команда могла сработать (тайм-аут) — не запускаем трек второй раз
                    return jsonify({"message": msg or "Не выполнено"}), 400
                break
    if not video_id:
        found = _search_ytm_tracks(f"{title} {artist}".strip(), limit=1)
        video_id = (found[0].get("video_id") or found[0].get("videoId") or "") if found else ""
    if not video_id:
        return jsonify({"message": "Трек не найден в YouTube Music"}), 404
    ok, msg = _play_or_add(video_id, title or video_id, True)
    if not ok:
        return jsonify({"message": msg}), 400
    log_action("media_history_play", {"title": title[:60]})
    return jsonify({"message": msg})
