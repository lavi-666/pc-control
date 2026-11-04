"""
PC Control — Модуль отправки мультимедийных клавиш Win32 и навигации окон медиаплееров.
"""

import ctypes
import os
import platform
import subprocess
import time
import urllib.parse
from ctypes import wintypes
from pathlib import Path

from core.config import CHROME, NO_WINDOW, is_safe_test_mode
from modules.system import _attach_input_desktop


def _send_media_key(action: str) -> bool:
    if is_safe_test_mode():
        return True
    u = ctypes.windll.user32
    KEYEVENTF_KEYUP = 0x0002
    vk_map = {
        "playpause": 0xB3,
        "play_pause": 0xB3,
        "play": 0xB3,
        "pause": 0xB3,
        "next": 0xB0,
        "prev": 0xB1,
        "previous": 0xB1,
        "stop": 0xB2,
    }
    vk = vk_map.get(action)
    if not vk:
        return False
    u.keybd_event(vk, 0, 0, 0)
    u.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    return True


def _find_media_window() -> int:
    user32 = ctypes.windll.user32
    _attach_input_desktop()
    found_hwnd = 0

    def cb(hwnd, extra):
        nonlocal found_hwnd
        if not user32.IsWindow(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.lower()
            if "youtube music" in title or "music.youtube" in title:
                found_hwnd = hwnd
                return False
        return True

    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    fn_ref1 = CMPFUNC(cb)
    user32.EnumWindows(fn_ref1, 0)
    if found_hwnd:
        return found_hwnd

    # Fallback: find any Chrome browser window with audio or general Chrome window
    def cb2(hwnd, extra):
        nonlocal found_hwnd
        if not user32.IsWindow(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.lower()
            if "chrome" in title and ("google chrome" in title or "youtube" in title):
                found_hwnd = hwnd
                return False
        return True

    fn_ref2 = CMPFUNC(cb2)
    user32.EnumWindows(fn_ref2, 0)
    return found_hwnd


def _send_media_click_or_key(action: str) -> bool:
    return _send_media_key(action)


def _navigate_chrome_or_launch(url: str, update_page_ids_fn=None) -> bool:
    """Переходит по URL в активном окне плеера/Chrome без открытия дублирующих окон
    и сохраняет буфер обмена пользователя в неизменном виде."""
    if is_safe_test_mode():
        return True
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        v = params["v"][0] if ("v" in params and params["v"]) else ""
        p = params["list"][0] if ("list" in params and params["list"]) else ""
        if update_page_ids_fn:
            update_page_ids_fn(v, p)
    except Exception:
        pass

    hwnd = _find_media_window()
    if hwnd:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

        _attach_input_desktop()

        prev_clipboard = None
        try:
            if user32.OpenClipboard(0):
                try:
                    h_data = user32.GetClipboardData(13)  # CF_UNICODETEXT
                    if h_data:
                        ptr = kernel32.GlobalLock(h_data)
                        if ptr:
                            prev_clipboard = ctypes.wstring_at(ptr)
                            kernel32.GlobalUnlock(h_data)
                finally:
                    user32.CloseClipboard()
        except Exception:
            prev_clipboard = None

        try:
            p = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
            p.communicate(input=url, timeout=0.8)
        except Exception:
            pass

        cursor_pos = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cursor_pos))
        fg = user32.GetForegroundWindow()
        was_iconic = bool(user32.IsIconic(hwnd))

        cur_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        attached_target = False
        attached_fg = False

        try:
            if target_tid and cur_tid != target_tid:
                user32.AttachThreadInput(cur_tid, target_tid, True)
                attached_target = True
            if fg_tid and cur_tid != fg_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, True)
                attached_fg = True

            if was_iconic:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            # Обход ограничения Windows на передачу фокуса через Alt-key
            user32.keybd_event(0x12, 0x38, 0, 0)
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(0x12, 0x38, 2, 0)
            time.sleep(0.12)

            VK_CONTROL, VK_L, VK_V, VK_RETURN, VK_MENU = 0x11, 0x4C, 0x56, 0x0D, 0x12
            KEYEVENTF_KEYUP = 0x0002

            sc_ctrl = user32.MapVirtualKeyW(VK_CONTROL, 0)
            sc_l = user32.MapVirtualKeyW(VK_L, 0)
            sc_v = user32.MapVirtualKeyW(VK_V, 0)
            sc_ret = user32.MapVirtualKeyW(VK_RETURN, 0)

            # Focus address bar (Ctrl+L)
            user32.keybd_event(VK_CONTROL, sc_ctrl, 0, 0)
            user32.keybd_event(VK_L, sc_l, 0, 0)
            user32.keybd_event(VK_L, sc_l, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, sc_ctrl, KEYEVENTF_KEYUP, 0)
            time.sleep(0.12)

            # Paste URL (Ctrl+V)
            user32.keybd_event(VK_CONTROL, sc_ctrl, 0, 0)
            user32.keybd_event(VK_V, sc_v, 0, 0)
            user32.keybd_event(VK_V, sc_v, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, sc_ctrl, KEYEVENTF_KEYUP, 0)
            time.sleep(0.08)

            # Navigate (Enter) с аппаратным скан-кодом (0x1C)
            user32.keybd_event(VK_RETURN, sc_ret, 0, 0)
            time.sleep(0.04)
            user32.keybd_event(VK_RETURN, sc_ret, KEYEVENTF_KEYUP, 0)
            time.sleep(0.2)

            # Check if "Leave site?" prompt appeared and confirm it
            dlg = user32.GetForegroundWindow()
            if dlg and dlg != hwnd:
                dlg_len = user32.GetWindowTextLengthW(dlg)
                if dlg_len > 0:
                    dlg_buf = ctypes.create_unicode_buffer(dlg_len + 1)
                    user32.GetWindowTextW(dlg, dlg_buf, dlg_len + 1)
                    if "leave" in dlg_buf.value.lower():
                        user32.keybd_event(VK_MENU, 0, 0, 0)
                        user32.keybd_event(VK_L, 0, 0, 0)
                        user32.keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
                        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                        time.sleep(0.03)
                        user32.keybd_event(VK_RETURN, sc_ret, 0, 0)
                        user32.keybd_event(VK_RETURN, sc_ret, KEYEVENTF_KEYUP, 0)

            if was_iconic:
                user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return True
        except Exception:
            pass
        finally:
            if prev_clipboard is not None:
                try:
                    p_rest = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
                    p_rest.communicate(input=prev_clipboard, timeout=0.8)
                except Exception:
                    pass
            if attached_target:
                try:
                    user32.AttachThreadInput(cur_tid, target_tid, False)
                except Exception:
                    pass
            if attached_fg:
                try:
                    user32.AttachThreadInput(cur_tid, fg_tid, False)
                except Exception:
                    pass
            if fg and fg != hwnd:
                user32.SetForegroundWindow(fg)
            user32.SetCursorPos(cursor_pos.x, cursor_pos.y)

    if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
        return False
    try:
        os.startfile(url)
        return True
    except Exception:
        pass
    try:
        subprocess.Popen([CHROME, url], creationflags=NO_WINDOW)
        return True
    except Exception:
        return False
