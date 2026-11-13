"""
PC Control — сборка персонального PC_Control.apk из панели (обёртка над scripts/build_apk.py).

Вынесено из scripts/control_panel.py. Заменяет прежний неиспользуемый core/launcher/apk_mgr.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0


def apk_fingerprint(cfg: dict) -> dict:
    """Что вшито в персональный APK: при смене адреса, порта, MAC или пароля его нужно пересобрать."""
    token = str(cfg.get("token") or "")
    return {
        "lan_ip": str(cfg.get("lan_ip") or ""),
        "port": int(cfg.get("port", 5000) or 5000),
        "mac": str(cfg.get("mac_address") or ""),
        "vpn_ip": str(cfg.get("vpn_ip") or ""),
        "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest() if token else "",
    }


class ApkBuilder:
    def __init__(self, base_dir: Path, logs_dir: Path, python_cli: Callable[[], str],
                 load_config: Callable[[], dict], log: Callable[[str], None]):
        self.base_dir = Path(base_dir)
        self.logs_dir = Path(logs_dir)
        self.apk_path = self.base_dir / "PC_Control.apk"
        self.script = self.base_dir / "scripts" / "build_apk.py"
        self.info_file = self.logs_dir / "apk_build_info.json"
        self._python_cli = python_cli
        self._load_config = load_config
        self._log = log
        self._lock = threading.Lock()
        self.state: dict = {"state": "idle", "message": "", "details": "", "started_at": 0, "finished_at": 0}

    def sources_available(self) -> bool:
        """Персональный APK собирается только из полных исходников приложения (есть в ZIP с GitHub
        и в установщике). В релизном архиве их нет — там используется готовый универсальный APK."""
        app = self.base_dir / "android_app"
        src = app / "src" / "com" / "pccontrol" / "remote"
        return (self.script.is_file() and (src / "MainActivity.java").is_file()
                and (src / "PcInputClient.java").is_file() and (app / "AndroidManifest.xml").is_file())

    def is_personalized(self, cfg: dict) -> bool:
        try:
            info = json.loads(self.info_file.read_text(encoding="utf-8"))
            return (self.apk_path.is_file() and info.get("fingerprint") == apk_fingerprint(cfg)
                    and abs(float(info.get("apk_mtime", 0)) - self.apk_path.stat().st_mtime) < 2)
        except (OSError, ValueError, TypeError):
            return False

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)

    def mark_running(self):
        with self._lock:
            self.state.update({"state": "running", "message": "", "details": "", "started_at": time.time(), "finished_at": 0})

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def run(self, script_path: Path | None = None) -> tuple:
        """Собирает персональный APK (IP, MAC и пароль этого ПК вшиты). Весь вывод — в консоль панели
        и logs\\apk_build.log. Возвращает (ok, error_code, details)."""
        script_path = script_path or self.script
        build_log = self.logs_dir / "apk_build.log"
        out_lines: list = []
        code = "ERR_APK_BUILD_EXCEPTION"
        ok = False
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["PYTHONNOUSERSITE"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            with open(build_log, "w", encoding="utf-8") as log_f:
                proc = subprocess.Popen(
                    [self._python_cli(), "-u", str(script_path), "--bootstrap-sdk", "--embed-token"],
                    cwd=str(self.base_dir), env=env, shell=False,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                )
                for line in proc.stdout:
                    line_str = line.rstrip()
                    log_f.write(line_str + "\n")
                    log_f.flush()
                    if line_str.strip():
                        out_lines.append(line_str.strip())
                        self._log(line_str.strip())
                        self._set(message=line_str.strip()[-300:])
                proc.wait()
            ok = proc.returncode == 0
            code = "" if ok else f"ERR_APK_BUILD_{proc.returncode}"
            if ok:
                self._log("PC_Control.apk rebuild completed successfully.")
                self._set(message="APK собран и подписан")
                try:
                    self.info_file.write_text(json.dumps({
                        "fingerprint": apk_fingerprint(self._load_config()),
                        "apk_mtime": self.apk_path.stat().st_mtime,
                        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }), encoding="utf-8")
                except (OSError, ValueError):
                    pass
            else:
                self._log(f"PC_Control.apk rebuild failed with exit code {proc.returncode}. Full log: logs\\apk_build.log")
                err_line = next((l for l in reversed(out_lines) if l.startswith("[ERROR]")), "") or \
                    next((l for l in reversed(out_lines) if "error" in l.lower()), "")
                self._set(message=(err_line or f"Сборка APK завершилась с ошибкой (код {proc.returncode})")[-300:])
        except Exception as e:
            self._log(f"Error during APK rebuild: {e}")
            out_lines.append(str(e))
            self._set(message=str(e))
        details = "\n".join(out_lines[-25:])
        self._set(state="ok" if ok else "failed", details=details, finished_at=time.time())
        return ok, code, details
