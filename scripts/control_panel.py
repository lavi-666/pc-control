#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC Control - Панель управления и запуска (Control Center / Launcher).
Пошаговая подготовка к первому запуску, автоматизация скриптов и управление сервером.
Поддержка трех языков (English, Русский, Українська) и сворачиваемая консоль логов.
Работает на базе стандартной библиотеки Python (без обязательных внешних pip-пакетов).
"""

import http.server
import hashlib
import functools
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

# Кодировка вывода
try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
CONFIG_FILE = BASE_DIR / "config.json"
SCRIPTS_DIR = BASE_DIR / "scripts"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

CONTROL_PORT = int(os.environ.get("PC_CONTROL_PANEL_PORT", "5055"))
if not 1 <= CONTROL_PORT <= 65535:
    raise ValueError("Invalid PC_CONTROL_PANEL_PORT")
_settings_lock = threading.RLock()


def save_config_data(cfg):
    """Replace the config atomically; a failed write never reports success."""
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_FILE.parent,
                                         prefix="config-", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, CONFIG_FILE)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def validate_network_settings(data):
    result = {}
    for key in ("port", "relay_port"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise ValueError(f"{key}: expected an integer from 1 to 65535")
        result[key] = value
    if result["port"] in (5051, CONTROL_PORT) or result["port"] == result["relay_port"]:
        raise ValueError("Server port conflicts with the launcher, streamer or relay")
    for key in ("lan_ip", "vpn_ip", "wol_relay_ip"):
        value = data.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{key}: expected an IPv4 address")
        value = value.strip()
        if value:
            ipaddress.IPv4Address(value)
        result[key] = value
    mac = data.get("mac_address", "")
    if not isinstance(mac, str) or (mac.strip() and not re.fullmatch(r"[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}", mac.strip())):
        raise ValueError("Invalid MAC address")
    result["mac_address"] = mac.strip().upper().replace(":", "-")
    return result

# Буфер вывода консоли
_log_lock = threading.Lock()
_action_logs = [
    "[INFO] PC Control Center started successfully.",
    "[INFO] Ready for system checks and automation tasks."
]
_is_busy = False
_busy_action = ""
_background_lock = threading.Lock()
_lifecycle_lock = threading.RLock()


def serialize_lifecycle(operation):
    @functools.wraps(operation)
    def run(*args, **kwargs):
        if _is_busy and _busy_action == "Full project update":
            return False, "ERR_SYSTEM_BUSY", "Обновление проекта", "Дождитесь завершения обновления."
        if not _lifecycle_lock.acquire(blocking=False):
            return False, "ERR_SYSTEM_BUSY", "Операция уже выполняется", "Дождитесь завершения запуска или остановки сервера."
        try:
            return operation(*args, **kwargs)
        finally:
            _lifecycle_lock.release()
    return run


def append_log(line: str):
    global _action_logs
    with _log_lock:
        timestamp = time.strftime("%H:%M:%S")
        _action_logs.append(f"[{timestamp}] {line}")
        if len(_action_logs) > 400:
            _action_logs = _action_logs[-300:]


def get_logs() -> list:
    with _log_lock:
        return list(_action_logs)


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_pythonw_path() -> str:
    bundled = BASE_DIR / "runtime" / "pythonw.exe"
    if bundled.is_file():
        return str(bundled)
    venv_pyw = BASE_DIR / "venv" / "Scripts" / "pythonw.exe"
    if venv_pyw.exists():
        return str(venv_pyw)
    cur_py = Path(sys.executable)
    if "pythonw" in cur_py.name.lower():
        return str(cur_py)
    sibling_pyw = cur_py.parent / "pythonw.exe"
    if sibling_pyw.exists():
        return str(sibling_pyw)
    return str(cur_py)


def get_python_cli_path() -> str:
    pyw = get_pythonw_path()
    if pyw.lower().endswith("pythonw.exe"):
        cli = str(Path(pyw).with_name("python.exe"))
        if Path(cli).is_file():
            return cli
    if Path(sys.executable).is_file():
        return str(sys.executable)
    return "python"


_last_activity_time = time.time()

def record_activity():
    global _last_activity_time
    _last_activity_time = time.time()

def _idle_watchdog():
    # Защита от процессов-зомби: если браузер закрыт и нет запросов более 5 минут, процесс панели завершается
    time.sleep(30)
    while True:
        time.sleep(5)
        if (time.time() - _last_activity_time) > 300.0:
            os._exit(0)

def is_already_serving() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CONTROL_PORT}/api/identity", timeout=1) as response:
            return json.load(response).get("instance") == instance_id()
    except Exception:
        return False


def instance_id():
    return hashlib.sha256(str(BASE_DIR.resolve()).lower().rstrip("\\/").encode("utf-8")).hexdigest()


NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

_cached_ts = None
_cached_ts_time = 0.0

def find_tailscale_binaries() -> dict:
    """Всесторонний поиск установленных компонентов Tailscale в системе (PATH, реестр, папки, ярлыки)."""
    gui_path = None
    cli_path = None
    shortcut_path = None

    # 1. Поиск в системной переменной PATH
    w_gui = shutil.which("tailscale-ipn.exe") or shutil.which("tailscale-ipn")
    if w_gui and Path(w_gui).is_file():
        gui_path = Path(w_gui)
    w_cli = shutil.which("tailscale.exe") or shutil.which("tailscale")
    if w_cli and Path(w_cli).is_file():
        cli_path = Path(w_cli)

    # 2. Поиск в системном реестре Windows
    reg_dirs = []
    if winreg is not None and platform.system() == "Windows":
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for subkey in (
                r"SOFTWARE\Tailscale IPN",
                r"SOFTWARE\WOW6432Node\Tailscale IPN",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tailscale-ipn.exe",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tailscale.exe",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Tailscale",
            ):
                try:
                    with winreg.OpenKey(root, subkey) as k:
                        for val_name in ("", "InstallDir", "InstallLocation", "DisplayIcon"):
                            try:
                                val, _ = winreg.QueryValueEx(k, val_name)
                                if val and isinstance(val, str):
                                    p = Path(val.strip('"'))
                                    if p.is_file():
                                        reg_dirs.append(p.parent)
                                        if p.name.lower() == "tailscale-ipn.exe" and not gui_path:
                                            gui_path = p
                                        elif p.name.lower() == "tailscale.exe" and not cli_path:
                                            cli_path = p
                                    elif p.is_dir():
                                        reg_dirs.append(p)
                            except Exception:
                                pass
                except Exception:
                    pass

    # 3. Стандартные каталоги установки Windows
    candidate_dirs = list(reg_dirs)
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramData"):
        val = os.environ.get(env_key)
        if val:
            candidate_dirs.append(Path(val) / "Tailscale")
            candidate_dirs.append(Path(val) / "Programs" / "Tailscale")
    candidate_dirs.extend([
        Path(r"C:\Program Files\Tailscale"),
        Path(r"C:\Program Files (x86)\Tailscale")
    ])

    for d in candidate_dirs:
        if not gui_path and (d / "tailscale-ipn.exe").is_file():
            gui_path = d / "tailscale-ipn.exe"
        if not cli_path and (d / "tailscale.exe").is_file():
            cli_path = d / "tailscale.exe"

    # 4. Ярлыки в меню «Пуск»
    shortcut_candidates = [
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Tailscale.lnk"),
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        shortcut_candidates.append(Path(appdata) / r"Microsoft\Windows\Start Menu\Programs\Tailscale.lnk")
    for sc in shortcut_candidates:
        if sc.is_file():
            shortcut_path = sc
            break

    return {
        "gui": gui_path,
        "cli": cli_path,
        "shortcut": shortcut_path,
        "installed": bool(gui_path or cli_path or shortcut_path)
    }


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


def launch_tailscale_app_window(target_url: str = "http://100.100.100.100") -> bool:
    """Запуск приложения Tailscale в компактном нормальном окне справа от PC Control."""
    layout = get_desktop_window_layout()["tailscale"]
    edge_anti_translate = [
        "--disable-features=Translate,msEdgeTranslate,TranslateUI",
        "--disable-translate",
        "--no-first-run",
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
                append_log("Tailscale application opened in compact window on the right side.")
                return True
            except Exception as e:
                append_log(f"Failed to launch Edge app window for Tailscale: {e}")

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
                append_log("Tailscale application opened in compact Chrome window on the right side.")
                return True
            except Exception as e:
                append_log(f"Failed to launch Chrome app window for Tailscale: {e}")

    try:
        webbrowser.open(target_url)
        append_log("Tailscale interface opened in default browser.")
        return True
    except Exception as e:
        append_log(f"Failed to open Tailscale interface in browser: {e}")
        return False


def get_tailscale_info() -> dict:
    global _cached_ts, _cached_ts_time
    now = time.time()
    if _cached_ts is not None and (now - _cached_ts_time < 5.0):
        return _cached_ts

    bins = find_tailscale_binaries()
    ts_cli = bins.get("cli")
    ts_gui = bins.get("gui")
    installer_exists = (BASE_DIR / "tailscale-setup-1.102.4.exe").exists() or bool(list(BASE_DIR.glob("tailscale-setup*.exe")))

    ip = ""
    account = ""
    device_name = ""
    magic_dns = ""
    peers = []
    backend_state = "Stopped"

    # Расширенный опрос параметров через tailscale.exe status --json
    if ts_cli and ts_cli.is_file():
        try:
            res = subprocess.run(
                [str(ts_cli), "status", "--json"],
                capture_output=True,
                text=True,
                timeout=1.2,
                creationflags=0x08000000 if os.name == "nt" else 0
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                backend_state = data.get("BackendState", "Running" if ip else "Stopped")
                self_node = data.get("Self") or {}
                device_name = self_node.get("HostName", "")
                magic_dns = self_node.get("DNSName", "").rstrip(".")
                ts_ips = data.get("TailscaleIPs") or self_node.get("TailscaleIPs") or []
                if ts_ips:
                    ip = next((v for v in ts_ips if ':' not in v), '')
                users = data.get("User") or {}
                if users:
                    first_user = users.get(str(self_node.get("UserID", "")), {})
                    account = first_user.get("LoginName") or first_user.get("DisplayName", "")
                raw_peers = data.get("Peer") or {}
                for p in raw_peers.values():
                    p_ips = p.get("TailscaleIPs") or []
                    peers.append({
                        "name": p.get("HostName") or "Unknown Device",
                        "ip": p_ips[0] if p_ips else "",
                        "online": bool(p.get("Online")),
                        "os": p.get("OS", "")
                    })
        except Exception:
            pass

    is_running = backend_state == "Running" and bool(ip)
    is_installed = bool((ts_cli and ts_cli.is_file()) or (ts_gui and ts_gui.is_file()) or is_running or bins.get("installed"))

    if not is_installed:
        details = "Tailscale is not installed"
    elif is_running:
        details = f"Connected ({ip})" if ip else "Running"
    else:
        details = "Installed, but not running"

    _cached_ts = {
        "installed": is_installed,
        "running": is_running,
        "ip": ip,
        "installer_exists": installer_exists,
        "details": details,
        "account": account,
        "device_name": device_name,
        "magic_dns": magic_dns,
        "peers": peers,
        "backend_state": backend_state,
        "gui_path": str(ts_gui) if ts_gui else "",
        "cli_path": str(ts_cli) if ts_cli else ""
    }
    _cached_ts_time = now
    return _cached_ts


def is_server_running(port: int | None = None) -> bool:
    if port is None:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    port = int(json.load(f).get("port", 5000))
            else:
                port = 5000
        except Exception:
            port = 5000
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/status", headers={"User-Agent": "PC-Control-Launcher"})
        with urllib.request.urlopen(req, timeout=0.45) as resp:
            if resp.status == 200:
                body = json.load(resp)
                return body.get("status") == "online" and body.get("instance") == instance_id()
    except Exception:
        pass
    return False


_cached_fw_ok = False
_cached_fw_time = 0.0
_cached_fw_port = None


def firewall_rule_matches(value, port):
    fields = dict(part.split("=", 1) for part in str(value).split("|") if "=" in part)
    return (fields.get("Name") == "PC Control Server" and fields.get("Active", "").upper() == "TRUE"
            and fields.get("Action") == "Allow" and fields.get("Dir") == "In"
            and fields.get("Protocol") == "6" and fields.get("LPort") == str(port))

def is_firewall_configured() -> bool:
    global _cached_fw_ok, _cached_fw_time, _cached_fw_port
    port = load_config_data().get("port", 5000)
    now = time.time()
    if now - _cached_fw_time < 2.0 and port == _cached_fw_port:
        return _cached_fw_ok

    if platform.system() != "Windows":
        _cached_fw_ok = True
        _cached_fw_time = now
        return True

    # Чистый Python реестр Windows (HKLM) без запуска netsh.exe (ноль всплывающих окон)
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules",
            0,
            winreg.KEY_READ
        ) as key:
            num_values = winreg.QueryInfoKey(key)[1]
            found = False
            for i in range(num_values):
                val_name, val_data, _ = winreg.EnumValue(key, i)
                if firewall_rule_matches(val_data, port):
                    found = True
                    break
            _cached_fw_ok = found
    except Exception:
        _cached_fw_ok = False

    _cached_fw_time = now
    _cached_fw_port = port
    return _cached_fw_ok


REQUIRED_PACKAGES = [
    ("Flask", "flask"),
    ("Pillow", "PIL"),
    ("pycaw", "pycaw"),
    ("comtypes", "comtypes"),
    ("winsdk", "winsdk"),
    ("psutil", "psutil"),
    ("pyaudiowpatch", "pyaudiowpatch"),
    ("mss", "mss"),
    ("qrcode", "qrcode"),
    ("numpy", "numpy"),
]

_cached_deps = None
_cached_deps_time = 0.0
_deps_lock = threading.Lock()

def check_python_deps() -> dict:
    with _deps_lock:
        return _check_python_deps()


def _check_python_deps() -> dict:
    global _cached_deps, _cached_deps_time
    now = time.time()
    if _cached_deps is not None and (now - _cached_deps_time < 30.0):
        return _cached_deps

    # Probe the interpreter that actually runs the server. Importing into this
    # long-lived panel would cache obsolete modules and mix virtual environments.
    probe = """
import importlib, json, sys
result = {'installed_list': [], 'errors': {}, 'python_version': sys.version.split()[0]}
for name, module in json.loads(sys.argv[1]):
    try:
        importlib.import_module(module)
        if module == 'winsdk':
            importlib.import_module('winsdk.windows.media.control')
        result['installed_list'].append(name)
    except Exception as exc:
        result['errors'][name] = str(exc)
print(json.dumps(result))
"""
    try:
        process = subprocess.run([get_python_cli_path(), "-I", "-c", probe, json.dumps(REQUIRED_PACKAGES)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=30, creationflags=NO_WINDOW)
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or f"Python exit code {process.returncode}")
        result = json.loads(process.stdout.strip().splitlines()[-1])
    except Exception as exc:
        result = {"installed_list": [], "errors": {name: str(exc) for name, _ in REQUIRED_PACKAGES},
                  "python_version": "unavailable"}
    has_venv = (BASE_DIR / "runtime" / "python.exe").exists() or (BASE_DIR / "venv" / "Scripts" / "python.exe").exists()
    missing = list(result["errors"])
    installed_list = result["installed_list"]

    is_all_installed = len(missing) == 0

    if is_all_installed:
        details = "All required Python libraries are installed."
    else:
        details = f"Missing packages ({len(missing)}): {', '.join(missing)}"

    _cached_deps = {
        "has_venv": has_venv,
        "installed": is_all_installed,
        "missing": missing,
        "missing_count": len(missing),
        "installed_list": installed_list,
        "details": details,
        "python_version": result["python_version"],
        "errors": result["errors"],
        "interpreter": get_python_cli_path()
    }
    _cached_deps_time = now
    return _cached_deps


_network_sync_time = 0.0


def sync_network_settings(cfg, ts, force=False):
    global _network_sync_time
    if not force and time.monotonic() - _network_sync_time < 10:
        return cfg
    from scripts.network_setup import detect_network
    with _settings_lock:
        cfg = load_config_data()
        before = dict(cfg)
        if force:
            cfg['auto_network'] = True
        if cfg.get('auto_network', False):
            detected = detect_network()
            cfg.update(detected)
        if ts.get('running') and (cfg.get('auto_network', False) or not cfg.get('vpn_ip')):
            cfg['vpn_ip'] = ts['ip']
        elif cfg.get('auto_network', False):
            cfg['vpn_ip'] = ''
        if cfg != before:
            save_config_data(cfg)
        _network_sync_time = time.monotonic()
        return cfg


def load_config_data() -> dict:
    with _settings_lock:
        return _load_config_data()


def _load_config_data() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "language" not in data:
                    data["language"] = "en"
                return data
        except Exception:
            pass

    # Первоначальное создание config.json с авто-определением сетевых настроек
    lan_ip = get_local_ip()
    ts = get_tailscale_info()
    vpn_ip = ts.get("ip", "") if ts.get("running") else ""

    from scripts.network_setup import detect_network
    detected = detect_network()
    lan_ip = detected['lan_ip']
    mac_address = detected['mac_address']

    default_lang = "en"
    try:
        import locale
        loc = (locale.getdefaultlocale()[0] or "").lower()
        if loc.startswith("uk"):
            default_lang = "uk"
        elif any(loc.startswith(p) for p in ("ru", "be", "kk")):
            default_lang = "ru"
    except Exception:
        pass

    cfg = {
        "auto_network": True,
        "token": secrets.token_hex(8),
        "lan_ip": lan_ip,
        "vpn_ip": vpn_ip,
        "wol_relay_ip": "",
        "mac_address": mac_address,
        "port": 5000,
        "relay_port": 5050,
        "language": default_lang,
        "cors_allowed_origins": [
            "http://localhost:*",
            "http://127.0.0.1:*",
            "http://192.168.*",
            "http://100.*",
            "http://10.*",
            "https://localhost:*",
            "https://127.0.0.1:*"
        ]
    }
    try:
        tmp_file = CONFIG_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, CONFIG_FILE)
        append_log("[FIRST RUN] Auto-generated config.json with detected system network parameters.")
    except Exception as e:
        append_log(f"[WARNING] Could not write config.json: {e}")

    return cfg


def run_install_dependencies_task(auto_start_server: bool = False):
    """
    Автоматическая установка зависимостей из requirements.txt через текущий Python.
    Без блокирующих batch-скриптов с pause, с потоковым выводом логов в консоль панели.
    При успехе автоматически запускает server.py и сторожевой процесс watchdog.
    """
    global _is_busy, _busy_action, _cached_deps_time
    if not _background_lock.acquire(blocking=False):
        return False
    _is_busy = True
    _busy_action = "Python Dependencies Installation"
    append_log("Starting installation of required Python libraries from requirements.txt...")

    def _worker():
        global _is_busy, _busy_action, _cached_deps_time
        try:
            req_file = BASE_DIR / "requirements-runtime.lock"
            if not req_file.exists():
                append_log("[ERROR] requirements.txt not found in project root directory.")
                return

            py_cli = get_python_cli_path()
            append_log(f"Using Python interpreter: {py_cli}")
            append_log(f"Running: {py_cli} -m pip install -r {req_file.name}")

            cmd = [py_cli, "-I", "-m", "pip", "install", "--only-binary=:all:", "-r", str(req_file)]
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW
            )
            for line in proc.stdout:
                l_str = line.strip()
                if l_str:
                    append_log(l_str)

            proc.wait()
            _cached_deps_time = 0.0

            deps_after = check_python_deps()
            if proc.returncode == 0 and deps_after.get("installed", False):
                append_log("[SUCCESS] All required Python libraries installed successfully!")
                if auto_start_server:
                    append_log("[FIRST RUN] Automatically starting PC Control server and watchdog supervisor...")
                    time.sleep(0.5)
                    ok, code, title, msg = start_server_process()
                    if ok:
                        append_log(f"[SUCCESS] {msg}")
                    else:
                        append_log(f"[WARNING] Automatic server start: {title} - {msg}")
            else:
                append_log(f"[ERROR] Dependency preparation failed (pip exit {proc.returncode}): {deps_after['details']}")
        except Exception as e:
            append_log(f"[ERROR] Exception during dependency installation: {e}")
        finally:
            _is_busy = False
            _busy_action = ""
            _cached_deps_time = 0.0
            _background_lock.release()

    threading.Thread(target=_worker, daemon=True).start()
    return True


_first_run_checked = False

def check_first_run_setup():
    global _first_run_checked
    if _first_run_checked:
        return
    _first_run_checked = True

    # 1. Автоматическое создание config.json с авто-определением сетевых настроек
    load_config_data()

    # 2. Проверка библиотек и автоматическая установка на первом запуске
    deps = check_python_deps()
    if not deps.get("installed", False):
        append_log("[FIRST RUN] Missing Python dependencies detected. Starting automated environment preparation...")
        run_install_dependencies_task(auto_start_server=True)
    else:
        append_log("[READY] Components verified. Use Start server when ready.")


@serialize_lifecycle
def start_server_process() -> tuple:
    """
    Выполняет запуск server.py и сторожевого таймера.
    Возвращает (success: bool, error_code: str, error_title: str, details: str)
    """
    deps = check_python_deps()
    if not deps.get("installed", False):
        return (
            False,
            "ERR_PYTHON_DEPS_MISSING",
            "Не установлены библиотеки Python",
            "Для работы сервера требуются библиотеки Flask, Pillow, Winsdk и др.\nНажмите кнопку 'Установить' в Шаге 1 чек-листа перед запуском."
        )

    cfg = load_config_data()
    port = int(cfg.get("port", 5000))

    if is_server_running(port):
        return (True, "", "", f"Сервер уже запущен и принимает подключения на порту {port}.")

    # Проверка доступности порта перед запуском
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        port_in_use = (s.connect_ex(("127.0.0.1", port)) == 0)
    except Exception:
        port_in_use = False
    finally:
        s.close()

    if port_in_use:
        return (
            False,
            "ERR_PORT_OCCUPIED",
            f"Порт {port} уже занят",
            f"Порт {port} занят сторонним приложением или зависшим процессом.\nОсвободите порт {port} или проверьте Диспетчер задач Windows."
        )

    flag = LOGS_DIR / "manual_stop.flag"
    if flag.exists():
        try:
            flag.unlink()
        except Exception:
            pass

    # Перед запуском гарантируем отсутствие зависших процессов server.py
    if not is_server_running(port):
        kill_processes_by_name("server.py")

    pyw_bin = get_pythonw_path()
    server_script = BASE_DIR / "server.py"
    if not server_script.exists():
        return (
            False,
            "ERR_SCRIPT_NOT_FOUND",
            "Файл server.py не найден",
            f"Не найден исполняемый скрипт сервера по пути:\n{server_script}"
        )

    stderr_path = LOGS_DIR / "server_stderr.log"
    stdout_path = LOGS_DIR / "server_stdout.log"
    try:
        with open(stderr_path, "w", encoding="utf-8") as f:
            f.write("")
        with open(stdout_path, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass

    try:
        err_f = open(stderr_path, "a", encoding="utf-8", errors="replace")
        out_f = open(stdout_path, "a", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(
                [pyw_bin, "-E", "-s", str(server_script)],
                cwd=str(BASE_DIR),
                creationflags=NO_WINDOW,
                stdout=out_f,
                stderr=err_f
            )
        finally:
            try:
                out_f.close()
            except Exception:
                pass
            try:
                err_f.close()
            except Exception:
                pass
        watchdog_script = SCRIPTS_DIR / "watchdog.pyw"
        if watchdog_script.exists():
            subprocess.Popen([pyw_bin, "-E", "-s", str(watchdog_script)], cwd=str(BASE_DIR), creationflags=NO_WINDOW)
    except Exception as e:
        return (
            False,
            "ERR_SPAWN_FAILED",
            "Ошибка создания процесса",
            f"Не удалось запустить процесс server.py через {pyw_bin}:\n{e}"
        )

    # Success means the HTTP health endpoint answered, not merely a live PID.
    start_t = time.time()
    while time.time() - start_t < 20:
        ret = proc.poll()
        if ret is not None:
            # Процесс упал сразу после запуска!
            err_text = ""
            try:
                if stderr_path.exists():
                    err_text = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                pass
            if not err_text:
                err_text = f"Процесс server.py завершился с кодом возврата {ret}."
            return (
                False,
                "ERR_SERVER_CRASHED",
                "Сбой при запуске сервера",
                err_text
            )
        if is_server_running(port):
            return (True, "", "", f"Сервер успешно запущен на порту {port}.")
        time.sleep(0.25)

    return (
        False,
        "ERR_STARTUP_TIMEOUT",
        "Таймаут ожидания запуска",
        f"Сервер не ответил на порту {port} за отведенное время."
    )


def get_pids_on_port(port: int = 5000) -> list:
    pids = []
    if platform.system() != "Windows":
        return pids
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            creationflags=NO_WINDOW,
            text=True,
            timeout=2.0
        )
        target = f":{port} "
        for line in out.splitlines():
            if target in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    try:
                        pid = int(parts[-1])
                        if pid > 0 and pid not in pids:
                            pids.append(pid)
                    except ValueError:
                        pass
    except Exception:
        pass
    return pids


def kill_pid(pid: int):
    # Never terminate an unrelated application just because it owns our port.
    try:
        import psutil
        process = psutil.Process(pid)
        cmdline = process.cmdline()
        owned_scripts = {(BASE_DIR / "server.py").resolve(), (SCRIPTS_DIR / "watchdog.pyw").resolve()}
        cwd = Path(process.cwd())
        if not any((cwd / arg).resolve() in owned_scripts for arg in cmdline[1:] if not arg.startswith("-")):
            return
    except Exception:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            creationflags=NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0
        )
    except Exception:
        pass


def kill_processes_by_name(process_script: str):
    if platform.system() != "Windows":
        return
    try:
        import psutil
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            if (process.info.get("name") or "").lower().startswith("python"):
                if any(Path(arg).name == process_script for arg in (process.info.get("cmdline") or [])[1:]):
                    kill_pid(process.pid)
    except Exception:
        pass


@serialize_lifecycle
def stop_server_process() -> tuple:
    """
    Выполняет гарантированную остановку server.py и сторожевого таймера.
    """
    # 1. Записываем флаг ручной остановки, чтобы watchdog не перезапускал сервер
    try:
        with open(LOGS_DIR / "manual_stop.flag", "w") as f:
            f.write("manual_stop")
    except Exception:
        pass

    # 2. Мягкая остановка через HTTP API сервера
    cfg = load_config_data()
    token = cfg.get("token", "")
    port = int(cfg.get("port", 5000))
    try:
        if not is_server_running(port):
            raise ConnectionError("No server belonging to this installation on this port")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/server/stop",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-Auth-Token": urllib.parse.quote(token)},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=1.0):
            pass
    except Exception:
        pass

    # 3. Ждем до 1.0 сек мягкого завершения
    start_t = time.time()
    while time.time() - start_t < 1.0:
        if not is_server_running(port):
            break
        time.sleep(0.15)

    # 4. Если порт всё ещё занят или остались процессы server.py / watchdog.pyw — завершаем их принудительно
    for pid in get_pids_on_port(port):
        kill_pid(pid)

    kill_processes_by_name("server.py")
    kill_processes_by_name("watchdog.pyw")

    # 5. Проверка освобождения порта
    time.sleep(0.2)
    if not is_server_running(port):
        return (True, "", "", "Сервер успешно остановлен.")
    else:
        for pid in get_pids_on_port(port):
            kill_pid(pid)
        time.sleep(0.2)
        if is_server_running(port):
            return (False, "ERR_STOP_FAILED", "Ошибка остановки", "Сервер продолжает работать.")
        return (True, "", "", "Процессы сервера принудительно остановлены.")


@serialize_lifecycle
def restart_server_process() -> tuple:
    """
    Выполняет перезапуск сервера.
    """
    result = stop_server_process()
    if not result[0]:
        return result
    time.sleep(0.4)
    return start_server_process()


def save_token_everywhere(new_token: str):
    new_token = str(new_token).strip()
    if not new_token:
        return False

    with _settings_lock:
        cfg = load_config_data()
        cfg["token"] = new_token
        save_config_data(cfg)

    return True


def clean_browser_profiles() -> dict:
    """Очищает временные профили и кэш браузеров из %LOCALAPPDATA%\\PCControl."""
    import shutil
    local_root = os.environ.get("LOCALAPPDATA")
    if not local_root or not Path(local_root).is_absolute():
        return {"ok": False, "message": "LOCALAPPDATA is unavailable; no files were removed", "removed_items": [], "freed_mb": 0}
    local_app = Path(local_root) / "PCControl"
    removed_items = []
    failures = []
    freed_bytes = 0
    if local_app.exists():
        for item in local_app.iterdir():
            if item.name in ("TailscaleAppProfile", "ChromeProfile", "EdgeProfile", "LauncherProfile", "EBWebView", "Cache"):
                try:
                    size = 0
                    if item.is_dir():
                        for root, dirs, files in os.walk(item):
                            for f in files:
                                try:
                                    size += os.path.getsize(os.path.join(root, f))
                                except Exception:
                                    pass
                        shutil.rmtree(item)
                    else:
                        size = item.stat().st_size
                        item.unlink(missing_ok=True)
                    freed_bytes += size
                    removed_items.append(item.name)
                except Exception as e:
                    failures.append(item.name)
                    append_log(f"Could not remove {item.name}: {e}")
    mb = round(freed_bytes / (1024 * 1024), 2)
    return {
        "ok": not failures,
        "message": "Could not remove: " + ", ".join(failures) if failures else "Browser profiles cleaned",
        "freed_bytes": freed_bytes,
        "freed_mb": mb,
        "removed_items": removed_items
    }


LATEST_UPDATE_INFO = None


def get_local_launcher_hash() -> str:
    """Вычисляет SHA-256 локального Launcher.exe."""
    local_exe = BASE_DIR / "Launcher.exe"
    if not local_exe.exists():
        return ""
    try:
        import hashlib
        return hashlib.sha256(local_exe.read_bytes()).hexdigest().lower()
    except Exception:
        return ""


def find_git_binary() -> str:
    which_git = shutil.which("git")
    if which_git:
        return which_git
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            try:
                for g in winget_pkgs.glob("**/cmd/git.exe"):
                    if g.exists():
                        return str(g)
            except Exception:
                pass
    for std_p in (r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files (x86)\Git\cmd\git.exe"):
        if os.path.exists(std_p):
            return std_p
    return "git"


def check_github_updates() -> dict:
    global LATEST_UPDATE_INFO
    from scripts import full_update
    LATEST_UPDATE_INFO = full_update.check(BASE_DIR)
    return LATEST_UPDATE_INFO


def apply_github_update() -> dict:
    global _is_busy, _busy_action
    from scripts import full_update
    if not _background_lock.acquire(False):
        return {"ok": False, "message": "Другая операция ещё выполняется."}
    _is_busy, _busy_action = True, "Full project update"
    restarting = False
    try:
        result = full_update.prepare(BASE_DIR, CONTROL_PORT, is_server_running(), append_log)
        restarting = bool(result.get('restarting'))
        return result
    finally:
        if not restarting:
            _is_busy, _busy_action = False, ""
            _background_lock.release()


def get_update_status():
    try:
        return json.loads((LOGS_DIR / 'update_status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def get_windows_hello_status() -> dict:
    """
    Проверяет реальное состояние настройки Windows Hello PasswordLess в реестре Windows.
    HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\PasswordLess\\Device
    DevicePasswordLessBuildVersion:
      2 (или отсутствует по умолчанию в Win10/11) -> Enabled (Windows Hello required for MS accounts, netplwiz checkbox hidden)
      0 -> Disabled (Windows Hello requirement disabled, netplwiz checkbox visible)
    """
    if platform.system() != "Windows":
        return {"supported": False, "enabled": False, "raw_value": None}
    try:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device") as k:
                val, _ = winreg.QueryValueEx(k, "DevicePasswordLessBuildVersion")
                enabled = (int(val) != 0)
                raw_val = int(val)
        except FileNotFoundError:
            enabled = True
            raw_val = None
        except Exception:
            enabled = True
            raw_val = None

        return {
            "supported": True,
            "enabled": enabled,
            "raw_value": raw_val,
        }
    except Exception as e:
        return {"supported": False, "enabled": False, "raw_value": None, "error": str(e)}


def run_elevated_command(target: str, params: str = "", work_dir: str = "", show: bool = True, timeout: int = 120) -> tuple[bool, str, str]:
    """
    Выполняет запуск команды/процесса с запросом прав администратора (UAC) в Windows.
    Решает проблему песочниц (включая Microsoft Store/MSIX Python, где прямой Win32 ShellExecute
    блокируется ядром ОС с кодом 5 ERROR_ACCESS_DENIED или кодом 50 без вывода окна UAC).
    
    Обеспечивает гарантированное появление системного окна подтверждения UAC на экране пользователя.
    
    Возвращает:
        (ok: bool, code: str, message: str)
    """
    if platform.system() != "Windows":
        return False, "ERR_NOT_SUPPORTED", "UAC elevation is only supported on Windows."

    # Способ 1: Прямой ShellExecuteW (работает в стандартном Win32 Python окружении)
    try:
        import ctypes
        from ctypes import wintypes
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.ShellExecuteW.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = wintypes.HINSTANCE
        hwnd = ctypes.windll.user32.GetForegroundWindow() or None
        ctypes.set_last_error(0)
        res = shell32.ShellExecuteW(
            hwnd,
            "runas",
            target,
            params,
            work_dir or None,
            1 if show else 0
        )
        last_err = ctypes.get_last_error()
        res_val = int(res) if res is not None else 0
        if res_val > 32:
            return True, "OK", "Elevation launched successfully via ShellExecuteW"
        if last_err == 1223:  # ERROR_CANCELLED - user explicitly declined UAC
            return False, "ERR_UAC_DENIED", "Запрос прав администратора (UAC) был отклонен пользователем."
    except Exception:
        res_val = 0

    # Способ 2: Shell.Application COM через powershell.exe
    # Этот способ работает из любого окружения (включая Store/MSIX Python и фоновые процессы),
    # так как обращается к COM-серверу Проводника (Explorer Shell) на интерактивном рабочем столе пользователя.
    t_esc = target.replace("'", "''")
    p_esc = params.replace("'", "''")
    w_esc = work_dir.replace("'", "''")
    n_show = 1 if show else 0

    ps_script = (
        f"$ErrorActionPreference = 'Stop'; "
        f"try {{ "
        f"  $sh = New-Object -ComObject Shell.Application; "
        f"  $sh.ShellExecute('{t_esc}', '{p_esc}', '{w_esc}', 'runas', {n_show}); "
        f"  Write-Output 'UAC_OK'; "
        f"}} catch {{ "
        f"  $msg = $_.Exception.Message; "
        f"  if ($msg -match '0x800704C7' -or $msg -match '1223' -or $msg -match 'canceled' -or $msg -match 'cancel' -or $msg -match 'отменен' -or $msg -match 'отклон') {{ "
        f"    Write-Output 'UAC_CANCELLED'; "
        f"  }} else {{ "
        f"    Write-Output ('UAC_ERROR:' + $msg); "
        f"  }} "
        f"  exit 1; "
        f"}}"
    )

    try:
        proc = subprocess.run([
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden",
            "-Command", ps_script
        ], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)

        out = proc.stdout.strip()
        if "UAC_OK" in out:
            return True, "OK", "Команда с правами администратора успешно запущена."
        elif "UAC_CANCELLED" in out:
            return False, "ERR_UAC_DENIED", "Запрос прав администратора (UAC) был отклонен пользователем."
        else:
            err_line = next((l for l in out.splitlines() if l.startswith("UAC_ERROR:")), out or proc.stderr.strip())
            return False, "ERR_UAC_FAILED", f"Не удалось повысить привилегии: {err_line}"

    except subprocess.TimeoutExpired:
        return False, "ERR_UAC_TIMEOUT", "Истекло время ожидания подтверждения запроса прав администратора (UAC)."
    except Exception as e:
        return False, "ERR_UAC_EXCEPTION", f"Сбой вызова механизма UAC: {e}"


def set_windows_hello_state(enabled: bool) -> tuple[bool, str]:
    """
    Устанавливает DevicePasswordLessBuildVersion (2 = Включено, 0 = Отключено).
    Запрашивает права администратора (UAC) гарантированно через run_elevated_command.
    После выполнения обязательно проверяет фактическое значение в реестре!
    """
    if platform.system() != "Windows":
        return (False, "Изменение параметров Windows Hello поддерживается только в ОС Windows.")

    target_val = 2 if enabled else 0
    current_status = get_windows_hello_status()
    if current_status.get("supported") and current_status.get("enabled") == enabled:
        return (True, f"Настройка Windows Hello уже {'включена' if enabled else 'отключена'}.")

    ps_cmd = (
        f"$p = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\PasswordLess\\Device'; "
        f"if (-not (Test-Path $p)) {{ New-Item -Path $p -Force | Out-Null }}; "
        f"Set-ItemProperty -Path $p -Name 'DevicePasswordLessBuildVersion' -Value {target_val} -Type DWord"
    )

    ok, code, msg = run_elevated_command(
        "powershell.exe",
        f'-NoProfile -NonInteractive -WindowStyle Hidden -Command "{ps_cmd}"',
        show=False
    )
    if not ok:
        return (False, msg)

    # Ждём до 3 секунд и проверяем фактическое значение в реестре
    for _ in range(15):
        time.sleep(0.2)
        new_status = get_windows_hello_status()
        if new_status.get("enabled") == enabled:
            return (True, f"Windows Hello успешно {'включен' if enabled else 'отключен'}.")

    return (False, "Значение реестра не изменилось. Возможно, действуют групповые политики Windows или изменение заблокировано системой.")


def launch_netplwiz() -> tuple[bool, str]:
    """
    Запускает только системную утилиту netplwiz.exe (или control userpasswords2).
    НЕ изменяет никаких учетных данных или системных параметров.
    """
    if platform.system() != "Windows":
        return (False, "Утилита netplwiz доступна только в ОС Windows.")
    try:
        import ctypes
        res = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            "netplwiz.exe",
            None,
            None,
            1  # SW_SHOWNORMAL
        )
        if res > 32:
            return (True, "Системное окно netplwiz успешно открыто.")
        else:
            res2 = ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                "control.exe",
                "userpasswords2",
                None,
                1
            )
            if res2 > 32:
                return (True, "Системное окно netplwiz (userpasswords2) открыто.")
            return (False, f"Не удалось открыть netplwiz (код ошибки {res}).")
    except Exception as e:
        return (False, f"Ошибка при запуске netplwiz: {e}")


def open_signin_settings() -> tuple[bool, str]:
    """
    Открывает системный раздел «Параметры -> Учетные записи -> Варианты входа» (ms-settings:signinoptions).
    """
    if platform.system() != "Windows":
        return (False, "Параметры Windows доступны только в ОС Windows.")
    try:
        import ctypes
        res = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            "ms-settings:signinoptions",
            None,
            None,
            1
        )
        if res > 32:
            return (True, "Раздел параметров входа Windows открыт.")
        return (False, f"Не удалось открыть параметры входа (код ошибки {res}).")
    except Exception as e:
        return (False, f"Ошибка при открытии параметров входа: {e}")


def run_command_async(cmd, name=""):
    global _is_busy, _busy_action

    def _worker():
        global _is_busy, _busy_action
        _is_busy = True
        _busy_action = name
        append_log(f"Starting task: {name}...")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW
            )
            for line in proc.stdout:
                line_str = line.strip()
                if line_str:
                    append_log(line_str)
            proc.wait()
            if proc.returncode == 0:
                append_log(f"Task '{name}' completed successfully.")
            else:
                append_log(f"Task '{name}' finished with exit code {proc.returncode}.")
        except Exception as e:
            append_log(f"Error during '{name}': {e}")
        finally:
            _is_busy = False
            _busy_action = ""

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


class ControlPanelHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            # A browser may cancel an in-flight poll on reload or close.
            pass

    def _trusted_request(self):
        # Loopback binding alone does not protect against hostile browser pages
        # or DNS rebinding. Only this panel's own origin may use its API.
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin.lower() not in
                                   {f"http://{h}" for h in allowed}):
            self.send_json({"ok": False, "message": "Untrusted panel origin"}, 403)
            return False
        return True

    def do_GET(self):
        if not self._trusted_request():
            return
        record_activity()
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path

        if path == "/api/identity":
            self.send_json({"application": "PCControl", "instance": instance_id()})
            return
        if path == "/download/apk":
            apk = BASE_DIR / "PC_Control.apk"
            if not apk.is_file():
                self.send_json({"ok": False, "message": "PC_Control.apk is missing from the archive"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.android.package-archive")
            self.send_header("Content-Disposition", 'attachment; filename="PC_Control.apk"')
            self.send_header("Content-Length", str(apk.stat().st_size))
            self.end_headers()
            try:
                with apk.open("rb") as stream:
                    shutil.copyfileobj(stream, self.wfile)
            except (ConnectionError, OSError):
                pass
            return
        elif path == "/api/status":
            cfg = load_config_data()
            port = int(cfg.get("port", 5000))
            server_up = is_server_running(port)
            lan_ip = cfg.get("lan_ip") or get_local_ip()
            ts_info = get_tailscale_info()
            cfg = sync_network_settings(cfg, ts_info)
            lan_ip = cfg.get("lan_ip", "")
            fw_ok = is_firewall_configured()
            py_deps = check_python_deps()

            self.send_json({
                "server_running": server_up,
                "server_url": f"http://{lan_ip}:{port}",
                "port": port,
                "lan_ip": lan_ip,
                "tailscale": ts_info,
                "firewall_configured": fw_ok,
                "python_deps": py_deps,
                "apk_build_available": (BASE_DIR / "android_app" / "AndroidManifest.xml").is_file() and (BASE_DIR / ".android_sdk").is_dir(),
                "windows_hello": get_windows_hello_status(),
                "token": cfg.get("token", ""),
                "mac_address": cfg.get("mac_address", "AA-BB-CC-DD-EE-FF"),
                "language": cfg.get("language", "en"),
                "cors_allowed_origins": cfg.get("cors_allowed_origins", [
                    "http://localhost:*",
                    "http://127.0.0.1:*",
                    "http://192.168.*",
                    "http://100.*",
                    "http://10.*"
                ]),
                "is_busy": _is_busy,
                "busy_action": _busy_action,
                "setup_in_progress": bool(_is_busy and "Dependencies Installation" in _busy_action),
                "update_info": LATEST_UPDATE_INFO,
                "full_update_status": get_update_status()
            })
            return

        if path == "/api/logs":
            self.send_json({
                "logs": get_logs(),
                "is_busy": _is_busy,
                "busy_action": _busy_action
            })
            return

        if path == "/favicon.ico":
            ico_path = BASE_DIR / "pc_control.ico"
            if ico_path.exists():
                try:
                    data = ico_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/x-icon")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    pass

        if path == "/logo.png":
            logo_path = BASE_DIR / "web" / "logo.png"
            if logo_path.exists():
                try:
                    data = logo_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    pass

        if not path.startswith("/api/"):
            content = get_panel_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if not self._trusted_request():
            return
        record_activity()
        try:
            self._handle_post()
        except Exception as e:
            append_log(f"[ERROR] Unhandled POST exception: {e}")
            try:
                self.send_json({
                    "ok": False,
                    "error_code": "ERR_INTERNAL",
                    "error_title": "Внутренняя ошибка панели",
                    "message": str(e),
                    "details": str(e)
                }, 500)
            except Exception:
                pass

    def _handle_post(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path

        try:
            length = int(self.headers.get("Content-Length", 0))
            if length < 0 or length > 65536:
                raise ValueError("Request body must be at most 64 KiB")
            self.connection.settimeout(10)
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            req_data = json.loads(body)
            if not isinstance(req_data, dict):
                raise ValueError("Expected a JSON object")
        except (ValueError, UnicodeError) as exc:
            self.send_json({"ok": False, "message": str(exc)}, 400)
            return

        if path == "/api/action":
            action = req_data.get("action", "")

            if action == "detect_network":
                cfg = sync_network_settings(load_config_data(), get_tailscale_info(), force=True)
                self.send_json({"ok": bool(cfg.get("lan_ip")), "message": "Network detected" if cfg.get("lan_ip") else "No active LAN adapter found", "settings": cfg})
                return

            if action == "get_settings":
                cfg = load_config_data()
                keys = ("lan_ip", "vpn_ip", "wol_relay_ip", "mac_address", "port", "relay_port")
                self.send_json({"ok": True, "settings": {key: cfg.get(key, "") for key in keys}})
                return

            if action == "save_settings":
                try:
                    settings = validate_network_settings(req_data.get("settings", {}))
                except (ValueError, AttributeError) as exc:
                    self.send_json({"ok": False, "message": str(exc)}, 400)
                    return
                with _settings_lock:
                    cfg = load_config_data()
                    if settings["port"] != cfg.get("port", 5000) and is_server_running(int(cfg.get("port", 5000))):
                        self.send_json({"ok": False, "message": "Stop the server before changing its port / Сначала остановите сервер"}, 409)
                        return
                    manual_addresses = any(settings[k] != cfg.get(k, '') for k in ('lan_ip', 'vpn_ip', 'mac_address'))
                    cfg.update(settings)
                    if manual_addresses:
                        cfg["auto_network"] = False
                    save_config_data(cfg)
                self.send_json({"ok": True, "settings": settings})
                return

            if action == "set_language":
                lang = str(req_data.get("language", "")).strip().lower()
                if lang in ("en", "ru", "uk"):
                    try:
                        with _settings_lock:
                            cfg = load_config_data()
                            cfg["language"] = lang
                            save_config_data(cfg)
                        append_log(f"Interface language saved to config.json: {lang.upper()}")
                        self.send_json({"ok": True, "language": lang})
                    except Exception as e:
                        self.send_json({
                            "ok": False,
                            "error_code": "ERR_CONFIG_WRITE",
                            "error_title": "Ошибка сохранения конфигурации",
                            "message": f"Не удалось записать язык в config.json: {e}",
                            "details": str(e)
                        }, 500)
                else:
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_INVALID_PARAM",
                        "error_title": "Неподдерживаемый язык",
                        "message": f"Язык '{lang}' не поддерживается.",
                        "details": f"Supported: en, ru, uk. Received: {lang}"
                    }, 400)
                return

            if action == "start_server":
                append_log("Starting server...")
                deps = check_python_deps()
                if not deps.get("installed", False):
                    append_log("[FIRST RUN] Missing Python dependencies detected. Starting automated installation...")
                    if not run_install_dependencies_task(auto_start_server=True):
                        self.send_json({"ok": False, "message": "Another background task is already running"}, 409)
                        return
                    self.send_json({
                        "ok": True,
                        "setup_started": True,
                        "message": "Установка библиотек запущена. Сервер запустится автоматически сразу после завершения."
                    })
                    return
                ok, err_code, err_title, details = start_server_process()
                if ok:
                    append_log("Server started successfully.")
                    self.send_json({"ok": True, "message": details})
                else:
                    append_log(f"[ERROR] {err_title} ({err_code}): {details}")
                    self.send_json({
                        "ok": False,
                        "error_code": err_code,
                        "error_title": err_title,
                        "message": details,
                        "details": details
                    }, 500)
                return

            if action == "stop_server":
                append_log("Stopping server and watchdog supervisor...")
                ok, err_code, err_title, details = stop_server_process()
                append_log(details)
                self.send_json({"ok": ok, "message": details, "error_code": err_code}, 200 if ok else 500)
                return

            if action == "restart_server":
                append_log("Restarting server...")
                ok, err_code, err_title, details = restart_server_process()
                if ok:
                    append_log("Server restarted successfully.")
                    self.send_json({"ok": True, "message": details})
                else:
                    append_log(f"[ERROR] {err_title} ({err_code}): {details}")
                    self.send_json({
                        "ok": False,
                        "error_code": err_code,
                        "error_title": err_title,
                        "message": details,
                        "details": details
                    }, 500)
                return

            if action == "install_deps":
                started = run_install_dependencies_task(auto_start_server=True)
                self.send_json({"ok": started, "message": "Dependencies installation started" if started else "Another background task is already running"}, 200 if started else 409)
                return

            if action == "apply_firewall":
                append_log("Requesting Administrator privileges (UAC) to configure Windows Firewall...")
                script_path = SCRIPTS_DIR / "apply_firewall_rule.bat"
                if not script_path.exists():
                    append_log("[ERROR] apply_firewall_rule.bat not found.")
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_SCRIPT_NOT_FOUND",
                        "error_title": "Скрипт не найден",
                        "message": "Файл apply_firewall_rule.bat не найден в папке scripts.",
                        "details": str(script_path)
                    }, 404)
                    return

                ok, code, msg = run_elevated_command(
                    "cmd.exe",
                    f'/c ""{script_path}""',
                    str(BASE_DIR),
                    show=True
                )
                if ok:
                    global _cached_fw_time
                    _cached_fw_time = 0.0
                    append_log("Firewall setup window opened (please confirm UAC in Windows).")
                    self.send_json({"ok": True, "message": "Окно настройки брандмауэра открыто (подтвердите UAC)"})
                else:
                    append_log(f"[ERROR] {msg} ({code})")
                    self.send_json({
                        "ok": False,
                        "error_code": code,
                        "error_title": "Ошибка прав администратора (UAC)" if code == "ERR_UAC_DENIED" else "Сбой настройки брандмауэра",
                        "message": msg,
                        "details": f"Elevation error: {code} - {msg}"
                    }, 403 if code == "ERR_UAC_DENIED" else 500)
                return

            if action == "launch_netplwiz":
                append_log("Launching Windows User Accounts utility (netplwiz.exe)...")
                ok, msg = launch_netplwiz()
                if ok:
                    append_log("System utility netplwiz opened successfully.")
                    self.send_json({"ok": True, "message": msg})
                else:
                    append_log(f"[ERROR] Failed to launch netplwiz: {msg}")
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_NETPLWIZ_LAUNCH",
                        "error_title": "Сбой запуска netplwiz",
                        "message": msg,
                        "details": msg
                    }, 500)
                return

            if action == "open_signin_settings":
                append_log("Opening Windows Sign-In Options (ms-settings:signinoptions)...")
                ok, msg = open_signin_settings()
                if ok:
                    append_log("Windows Sign-In Options opened successfully.")
                    self.send_json({"ok": True, "message": msg})
                else:
                    append_log(f"[ERROR] Failed to open Windows settings: {msg}")
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_SETTINGS_LAUNCH",
                        "error_title": "Сбой открытия настроек Windows",
                        "message": msg,
                        "details": msg
                    }, 500)
                return

            if action == "set_windows_hello":
                enabled = req_data.get("enabled")
                if not isinstance(enabled, bool):
                    self.send_json({"ok": False, "message": "enabled must be a boolean"}, 400)
                    return
                state_str = "Enabled" if enabled else "Disabled"
                append_log(f"Requesting UAC elevation to set Windows Hello to {state_str}...")
                ok, msg = set_windows_hello_state(enabled)
                st = get_windows_hello_status()
                if ok:
                    append_log(f"Windows Hello requirement successfully set to {state_str}.")
                    self.send_json({"ok": True, "enabled": st.get("enabled"), "message": msg})
                else:
                    append_log(f"[ERROR] Failed to set Windows Hello: {msg}")
                    self.send_json({
                        "ok": False,
                        "enabled": st.get("enabled"),
                        "error_code": "ERR_HELLO_CHANGE_FAILED",
                        "error_title": "Сбой изменения Windows Hello",
                        "message": msg,
                        "details": msg
                    }, 400)
                return

            if action == "setup_autologon":
                append_log("Requesting Administrator privileges (UAC) for Autologon setup...")
                ps_script = SCRIPTS_DIR / "setup_autologon.ps1"
                if not ps_script.exists():
                    append_log("[ERROR] setup_autologon.ps1 not found.")
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_SCRIPT_NOT_FOUND",
                        "error_title": "Скрипт не найден",
                        "message": "Файл setup_autologon.ps1 не найден в папке scripts.",
                        "details": str(ps_script)
                    }, 404)
                    return

                ok, code, msg = run_elevated_command(
                    "powershell.exe",
                    f'-NoProfile -ExecutionPolicy Bypass -File "{ps_script}"',
                    str(SCRIPTS_DIR),
                    show=True
                )
                if ok:
                    append_log("Interactive autologon setup window opened (please confirm UAC).")
                    self.send_json({"ok": True, "message": "Окно настройки автовхода открыто (подтвердите UAC)"})
                else:
                    append_log(f"[ERROR] {msg} ({code})")
                    self.send_json({
                        "ok": False,
                        "error_code": code,
                        "error_title": "Ошибка прав администратора (UAC)" if code == "ERR_UAC_DENIED" else "Сбой настройки автовхода",
                        "message": msg,
                        "details": f"Elevation error: {code} - {msg}"
                    }, 403 if code == "ERR_UAC_DENIED" else 500)
                return

            if action == "set_password":
                new_pwd = req_data.get("password", "")
                if not isinstance(new_pwd, str):
                    self.send_json({"ok": False, "message": "Password must be text"}, 400)
                    return
                new_pwd = new_pwd.strip()
                if not new_pwd:
                    self.send_json({"ok": False, "message": "Password cannot be empty"}, 400)
                    return
                if not save_token_everywhere(new_pwd):
                    self.send_json({"ok": False, "message": "Could not save password"}, 500)
                    return
                append_log("Access password changed.")
                self.send_json({"ok": True, "message": "Password successfully saved"})
                return

            if action == "rebuild_apk":
                global _is_busy, _busy_action
                if not _background_lock.acquire(blocking=False):
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_SYSTEM_BUSY",
                        "error_title": "Система занята",
                        "message": f"Уже выполняется фоновая задача: {_busy_action}. Дождитесь её завершения.",
                        "details": "Пожалуйста, дождитесь окончания текущей операции."
                    }, 409)
                    return

                script_path = SCRIPTS_DIR / "build_apk.py"
                if not script_path.exists():
                    script_path = BASE_DIR / "build_apk.py"
                if not script_path.exists():
                    append_log("[ERROR] Script build_apk.py not found.")
                    _background_lock.release()
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_SCRIPT_NOT_FOUND",
                        "error_title": "Скрипт не найден",
                        "message": "Файл build_apk.py не найден в папке проекта.",
                        "details": "Проверьте наличие файла scripts/build_apk.py."
                    }, 404)
                    return

                append_log("Starting Android APK rebuild (PC_Control.apk)...")
                _is_busy = True
                _busy_action = "Rebuild PC_Control.apk"
                try:
                    py_cli = get_python_cli_path()
                    proc = subprocess.Popen(
                        [py_cli, str(script_path)],
                        cwd=str(BASE_DIR),
                        shell=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=NO_WINDOW
                    )
                    out_lines = []
                    for line in proc.stdout:
                        line_str = line.strip()
                        if line_str:
                            out_lines.append(line_str)
                            append_log(line_str)
                    proc.wait()
                    if proc.returncode == 0:
                        append_log("PC_Control.apk rebuild completed successfully.")
                        self.send_json({
                            "ok": True,
                            "message": "Android APK успешно пересобран и подписан!"
                        })
                    else:
                        details_text = "\n".join(out_lines[-25:])
                        append_log(f"PC_Control.apk rebuild failed with exit code {proc.returncode}.")
                        self.send_json({
                            "ok": False,
                            "error_code": f"ERR_APK_BUILD_{proc.returncode}",
                            "error_title": "Ошибка сборки APK",
                            "message": f"Сборка APK завершилась с ошибкой (код {proc.returncode}).",
                            "details": details_text
                        }, 500)
                except Exception as e:
                    append_log(f"Error during APK rebuild: {e}")
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_APK_BUILD_EXCEPTION",
                        "error_title": "Сбой сборки APK",
                        "message": str(e),
                        "details": str(e)
                    }, 500)
                finally:
                    _is_busy = False
                    _busy_action = ""
                    _background_lock.release()
                return

            if action == "launch_tailscale":
                bins = find_tailscale_binaries()
                if not bins.get("installed"):
                    if not _background_lock.acquire(False):
                        self.send_json({"ok": False, "message": "Another operation is running"}, 409)
                        return
                    try:
                        from scripts.network_setup import download_tailscale
                        installer = download_tailscale(BASE_DIR / "logs/installers")
                        os.startfile(str(installer))
                        self.send_json({"ok": True, "installer_launched": True, "message": "Tailscale: подтвердите установку Windows, затем войдите в аккаунт. IP подтянется автоматически."})
                    except Exception as error:
                        self.send_json({"ok": False, "message": "Tailscale installer: " + str(error)}, 500)
                    finally:
                        _background_lock.release()
                    return
                lang = req_data.get("lang") or "ru"
                installer_file = None
                for cand in [BASE_DIR / "tailscale-setup-1.102.4.exe"] + list(BASE_DIR.glob("tailscale-setup*.exe")):
                    if cand.is_file():
                        installer_file = cand
                        break

                # 1. Если Tailscale не установлен — запускаем локальный установщик или открываем страницу загрузки
                if not bins.get("installed"):
                    ts_info = get_tailscale_info()
                    if not ts_info.get("installed"):
                        if installer_file:
                            try:
                                os.startfile(str(installer_file))
                                append_log(f"Launched local Tailscale installer: {installer_file.name}")
                                msg = (
                                    f"Запущен установщик {installer_file.name}" if lang == "ru" else
                                    f"Запущено інсталятор {installer_file.name}" if lang == "uk" else
                                    f"Launched installer {installer_file.name}"
                                )
                                self.send_json({"ok": True, "message": msg, "installer_launched": True})
                                return
                            except Exception as e:
                                append_log(f"Could not start local installer: {e}")
                        try:
                            webbrowser.open("https://tailscale.com/download/windows")
                            append_log("Opened Tailscale official download page in browser.")
                        except Exception:
                            pass
                        if lang == "ru":
                            err_title = "Tailscale не установлен"
                            err_msg = "Открыта страница загрузки Tailscale. Скачайте и установите клиент для Windows."
                            inst_hint = f"\n\nВ папке проекта обнаружен файл установщика: {installer_file.name}. Вы можете установить его." if installer_file else ""
                            err_details = (
                                "Исполняемые файлы Tailscale (tailscale-ipn.exe, tailscale.exe) не найдены "
                                "в каталогах Program Files, реестре Windows и системном PATH.\n\n"
                                "Для работы защищенного удаленного доступа скачайте и установите Tailscale:\n"
                                f"https://tailscale.com/download/windows{inst_hint}"
                            )
                        elif lang == "uk":
                            err_title = "Tailscale не встановлено"
                            err_msg = "Відкрито сторінку завантаження Tailscale. Завантажте та встановіть клієнт для Windows."
                            inst_hint = f"\n\nУ папці проекту виявлено файл інсталятора: {installer_file.name}." if installer_file else ""
                            err_details = (
                                "Виконувані файли Tailscale (tailscale-ipn.exe, tailscale.exe) не знайдено "
                                "у каталогах Program Files, реєстрі Windows та системному PATH.\n\n"
                                "Для роботи захищеного віддаленого доступу завантажте та встановіть Tailscale:\n"
                                f"https://tailscale.com/download/windows{inst_hint}"
                            )
                        else:
                            err_title = "Tailscale Not Installed"
                            err_msg = "Opened Tailscale download page. Please download and install Tailscale for Windows."
                            inst_hint = f"\n\nA local installer was found in the project folder: {installer_file.name}." if installer_file else ""
                            err_details = (
                                "Tailscale executables (tailscale-ipn.exe, tailscale.exe) were not found "
                                "in Program Files, Windows Registry, or system PATH.\n\n"
                                "To use secure remote control, please download and install Tailscale:\n"
                                f"https://tailscale.com/download/windows{inst_hint}"
                            )
                        self.send_json({
                            "ok": False,
                            "error_code": "ERR_TAILSCALE_NOT_INSTALLED",
                            "error_title": err_title,
                            "message": err_msg,
                            "details": err_details,
                            "download_url": "https://tailscale.com/download/windows",
                            "installer_exists": bool(installer_file)
                        }, 404)
                        return

                # 2. Tailscale установлен — проверяем процесс трея (tailscale-ipn.exe)
                is_ipn_running = False
                try:
                    import psutil
                    for p in psutil.process_iter(["name"]):
                        if "tailscale-ipn" in (p.info.get("name") or "").lower():
                            is_ipn_running = True
                            break
                except Exception:
                    pass

                if not is_ipn_running:
                    if bins.get("shortcut") and bins["shortcut"].is_file():
                        try:
                            os.startfile(str(bins["shortcut"]))
                            append_log(f"Started Tailscale tray process via shortcut: {bins['shortcut'].name}")
                        except Exception as e:
                            append_log(f"Could not open Tailscale shortcut: {e}")
                    elif bins.get("gui") and bins["gui"].is_file():
                        try:
                            subprocess.Popen([str(bins["gui"])], cwd=str(bins["gui"].parent))
                            append_log(f"Started Tailscale GUI process: {bins['gui']}")
                        except Exception as e:
                            append_log(f"Could not start tailscale-ipn: {e}")
                else:
                    append_log("Tailscale background service (tailscale-ipn) is already active.")

                # 3. Определяем URL интерфейса Tailscale
                target_url = "http://100.100.100.100"
                if not check_tailscale_web_accessible(target_url, timeout=0.6):
                    if check_tailscale_web_accessible("http://127.0.0.1:8088", timeout=0.3):
                        target_url = "http://127.0.0.1:8088"
                    elif bins.get("cli") and bins["cli"].is_file():
                        try:
                            subprocess.Popen(
                                [str(bins["cli"]), "web", "--listen", "127.0.0.1:8088"],
                                creationflags=NO_WINDOW
                            )
                            time.sleep(0.4)
                            if check_tailscale_web_accessible("http://127.0.0.1:8088", timeout=0.8):
                                target_url = "http://127.0.0.1:8088"
                        except Exception:
                            pass

                if not check_tailscale_web_accessible(target_url, timeout=1):
                    self.send_json({"ok": False, "message": "Интерфейс Tailscale пока недоступен. Откройте значок Tailscale в трее, войдите в аккаунт и повторите."}, 503)
                    return
                # 4. Открываем окно приложения Tailscale
                launched = launch_tailscale_app_window(target_url)
                if launched:
                    succ_msg = (
                        "Приложение Tailscale открыто" if lang == "ru" else
                        "Додаток Tailscale відкрито" if lang == "uk" else
                        "Tailscale application opened"
                    )
                    append_log(f"Tailscale interface launched successfully ({target_url}).")
                    self.send_json({"ok": True, "message": succ_msg, "url": target_url})
                else:
                    err_msg = (
                        "Не удалось открыть окно Tailscale" if lang == "ru" else
                        "Не вдалося відкрити вікно Tailscale" if lang == "uk" else
                        "Failed to open Tailscale window"
                    )
                    self.send_json({
                        "ok": False,
                        "error_code": "ERR_LAUNCH_FAILED",
                        "error_title": "Ошибка запуска" if lang == "ru" else "Launch Error",
                        "message": err_msg,
                        "details": f"Не удалось запустить окно Tailscale по адресу {target_url}."
                    }, 500)
                return

            if action in ("open_web", "open_web_standalone"):
                cfg = load_config_data()
                port = int(cfg.get("port", 5000))
                # Убеждаемся, что сервер запущен, чтобы веб-пульт сразу подключился
                if not is_server_running(port):
                    append_log("Starting PC Control server before opening remote...")
                    ok, code, title, msg = start_server_process()
                    if not ok:
                        self.send_json({"ok": False, "message": msg or "Failed to start server"}, 500)
                        return
                    time.sleep(0.8)

                lang = req_data.get("lang") or cfg.get("language", "ru")
                token = cfg.get("token", "")
                token_param = f"token={urllib.parse.quote(token)}&" if token else ""
                remote_url = f"http://127.0.0.1:{port}/?{token_param}lang={urllib.parse.quote(lang)}"

                layout = get_desktop_window_layout()["remote"]
                window_flags = [
                    f"--window-position={layout['x']},{layout['y']}",
                    f"--window-size={layout['w']},{layout['h']}",
                ]
                edge_anti_translate = [
                    "--disable-features=Translate,msEdgeTranslate,TranslateUI",
                    "--disable-translate",
                    "--no-first-run",
                ]
                edge_paths = [
                    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    Path(os.environ.get("LocalAppData", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                ]
                edge_launched = False
                for edge_path in edge_paths:
                    if edge_path.exists():
                        try:
                            cmd = [
                                str(edge_path),
                                f"--app={remote_url}",
                            ] + window_flags + edge_anti_translate
                            subprocess.Popen(cmd)
                            enforce_window_geometry_async(["pc control — remote", "remote", str(port)], layout['x'], layout['y'], layout['w'], layout['h'])
                            edge_launched = True
                            append_log("Remote control opened in standalone window on the right side of PC Control.")
                            break
                        except Exception as e:
                            append_log(f"Failed to launch standalone Edge window: {e}")

                if not edge_launched:
                    chrome_paths = [
                        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
                        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
                        Path(os.environ.get("LocalAppData", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
                    ]
                    for cp in chrome_paths:
                        if cp.exists():
                            try:
                                subprocess.Popen([
                                    str(cp),
                                    f"--app={remote_url}",
                                ] + window_flags + edge_anti_translate)
                                enforce_window_geometry_async(["pc control — remote", "remote", str(port)], layout['x'], layout['y'], layout['w'], layout['h'])
                                edge_launched = True
                                append_log("Remote control opened in standalone Chrome window on the right side of PC Control.")
                                break
                            except Exception as e:
                                append_log(f"Failed to launch standalone Chrome window: {e}")

                if not edge_launched:
                    webbrowser.open(remote_url)
                    append_log("Remote control opened in default browser")

                self.send_json({"ok": True, "url": remote_url})
                return

            if action == "open_folder":
                os.startfile(str(BASE_DIR))
                self.send_json({"ok": True})
                return

            if action == "open_logs":
                os.startfile(str(LOGS_DIR))
                self.send_json({"ok": True})
                return

            if action == "clear_logs":
                global _action_logs
                with _log_lock:
                    _action_logs = ["[INFO] Console log cleared."]
                self.send_json({"ok": True})
                return

            if action == "rotate_token":
                import secrets
                new_token = secrets.token_hex(8)
                if not save_token_everywhere(new_token):
                    self.send_json({"ok": False, "message": "Could not save token"}, 500)
                    return
                append_log("Access token rotated.")
                self.send_json({"ok": True, "token": new_token, "message": "Токен доступа успешно обновлён"})
                return

            if action == "get_cors_origins":
                from core.config import get_cors_allowed_origins
                self.send_json({"ok": True, "origins": get_cors_allowed_origins()})
                return

            if action == "set_cors_origins":
                from core.config import update_cors_origins
                origins_in = req_data.get("origins")
                if isinstance(origins_in, str):
                    origins_list = [o.strip() for o in re.split(r"[,\r\n]+", origins_in) if o.strip()]
                elif isinstance(origins_in, list):
                    if not all(isinstance(o, str) for o in origins_in):
                        self.send_json({"ok": False, "message": "Origins must contain only strings"}, 400)
                        return
                    origins_list = [str(o).strip() for o in origins_in if str(o).strip()]
                else:
                    self.send_json({"ok": False, "message": "Origins must be text or a list"}, 400)
                    return
                with _settings_lock:
                    if not update_cors_origins(origins_list):
                        self.send_json({"ok": False, "message": "Could not save CORS settings"}, 500)
                        return
                append_log(f"CORS allowed origins updated: {origins_list}")
                self.send_json({"ok": True, "origins": origins_list})
                return

            if action == "check_updates":
                res = check_github_updates()
                self.send_json(res)
                return

            if action == "apply_update":
                res = apply_github_update()
                self.send_json(res)
                if res.get("ok") and res.get("restarting"):
                    threading.Timer(0.6, lambda: os._exit(0)).start()
                return

            if action == "clean_browser_profiles":
                res = clean_browser_profiles()
                append_log(f"Browser profiles cleaned: {res.get('freed_mb')} MB freed ({res.get('removed_items')})")
                self.send_json(res)
                return

            self.send_json({"ok": False, "message": "Unknown action"}, 400)
            return

        self.send_response(404)
        self.end_headers()


PANEL_HTML_PATH = BASE_DIR / "web" / "control_panel.html"

def get_panel_html() -> bytes:
    if PANEL_HTML_PATH.exists():
        return PANEL_HTML_PATH.read_bytes()
    return b"<h1>PC Control - Control Panel</h1>"



def launch_browser_gui(url: str):
    cache_bust_url = f"{url}/?v={int(time.time())}" + ("&show_update_banner=1" if "--check-update" in sys.argv else "")
    layout = get_desktop_window_layout()["launcher"]
    window_flags = [
        f"--window-position={layout['x']},{layout['y']}",
        f"--window-size={layout['w']},{layout['h']}",
    ]
    edge_anti_translate = [
        "--disable-features=Translate,msEdgeTranslate,TranslateUI",
        "--disable-translate",
        "--no-first-run",
    ]
    edge_paths = [
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LocalAppData", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for p in edge_paths:
        if p.exists():
            try:
                subprocess.Popen([str(p), f"--app={cache_bust_url}"] + window_flags + edge_anti_translate)
                enforce_window_geometry_async(["control panel", "панель управления", "5055"], layout['x'], layout['y'], layout['w'], layout['h'])
                return
            except Exception:
                pass

    chrome_paths = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LocalAppData", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for p in chrome_paths:
        if p.exists():
            try:
                subprocess.Popen([str(p), f"--app={cache_bust_url}"] + window_flags + ["--disable-features=Translate,TranslateUI", "--disable-translate"])
                enforce_window_geometry_async(["control panel", "панель управления", "5055"], layout['x'], layout['y'], layout['w'], layout['h'])
                return
            except Exception:
                pass

    webbrowser.open(cache_bust_url)


def main():
    gui_url = f"http://127.0.0.1:{CONTROL_PORT}"

    # Если сервер уже запущен другим процессом — просто открываем окно браузера и выходим
    if is_already_serving():
        if "--no-browser" not in sys.argv:
            launch_browser_gui(gui_url)
        sys.exit(0)

    print("=" * 70)
    print("       PC CONTROL - ПАНЕЛЬ УПРАВЛЕНИЯ И ЗАПУСКА (LAUNCHER)      ")
    print("=" * 70)
    print(f"Запуск веб-сервера панели на http://127.0.0.1:{CONTROL_PORT} ...")

    server_address = ("127.0.0.1", CONTROL_PORT)
    try:
        httpd = http.server.ThreadingHTTPServer(server_address, ControlPanelHandler)
    except Exception as e:
        print(f"[ОШИБКА] Не удалось занять порт {CONTROL_PORT}: {e}")
        return

    # Запускаем фоновый сторож активности: при закрытии браузера процесс завершится сам
    threading.Thread(target=_idle_watchdog, daemon=True).start()

    # Проверка первого запуска: авто-создание config.json и автоустановка библиотек
    threading.Timer(0.8, check_first_run_setup).start()

    # Фоновая автоматическая проверка обновлений при старте лаунчера
    threading.Timer(2.0, check_github_updates).start()

    if "--no-browser" not in sys.argv:
        threading.Timer(0.4, lambda: launch_browser_gui(gui_url)).start()

    print(f"Панель готова к работе: {gui_url}")
    print("Для завершения работы панели нажмите Ctrl + C.")
    print("=" * 70)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nЗавершение работы панели управления.")
        httpd.server_close()


if __name__ == "__main__":
    main()
