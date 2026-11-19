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
# Ports used by PC Control itself (QA L-14): streamer 5051, control panel, media bridge 5017,
# adb server 5037, USB discovery beacon 5058. Never a server or relay port.
INTERNAL_PORTS = frozenset({5051, 5055, CONTROL_PORT, 5017, 5037, 5058})
# The server port additionally must not be 5050 (Wake-on-LAN relay default).
RESERVED_PORTS = INTERNAL_PORTS | {5050}
MIN_USER_PORT = 1024  # system ports need administrator rights / belong to Windows services
# Общая с сервером блокировка config.json (между процессами) — см. core/config.py
from core.config import CONFIG_LOCK as _settings_lock  # noqa: E402
from core.winpaths import sys_exe  # QA R-14: full System32 paths


def save_config_data(cfg):
    """Replace the config atomically; a failed write never reports success."""
    with _settings_lock:
        _save_config_data(cfg)


def _save_config_data(cfg):
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_FILE.parent,
                                         prefix="config-", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        for attempt in range(5):
            try:
                os.replace(temp_path, CONFIG_FILE)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)
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
    # QA L-14: the same reservations as _find_free_port, for both ports.
    for key, reserved in (("port", RESERVED_PORTS), ("relay_port", INTERNAL_PORTS)):
        value = result[key]
        if value < MIN_USER_PORT or value in reserved:
            what = "Server port" if key == "port" else "Relay port"
            what_ru = "Порт сервера" if key == "port" else "Порт ретранслятора"
            raise ValueError(
                f"{what} {value} is reserved (below {MIN_USER_PORT}, or used by PC Control: 5050 Wake-on-LAN relay, "
                f"5051 streamer, {CONTROL_PORT} control panel, 5017 media bridge, 5037 adb, 5058 USB beacon). "
                f"Choose another port. / {what_ru} {value} зарезервирован (меньше {MIN_USER_PORT} или занят "
                f"PC Control: 5050 ретранслятор Wake-on-LAN, 5051 стример, {CONTROL_PORT} панель управления, "
                f"5017 медиамост, 5037 adb, 5058 USB-маяк). Выберите другой порт.")
    if result["port"] == result["relay_port"]:
        raise ValueError(f"Server port and relay port are both {result['port']}. / "
                         f"Порт сервера совпадает с портом ретранслятора ({result['port']}).")
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
    try:
        from scripts.network_setup import get_best_lan_ip
        best = get_best_lan_ip()
        if best and best != "127.0.0.1":
            return best
    except Exception:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = ""
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
        # Пока идёт фоновая задача (установка библиотек, сборка APK — до 30 мин) или запуск/остановка
        # сервера, не выходим: раньше закрытое окно панели обрывало такую задачу на середине.
        if _is_busy or not _lifecycle_idle():
            record_activity()
            continue
        if (time.time() - _last_activity_time) > 300.0:
            os._exit(0)


def _lifecycle_idle() -> bool:
    """Никакой поток сейчас не запускает/не останавливает сервер."""
    if _lifecycle_lock.acquire(blocking=False):
        _lifecycle_lock.release()
        return True
    return False

def _code_fingerprint() -> str:
    """Отпечаток кода панели (время изменения и размер файлов).
    Launcher.exe при уже запущенной панели только открывает её окно, поэтому после обновления или
    исправления старый процесс продолжал бы работать со старым кодом."""
    files = [BASE_DIR / "scripts" / "control_panel.py", BASE_DIR / "web" / "control_panel.html"]
    for folder in (BASE_DIR / "core", BASE_DIR / "core" / "launcher", BASE_DIR / "scripts"):
        try:
            files.extend(sorted(folder.glob("*.py")))
        except OSError:
            pass
    parts = []
    for f in files:
        try:
            st = f.stat()
            parts.append(f"{f.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{f.name}:-")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


PANEL_BUILD = _code_fingerprint()
_httpd = None
_self_restart_blocked = False


def _self_restart_watcher():
    """Код панели на диске изменился → запускаем новую копию панели и завершаем эту.
    Сервер управления ПК (server.py) — отдельный процесс и при этом не перезапускается."""
    time.sleep(10)
    while True:
        time.sleep(3)
        if _is_busy or _self_restart_blocked or _code_fingerprint() == PANEL_BUILD:
            continue
        time.sleep(2)  # даём дописать все файлы (обновление копирует их по одному)
        # Не перезапускаемся посреди запуска/остановки сервера: ответ кнопке «Запустить» потерялся бы.
        if _is_busy or _self_restart_blocked or not _lifecycle_idle():
            continue
        try:
            args = [a for a in sys.argv[1:] if a not in ("--no-browser", "--replace", "--check-update")]
            subprocess.Popen([sys.executable, "-E", "-s", str(Path(__file__).resolve()), *args,
                              "--no-browser", "--replace"],
                             cwd=str(BASE_DIR), creationflags=NO_WINDOW)
        except Exception as e:
            append_log(f"[WARNING] Panel code changed, but the new panel could not be started: {e}")
            return
        append_log("[INFO] Panel code was updated - restarting the control panel...")
        try:
            if _httpd is not None:
                _httpd.server_close()
        finally:
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

# Логика панели по областям — core/launcher/ (здесь остаются тонкие обёртки с прежними именами).
from core.launcher import firewall as _fw  # noqa: E402
from core.launcher import tailscale as _ts  # noqa: E402
from core.launcher import deps as _deps  # noqa: E402
from core.launcher.apk import ApkBuilder  # noqa: E402
from core.launcher.deps import REQUIRED_PACKAGES  # noqa: E402,F401
from core.launcher.elevation import run_elevated_command, run_elevated_and_wait  # noqa: E402
from core.launcher.firewall import (  # noqa: E402,F401
    firewall_rule_matches, firewall_rule_allows_runtime, firewall_rule_blocks_own_program,
)
from core.launcher.status import BackgroundStatus  # noqa: E402
from core.launcher.tailscale import find_tailscale_binaries  # noqa: E402
from core.launcher.windows_signin import (  # noqa: E402
    get_windows_hello_status, set_windows_hello_state, launch_netplwiz, open_signin_settings,
)
from core.launcher.windows_ui import (  # noqa: E402
    get_desktop_window_layout, enforce_window_geometry_async, check_tailscale_web_accessible,
)
from core.launcher import windows_ui as _ui  # noqa: E402


def launch_tailscale_app_window(target_url: str = "http://100.100.100.100") -> bool:
    return _ui.launch_tailscale_app_window(target_url, log=append_log)


_cached_ts = None
_cached_ts_time = 0.0


def get_tailscale_info() -> dict:
    """Состояние Tailscale (кэш 5 с). Поиск и опрос — core/launcher/tailscale.py."""
    global _cached_ts, _cached_ts_time
    now = time.time()
    if _cached_ts is not None and (now - _cached_ts_time < 5.0):
        return _cached_ts

    bins = find_tailscale_binaries()
    ts_cli = bins.get("cli")
    ts_gui = bins.get("gui")
    installer_exists = (BASE_DIR / "tailscale-setup-1.102.4.exe").exists() or bool(list(BASE_DIR.glob("tailscale-setup*.exe")))
    st = _ts.read_status(ts_cli)
    ip = st["ip"]
    is_running = st["backend_state"] == "Running" and bool(ip)
    is_installed = bool((ts_cli and Path(ts_cli).is_file()) or (ts_gui and Path(ts_gui).is_file()) or is_running or bins.get("installed"))
    if not is_installed:
        details = "Tailscale is not installed"
    elif is_running:
        details = f"Connected ({ip})"
    else:
        details = "Installed, but not running"

    _cached_ts = {
        "installed": is_installed,
        "running": is_running,
        "ip": ip,
        "installer_exists": installer_exists,
        "details": details,
        "account": st["account"],
        "device_name": st["device_name"],
        "magic_dns": st["magic_dns"],
        "peers": st["peers"],
        "backend_state": st["backend_state"],
        "gui_path": str(ts_gui) if ts_gui else "",
        "cli_path": str(ts_cli) if ts_cli else ""
    }
    _cached_ts_time = now
    return _cached_ts


def is_server_running(port: int | None = None, timeout: float = 0.45) -> bool:
    if port is None:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    port = int(json.load(f).get("port", 5000))
            else:
                port = 5000
        except Exception:
            port = 5000
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/status", headers={"User-Agent": "PC-Control-Launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = json.load(resp)
                return body.get("status") == "online" and body.get("instance") == instance_id()
    except Exception:
        pass
    return False


def is_dev_folder(base: Path | None = None) -> bool:
    """QA L-7: a development checkout (.git / Rust sources) — the uninstaller refuses to run there."""
    root = base or BASE_DIR
    return ((root / ".git").exists() or (root / "Cargo.toml").is_file()
            or (root / "streamer_rs" / "Cargo.toml").is_file() or (root / "media_helper_rs" / "Cargo.toml").is_file())


def _usb_status(server_up: bool, port: int) -> dict:
    """Phones connected by cable: written by the server (core/usb_link.py → logs/usb_link.json)."""
    try:
        from core import usb_link
        data = usb_link.read_status_file()
    except Exception:
        data = {}
    if not server_up or not data or int(data.get("port") or 0) != int(port) or not data.get("running", True):
        return {"active": False, "devices": []}
    devices = [{
        "model": str(d.get("model") or d.get("serial") or "Android"),
        "state": str(d.get("state") or ""),
        "ready": bool(d.get("reverse")),
    } for d in (data.get("devices") or []) if isinstance(d, dict)]
    return {"active": True, "adb": str(data.get("adb") or ""), "devices": devices}


_cached_fw_ok = False
_cached_fw_time = 0.0
_cached_fw_port = None
_cached_fw_blocking: list = []


def firewall_blocking_programs() -> list:
    is_firewall_configured()
    return list(_cached_fw_blocking)


def is_firewall_configured() -> bool:
    """Правило для сервера есть и Windows не блокирует программы установки (кэш 2 с).
    Разбор правил — core/launcher/firewall.py."""
    global _cached_fw_ok, _cached_fw_time, _cached_fw_port, _cached_fw_blocking
    port = load_config_data().get("port", 5000)
    now = time.time()
    if now - _cached_fw_time < 2.0 and port == _cached_fw_port:
        return _cached_fw_ok
    if platform.system() != "Windows":
        _cached_fw_ok, _cached_fw_blocking = True, []
    else:
        result = _fw.scan(BASE_DIR, port)
        _cached_fw_ok, _cached_fw_blocking = result.configured, result.blocking
    _cached_fw_time = now
    _cached_fw_port = port
    return _cached_fw_ok


# Сборка персонального APK — core/launcher/apk.py
_apk = ApkBuilder(BASE_DIR, LOGS_DIR, lambda: get_python_cli_path(), lambda: load_config_data(),
                  lambda line: append_log(line))
APK_BUILD_INFO = _apk.info_file


def apk_sources_available() -> bool:
    return _apk.sources_available()


def is_apk_personalized(cfg: dict) -> bool:
    return _apk.is_personalized(cfg)


def run_apk_build(script_path: Path) -> tuple:
    return _apk.run(script_path)


# Фоновый статус для /api/status (core/launcher/status.py). Поставщики вызывают функции модуля
# по имени — подмены в тестах (mock.patch.object(control_panel, ...)) продолжают работать.
_status = BackgroundStatus()
_status.register("tailscale", lambda: get_tailscale_info(), 4.0)
_status.register("firewall", lambda: (is_firewall_configured(), firewall_blocking_programs()), 3.0)
_status.register("deps", lambda: check_python_deps(), 20.0)
_status.register("network", lambda: sync_network_settings(load_config_data(), get_tailscale_info()), 10.0)

_cached_deps = None
_cached_deps_time = 0.0
_deps_lock = threading.Lock()


def check_python_deps(timeout: float | None = None, force: bool = False) -> dict:
    """Библиотеки сервера (кэш 30 с). Проверка — core/launcher/deps.py.
    Неудавшаяся проверка (таймаут/сбой процесса) кэшируется лишь на 5 с и НЕ означает «нет библиотек»."""
    global _cached_deps, _cached_deps_time
    with _deps_lock:
        now = time.time()
        ttl = 5.0 if (_cached_deps or {}).get("probe_failed") else 30.0
        if not force and _cached_deps is not None and (now - _cached_deps_time < ttl):
            return _cached_deps
        has_runtime = (BASE_DIR / "runtime" / "python.exe").exists() or (BASE_DIR / "venv" / "Scripts" / "python.exe").exists()
        _cached_deps = _deps.probe(get_python_cli_path(), has_runtime, timeout or _deps.DEFAULT_TIMEOUT)
        _cached_deps_time = time.time()
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


def _detect_default_language() -> str:
    """Язык панели при первом запуске: язык интерфейса Windows, затем региональный формат.
    (locale.getdefaultlocale устарел и удаляется в Python 3.15.)"""
    from core.config import default_language
    return default_language()


def load_config_data() -> dict:
    with _settings_lock:
        return _load_config_data()


def _load_config_data() -> dict:
    if CONFIG_FILE.exists():
        for attempt in range(60):
            try:
                # utf-8-sig: файл, сохранённый Блокнотом/PowerShell с BOM, тоже читается.
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("config.json must contain a JSON object")
                if "language" not in data:
                    data["language"] = "en"
                return data
            except PermissionError:
                # QA A-11: the file is locked for a moment (antivirus, the server saving it). Before,
                # after 5 tries (0.1 s) a NEW config with a NEW password was written over it and the
                # phone lost access. Wait longer, and never regenerate an existing file.
                if attempt < 59:
                    time.sleep(0.05)
                    continue
                raise RuntimeError("config.json is locked by another program; try again in a moment")
            except Exception as e:
                # Повреждённый файл не затираем молча: сохраняем копию, чтобы токен и настройки
                # можно было восстановить, и честно сообщаем об этом в журнале.
                backup = CONFIG_FILE.with_name(f"config.broken-{time.strftime('%Y%m%d-%H%M%S')}.json")
                try:
                    shutil.copy2(CONFIG_FILE, backup)
                    append_log(f"[ERROR] config.json is damaged ({e}). A copy was saved as {backup.name}; "
                               f"a new config was created. The phone must be paired again (new access key).")
                except Exception as copy_err:
                    append_log(f"[ERROR] config.json is damaged ({e}) and could not be backed up: {copy_err}")
                break

    # Первоначальное создание config.json — одни и те же значения, что у сервера (core/config.py)
    from core.config import auto_detect_network_params
    cfg = auto_detect_network_params()
    ts = get_tailscale_info()
    if ts.get("running") and ts.get("ip"):
        cfg["vpn_ip"] = ts["ip"]
    try:
        save_config_data(cfg)
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
                req_file = BASE_DIR / "requirements.txt"
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
            _status.invalidate("deps")

            deps_after = check_python_deps()
            if deps_after.get("installed", False):
                if proc.returncode == 0:
                    append_log("[SUCCESS] All required Python libraries installed successfully!")
                else:
                    append_log("[SUCCESS] All required Python libraries are already installed and verified!")
                if auto_start_server and not is_server_running():
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
            _status.invalidate("deps")
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
    if deps.get("probe_failed"):
        # Проверка не успела/упала (например, сразу после входа в Windows) — это не повод
        # переустанавливать библиотеки; фоновый статус повторит проверку.
        append_log(f"[WARNING] {deps.get('details')}. The check will be repeated automatically.")
    elif _deps.definitely_missing(deps):
        append_log("[FIRST RUN] Missing Python dependencies detected. Starting automated environment preparation...")
        # Сервер сам не запускаем, пока не пройдена настройка: первый запуск до правила брандмауэра
        # вызывает окно Windows, которое в общедоступной сети создаёт БЛОКИРУЮЩЕЕ правило.
        run_install_dependencies_task(auto_start_server=bool(load_config_data().get("setup_completed")))
    elif not deps.get("installed", False):
        append_log(f"[WARNING] {deps.get('details')}")
    else:
        append_log("[READY] Components verified. Use Start server when ready.")


def _port_bindable(port: int) -> bool:
    """Свободен ли порт для сервера: тот же адрес, что использует server.py (0.0.0.0).
    Ловит и занятый другой программой порт, и порт, зарезервированный Windows."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        s.bind(("0.0.0.0", int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _find_free_port(start: int, attempts: int = 100) -> int | None:
    # Те же запреты, что в validate_network_settings: раньше здесь не было порта стримера (5051)
    # и настроенного порта WOL-реле — автоматически выбранный порт мог совпасть с ними.
    try:
        relay = int(load_config_data().get("relay_port", 5050) or 5050)
    except (TypeError, ValueError):
        relay = 5050
    reserved = set(RESERVED_PORTS) | {relay}
    for candidate in range(max(1024, start), min(65535, start + attempts)):
        if candidate in reserved:
            continue  # порт WOL-реле, стримера и панели управления
        if _port_bindable(candidate):
            return candidate
    return None


STARTUP_TIMEOUT_SEC = 20.0


def start_lock_name() -> str:
    """Имя мьютекса «запуск сервера» этой установки — общее для панели, autostart и watchdog.pyw."""
    key = str(BASE_DIR).lower()
    data_dir = os.environ.get("PC_CONTROL_DATA_DIR") or ""
    if data_dir:
        key += "|" + os.path.normcase(os.path.abspath(data_dir))
    return "Local\\PCControlServerStart_" + hashlib.sha256(key.encode("utf-8")).hexdigest()


class _CrossProcessStartLock:
    """Запуск сервера — по одному на установку МЕЖДУ процессами. Раньше панель и autostart при входе
    в Windows могли одновременно пройти проверки (проверка библиотек длится секунды), и второй
    убивал только что запущенный первым server.py: первый сообщал «Сбой при запуске сервера».
    Мьютекс освобождается и при аварийном завершении процесса; без kernel32 — работаем как раньше."""

    def __init__(self, timeout: float):
        self.timeout = timeout
        self.handle = None
        self.owned = False
        self.waited = False

    def __enter__(self):
        try:
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            k32.CreateMutexW.restype = ctypes.c_void_p
            k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            k32.WaitForSingleObject.restype = ctypes.c_uint32
            k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._k32 = k32
            self.handle = k32.CreateMutexW(None, False, start_lock_name())
            if self.handle:
                rc = k32.WaitForSingleObject(self.handle, 0)
                if rc not in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED
                    self.waited = True
                    rc = k32.WaitForSingleObject(self.handle, int(max(0.0, self.timeout) * 1000))
                self.owned = rc in (0, 0x80)
        except Exception:
            self.owned = False
        return self

    def __exit__(self, *exc):
        try:
            if self.handle:
                if self.owned:
                    self._k32.ReleaseMutex(self.handle)
                self._k32.CloseHandle(self.handle)
        except Exception:
            pass
        self.handle = None
        self.owned = False
        return False


@serialize_lifecycle
def start_server_process(startup_timeout: float = STARTUP_TIMEOUT_SEC, deps_timeout: float | None = None,
                         clear_manual_stop: bool = True) -> tuple:
    """Запуск сервера под межпроцессной блокировкой (см. _CrossProcessStartLock)."""
    with _CrossProcessStartLock(startup_timeout + 90.0) as lock:
        if lock.waited:
            append_log("[INFO] Another PC Control process was starting the server - waited for it.")
        return _start_server_process_locked(startup_timeout, deps_timeout, clear_manual_stop)


def _start_server_process_locked(startup_timeout: float = STARTUP_TIMEOUT_SEC, deps_timeout: float | None = None,
                                 clear_manual_stop: bool = True) -> tuple:
    """
    Выполняет запуск server.py и сторожевого таймера.
    Возвращает (success: bool, error_code: str, error_title: str, details: str)

    ERR_STARTUP_TIMEOUT означает: процесс сервера жив, но ещё не ответил (медленный «холодный» старт
    Windows). Его НЕ убиваем — за ним уже следит watchdog, а вызывающий код может подождать ещё.
    """
    deps = check_python_deps(timeout=deps_timeout)
    if _deps.definitely_missing(deps):
        return (
            False,
            "ERR_PYTHON_DEPS_MISSING",
            "Не установлены библиотеки Python",
            "Для работы сервера требуются библиотеки Flask, Pillow, Winsdk и др.\nНажмите кнопку 'Установить' в Шаге 1 чек-листа перед запуском.\n"
            + str(deps.get("details", ""))
        )
    if not deps.get("installed", False):
        # Проверка не удалась (таймаут/сбой) или модуль временно не загрузился — это не «нет библиотек».
        # Пробуем запустить: если библиотек правда нет, сервер упадёт и покажет причину в stderr.
        append_log(f"[WARNING] {deps.get('details')} - starting the server anyway.")

    cfg = load_config_data()
    port = int(cfg.get("port", 5000))

    # Дольше обычного ждём ответа: занятый (трансляция экрана) сервер может отвечать дольше 0,45 с,
    # а ниже его процессы завершаются — работающий сервер нельзя убить из-за медленного ответа.
    if is_server_running(port, timeout=3.0):
        return (True, "", "", f"Сервер уже запущен и принимает подключения на порту {port}.")

    # A start by the user clears «stopped manually». Autostart / watchdog must NOT (QA L-2): a Stop
    # pressed while autostart retries has to win, not be erased by the next attempt.
    flag = LOGS_DIR / "manual_stop.flag"
    if clear_manual_stop and flag.exists():
        try:
            flag.unlink()
        except Exception:
            pass

    # Сервер этой установки только что запущен (автозапуск при входе в Windows, watchdog) и ещё
    # грузится — не убиваем его, а ждём ответа. Раньше «Запустить» в этот момент обрывал запуск.
    if _youngest_owned_server_age() is not None:
        append_log("[INFO] The server process is already starting - waiting for it instead of starting another one.")
        start_t = time.time()
        while time.time() - start_t < startup_timeout:
            if is_server_running(port):
                return (True, "", "", f"Сервер успешно запущен на порту {port}.")
            if _youngest_owned_server_age() is None:
                break  # процесс завершился — запускаем заново ниже
            time.sleep(0.5)

    # Сначала убираем СВОИ зависшие процессы server.py (раньше это делалось уже после проверки
    # порта — и порт, занятый собственным зависшим сервером, давал ошибку вместо исправления).
    kill_processes_by_name("server.py")
    for _pid in get_pids_on_port(port):
        kill_pid(_pid)  # kill_pid завершает только процессы этой установки

    # Порт может быть занят другой программой или зарезервирован Windows (Hyper-V/WSL):
    # проверяем привязкой, а не подключением, и при необходимости выбираем свободный порт сами.
    port_note = ""
    if not _port_bindable(port):
        time.sleep(0.5)
    if not _port_bindable(port):
        new_port = _find_free_port(port + 1)
        if new_port is None:
            return (
                False,
                "ERR_PORT_OCCUPIED",
                f"Порт {port} уже занят",
                f"Порт {port} и следующие 100 портов заняты другими программами. "
                f"Укажите свободный порт в «Настройки сети»."
            )
        with _settings_lock:
            cfg = load_config_data()
            cfg["port"] = new_port
            save_config_data(cfg)
        append_log(f"[AUTO] Port {port} is busy (another program or reserved by Windows). Switched to free port {new_port}.")
        port_note = (f" Порт {port} был занят другой программой, поэтому выбран свободный порт {new_port}. "
                     f"Если телефон уже был подключён — подключите его заново по QR-коду. "
                     # QA L-21: the firewall rule is bound to the port
                     f"Правило брандмауэра Windows разрешает только старый порт: нажмите «Применить правило» "
                     f"в шаге «Брандмауэр Windows», иначе телефон не подключится по Wi-Fi.")
        port = new_port

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
    except Exception as e:
        return (
            False,
            "ERR_SPAWN_FAILED",
            "Ошибка создания процесса",
            f"Не удалось запустить процесс server.py через {pyw_bin}:\n{e}"
        )

    # Сторож запускается отдельно: его сбой не должен выдаваться за «сервер не запустился»
    # (раньше исключение здесь возвращало ERR_SPAWN_FAILED при уже запущенном server.py).
    ensure_watchdog_running(pyw_bin)

    # Success means the HTTP health endpoint answered, not merely a live PID.
    start_t = time.time()
    while time.time() - start_t < startup_timeout:
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
            return (True, "", "", f"Сервер успешно запущен на порту {port}.{port_note}")
        time.sleep(0.25)

    if is_server_running(port):
        return (True, "", "", f"Сервер успешно запущен на порту {port}.{port_note}")
    if proc.poll() is None:
        # Процесс жив и ещё запускается: не оставляем «полусостояние» без присмотра — его ведёт
        # watchdog (запущен выше), а панель покажет «Работает», как только сервер ответит.
        return (
            False,
            "ERR_STARTUP_TIMEOUT",
            "Сервер ещё запускается",
            f"Сервер не ответил на порту {port} за {int(startup_timeout)} с, но его процесс продолжает запуск "
            f"(после входа в Windows это бывает дольше обычного). Он не остановлен: сторожевой процесс следит за ним, "
            f"статус обновится автоматически.{port_note}"
        )
    return (
        False,
        "ERR_SERVER_CRASHED",
        "Сбой при запуске сервера",
        f"Процесс server.py завершился с кодом {proc.poll()} до ответа на порту {port}."
    )


def get_pids_on_port(port: int = 5000) -> list:
    pids = []
    if platform.system() != "Windows":
        return pids
    try:
        out = subprocess.check_output(
            [sys_exe("netstat"), "-ano", "-p", "tcp"],
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


def _same_path(a, b) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except Exception:
        return False


def process_runs_own_script(process, script_paths) -> bool:
    """Процесс — Python, выполняющий один из script_paths ЭТОЙ установки (рабочий, не тестовый).

    Строже прежней проверки: скриптом считается только ПЕРВЫЙ позиционный аргумент (а не любой
    аргумент, похожий на путь), путь сравнивается после resolve() без учёта регистра, а процесс с
    другой папкой данных (PC_CONTROL_DATA_DIR — изолированный тестовый сервер) не считается нашим.
    Любая ошибка (нет доступа к процессу, процесс завершился) — «не наш»: чужое не трогаем."""
    try:
        if not (process.name() or "").lower().startswith("python"):
            return False
        args = [a for a in (process.cmdline() or [])[1:] if a and not a.startswith("-")]
        if not args:
            return False
        script = Path(process.cwd()) / args[0]
        if not any(_same_path(script, target) for target in script_paths):
            return False
        try:
            other_data = process.environ().get("PC_CONTROL_DATA_DIR") or ""
        except Exception:
            other_data = ""
        own_data = os.environ.get("PC_CONTROL_DATA_DIR") or ""
        if other_data or own_data:
            if not (other_data and own_data and _same_path(other_data, own_data)):
                return False
        return True
    except Exception:
        return False


def kill_pid(pid: int):
    # Never terminate an unrelated application just because it owns our port.
    try:
        import psutil
        process = psutil.Process(pid)
        if not process_runs_own_script(process, (BASE_DIR / "server.py", SCRIPTS_DIR / "watchdog.pyw")):
            return
    except Exception:
        return
    try:
        subprocess.run(
            [sys_exe("taskkill"), "/PID", str(pid), "/F", "/T"],
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
    # Только процессы ЭТОЙ установки: другие установленные копии и тестовые серверы не трогаем.
    for pid in owned_script_pids(process_script):
        kill_pid(pid)


def owned_script_pids(process_script: str) -> list:
    """PID процессов Python этой установки, выполняющих scripts/<process_script> или server.py."""
    pids = []
    if platform.system() != "Windows":
        return pids
    target = (BASE_DIR / process_script) if process_script == "server.py" else (SCRIPTS_DIR / process_script)
    try:
        import psutil
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                # Быстрый отсев по имени файла, затем строгая проверка принадлежности
                if not any(Path(a).name.lower() == process_script.lower()
                           for a in (process.info.get("cmdline") or [])[1:]):
                    continue
                if process_runs_own_script(process, (target,)):
                    pids.append(process.pid)
            except Exception:
                continue
    except Exception:
        pass
    return pids


SERVER_BOOT_GRACE_SEC = 90.0


def _youngest_owned_server_age(max_age: float = SERVER_BOOT_GRACE_SEC) -> float | None:
    """Возраст (с) самого молодого процесса server.py этой установки, если он моложе max_age."""
    pids = owned_script_pids("server.py")
    if not pids:
        return None
    try:
        import psutil
        ages = []
        for pid in pids:
            try:
                ages.append(time.time() - psutil.Process(pid).create_time())
            except Exception:
                continue
        young = [a for a in ages if a < max_age]
        return min(young) if young else None
    except Exception:
        return None


def ensure_watchdog_running(pyw_bin: str | None = None) -> bool:
    """Запускает сторожевой процесс, если он ещё не работает (повторный запуск безопасен:
    watchdog.pyw сам выходит при уже занятом мьютексе)."""
    watchdog_script = SCRIPTS_DIR / "watchdog.pyw"
    if not watchdog_script.exists():
        return False
    if owned_script_pids("watchdog.pyw"):
        return True
    try:
        subprocess.Popen([pyw_bin or get_pythonw_path(), "-E", "-s", str(watchdog_script)],
                         cwd=str(BASE_DIR), creationflags=NO_WINDOW)
        return True
    except Exception as e:
        append_log(f"[WARNING] Could not start the watchdog supervisor: {e}")
        return False


@serialize_lifecycle
def stop_server_process() -> tuple:
    """
    Выполняет гарантированную остановку server.py и сторожевого таймера.
    """
    # 1. Записываем флаг ручной остановки, чтобы watchdog не перезапускал сервер
    try:
        with open(LOGS_DIR / "manual_stop.flag", "w", encoding="utf-8") as f:
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

    # 4. Если порт всё ещё занят или остались процессы server.py / watchdog.pyw — завершаем их принудительно.
    # Сначала сторожа: иначе он мог успеть запустить новый server.py уже после завершения старого.
    kill_processes_by_name("watchdog.pyw")
    for pid in get_pids_on_port(port):
        kill_pid(pid)

    kill_processes_by_name("server.py")

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


def auto_update_check_enabled() -> bool:
    if os.environ.get("PC_CONTROL_TEST_MODE") == "1" or os.environ.get("PC_CONTROL_NO_UPDATE_CHECK") == "1":
        return False
    try:
        return load_config_data().get("auto_update_check", True) is not False
    except Exception:
        return True


def check_github_updates() -> dict:
    global LATEST_UPDATE_INFO
    from scripts import full_update
    LATEST_UPDATE_INFO = full_update.check(BASE_DIR)
    return LATEST_UPDATE_INFO


def cleanup_update_workspaces():
    """Удаляет рабочие папки завершённых обновлений (~0.7 ГБ каждая) рядом с программой."""
    try:
        from scripts import full_update
        before = {p.name for p in BASE_DIR.parent.glob('.pccontrol-update-*')}
        full_update.prune_finished_jobs(BASE_DIR)
        removed = before - {p.name for p in BASE_DIR.parent.glob('.pccontrol-update-*')}
        if removed:
            append_log(f"[UPDATE] Removed {len(removed)} finished update workspace(s) next to the program.")
    except Exception as e:
        append_log(f"[WARNING] Could not clean finished update workspaces: {e}")


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


UPDATE_STATUS_SHOW_SEC = 15 * 60


def get_update_status():
    """Состояние последнего обновления для окна панели. Завершённое обновление («complete»,
    «rolled_back») показываем только 15 минут: раньше файл оставался навсегда, и при каждом
    открытии панели снова всплывали сообщение и уведомление о давнем обновлении.
    Сам файл не трогаем — его читает full_update.py."""
    try:
        status = json.loads((LOGS_DIR / 'update_status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict):
        return None
    if status.get('phase') in ('complete', 'rolled_back'):
        try:
            if time.time() - float(status.get('time', 0)) > UPDATE_STATUS_SHOW_SEC:
                return None
        except (TypeError, ValueError):
            return None
    return status


def uninstaller_exe(base: Path | None = None) -> Path | None:
    """Uninstall.exe (primary since 2.5.1), else the legacy unstaller.exe (same file), else None."""
    base = base or BASE_DIR
    for name in ("Uninstall.exe", "unstaller.exe"):
        if (base / name).is_file():
            return base / name
    return None


def repair_uninstall_registration():
    """2.5.1: Apps & features entry of THIS install -> Uninstall.exe (scripts/full_update.py
    repoint_uninstall_entry: ownership check by InstallLocation, idempotent, silent on failure).
    Installed copies only; a dev folder or a test-mode panel never touches the registry."""
    if is_dev_folder() or os.environ.get("PC_CONTROL_TEST_MODE") == "1":
        return
    try:
        from scripts import full_update
        full_update.repoint_uninstall_entry(BASE_DIR, log=lambda m: append_log("[SETUP] " + m))
    except Exception as e:
        append_log(f"[SETUP] Apps & features entry not checked: {e}")


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
        if path == "/api/qr":
            query = urllib.parse.parse_qs(url_parsed.query)
            target_url = (query.get("url") or [""])[0].strip()
            if not target_url:
                cfg = load_config_data()
                lan_ip = cfg.get("lan_ip") or get_local_ip()
                port = int(cfg.get("port", 5000))
                target_url = f"http://{lan_ip}:{port}/download/apk"
            if len(target_url) > 2048:
                self.send_json({"ok": False, "message": "URL too long"}, 400)
                return
            try:
                import io
                import qrcode
                img = qrcode.make(target_url)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                png_bytes = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(png_bytes)
                return
            except Exception as e:
                self.send_json({"ok": False, "message": str(e)}, 500)
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
            # Дорогие проверки (Tailscale, брандмауэр, библиотеки, определение сети) считает фоновый
            # поток _status; здесь — только готовые значения и дешёвая проверка «сервер отвечает».
            cfg = load_config_data()
            port = int(cfg.get("port", 5000))
            server_up = is_server_running(port)
            ts_info = _status.get("tailscale")
            if _status.running:
                _status.get("network")
                cfg = load_config_data()
            else:
                cfg = sync_network_settings(cfg, ts_info)
            port = int(cfg.get("port", 5000))
            lan_ip = cfg.get("lan_ip", "")
            fw_ok, fw_blocking = _status.get("firewall")
            py_deps = _status.get("deps")

            self.send_json({
                "server_running": server_up,
                "server_url": f"http://{lan_ip}:{port}",
                "port": port,
                "lan_ip": lan_ip,
                "tailscale": ts_info,
                "firewall_configured": fw_ok,
                "firewall_blocking": fw_blocking,
                "python_deps": py_deps,
                "apk_build_available": apk_sources_available(),
                "apk_build": _apk.snapshot(),
                "apk_personalized": is_apk_personalized(cfg),
                "apk_exists": (BASE_DIR / "PC_Control.apk").is_file() or (BASE_DIR / "PC-Control.apk").is_file(),
                "uninstaller_available": not is_dev_folder() and (uninstaller_exe() is not None or (BASE_DIR / "uninstall.bat").is_file()),
                "dev_folder": is_dev_folder(),
                "windows_hello": get_windows_hello_status(),
                "token": cfg.get("token", ""),
                "password_weak": 0 < len(str(cfg.get("token", "") or "")) < 8,  # QA L-13
                "mac_address": cfg.get("mac_address", "AA-BB-CC-DD-EE-FF"),
                "language": cfg.get("language", "en"),
                "cors_allowed_origins": cfg.get("cors_allowed_origins", [
                    "http://localhost:*",
                    "http://127.0.0.1:*",
                    "http://192.168.*",
                    "http://172.*",
                    "http://100.*",
                    "http://10.*"
                ]),
                "is_busy": _is_busy,
                "busy_action": _busy_action,
                "setup_in_progress": bool(_is_busy and "Dependencies Installation" in _busy_action),
                "setup_completed": bool(cfg.get("setup_completed", False)),
                "panel_build": PANEL_BUILD,
                "usb": _usb_status(server_up, port),
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
            if length < 0:
                raise ValueError("Request body length must be non-negative")
            self.connection.settimeout(10)
            if length > 65536:
                if length <= 1048576:
                    self.rfile.read(length)
                raise ValueError("Request body must be at most 64 KiB")
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
                _status.invalidate("network")
                interfaces = []
                try:
                    from scripts.network_setup import list_network_interfaces
                    interfaces = list_network_interfaces()
                except Exception:
                    pass
                self.send_json({"ok": bool(cfg.get("lan_ip")), "message": "Network detected" if cfg.get("lan_ip") else "No active LAN adapter found", "settings": cfg, "interfaces": interfaces})
                return

            if action == "get_settings":
                cfg = load_config_data()
                keys = ("lan_ip", "vpn_ip", "wol_relay_ip", "mac_address", "port", "relay_port")
                interfaces = []
                try:
                    from scripts.network_setup import list_network_interfaces
                    interfaces = list_network_interfaces()
                except Exception:
                    pass
                self.send_json({"ok": True, "settings": {key: cfg.get(key, "") for key in keys}, "interfaces": interfaces})
                return

            if action in ("list_sessions", "revoke_session", "revoke_all_sessions"):
                # Device sessions (plan 5.2): the panel works on logs/sessions.json directly; the
                # server notices revocations within ~2 s and closes that device's open streams.
                from core import sessions as _sessions
                try:
                    if action == "revoke_session":
                        sid = str(req_data.get("id") or "").strip()
                        if not sid or len(sid) > 64:
                            self.send_json({"ok": False, "message": "Bad session id"}, 400)
                            return
                        n = _sessions.revoke(sid)
                        append_log(f"[SECURITY] Device session {sid} revoked ({n}).")
                    elif action == "revoke_all_sessions":
                        n = _sessions.revoke(all_sessions=True)
                        append_log(f"[SECURITY] All device sessions revoked ({n}).")
                    cfg_s = load_config_data()
                    self.send_json({"ok": True, "sessions": _sessions.list_sessions(),
                                    "idle_expiry_days": _sessions.IDLE_EXPIRY_DAYS,
                                    "legacy_password_auth": cfg_s.get("legacy_password_auth", True) is not False})
                except Exception as e:
                    self.send_json({"ok": False, "message": str(e)}, 500)
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
                    # QA L-21: the firewall rules are bound to the ports - the panel reminds to apply them again.
                    try:
                        port_changed = settings["port"] != int(cfg.get("port", 5000) or 5000)
                        ports_changed = port_changed or settings["relay_port"] != int(cfg.get("relay_port", 5050) or 5050)
                    except (TypeError, ValueError):
                        port_changed = ports_changed = True
                    cfg.update(settings)
                    if manual_addresses:
                        cfg["auto_network"] = False
                    save_config_data(cfg)
                _status.invalidate("network", "firewall")  # порт мог смениться — правило проверяется заново
                self.send_json({"ok": True, "settings": settings, "port_changed": port_changed,
                                "firewall_update_needed": ports_changed})
                return

            if action == "mark_setup_complete":
                # Мастер первоначальной настройки прошёл все проверки — больше не открываем его сам.
                try:
                    with _settings_lock:
                        cfg = load_config_data()
                        cfg["setup_completed"] = True
                        save_config_data(cfg)
                    append_log("[SETUP] First-run setup wizard completed; all checks passed.")
                    self.send_json({"ok": True})
                except Exception as e:
                    self.send_json({"ok": False, "error_code": "ERR_CONFIG_WRITE",
                                    "message": "Не удалось сохранить config.json", "details": str(e)}, 500)
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
                # Установку запускаем только если библиотек ТОЧНО нет; неудавшаяся проверка — не повод.
                if _deps.definitely_missing(deps):
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
                # Мастер настройки передаёт start_server=false: сервер он запустит сам, после брандмауэра.
                started = run_install_dependencies_task(auto_start_server=bool(req_data.get("start_server", True)))
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

                try:
                    cfg_fw = load_config_data()
                    from core.system_state import capture_firewall_before_change
                    capture_firewall_before_change(int(cfg_fw.get("port", 5000)), int(cfg_fw.get("relay_port", 5050)))
                except Exception:
                    pass

                fw_log = LOGS_DIR / "firewall_setup.log"
                try:
                    fw_log.unlink(missing_ok=True)
                except OSError:
                    pass
                # Ждём завершения сценария и проверяем, что правило действительно появилось:
                # раньше ответ «успех» приходил сразу после запуска окна UAC.
                ok, code, msg, exit_code = run_elevated_and_wait(
                    sys_exe("cmd.exe"),
                    f'/d /s /c "set PC_CONTROL_NO_PAUSE=1&& "{script_path}" > "{fw_log}" 2>&1"',
                    str(BASE_DIR),
                )
                global _cached_fw_time
                _cached_fw_time = 0.0
                _status.invalidate("firewall")
                fw_active = is_firewall_configured()
                if ok and fw_active:
                    append_log("Windows Firewall rules successfully applied and verified.")
                    self.send_json({"ok": True, "firewall_ok": True, "message": "Правила брандмауэра Windows созданы и проверены"})
                elif code not in ("ERR_UAC_DENIED", "ERR_UAC_FAILED", "ERR_NOT_SUPPORTED"):
                    # права получены, но сценарий завершился ошибкой / по таймауту / правило не появилось
                    tail = ""
                    try:
                        tail = "\n".join(fw_log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:])
                    except OSError:
                        pass
                    append_log(f"[ERROR] Firewall setup did not create the rule ({msg}). {tail}")
                    self.send_json({
                        "ok": False,
                        "firewall_ok": False,
                        "error_code": "ERR_FIREWALL_NOT_APPLIED",
                        "error_title": "Правило брандмауэра не создано",
                        "message": "Настройка брандмауэра завершилась, но правило для порта сервера не появилось. "
                                   "Подробности — в logs\\firewall_setup.log.",
                        "details": tail or msg,
                    }, 500)
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

                try:
                    cfg_al = load_config_data()
                    from core.system_state import (
                        capture_firewall_before_change,
                        capture_hiberboot_before_change,
                        capture_windows_hello_before_change,
                    )
                    capture_windows_hello_before_change(False)
                    capture_hiberboot_before_change(0)
                    capture_firewall_before_change(int(cfg_al.get("port", 5000)), int(cfg_al.get("relay_port", 5050)))
                except Exception:
                    pass

                ok, code, msg = run_elevated_command(
                    sys_exe("powershell.exe"),
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
                # QA L-13 / A-8: at least 8 characters for a NEW password (an existing shorter one keeps
                # working; the panel only refuses to set a new short one).
                if len(new_pwd) < 8:
                    self.send_json({"ok": False, "error_code": "ERR_PASSWORD_SHORT",
                                    "message": "The password must be at least 8 characters long"}, 400)
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
                _apk.mark_running()

                def _apk_job():
                    global _is_busy, _busy_action
                    try:
                        return run_apk_build(script_path)
                    finally:
                        _is_busy = False
                        _busy_action = ""
                        _background_lock.release()

                if req_data.get("background"):
                    # Мастер настройки: сборка (с загрузкой Android SDK ~300 МБ при первом запуске)
                    # идёт в фоне, а ход и результат читаются из /api/status → apk_build.
                    threading.Thread(target=_apk_job, name="apk-build", daemon=True).start()
                    self.send_json({"ok": True, "started": True, "message": "Сборка APK запущена"}, 202)
                    return
                ok, code, details_text = _apk_job()
                if ok:
                    self.send_json({"ok": True, "message": "Android APK успешно пересобран и подписан!"})
                else:
                    self.send_json({
                        "ok": False,
                        "error_code": code,
                        "error_title": "Ошибка сборки APK",
                        "message": _apk.snapshot().get("message") or "Сборка APK завершилась с ошибкой.",
                        "details": details_text
                    }, 500)
                return

            if action == "launch_tailscale":
                global _cached_ts_time
                lang = req_data.get("lang") or load_config_data().get("language", "ru")
                bins = find_tailscale_binaries()

                # 1. Если Tailscale не установлен — запускаем локальный установщик или скачиваем официальный
                if not bins.get("installed"):
                    if not _background_lock.acquire(False):
                        self.send_json({"ok": False, "message": "Another operation is running"}, 409)
                        return
                    try:
                        installer_file = None
                        for cand in (
                            [BASE_DIR / "tailscale-setup-1.102.4.exe"]
                            + list((BASE_DIR / "logs/installers").glob("tailscale-setup*.exe"))
                            + list(BASE_DIR.glob("tailscale-setup*.exe"))
                        ):
                            if cand.is_file() and cand.stat().st_size > 1_000_000:
                                installer_file = cand
                                break
                        if not installer_file:
                            from scripts.network_setup import download_tailscale
                            installer_file = download_tailscale(BASE_DIR / "logs/installers")
                        os.startfile(str(installer_file))
                        append_log(f"Launched Tailscale installer: {installer_file.name}")
                        msg = (
                            "Tailscale: подтвердите установку Windows, затем войдите в аккаунт. IP подтянется автоматически." if lang == "ru" else
                            "Tailscale: підтвердіть встановлення Windows, потім увійдіть в акаунт. IP підтягнеться автоматично." if lang == "uk" else
                            "Tailscale: confirm Windows installation, then sign in. The VPN IP will be detected automatically."
                        )
                        self.send_json({"ok": True, "installer_launched": True, "message": msg})
                    except Exception as error:
                        append_log(f"[ERROR] Tailscale installer error: {error}")
                        self.send_json({"ok": False, "message": "Tailscale installer: " + str(error)}, 500)
                    finally:
                        _background_lock.release()
                    return

                # 2. Tailscale установлен — проверяем процесс трея (tailscale-ipn.exe)
                _cached_ts_time = 0.0
                _status.invalidate("tailscale", "network")
                is_ipn_running = False
                try:
                    import psutil
                    for p in psutil.process_iter(["name"]):
                        if "tailscale-ipn" in (p.info.get("name") or "").lower():
                            is_ipn_running = True
                            break
                except Exception:
                    pass

                gui_started = False
                if not is_ipn_running:
                    if bins.get("shortcut") and bins["shortcut"].is_file():
                        try:
                            os.startfile(str(bins["shortcut"]))
                            gui_started = True
                            append_log(f"Started Tailscale tray process via shortcut: {bins['shortcut'].name}")
                        except Exception as e:
                            append_log(f"Could not open Tailscale shortcut: {e}")
                    elif bins.get("gui") and bins["gui"].is_file():
                        try:
                            subprocess.Popen([str(bins["gui"])], cwd=str(bins["gui"].parent))
                            gui_started = True
                            append_log(f"Started Tailscale GUI process: {bins['gui']}")
                        except Exception as e:
                            append_log(f"Could not start tailscale-ipn: {e}")
                else:
                    append_log("Tailscale background service (tailscale-ipn) is already active.")

                if bins.get("cli") and bins["cli"].is_file():
                    ts_cur = get_tailscale_info()
                    if not ts_cur.get("running"):
                        try:
                            subprocess.Popen([str(bins["cli"]), "up", "--unattended"], creationflags=NO_WINDOW)
                            _cached_ts_time = 0.0
                            _status.invalidate("tailscale", "network")
                        except Exception:
                            pass

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

                succ_msg = (
                    "Приложение Tailscale открыто" if lang == "ru" else
                    "Додаток Tailscale відкрито" if lang == "uk" else
                    "Tailscale application opened"
                )
                if check_tailscale_web_accessible(target_url, timeout=1):
                    launched = launch_tailscale_app_window(target_url)
                    if launched:
                        append_log(f"Tailscale interface launched successfully ({target_url}).")
                        self.send_json({"ok": True, "message": succ_msg, "url": target_url})
                        return

                # Fallback: активация нативного клиента Tailscale в трее / окне Windows
                if not gui_started:
                    if bins.get("gui") and bins["gui"].is_file():
                        try:
                            subprocess.Popen([str(bins["gui"])], cwd=str(bins["gui"].parent))
                            gui_started = True
                            append_log(f"Activated native Tailscale client: {bins['gui']}")
                        except Exception as e:
                            append_log(f"Could not activate tailscale-ipn: {e}")
                    elif bins.get("shortcut") and bins["shortcut"].is_file():
                        try:
                            os.startfile(str(bins["shortcut"]))
                            gui_started = True
                            append_log(f"Activated Tailscale via shortcut: {bins['shortcut'].name}")
                        except Exception as e:
                            append_log(f"Could not open Tailscale shortcut: {e}")

                if gui_started or is_ipn_running:
                    _cached_ts_time = 0.0
                    _status.invalidate("tailscale", "network")
                    self.send_json({"ok": True, "message": succ_msg})
                else:
                    self.send_json({"ok": False, "message": "Интерфейс Tailscale пока недоступен. Откройте значок Tailscale в трее, войдите в аккаунт и повторите."}, 503)
                return

            if action in ("open_web", "open_web_standalone"):
                cfg = load_config_data()
                port = int(cfg.get("port", 5000))
                # Убеждаемся, что сервер запущен, чтобы веб-пульт сразу подключился
                if not is_server_running(port):
                    append_log("Starting PC Control server before opening remote...")
                    ok, code, title, msg = start_server_process()
                    if not ok:
                        self.send_json({"ok": False, "error_code": code, "error_title": title,
                                        "message": msg or "Failed to start server"}, 500)
                        return
                    time.sleep(0.8)
                    # Порт мог смениться автоматически (прежний был занят) — берём актуальный.
                    cfg = load_config_data()
                    port = int(cfg.get("port", 5000))

                lang = req_data.get("lang") or cfg.get("language", "ru")
                token = cfg.get("token", "")
                # Билет должен выпустить сам сервер: билеты хранятся в памяти процесса сервера,
                # а созданный здесь (в процессе панели) сервер не мог погасить — веб-пульт
                # открывался с недействительным билетом и снова просил пароль.
                auth_param = f"token={urllib.parse.quote(token)}&" if token else ""
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/pair/ticket",
                        headers={"X-Auth-Token": token},
                    )
                    with urllib.request.urlopen(req, timeout=3) as r:
                        ticket = json.loads(r.read().decode("utf-8")).get("ticket") or ""
                    if ticket:
                        auth_param = f"ticket={urllib.parse.quote(ticket)}&"
                except Exception as ex:
                    append_log(f"Pairing ticket request failed, falling back to token: {ex}")
                remote_url = f"http://127.0.0.1:{port}/?{auth_param}lang={urllib.parse.quote(lang)}"

                layout = get_desktop_window_layout()["remote"]
                window_flags = [
                    f"--window-position={layout['x']},{layout['y']}",
                    f"--window-size={layout['w']},{layout['h']}",
                ]
                edge_anti_translate = [
                    "--disable-features=Translate,msEdgeTranslate,TranslateUI,AutofillServerCommunication",
                    "--disable-translate",
                    "--no-first-run",
                    "--disable-save-password-bubble",
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
                cfg = load_config_data()
                origins = cfg.get("cors_allowed_origins")
                if isinstance(origins, list):
                    origins_list = [str(o).strip() for o in origins if str(o).strip()]
                else:
                    origins_list = [
                        "http://localhost:*",
                        "http://127.0.0.1:*",
                        "http://192.168.*",
                        "http://172.*",
                        "http://100.*",
                        "http://10.*"
                    ]
                self.send_json({"ok": True, "origins": origins_list})
                return

            if action == "set_cors_origins":
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
                try:
                    with _settings_lock:
                        cfg = load_config_data()
                        cfg["cors_allowed_origins"] = origins_list
                        save_config_data(cfg)
                except Exception:
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
                global _self_restart_blocked
                _self_restart_blocked = True  # обновление само перезапустит панель
                res = apply_github_update()
                if not (res.get("ok") and res.get("restarting")):
                    _self_restart_blocked = False
                self.send_json(res)
                if res.get("ok") and res.get("restarting"):
                    threading.Timer(0.6, lambda: os._exit(0)).start()
                return

            if action == "clean_browser_profiles":
                res = clean_browser_profiles()
                append_log(f"Browser profiles cleaned: {res.get('freed_mb')} MB freed ({res.get('removed_items')})")
                self.send_json(res)
                return

            if action == "check_phone_connection":
                cfg = load_config_data()
                port = int(cfg.get("port", 5000))
                lan_ip = (cfg.get("lan_ip") or get_local_ip()).strip()
                server_up = is_server_running(port)
                fw_ok = is_firewall_configured()
                lan_reachable = False
                if server_up and lan_ip and lan_ip != "127.0.0.1":
                    try:
                        req_lan = urllib.request.Request(
                            f"http://{lan_ip}:{port}/status",
                            headers={"User-Agent": "PC-Control-LAN-Probe"}
                        )
                        with urllib.request.urlopen(req_lan, timeout=1.2) as r_lan:
                            if r_lan.status == 200:
                                b_lan = json.load(r_lan)
                                # Отвечать должен именно наш сервер, а не другая программа на этом порту
                                lan_reachable = (b_lan.get("status") == "online" and b_lan.get("instance") == instance_id())
                    except Exception:
                        lan_reachable = False
                interfaces = []
                try:
                    from scripts.network_setup import list_network_interfaces
                    interfaces = list_network_interfaces()
                except Exception:
                    pass
                self.send_json({
                    "ok": True,
                    "server_running": server_up,
                    "lan_ip": lan_ip,
                    "port": port,
                    "lan_reachable": lan_reachable,
                    "firewall_configured": fw_ok,
                    "firewall_blocking": firewall_blocking_programs(),
                    "interfaces": interfaces,
                })
                return

            if action == "export_diagnostics":
                try:
                    cfg = load_config_data()
                    port = int(cfg.get("port", 5000))
                    interfaces = []
                    try:
                        from scripts.network_setup import list_network_interfaces
                        interfaces = list_network_interfaces()
                    except Exception:
                        pass
                    journal_data, journal_status = {}, "unavailable"
                    try:
                        from core.system_state import load_journal
                        # load_journal() возвращает (журнал, статус) — раньше здесь брался кортеж целиком,
                        # и кнопка «Диагностика системы» всегда завершалась ошибкой.
                        journal_data, journal_status = load_journal()
                    except Exception as e:
                        journal_status = f"error: {e}"
                    diag = {
                        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "platform": platform.platform(),
                        "python_version": sys.version,
                        "python_executable": sys.executable,
                        "base_dir": str(BASE_DIR),
                        "server_running": is_server_running(port),
                        "firewall_configured": is_firewall_configured(),
                        "python_deps": check_python_deps(),
                        "network_settings": {
                            "lan_ip": cfg.get("lan_ip", ""),
                            "vpn_ip": cfg.get("vpn_ip", ""),
                            "mac_address": cfg.get("mac_address", ""),
                            "port": port,
                            "relay_port": cfg.get("relay_port", 5050),
                            "auto_network": cfg.get("auto_network", True),
                        },
                        "network_interfaces": interfaces,
                        "tailscale": get_tailscale_info(),
                        "apk_exists": (BASE_DIR / "PC_Control.apk").is_file(),
                        "uninstaller_exists": uninstaller_exe() is not None,
                        "system_state_journal_status": journal_status,
                        "system_state_journal_entries": list((journal_data.get("entries") or {}).keys())
                        if isinstance(journal_data, dict) else [],
                        "recent_logs": get_logs()[-50:],
                    }
                    diag_path = LOGS_DIR / "diagnostic_report.json"
                    diag_path.write_text(json.dumps(diag, indent=2, ensure_ascii=False), encoding="utf-8")
                    checks = {
                        "server": bool(diag["server_running"]),
                        "firewall": bool(diag["firewall_configured"]),
                        "deps": bool((diag["python_deps"] or {}).get("installed")),
                        "lan_ip": bool(cfg.get("lan_ip")) and cfg.get("lan_ip") != "127.0.0.1",
                    }
                    for name, passed in checks.items():
                        append_log(f"[DIAGNOSTICS] {name}: {'OK' if passed else 'FAIL'}")
                    append_log(f"[DIAGNOSTICS] Saved diagnostic report to {diag_path}")
                    self.send_json({"ok": True, "path": str(diag_path), "checks": checks, "report": diag})
                except Exception as e:
                    import traceback
                    append_log(f"[ERROR] Diagnostics failed: {e}")
                    self.send_json({"ok": False, "error_code": "ERR_DIAGNOSTICS",
                                    "error_title": "Сбой диагностики",
                                    "message": f"Не удалось собрать отчёт диагностики: {e}",
                                    "details": traceback.format_exc()[-1500:]}, 500)
                return

            if action == "launch_uninstaller":
                if is_dev_folder():
                    # QA L-7: never offer to delete a development checkout
                    self.send_json({"ok": False, "error_code": "ERR_DEV_FOLDER",
                                    "message": "This folder is a development checkout (.git / Rust sources); "
                                               "the uninstaller is disabled here."}, 409)
                    return
                uninst_exe = uninstaller_exe() or BASE_DIR / "Uninstall.exe"
                uninst_bat = BASE_DIR / "uninstall.bat"
                if uninst_exe.is_file():
                    try:
                        os.startfile(str(uninst_exe))
                        append_log(f"Launched {uninst_exe.name}")
                        self.send_json({"ok": True, "message": f"Окно деинсталлятора {uninst_exe.name} открыто."})
                        return
                    except Exception as e:
                        self.send_json({"ok": False, "message": str(e)}, 500)
                        return
                elif uninst_bat.is_file():
                    try:
                        os.startfile(str(uninst_bat))
                        append_log("Launched uninstall.bat")
                        self.send_json({"ok": True, "message": "Скрипт удаления uninstall.bat запущен."})
                        return
                    except Exception as e:
                        self.send_json({"ok": False, "message": str(e)}, 500)
                        return
                self.send_json({"ok": False, "message": "Uninstall.exe not found"}, 404)
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
        "--disable-features=Translate,msEdgeTranslate,TranslateUI,AutofillServerCommunication",
        "--disable-translate",
        "--no-first-run",
        "--disable-save-password-bubble",
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
                enforce_window_geometry_async(["control panel", "панель управления", str(CONTROL_PORT)], layout['x'], layout['y'], layout['w'], layout['h'])
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
                subprocess.Popen([str(p), f"--app={cache_bust_url}"] + window_flags + [
                    "--disable-features=Translate,TranslateUI,AutofillServerCommunication",
                    "--disable-translate",
                    "--no-first-run",
                    "--disable-save-password-bubble",
                ])
                enforce_window_geometry_async(["control panel", "панель управления", str(CONTROL_PORT)], layout['x'], layout['y'], layout['w'], layout['h'])
                return
            except Exception:
                pass

    webbrowser.open(cache_bust_url)


def main():
    gui_url = f"http://127.0.0.1:{CONTROL_PORT}"

    global _httpd
    if "--replace" in sys.argv:
        # Нас запустила прежняя копия панели (её код обновился): ждём, пока она освободит порт.
        for _ in range(60):
            if not is_already_serving():
                break
            time.sleep(0.25)
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
    httpd = None
    for attempt in range(20 if "--replace" in sys.argv else 1):
        try:
            httpd = http.server.ThreadingHTTPServer(server_address, ControlPanelHandler)
            break
        except OSError as e:
            if attempt == (19 if "--replace" in sys.argv else 0):
                print(f"[ОШИБКА] Не удалось занять порт {CONTROL_PORT}: {e}")
                return
            time.sleep(0.25)
    _httpd = httpd

    # Запускаем фоновый сторож активности: при закрытии браузера процесс завершится сам
    threading.Thread(target=_idle_watchdog, daemon=True).start()
    # Код панели обновился на диске → панель перезапускает себя сама
    threading.Thread(target=_self_restart_watcher, daemon=True).start()

    # Проверка первого запуска: авто-создание config.json и автоустановка библиотек
    threading.Timer(0.8, check_first_run_setup).start()
    # Фоновый расчёт статуса: /api/status отдаёт готовые значения
    _status.start()

    # Фоновая автоматическая проверка обновлений при старте лаунчера (api.github.com).
    # QA П-9: not in test mode, and switchable off (config "auto_update_check": false or
    # PC_CONTROL_NO_UPDATE_CHECK=1). The "Check for updates" button still works.
    if auto_update_check_enabled():
        threading.Timer(2.0, check_github_updates).start()
    else:
        append_log("[UPDATE] Automatic update check at start is switched off.")
    # Через минуту (процесс-исполнитель обновления к этому времени завершён) убираем его рабочую папку
    threading.Timer(60.0, cleanup_update_workspaces).start()
    # Apps & features of an installer-made copy: unstaller.exe -> Uninstall.exe (self-heal, 2.5.1)
    threading.Timer(3.0, repair_uninstall_registration).start()

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
