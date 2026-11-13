"""
PC Control — поиск и опрос Tailscale (вынесено из scripts/control_panel.py).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

try:
    import winreg
except ImportError:  # не Windows
    winreg = None


def find_tailscale_binaries() -> dict:
    """Поиск установленного Tailscale: PATH, реестр, стандартные папки, ярлыки «Пуска»."""
    gui_path = None
    cli_path = None
    shortcut_path = None

    # 1. PATH
    w_gui = shutil.which("tailscale-ipn.exe") or shutil.which("tailscale-ipn")
    if w_gui and Path(w_gui).is_file():
        gui_path = Path(w_gui)
    w_cli = shutil.which("tailscale.exe") or shutil.which("tailscale")
    if w_cli and Path(w_cli).is_file():
        cli_path = Path(w_cli)

    # 2. Реестр
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
                            except Exception:
                                continue
                            if not val or not isinstance(val, str):
                                continue
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

    # 3. Стандартные каталоги установки
    candidate_dirs = list(reg_dirs)
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramData"):
        val = os.environ.get(env_key)
        if val:
            candidate_dirs.append(Path(val) / "Tailscale")
            candidate_dirs.append(Path(val) / "Programs" / "Tailscale")
    candidate_dirs.extend([Path(r"C:\Program Files\Tailscale"), Path(r"C:\Program Files (x86)\Tailscale")])
    for d in candidate_dirs:
        if not gui_path and (d / "tailscale-ipn.exe").is_file():
            gui_path = d / "tailscale-ipn.exe"
        if not cli_path and (d / "tailscale.exe").is_file():
            cli_path = d / "tailscale.exe"

    # 4. Ярлыки в меню «Пуск»
    shortcut_candidates = [Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Tailscale.lnk")]
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
        "installed": bool(gui_path or cli_path or shortcut_path),
    }


_last_good: tuple[float, dict] | None = None
LAST_GOOD_TTL = 30.0


def read_status(cli_path) -> dict:
    """`tailscale status --json` → IP, учётная запись, имя устройства, MagicDNS, устройства в сети.

    Если команда не успела ответить или упала, в течение 30 с возвращается последний удачный ответ:
    раньше один медленный ответ (таймаут 1,2 с) выдавался за «Tailscale остановлен», и при
    автоопределении сети панель стирала vpn_ip в config.json, а через секунды записывала снова."""
    global _last_good
    info = {"ip": "", "account": "", "device_name": "", "magic_dns": "", "peers": [], "backend_state": "Stopped"}
    if not cli_path or not Path(cli_path).is_file():
        return info
    try:
        res = subprocess.run([str(cli_path), "status", "--json"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=3.0, creationflags=NO_WINDOW)
        if res.returncode != 0 or not res.stdout.strip():
            # Tailscale ответил «не работает» (служба остановлена / не вошли) — это настоящий ответ.
            _last_good = None
            return info
        data = json.loads(res.stdout)
        self_node = data.get("Self") or {}
        ts_ips = data.get("TailscaleIPs") or self_node.get("TailscaleIPs") or []
        if ts_ips:
            info["ip"] = next((v for v in ts_ips if ":" not in v), "")
        info["backend_state"] = data.get("BackendState", "Running" if info["ip"] else "Stopped")
        info["device_name"] = self_node.get("HostName", "")
        info["magic_dns"] = self_node.get("DNSName", "").rstrip(".")
        users = data.get("User") or {}
        if users:
            first_user = users.get(str(self_node.get("UserID", "")), {})
            info["account"] = first_user.get("LoginName") or first_user.get("DisplayName", "")
        for p in (data.get("Peer") or {}).values():
            p_ips = p.get("TailscaleIPs") or []
            info["peers"].append({
                "name": p.get("HostName") or "Unknown Device",
                "ip": p_ips[0] if p_ips else "",
                "online": bool(p.get("Online")),
                "os": p.get("OS", ""),
            })
    except Exception:
        # Таймаут / сбой разбора: не выдаём это за «остановлен», пока свеж прошлый удачный ответ.
        if _last_good is not None and time.monotonic() - _last_good[0] < LAST_GOOD_TTL:
            return dict(_last_good[1])
        return info
    _last_good = (time.monotonic(), dict(info))
    return info
