#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC Control - Interactive Configuration Wizard.
Configures security token (password), LAN IP, Tailscale IP,
Wake-on-LAN relay, and updates server and web client settings.
"""

import json
import os
import re
import secrets
import socket
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"


def detect_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "192.168.0.100"
    finally:
        s.close()
    return ip


def detect_tailscale_ip():
    ts_paths = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Tailscale" / "tailscale.exe",
        Path("C:\\Program Files\\Tailscale\\tailscale.exe"),
    ]
    for p in ts_paths:
        if p.exists():
            try:
                out = subprocess.check_output([str(p), "ip", "-4"], text=True, timeout=3).strip()
                if out:
                    return out.splitlines()[0].strip()
            except Exception:
                pass

    try:
        cmd = [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-Command", 'Get-NetIPAddress -InterfaceAlias *Tailscale* -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress']
        out = subprocess.check_output(cmd, env={k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}, stderr=subprocess.DEVNULL, text=True, timeout=4).strip()
        if out:
            return out.splitlines()[0].strip()
    except Exception:
        pass

    return ""


def detect_mac_address():
    try:
        cmd = [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-Command", "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -notmatch 'Virtual|Tailscale|WSL|Hyper-V' } | Select-Object -First 1 -ExpandProperty MacAddress"]
        out = subprocess.check_output(cmd, env={k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}, stderr=subprocess.DEVNULL, text=True, timeout=4).strip()
        if out and re.match(r"^[0-9A-Fa-f]{2}(-[0-9A-Fa-f]{2}){5}$", out):
            return out.upper()
    except Exception:
        pass
    return "AA-BB-CC-DD-EE-FF"


def load_config():
    defaults = {
        "token": secrets.token_hex(8),
        "lan_ip": detect_lan_ip(),
        "vpn_ip": detect_tailscale_ip(),
        "wol_relay_ip": "",
        "mac_address": detect_mac_address(),
        "port": 5000,
        "relay_port": 5050,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_config(cfg):
    try:
        from scripts.control_panel import save_config_data, validate_network_settings
    except ImportError:
        from control_panel import save_config_data, validate_network_settings
    cfg.update(validate_network_settings(cfg))
    save_config_data(cfg)


def update_source_file(file_path, cfg):
    if not file_path.exists():
        return
    text = file_path.read_text(encoding="utf-8")

    lan_url = f"http://{cfg['lan_ip']}:{cfg['port']}"
    vpn_url = f"http://{cfg['vpn_ip']}:{cfg['port']}"
    relay_url = f"http://{cfg['wol_relay_ip']}:{cfg['relay_port']}"
    token = cfg["token"]

    text = re.sub(r"const DEFAULT_LAN_HOST = ['\"][^'\"]*['\"];", f"const DEFAULT_LAN_HOST = '{lan_url}';", text)
    text = re.sub(r"const DEFAULT_VPN_HOST = ['\"][^'\"]*['\"];", f"const DEFAULT_VPN_HOST = '{vpn_url}';", text)
    text = re.sub(r"const DEFAULT_WOL_RELAY = ['\"][^'\"]*['\"];", f"const DEFAULT_WOL_RELAY = '{relay_url}';", text)
    text = re.sub(r"const DEFAULT_APP_TOKEN = ['\"][^'\"]*['\"];", "const DEFAULT_APP_TOKEN = '';", text)

    file_path.write_text(text, encoding="utf-8")


def main():
    print("=" * 70)
    print("           PC CONTROL - INTERACTIVE SETUP WIZARD            ")
    print("=" * 70)
    print("This script configures access password and IP addresses for your PC.")
    print("Press Enter to keep the suggested default in brackets [ ... ].")
    print("-" * 70)

    cfg = load_config()

    # 1. Token / password
    val = input(f"[1/5] Server access password [{cfg['token']}]: ").strip()
    if val:
        cfg["token"] = val

    # 2. Local IP
    val = input(f"[2/5] PC local IP on Wi-Fi network [{cfg['lan_ip']}]: ").strip()
    if val:
        cfg["lan_ip"] = val

    # 3. Tailscale IP
    val = input(f"[3/5] PC Tailscale IP (if used) [{cfg['vpn_ip']}]: ").strip()
    if val:
        cfg["vpn_ip"] = val

    # 4. WOL relay
    val = input(f"[4/5] WOL relay phone IP [{cfg['wol_relay_ip']}]: ").strip()
    if val:
        cfg["wol_relay_ip"] = val

    # 5. MAC address
    val = input(f"[5/5] PC network card MAC address for Wake-on-LAN [{cfg['mac_address']}]: ").strip()
    if val:
        cfg["mac_address"] = val.upper()

    print("\nSaving configuration...")
    cfg['auto_network'] = False
    save_config(cfg)

    print("Settings saved. Enter the server address and password in the client settings.")
    print("No source files or APK rebuild are required.")

    print("=" * 70)
    print("                      SETUP COMPLETED SUCCESSFULLY!                    ")
    print("=" * 70)
    print(f"  Access Password:      {cfg['token']}")
    print(f"  Local Address:        http://{cfg['lan_ip']}:{cfg['port']}")
    print(f"  Tailscale Address:    http://{cfg['vpn_ip']}:{cfg['port']}")
    print(f"  WOL Relay:            http://{cfg['wol_relay_ip']}:{cfg['relay_port']}")
    print(f"  Wake-on-LAN MAC:      {cfg['mac_address']}")
    print("=" * 70)
    print("Now you can launch scripts\\3_start_server.bat - the server will run")
    print("with your personalized parameters!")
    print("=" * 70)


if __name__ == "__main__":
    main()
