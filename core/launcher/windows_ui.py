"""
PC Control — окна приложения: раскладка окон панели/пульта/Tailscale и окно Tailscale.

Вынесено из scripts/control_panel.py.
"""

from __future__ import annotations

import os
import subprocess
import threading
import urllib.request
import webbrowser
from pathlib import Path


def get_desktop_window_layout() -> dict:
    """Рассчитывает адаптивные координаты и размеры окон для комфортной работы бок о бок.

    1. Главное окно (PC Control Launcher) — всегда фиксируется на левой стороне экрана.
    2. Окно удалённого управления (Remote Control Panel) — открывается СПРАВА от PC Control,
       не распахнуто, оптимальной ширины для комфортной работы со всеми функциями.
    3. Окно Tailscale — открывается СПРАВА от PC Control в компактном нормальном окне (не Maximized),
       где видны все элементы управления и статус.
    """
    import ctypes
    work_x, work_y, work_w, work_h = 0, 0, 1920, 1040
    try:
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long)
            ]
        rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            work_x = rect.left
            work_y = rect.top
            work_w = rect.right - rect.left
            work_h = rect.bottom - rect.top
    except Exception:
        pass

    margin = 16
    gap = 16

    # 1. Лаунчер PC Control (слева)
    if work_w >= 1800:
        launcher_w = 900
    elif work_w >= 1400:
        launcher_w = min(880, int((work_w - margin * 2 - gap) * 0.49))
    else:
        launcher_w = min(work_w - 32, max(600, int((work_w - margin * 2 - gap) * 0.5)))

    launcher_h = min(980, max(650, work_h - margin * 2))
    launcher_x = work_x + margin
    launcher_y = work_y + margin

    # 2. Правая позиция (ровно справа от PC Control)
    right_x = launcher_x + launcher_w + gap
    available_right_w = max(480, (work_x + work_w) - right_x - margin)

    # 3. Окно удалённого управления (Remote Control Panel) справа
    remote_w = min(980, max(600, available_right_w))
    remote_h = launcher_h
    remote_x = right_x
    remote_y = launcher_y

    # 4. Окно Tailscale (компактное окно справа от PC Control)
    tailscale_w = min(600, max(480, int(available_right_w * 0.72)))
    tailscale_h = min(820, max(580, work_h - margin * 2))
    tailscale_x = right_x
    tailscale_y = launcher_y

    return {
        "launcher": {"x": launcher_x, "y": launcher_y, "w": launcher_w, "h": launcher_h},
        "remote": {"x": remote_x, "y": remote_y, "w": remote_w, "h": remote_h},
        "tailscale": {"x": tailscale_x, "y": tailscale_y, "w": tailscale_w, "h": tailscale_h},
    }


def enforce_window_geometry_async(title_keywords: list[str], x: int, y: int, w: int, h: int, timeout_sec: float = 4.0):
    """Фоновый поток Win32 отслеживает появление окна приложения, снимает режим Maximized
    (развернуто на весь экран) и точно выставляет позицию и размеры, исключая случайные сдвиги."""
    def _worker():
        import ctypes
        import time
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        SWP_NOZORDER = 0x0004
        SWP_SHOWWINDOW = 0x0040

        start = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(0.18)
            matched_hwnds = []

            def _enum_cb(hwnd, lparam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        val = buf.value.lower()
                        if any(k.lower() in val for k in title_keywords):
                            matched_hwnds.append(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            try:
                user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
            except Exception:
                pass

            if matched_hwnds:
                for hwnd in matched_hwnds:
                    try:
                        if user32.IsZoomed(hwnd):
                            user32.ShowWindow(hwnd, SW_RESTORE)
                        user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), SWP_NOZORDER | SWP_SHOWWINDOW)
                    except Exception:
                        pass
                break

    threading.Thread(target=_worker, daemon=True).start()


def check_tailscale_web_accessible(url: str, timeout: float = 0.6) -> bool:
    """Проверка доступности локального веб-клиента Tailscale по указанному URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PC-Control-Launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def launch_tailscale_app_window(target_url: str = "http://100.100.100.100", log=print) -> bool:
    """Запуск приложения Tailscale в компактном нормальном окне справа от PC Control."""
    layout = get_desktop_window_layout()["tailscale"]
    edge_anti_translate = [
        "--disable-features=Translate,msEdgeTranslate,TranslateUI,AutofillServerCommunication",
        "--disable-translate",
        "--no-first-run",
        "--disable-save-password-bubble",
    ]
    window_flags = [
        f"--window-position={layout['x']},{layout['y']}",
        f"--window-size={layout['w']},{layout['h']}",
    ]
    edge_paths = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LocalAppData", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for edge_path in edge_paths:
        if edge_path.is_file():
            try:
                cmd = [
                    str(edge_path),
                    f"--app={target_url}",
                ] + window_flags + edge_anti_translate
                subprocess.Popen(cmd)
                enforce_window_geometry_async(["tailscale", "100.100.100.100"], layout['x'], layout['y'], layout['w'], layout['h'])
                log("Tailscale application opened in compact window on the right side.")
                return True
            except Exception as e:
                log(f"Failed to launch Edge app window for Tailscale: {e}")

    chrome_paths = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LocalAppData", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for cp in chrome_paths:
        if cp.is_file():
            try:
                subprocess.Popen([
                    str(cp),
                    f"--app={target_url}",
                ] + window_flags + edge_anti_translate)
                enforce_window_geometry_async(["tailscale", "100.100.100.100"], layout['x'], layout['y'], layout['w'], layout['h'])
                log("Tailscale application opened in compact Chrome window on the right side.")
                return True
            except Exception as e:
                log(f"Failed to launch Chrome app window for Tailscale: {e}")

    try:
        webbrowser.open(target_url)
        log("Tailscale interface opened in default browser.")
        return True
    except Exception as e:
        log(f"Failed to open Tailscale interface in browser: {e}")
        return False
