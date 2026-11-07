"""
PC Control — Тихий запуск веб-пульта в компактном окне (App-режим Chrome/Edge без адресной строки).
Если передан аргумент --create-shortcut, создаёт ярлык «PC Control.lnk» с иконкой на Рабочем столе и в папке проекта.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
import webbrowser

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts import control_panel as panel

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
ICON_FILE = BASE_DIR / "pc_control.ico"

BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def get_app_url() -> str:
    cfg = panel.load_config_data()
    port = int(cfg.get("port", 5000))
    token = str(cfg.get("token", "")).strip()
    url = f"http://127.0.0.1:{port}/"
    return f"{url}?token={quote(token, safe='')}" if token else url


def ensure_server_running():
    cfg = panel.load_config_data()
    if panel.is_server_running(int(cfg.get("port", 5000))):
        return
    panel.start_server_process()


def create_shortcuts():
    pythonw = panel.get_pythonw_path()
    script_path = str(Path(__file__).resolve())
    icon_path = str(ICON_FILE) if ICON_FILE.exists() else pythonw
    desktop = Path(os.path.expandvars("%USERPROFILE%")) / "Desktop"
    targets = [BASE_DIR / "PC Control.lnk"]
    if desktop.exists():
        targets.append(desktop / "PC Control.lnk")

    try:
        from core.system_state import capture_shortcut_before_change
    except Exception:
        capture_shortcut_before_change = None

    for idx, lnk in enumerate(targets):
        if capture_shortcut_before_change is not None:
            comp_id = "shortcut.local" if idx == 0 else "shortcut.desktop"
            try:
                capture_shortcut_before_change(comp_id, lnk, pythonw, f"Ярлык {lnk.name}")
            except Exception:
                pass
        env = os.environ.copy()
        env["LNK_PATH"] = str(lnk)
        env["TARGET_PATH"] = pythonw
        env["SCRIPT_ARG"] = f'"{script_path}"'
        env["WORK_DIR"] = str(BASE_DIR)
        env["ICON_LOC"] = f"{icon_path},0"
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$s = $ws.CreateShortcut($env:LNK_PATH); "
            "$s.TargetPath = $env:TARGET_PATH; "
            "$s.Arguments = $env:SCRIPT_ARG; "
            "$s.WorkingDirectory = $env:WORK_DIR; "
            "$s.IconLocation = $env:ICON_LOC; "
            "$s.Description = 'PC Control — Панель управления ПК'; "
            "$s.Save()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], check=False, env=env, creationflags=NO_WINDOW)


def open_app_window():
    ensure_server_running()
    app_url = get_app_url()
    for path in BROWSER_CANDIDATES:
        if os.path.exists(path):
            subprocess.Popen(
                [path, f"--app={app_url}", "--window-size=430,860"],
                cwd=str(BASE_DIR),
                creationflags=NO_WINDOW,
            )
            return
    webbrowser.open(app_url)


if __name__ == "__main__":
    if "--create-shortcut" in sys.argv:
        create_shortcuts()
    else:
        open_app_window()
