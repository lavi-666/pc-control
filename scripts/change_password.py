#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC Control - Quick Server and App Password Utility.
Updates the shared configuration; clients accept the password in their settings.
"""

import json
import os
import re
import subprocess
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
WEB_HTML = BASE_DIR / "web" / "index.html"
APP_HTML = BASE_DIR / "android_app" / "assets" / "index.html"
SERVER_PY = BASE_DIR / "server.py"
BUILD_APK_SCRIPT = BASE_DIR / "scripts" / "build_apk.py"


def get_current_token() -> str:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return str(data.get("token", "")).strip()
        except Exception:
            pass
    return ""


def save_token_to_config(token: str):
    from control_panel import save_token_everywhere
    if not save_token_everywhere(token):
        raise ValueError("Password cannot be empty")


def update_token_in_file(file_path: Path, token: str):
    """В целях безопасности пароли хранятся исключительно в защищённом config.json
    и НИКОГДА не зашиваются в HTML-файлы или бинарные APK."""
    if not file_path.exists():
        return
    try:
        content = file_path.read_text(encoding="utf-8")
        content = re.sub(
            r"const DEFAULT_APP_TOKEN = ['\"][^'\"]*['\"];",
            "const DEFAULT_APP_TOKEN = '';",
            content
        )
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"[!] Error updating {file_path.name}: {e}")


def restart_server():
    """Softly restarts the server.py process so that changes take effect."""
    from control_panel import restart_server_process
    ok, code, title, message = restart_server_process()
    if not ok:
        raise RuntimeError(f"{code}: {title}: {message}")
    print(message)


def rebuild_apk():
    if not BUILD_APK_SCRIPT.exists():
        return
    print("[*] Rebuilding PC_Control.apk with new password...")
    try:
        res = subprocess.run([sys.executable, str(BUILD_APK_SCRIPT)], capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            print("[OK] Mobile app PC_Control.apk rebuilt and signed successfully!")
        else:
            print(f"[!] Warning during APK build: {res.stderr.strip()[:200]}")
    except Exception as e:
        print(f"[!] Skipping APK build: {e}")


def main():
    print("=" * 68)
    print("               PC CONTROL - SERVER PASSWORD SETUP                 ")
    print("=" * 68)

    current_tok = get_current_token()
    print(f"  Current server password: [ {current_tok} ]")
    print("-" * 68)

    new_token = ""
    if len(sys.argv) > 1 and sys.argv[1].strip():
        new_token = sys.argv[1].strip()
    else:
        try:
            prompt_text = f"Enter new password (press Enter to keep '{current_tok}'): "
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
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
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
