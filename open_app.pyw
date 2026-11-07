import ctypes
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from scripts import control_panel as panel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PY = os.path.join(BASE_DIR, "server.py")
ICO_PATH = os.path.join(BASE_DIR, "pc_control.ico")


def get_app_url() -> str:
    cfg = panel.load_config_data()
    token = str(cfg.get("token", "")).strip()
    base = f"http://127.0.0.1:{int(cfg.get('port', 5000))}/"
    return f"{base}?token={urllib.parse.quote(token, safe='')}" if token else base


CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def ensure_icon() -> str:
    if os.path.exists(ICO_PATH):
        return ICO_PATH
    try:
        from PIL import Image, ImageDraw
        sz = 256
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((12, 12, sz - 12, sz - 12), radius=56, fill=(14, 14, 14, 255), outline=(45, 45, 45, 255), width=4)
        d.ellipse((44, 44, sz - 44, sz - 44), fill=(255, 0, 51, 255))
        d.ellipse((64, 64, sz - 64, sz - 64), outline=(255, 255, 255, 70), width=4)
        d.polygon([(108, 88), (108, 168), (174, 128)], fill=(255, 255, 255, 255))
        img.save(ICO_PATH, format="ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    except Exception:
        pass
    return ICO_PATH


def create_shortcuts():
    ico = ensure_icon()
    pyw = panel.get_pythonw_path()
    if not os.path.exists(pyw):
        pyw = sys.executable
    script_path = os.path.abspath(__file__)

    vbs_path = os.path.join(BASE_DIR, "_make_lnk.vbs")
    vbs_code = f'''Set ws = CreateObject("WScript.Shell")
dt = ws.SpecialFolders("Desktop")
dirs = Array(dt, "{BASE_DIR}")
For Each d In dirs
    lnkPath = d & "\\PC Control.lnk"
    Set s = ws.CreateShortcut(lnkPath)
    s.TargetPath = "{pyw}"
    s.Arguments = "-E -s " & Chr(34) & "{script_path}" & Chr(34)
    s.WorkingDirectory = "{BASE_DIR}"
    s.IconLocation = "{ico},0"
    s.Description = "PC Control - YouTube Music & Remote Control"
    s.Save
    WScript.Echo lnkPath
Next
'''
    with open(vbs_path, "w", encoding="mbcs", errors="replace") as f:
        f.write(vbs_code)
    try:
        out = subprocess.check_output(["cscript", "//Nologo", vbs_path], text=True, creationflags=NO_WINDOW)
        print(out.strip())
    finally:
        try:
            os.remove(vbs_path)
        except OSError:
            pass


def is_server_running(host="127.0.0.1", port=None) -> bool:
    return panel.is_server_running(port)


def ensure_server_running():
    result = panel.start_server_process()
    if not result[0]:
        raise RuntimeError(result[3])


def find_chrome() -> str:
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


def launch_app_window():
    u32 = ctypes.windll.user32
    existing = u32.FindWindowW(None, "PC Control")
    if existing:
        u32.ShowWindow(existing, 9)  # SW_RESTORE
        u32.SetForegroundWindow(existing)
        return

    chrome = find_chrome()
    app_url = get_app_url()
    if chrome is None:
        if not webbrowser.open(app_url):
            raise RuntimeError("Could not open the default browser")
        return
    subprocess.Popen(
        [
            chrome,
            f"--app={app_url}",
            "--window-position=100,40",
            "--window-size=440,980",
        ],
        cwd=BASE_DIR,
    )

    for _ in range(30):
        hwnd = u32.FindWindowW(None, "PC Control")
        if hwnd:
            u32.MoveWindow(hwnd, 100, 40, 440, 980, True)
            u32.SetForegroundWindow(hwnd)
            break
        time.sleep(0.1)


if __name__ == "__main__":
    if "--create-shortcut" in sys.argv:
        create_shortcuts()
    else:
        try:
            ensure_server_running()
            launch_app_window()
        except Exception as error:
            ctypes.windll.user32.MessageBoxW(None, str(error), "PC Control", 0x10)
