import ctypes
import os
import socket
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PY = os.path.join(BASE_DIR, "server.py")
ICO_PATH = os.path.join(BASE_DIR, "pc_control.ico")


def get_app_url() -> str:
    token = ""
    cfg_file = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cfg_file):
        try:
            import json
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("token"):
                    token = str(cfg["token"]).strip()
        except Exception:
            pass
    base = f"http://127.0.0.1:{SERVER_PORT}/"
    return f"{base}?token={token}" if token else base


APP_URL = get_app_url()
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
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
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
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
    s.Arguments = Chr(34) & "{script_path}" & Chr(34)
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
        out = subprocess.check_output(["cscript", "//Nologo", vbs_path], text=True)
        print(out.strip())
    finally:
        try:
            os.remove(vbs_path)
        except OSError:
            pass


def is_server_running(host="127.0.0.1", port=None) -> bool:
    try:
        with socket.create_connection((host, port or SERVER_PORT), timeout=0.6):
            return True
    except OSError:
        return False


def ensure_server_running():
    if is_server_running():
        return
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    subprocess.Popen(
        [pyw, SERVER_PY],
        cwd=BASE_DIR,
        creationflags=0x00000008,  # DETACHED_PROCESS
        close_fds=True,
    )
    for _ in range(25):
        if is_server_running():
            break
        time.sleep(0.15)


def find_chrome() -> str:
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return "chrome.exe"


def launch_app_window():
    u32 = ctypes.windll.user32
    existing = u32.FindWindowW(None, "PC Control")
    if existing:
        u32.ShowWindow(existing, 9)  # SW_RESTORE
        u32.SetForegroundWindow(existing)
        return

    chrome = find_chrome()
    subprocess.Popen(
        [
            chrome,
            f"--app={APP_URL}",
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
        ensure_server_running()
        launch_app_window()
