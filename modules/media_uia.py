"""
PC Control — Модуль взаимодействия с браузером и YouTube Music через UI Automation (UIA) и Win32 Accessibility.
"""
import ctypes
from ctypes import wintypes
import threading
import time
import urllib.parse
from core.config import is_safe_test_mode
from modules.media_keys import _attach_input_desktop
from modules.media_volume import _co_init_safe


_uia_tls = threading.local()
_dom_backoff_until = 0.0


def _get_uia():
    """Один объект IUIAutomation на поток (так рекомендует Microsoft для клиентов UIA).
    Раньше на КАЖДОЕ чтение DOM (≈ раз в 0,85 с) создавался новый CUIAutomation, а
    CoUninitialize вызывался ещё до освобождения его объектов: рабочие потоки UIA оставались
    висеть — сервер терял ~40 потоков ОС в минуту (сотни за час, рост памяти и дескрипторов).
    COM на потоке инициализируется один раз и больше не деинициализируется."""
    pair = getattr(_uia_tls, "pair", None)
    if pair is None:
        import comtypes
        import comtypes.client
        _co_init_safe()
        UIA = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=UIA.IUIAutomation,
        )
        pair = (UIA, uia)
        _uia_tls.pair = pair
    return pair

_cached_ytm_hwnd: int = 0
_cached_ytm_url_time: float = 0.0
_cached_ytm_vid_pid: tuple[str, str] = ("", "")

_uia_dom_lock = threading.Lock()
_cached_dom_state: dict = {}
_cached_dom_time: float = 0.0
_last_a11y_wake_time: float = 0.0


def _norm_title(s: str) -> str:
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


def invalidate_dom_cache():
    global _cached_dom_time
    _cached_dom_time = 0.0


def _find_ytm_chrome_hwnds() -> list[int]:
    """Находит окна Chrome, ставя на первое место окно с YouTube Music."""
    global _cached_ytm_hwnd
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    _attach_input_desktop()

    ytm_hwnds: list[int] = []
    other_chrome_hwnds: list[int] = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                t = buf.value.lower()
                if "youtube music" in t or "music.youtube" in t:
                    ytm_hwnds.append(hwnd)
                elif "chrome" in t:
                    other_chrome_hwnds.append(hwnd)
        return True

    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    fn_ref = CMPFUNC(cb)
    user32.EnumWindows(fn_ref, 0)

    if ytm_hwnds:
        _cached_ytm_hwnd = ytm_hwnds[0]
    elif _cached_ytm_hwnd and _cached_ytm_hwnd in other_chrome_hwnds:
        other_chrome_hwnds.remove(_cached_ytm_hwnd)
        ytm_hwnds.append(_cached_ytm_hwnd)

    return ytm_hwnds + other_chrome_hwnds


def _wake_chrome_a11y(hwnd: int, force: bool = False):
    """Пробуждает дерево доступности WebContents в окне Chrome без перехвата фокуса."""
    global _last_a11y_wake_time
    now = time.time()
    if not force and (now - _last_a11y_wake_time) < 8.0:
        return
    try:
        import ctypes
        import comtypes
        user32 = ctypes.windll.user32
        oleacc = ctypes.windll.oleacc
        child = user32.FindWindowExW(hwnd, 0, "Chrome_RenderWidgetHostHWND", None)
        if child:
            IID_IAccessible = comtypes.GUID("{618736E0-3C3D-11CF-810C-00AA00389B71}")
            # Указатель comtypes освобождается сам (Release). Раньше сырой c_void_p никогда
            # не освобождался — каждый «будильник» оставлял COM-объект доступности Chrome.
            acc = ctypes.POINTER(comtypes.IUnknown)()
            oleacc.AccessibleObjectFromWindow(child, 0xFFFFFFFC, ctypes.byref(IID_IAccessible), ctypes.byref(acc))
            del acc
            _last_a11y_wake_time = now
    except Exception:
        pass


def _parse_url_vid_pid(raw_url: str) -> tuple[str, str]:
    if not raw_url:
        return "", ""
    u = raw_url.strip()
    if not u.startswith("http"):
        u = "https://" + u
    try:
        parsed = urllib.parse.urlparse(u)
        if "music.youtube.com" not in (parsed.netloc or "").lower():
            return "", ""
        qs = urllib.parse.parse_qs(parsed.query)
        vid = qs.get("v", [""])[0]
        pid = qs.get("list", [""])[0]
        return vid, pid
    except Exception:
        return "", ""


def _read_ytm_live_dom(force: bool = False, current_idx: int = 0) -> dict:
    """Читает реальную живую очередь и состояние плеера напрямую из DOM активной вкладки YouTube Music через UIA."""
    global _cached_dom_state, _cached_dom_time, _cached_ytm_hwnd, _cached_ytm_vid_pid, _cached_ytm_url_time
    global _dom_backoff_until
    now = time.time()
    if not force and (now - _cached_dom_time) < 0.85 and _cached_dom_state:
        return _cached_dom_state
    # Документ YouTube Music не найден: полный обход дерева доступности Chrome (FindAll по всем
    # потомкам + «будильник» MSAA) повторялся каждые 0,85 с — ~10 % CPU в простое и рост
    # рабочих потоков. После неудачи следующая попытка — через 5 с (force — сразу).
    if not force and now < _dom_backoff_until and _cached_dom_state:
        return _cached_dom_state

    if not _uia_dom_lock.acquire(blocking=force):
        return _cached_dom_state

    try:
        now = time.time()
        if not force and (now - _cached_dom_time) < 0.85 and _cached_dom_state:
            return _cached_dom_state

        _attach_input_desktop()
        hwnds = _find_ytm_chrome_hwnds()
        if not hwnds:
            _cached_dom_state = {"found": False}
            _cached_dom_time = now
            return _cached_dom_state

        import comtypes
        import comtypes.client
        UIA, uia = _get_uia()
        try:

            target_doc = None
            target_hwnd = 0
            doc_url = ""

            for hwnd in hwnds[:3]:
                _wake_chrome_a11y(hwnd, force=force)
                try:
                    root = uia.ElementFromHandle(hwnd)
                    doc_cond = uia.CreatePropertyCondition(30003, 50030)  # Document
                    docs = root.FindAll(4, doc_cond)
                    if docs.Length == 0:
                        _wake_chrome_a11y(hwnd, force=True)
                        docs = root.FindAll(4, doc_cond)
                    for d_i in range(docs.Length):
                        d = docs.GetElement(d_i)
                        d_name = d.CurrentName or ""
                        d_val = str(d.GetCurrentPropertyValue(30045) or "")
                        if "youtube music" in d_name.lower() or "music.youtube.com" in d_val.lower():
                            target_doc = d
                            target_hwnd = hwnd
                            doc_url = d_val
                            break
                    if target_doc is not None:
                        break
                except Exception:
                    continue

            if target_doc is None:
                # Попробуем хотя бы прочитать адресную строку первого окна YouTube Music
                for hwnd in hwnds[:2]:
                    try:
                        root = uia.ElementFromHandle(hwnd)
                        edit_el = root.FindFirst(4, uia.CreatePropertyCondition(30003, 50004))
                        if edit_el:
                            vp = edit_el.GetCurrentPattern(10002).QueryInterface(UIA.IUIAutomationValuePattern)
                            vid, pid = _parse_url_vid_pid(vp.CurrentValue or "")
                            if vid or pid:
                                _cached_ytm_vid_pid = (vid, pid)
                                _cached_ytm_url_time = now
                                _cached_dom_state = {
                                    "found": False,
                                    "vid": vid,
                                    "pid": pid,
                                    "hwnd": hwnd,
                                }
                                _cached_dom_time = now
                                _dom_backoff_until = now + 5.0
                                return _cached_dom_state
                    except Exception:
                        pass
                _cached_dom_state = {"found": False}
                _cached_dom_time = now
                _dom_backoff_until = now + 5.0
                return _cached_dom_state

            _cached_ytm_hwnd = target_hwnd
            vid, pid = _parse_url_vid_pid(doc_url)
            if not vid:
                try:
                    root = uia.ElementFromHandle(target_hwnd)
                    edit_el = root.FindFirst(4, uia.CreatePropertyCondition(30003, 50004))
                    if edit_el:
                        vp = edit_el.GetCurrentPattern(10002).QueryInterface(UIA.IUIAutomationValuePattern)
                        v2, p2 = _parse_url_vid_pid(vp.CurrentValue or "")
                        vid = vid or v2
                        pid = pid or p2
                except Exception:
                    pass

            if vid or pid:
                _cached_ytm_vid_pid = (vid, pid)
                _cached_ytm_url_time = now

            cache_req = uia.CreateCacheRequest()
            cache_req.AddProperty(30003)  # ControlType
            cache_req.AddProperty(30005)  # Name
            cache_req.AddProperty(30011)  # AutomationId
            cache_req.AddProperty(30012)  # ClassName

            all_els = target_doc.FindAllBuildCache(4, uia.CreateTrueCondition(), cache_req)
            n = all_els.Length

            dom_queue: list[dict] = []
            player_bar: dict = {}
            queue_source: str = ""
            in_player_page = False
            in_player_bar = False

            i = 0
            while i < n:
                sub = all_els.GetElement(i)
                cls = sub.CachedClassName or ""
                aid = sub.CachedAutomationId or ""
                nm = (sub.CachedName or "").strip()
                ctrl = sub.CachedControlType

                if cls == "style-scope ytmusic-app" and aid == "player-page":
                    in_player_page = True
                    in_player_bar = False
                    i += 1
                    continue

                if cls == "style-scope ytmusic-app" and nm == "Player bar":
                    in_player_bar = True
                    in_player_page = False
                    i += 1
                    continue

                if in_player_page and not queue_source and ctrl == 50020 and nm in (
                    "Playing from",
                    "Воспроизводится из",
                    "Відтворюється з",
                ):
                    if i + 1 < n:
                        s_next = all_els.GetElement(i + 1)
                        if s_next.CachedControlType == 50020:
                            queue_source = (s_next.CachedName or "").strip()
                    i += 1
                    continue

                # Элемент очереди ytmusic-player-queue-item
                if cls == "style-scope ytmusic-item-thumbnail-overlay-renderer" and aid == "play-button":
                    play_btn_name = nm
                    is_playing_btn = play_btn_name.startswith(("Pause ", "Пауза ", "Призупинити "))
                    title = ""
                    artist = ""
                    duration = ""
                    has_queue_marker = False

                    j = i + 1
                    while j < n:
                        s2 = all_els.GetElement(j)
                        c2 = s2.CachedClassName or ""
                        id2 = s2.CachedAutomationId or ""
                        nm2 = (s2.CachedName or "").strip()
                        ct2 = s2.CachedControlType

                        if c2 == "style-scope ytmusic-item-thumbnail-overlay-renderer" and id2 == "play-button":
                            break
                        if c2 == "style-scope ytmusic-app" and nm2 == "Player bar":
                            break
                        if "ytmusic-player-queue-item" in c2:
                            has_queue_marker = True

                        if not title and ct2 == 50020 and not c2:
                            title = nm2
                        elif title:
                            if "byline" in c2 and "ytmusic-player-queue-item" in c2:
                                artist = nm2
                            elif not artist and ct2 == 50020 and not c2 and nm2 not in ("Explicit", "E"):
                                artist = nm2
                            elif "duration" in c2 and "ytmusic-player-queue-item" in c2:
                                if j + 1 < n:
                                    s3 = all_els.GetElement(j + 1)
                                    if s3.CachedControlType == 50020:
                                        duration = (s3.CachedName or "").strip()
                                        j += 1
                                j += 1
                                break
                        j += 1

                    if title and has_queue_marker:
                        dom_queue.append({
                            "index": len(dom_queue),
                            "title": title,
                            "artist": artist,
                            "duration": duration,
                            "is_playing_btn": is_playing_btn,
                        })
                    i = j
                    continue

                # Панель управления ytmusic-player-bar
                if "play-pause-button" in cls and "ytmusic-player-bar" in cls and nm:
                    if nm.startswith(("Pause", "Пауза", "Призупинити")):
                        player_bar["status"] = "playing"
                    elif nm.startswith(("Play", "Воспроизвести", "Відтворити")):
                        player_bar["status"] = "paused"

                elif cls == "title style-scope ytmusic-player-bar":
                    if nm:
                        player_bar["title"] = nm
                    for back in (1, 2):
                        if i - back >= 0:
                            prev_el = all_els.GetElement(i - back)
                            p_nm = (prev_el.CachedName or "").strip()
                            if prev_el.CachedControlType == 50020 and "/" in p_nm:
                                parts = [p.strip() for p in p_nm.split("/", 1)]
                                if len(parts) == 2:
                                    player_bar["position"] = _parse_dur_to_seconds(parts[0])
                                    player_bar["duration"] = _parse_dur_to_seconds(parts[1])
                                    player_bar["duration_str"] = parts[1]
                                break

                elif "byline" in cls and "ytmusic-player-bar" in cls and nm:
                    sep = "•" if "•" in nm else ("·" if "·" in nm else None)
                    if sep:
                        b_parts = [p.strip() for p in nm.split(sep) if p.strip()]
                    else:
                        b_parts = [nm.strip()]
                    if b_parts:
                        player_bar["artist"] = b_parts[0]
                    if len(b_parts) >= 2:
                        player_bar["album"] = b_parts[1]

                i += 1

            # Определяем индекс активного трека в dom_queue
            active_idx = None
            for idx_q, q_it in enumerate(dom_queue):
                if q_it.get("is_playing_btn"):
                    active_idx = idx_q
                    break

            pb_title = player_bar.get("title", "")
            pb_artist = player_bar.get("artist", "")
            if active_idx is None and dom_queue and pb_title:
                nt_pb = _norm_title(pb_title)
                na_pb = _norm_title(pb_artist)
                candidates = []
                for idx_q, q_it in enumerate(dom_queue):
                    if _norm_title(q_it.get("title", "")) == nt_pb:
                        candidates.append(idx_q)
                if len(candidates) == 1:
                    active_idx = candidates[0]
                elif len(candidates) > 1:
                    # Если есть совпадение по артисту — фильтруем
                    art_cands = [
                        c for c in candidates
                        if not na_pb or na_pb in _norm_title(dom_queue[c].get("artist", "")) or _norm_title(dom_queue[c].get("artist", "")) in na_pb
                    ]
                    use_cands = art_cands or candidates
                    active_idx = min(use_cands, key=lambda c: abs(c - current_idx))

            if active_idx is None and dom_queue:
                active_idx = current_idx if 0 <= current_idx < len(dom_queue) else 0

            _cached_dom_state = {
                "found": True,
                "hwnd": target_hwnd,
                "vid": vid,
                "pid": pid,
                "queue_source": queue_source,
                "dom_queue": dom_queue,
                "active_idx": active_idx if active_idx is not None else 0,
                "player_bar": player_bar,
                "ts": now,
            }
            _cached_dom_time = now
            return _cached_dom_state
        finally:
            pass  # COM и объект UIA живут весь срок потока (см. _get_uia)
    except Exception:
        return _cached_dom_state or {"found": False}
    finally:
        _uia_dom_lock.release()


def _get_chrome_ytm_url(force: bool = False) -> tuple[str, str]:
    """Возвращает (videoId, playlistId) из активной вкладки YouTube Music."""
    global _cached_ytm_url_time, _cached_ytm_vid_pid
    now = time.time()
    if not force and (now - _cached_ytm_url_time) < 1.5 and _cached_ytm_vid_pid[0]:
        return _cached_ytm_vid_pid
    dom = _read_ytm_live_dom(force=force)
    vid = dom.get("vid", "")
    pid = dom.get("pid", "")
    if vid or pid:
        _cached_ytm_vid_pid = (vid, pid)
        _cached_ytm_url_time = now
        return vid, pid
    return _cached_ytm_vid_pid



def _uia_invoke_ytm_player_bar_button(action: str) -> bool:
    """Нажимает кнопку управления (play/pause/next/prev) напрямую в DOM ytmusic-player-bar через UIA."""
    if is_safe_test_mode():
        return True
    cls_map = {
        "play": "play-pause-button style-scope ytmusic-player-bar",
        "pause": "play-pause-button style-scope ytmusic-player-bar",
        "playpause": "play-pause-button style-scope ytmusic-player-bar",
        "play_pause": "play-pause-button style-scope ytmusic-player-bar",
        "next": "next-button style-scope ytmusic-player-bar",
        "prev": "previous-button style-scope ytmusic-player-bar",
        "previous": "previous-button style-scope ytmusic-player-bar",
    }
    target_cls = cls_map.get(action)
    if not target_cls:
        return False
    try:
        _attach_input_desktop()
        hwnds = _find_ytm_chrome_hwnds()
        if not hwnds:
            return False
        import comtypes
        import comtypes.client
        UIA, uia = _get_uia()
        try:
            for hwnd in hwnds[:2]:
                root = uia.ElementFromHandle(hwnd)
                el = root.FindFirst(4, uia.CreatePropertyCondition(30012, target_cls))
                if el:
                    nm = (el.CurrentName or "").strip()
                    if action == "play" and nm.startswith(("Pause", "Пауза", "Призупинити")):
                        return True
                    if action == "pause" and nm.startswith(("Play", "Воспроизвести", "Відтворити")):
                        return True
                    btn = el.FindFirst(4, uia.CreatePropertyCondition(30003, 50000)) or el
                    btn.GetCurrentPattern(10000).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
                    return True
        finally:
            pass  # COM и объект UIA живут весь срок потока (см. _get_uia)
    except Exception:
        pass
    return False



def _uia_invoke_ytm_queue_play(target_idx: int | None, target_title: str = "") -> bool:
    """Мгновенно кликает по нужному треку прямо внутри живой очереди YouTube Music (#queue) через UIA InvokePattern,
    без перезагрузки страницы, без перехвата фокуса и без потери пользовательских изменений очереди."""
    global _cached_dom_time
    if is_safe_test_mode():
        return True
    try:
        _attach_input_desktop()
        hwnds = _find_ytm_chrome_hwnds()
        if not hwnds:
            return False

        import comtypes
        import comtypes.client
        UIA, uia = _get_uia()
        try:
            norm_target = _norm_title(target_title)

            for hwnd in hwnds[:2]:
                _wake_chrome_a11y(hwnd, force=False)
                root = uia.ElementFromHandle(hwnd)
                docs = root.FindAll(4, uia.CreatePropertyCondition(30003, 50030))
                for d_i in range(docs.Length):
                    d = docs.GetElement(d_i)
                    d_name = d.CurrentName or ""
                    d_val = str(d.GetCurrentPropertyValue(30045) or "")
                    if "youtube music" not in d_name.lower() and "music.youtube.com" not in d_val.lower():
                        continue

                    pp = d.FindFirst(4, uia.CreatePropertyCondition(30011, "player-page")) or d
                    btns = pp.FindAll(
                        4,
                        uia.CreatePropertyCondition(30012, "style-scope ytmusic-item-thumbnail-overlay-renderer"),
                    )
                    if btns.Length == 0:
                        continue

                    chosen_btn = None
                    # 1. Проверяем точный индекс
                    if target_idx is not None and 0 <= target_idx < btns.Length:
                        cand = btns.GetElement(target_idx)
                        c_name = (cand.CurrentName or "").strip()
                        if not norm_target or norm_target in _norm_title(c_name):
                            chosen_btn = cand

                    # 2. Если индекс сместился, ищем по названию трека
                    if chosen_btn is None and norm_target:
                        best_dist = 10**9
                        for b_i in range(btns.Length):
                            cand = btns.GetElement(b_i)
                            c_name = (cand.CurrentName or "").strip()
                            for prefix in ("Play ", "Pause ", "Воспроизвести ", "Пауза ", "Відтворити ", "Призупинити "):
                                if c_name.startswith(prefix):
                                    c_name = c_name[len(prefix):]
                                    break
                            if _norm_title(c_name) == norm_target:
                                dist = abs(b_i - (target_idx if target_idx is not None else 0))
                                if dist < best_dist:
                                    best_dist = dist
                                    chosen_btn = cand

                    if chosen_btn is not None:
                        b_name = (chosen_btn.CurrentName or "").strip()
                        if b_name.startswith(("Pause ", "Пауза ", "Призупинити ")):
                            # Трек уже играет
                            _cached_dom_time = 0.0
                            return True
                        chosen_btn.GetCurrentPattern(10000).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
                        _cached_dom_time = 0.0
                        return True
        finally:
            pass  # COM и объект UIA живут весь срок потока (см. _get_uia)
    except Exception:
        pass
    return False



def _uia_invoke_ytm_queue_menu(target_idx: int, target_title: str, action_names: tuple[str, ...]) -> bool:
    """Вызывает пункт контекстного меню ('Remove from queue', 'Play next', 'Dismiss queue')
    у указанного трека в живой очереди YouTube Music через UIA."""
    global _cached_dom_time
    if is_safe_test_mode():
        return True
    try:
        _attach_input_desktop()
        hwnds = _find_ytm_chrome_hwnds()
        if not hwnds:
            return False

        import comtypes
        import comtypes.client
        UIA, uia = _get_uia()
        try:
            for hwnd in hwnds[:2]:
                root = uia.ElementFromHandle(hwnd)
                docs = root.FindAll(4, uia.CreatePropertyCondition(30003, 50030))
                for d_i in range(docs.Length):
                    d = docs.GetElement(d_i)
                    d_name = d.CurrentName or ""
                    d_val = str(d.GetCurrentPropertyValue(30045) or "")
                    if "youtube music" not in d_name.lower() and "music.youtube.com" not in d_val.lower():
                        continue

                    menus = d.FindAll(4, uia.CreatePropertyCondition(30012, "menu style-scope ytmusic-player-queue-item"))
                    if target_idx < 0 or target_idx >= menus.Length:
                        return False

                    m = menus.GetElement(target_idx)
                    btn = m.FindFirst(4, uia.CreatePropertyCondition(30003, 50000)) or m
                    btn.GetCurrentPattern(10000).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()

                    lower_targets = tuple(a.lower() for a in action_names)
                    for _ in range(18):
                        time.sleep(0.05)
                        popup_items = d.FindAll(4, uia.CreatePropertyCondition(30003, 50011))
                        for k in range(popup_items.Length):
                            pi = popup_items.GetElement(k)
                            nm = (pi.CurrentName or "").strip().lower()
                            if nm in lower_targets or any(t in nm for t in lower_targets):
                                pi.GetCurrentPattern(10000).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
                                _cached_dom_time = 0.0
                                return True

                    # Закрываем меню, если нужный пункт не найден
                    close_btn = d.FindFirst(4, uia.CreatePropertyCondition(30011, "hidden-close-button"))
                    if close_btn:
                        try:
                            close_btn.GetCurrentPattern(10000).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
                        except Exception:
                            pass
                    return False
        finally:
            pass  # COM и объект UIA живут весь срок потока (см. _get_uia)
    except Exception:
        pass
    return False


