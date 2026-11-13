#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC Control - Quick Server and App Password Utility.
Updates the shared configuration; clients accept the password in their settings.
"""

import json
import os
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows console
try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
# Пароль хранится только в config.json: веб-пульт и Android-приложение (assets/pc_defaults.json,
# создаётся build_apk.py) его не содержат (кроме сборки с --embed-token), поэтому менять файлы
# клиентов и пересобирать APK при смене пароля не нужно.
SERVER_PY = BASE_DIR / "server.py"


def get_current_token() -> str:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                return str(data.get("token", "")).strip()
        except Exception:
            pass
    return ""


def save_token_to_config(token: str):
    try:
        from scripts.control_panel import save_token_everywhere
    except ImportError:
        from control_panel import save_token_everywhere
    if not save_token_everywhere(token):
        raise ValueError("Password cannot be empty")


def restart_server():
    """Softly restarts the server.py process so that changes take effect."""
    try:
        from scripts.control_panel import restart_server_process
    except ImportError:
        from control_panel import restart_server_process
    ok, code, title, message = restart_server_process()
    if not ok:
        raise RuntimeError(f"{code}: {title}: {message}")
    print(message)


def main():
    print("=" * 68)
    print("               PC CONTROL - SERVER PASSWORD SETUP                 ")
    print("=" * 68)

    current_tok = get_current_token()
    # QA L-13: the current password is not printed (screen sharing / console logs)
    print(f"  Current server password: {'set (' + str(len(current_tok)) + ' characters)' if current_tok else 'not set'}")
    print("-" * 68)

    new_token = ""
    if len(sys.argv) > 1 and sys.argv[1].strip():
        new_token = sys.argv[1].strip()
    else:
        try:
            prompt_text = "Enter new password (at least 8 characters; press Enter to keep the current one): "
            entered = input(prompt_text).strip()
            if entered:
                new_token = entered
            else:
                new_token = current_tok
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled by user.")
            return

    if not new_token:
        import secrets
        new_token = secrets.token_hex(8)
    if new_token != current_tok and len(new_token) < 8:
        print("[ERROR] The password must be at least 8 characters long. Nothing was changed.")
        sys.exit(2)  # QA L2-5: scripts / the panel see the refusal
    if len(sys.argv) > 1:
        print("[!] Note: a password given on the command line stays in the shell history.")

    print(f"\n[*] Setting password: {new_token}")

    # 1. Save to config.json
    save_token_to_config(new_token)
    print("[OK] config.json file updated.")

    # Server reads the token from configuration on each request; client apps
    # accept it in their settings. No APK rebuild or process restart is needed.

    lan_ip = "192.168.0.100"
    vpn_ip = ""
    port = 5000
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                c = json.load(f)
                lan_ip = c.get("lan_ip", lan_ip)
                vpn_ip = c.get("vpn_ip", vpn_ip)
                port = c.get("port", port)
        except Exception:
            pass

    print("=" * 68)
    print("               DONE! PASSWORD UPDATED SUCCESSFULLY               ")
    print("=" * 68)
    print(f"  New password:      {new_token}")
    print(f"  Local link:        http://{lan_ip}:{port}")
    print(f"  Tailscale link:    http://{vpn_ip}:{port}")
    print("=" * 68)
    print("Now enter this password when connecting from any device.")
    print("=" * 68)


if __name__ == "__main__":
    main()
