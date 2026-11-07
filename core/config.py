"""
PC Control — Конфигурация и глобальные параметры.
"""

import json
import os
import platform
import secrets
import subprocess
import threading
import tempfile
import time
from pathlib import Path

# Базовые директории проекта
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
ERROR_LOG_FILE = LOGS_DIR / "error_log.txt"

LOG_FILE = BASE_DIR / "actions_log.jsonl"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

WEB_DIR = BASE_DIR / "web"
WEB_INDEX_FILE = WEB_DIR / "index.html"

# Настройки устройств и системы
MIC_DEVICE = os.environ.get("MIC_DEVICE_NAME", "")
NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def auto_detect_network_params() -> dict:
    import re
    import socket

    lan_ip = "192.168.0.100"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        lan_ip = s.getsockname()[0]
    except Exception:
        pass
    finally:
        s.close()

    vpn_ip = ""
    ts_paths = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Tailscale" / "tailscale.exe",
        Path("C:\\Program Files\\Tailscale\\tailscale.exe"),
    ]
    for p in ts_paths:
        if p.exists():
            try:
                out = subprocess.check_output([str(p), "ip", "-4"], text=True, timeout=3, creationflags=NO_WINDOW).strip()
                if out:
                    vpn_ip = out.splitlines()[0].strip()
                    break
            except Exception:
                pass

    if not vpn_ip and platform.system() == "Windows":
        try:
            cmd = [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-Command", 'Get-NetIPAddress -InterfaceAlias *Tailscale* -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress']
            out = subprocess.check_output(cmd, env={k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}, stderr=subprocess.DEVNULL, text=True, timeout=4, creationflags=NO_WINDOW).strip()
            if out:
                vpn_ip = out.splitlines()[0].strip()
        except Exception:
            pass

    from scripts.network_setup import detect_network
    detected = detect_network()
    lan_ip = detected['lan_ip']
    mac_address = detected['mac_address']

    # Генерируем криптографически стойкий 16-значный токен для нового конфига
    gen_token = secrets.token_hex(8)

    return {
        "auto_network": True,
        "token": gen_token,
        "lan_ip": lan_ip,
        "vpn_ip": vpn_ip,
        "wol_relay_ip": "",
        "mac_address": mac_address,
        "port": 5000,
        "relay_port": 5050,
        "language": "ru",
        "cors_allowed_origins": [
            "http://localhost:*",
            "http://127.0.0.1:*",
            "http://192.168.*",
            "http://100.*",
            "http://10.*"
        ]
    }

_config_lock = threading.RLock()
_cached_config: dict | None = None
_cached_config_mtime: int = -1


def load_app_config() -> dict:
    global _cached_config, _cached_config_mtime
    cfg_file = BASE_DIR / "config.json"
    with _config_lock:
        if cfg_file.exists():
            try:
                mtime = cfg_file.stat().st_mtime_ns
                if _cached_config is not None and mtime == _cached_config_mtime:
                    return dict(_cached_config)
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        _cached_config = data
                        _cached_config_mtime = mtime
                        return dict(data)
            except Exception:
                if _cached_config is not None:
                    return dict(_cached_config)
        else:
            try:
                cfg = auto_detect_network_params()
                tmp_file = cfg_file.with_suffix(".json.tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                os.replace(tmp_file, cfg_file)
                _cached_config = cfg
                try:
                    _cached_config_mtime = cfg_file.stat().st_mtime_ns
                except Exception:
                    _cached_config_mtime = -1
                print("[INFO] Персональный config.json создан с авто-определением параметров сети.")
                return dict(cfg)
            except Exception:
                pass
        return dict(_cached_config) if _cached_config is not None else {}


APP_CONFIG = load_app_config()


def save_app_config(cfg: dict) -> bool:
    global APP_CONFIG, AUTH_TOKEN, _cached_config, _cached_config_mtime
    cfg_file = BASE_DIR / "config.json"
    with _config_lock:
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cfg_file.parent,
                                             prefix="config-", suffix=".tmp", delete=False) as f:
                tmp_file = Path(f.name)
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            for attempt in range(5):
                try:
                    os.replace(tmp_file, cfg_file)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.02)
            _cached_config = dict(cfg)
            try:
                _cached_config_mtime = cfg_file.stat().st_mtime_ns
            except Exception:
                _cached_config_mtime = -1
            APP_CONFIG = cfg
            AUTH_TOKEN = str(cfg.get("token", "")).strip()
            return True
        except Exception as e:
            print(f"[ERROR] Не удалось сохранить config.json: {e}")
            return False
        finally:
            if tmp_file is not None:
                try:
                    tmp_file.unlink(missing_ok=True)
                except OSError:
                    pass


def get_auth_token() -> str:
    env_token = os.environ.get("PC_REMOTE_TOKEN")
    if env_token:
        return env_token.strip()
    cfg = load_app_config()
    if cfg and "token" in cfg and str(cfg["token"]).strip():
        return str(cfg["token"]).strip()
    return ""


def update_config_section(key: str, values: dict) -> bool:
    """Merge a section against the latest disk configuration under our write lock."""
    with _config_lock:
        cfg = load_app_config()
        cfg[key] = dict(values)
        return save_app_config(cfg)


def update_auth_token(new_token: str) -> bool:
    global AUTH_TOKEN
    new_token = str(new_token).strip()
    if not new_token:
        return False
    cfg = load_app_config() or {}
    cfg["token"] = new_token
    ok = save_app_config(cfg)
    if ok:
        AUTH_TOKEN = new_token
        if "PC_REMOTE_TOKEN" in os.environ:
            os.environ["PC_REMOTE_TOKEN"] = new_token
    return ok

def get_cors_allowed_origins() -> list[str]:
    cfg = load_app_config() or {}
    origins = cfg.get("cors_allowed_origins")
    if isinstance(origins, list):
        return [str(o).strip() for o in origins if str(o).strip()]
    return [
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://192.168.*",
        "http://100.*",
        "http://10.*"
    ]

def update_cors_origins(origins: list[str]) -> bool:
    cfg = load_app_config() or {}
    cleaned = [str(o).strip() for o in origins if str(o).strip()]
    cfg["cors_allowed_origins"] = cleaned
    return save_app_config(cfg)

AUTH_TOKEN = get_auth_token()

def is_safe_test_mode() -> bool:
    """Тестовый режим включается ИСКЛЮЧИТЕЛЬНО через переменные окружения (PC_CONTROL_TEST_MODE=1 или SAFE_TEST_MODE=1)."""
    return os.environ.get("PC_CONTROL_TEST_MODE") == "1" or os.environ.get("SAFE_TEST_MODE") == "1"


def set_safe_test_mode(value: bool):
    """Устанавливает или снимает флаг тестового режима в окружении процесса."""
    if value:
        os.environ["PC_CONTROL_TEST_MODE"] = "1"
        os.environ["SAFE_TEST_MODE"] = "1"
    else:
        os.environ.pop("PC_CONTROL_TEST_MODE", None)
        os.environ.pop("SAFE_TEST_MODE", None)
