"""
PC Control — Модуль управления сборкой Android APK (APK Manager).
Обеспечивает асинхронную сборку APK в фоновом потоке, проверку готовности
портативного SDK и отдачу статуса без блокировки веб-интерфейса лаунчера.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class ApkManager:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.apk_path = self.base_dir / "PC_Control.apk"
        self.script_path = self.base_dir / "scripts" / "build_apk.py"
        self._lock = threading.Lock()
        self._is_building = False
        self._status: Dict[str, Any] = {
            "is_building": False,
            "phase": "idle",
            "percent": 0,
            "message": "Готов к сборке",
            "error": None,
            "last_built_at": None,
        }

    def is_apk_available(self) -> bool:
        """Проверяет существование собранного APK-файла."""
        return self.apk_path.is_file() and self.apk_path.stat().st_size > 10000

    def get_apk_info(self) -> Dict[str, Any]:
        """Возвращает метаданные существующего APK."""
        if not self.is_apk_available():
            return {
                "available": False,
                "size_bytes": 0,
                "size_formatted": "0 KB",
                "mtime": None,
            }
        st = self.apk_path.stat()
        kb = st.st_size // 1024
        return {
            "available": True,
            "size_bytes": st.st_size,
            "size_formatted": f"{kb} KB",
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        }

    def get_status(self) -> Dict[str, Any]:
        """Возвращает текущий прогресс сборки."""
        with self._lock:
            info = self.get_apk_info()
            res = dict(self._status)
            res["apk_info"] = info
            return res

    def start_build_async(
        self,
        embed_token: bool = True,
        lan_ip: Optional[str] = None,
        mac_address: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Запускает сборку APK в отдельном потоке."""
        if not self.script_path.is_file():
            return False, "Скрипт сборки scripts/build_apk.py не найден."

        with self._lock:
            if self._is_building:
                return False, "Сборка APK уже выполняется."
            self._is_building = True
            self._status = {
                "is_building": True,
                "phase": "starting",
                "percent": 5,
                "message": "Подготовка сборочного окружения...",
                "error": None,
                "last_built_at": None,
            }

        thread = threading.Thread(
            target=self._build_worker,
            args=(embed_token, lan_ip, mac_address, token),
            daemon=True,
        )
        thread.start()
        return True, "Сборка APK запущена в фоновом режиме."

    def _build_worker(
        self,
        embed_token: bool,
        lan_ip: Optional[str],
        mac_address: Optional[str],
        token: Optional[str],
    ) -> None:
        try:
            with self._lock:
                self._status["phase"] = "sdk_check"
                self._status["percent"] = 15
                self._status["message"] = "Проверка наличия Android SDK и инструментов..."

            python_exe = sys.executable
            runtime_python = self.base_dir / "runtime" / "python.exe"
            if runtime_python.is_file():
                python_exe = str(runtime_python)

            cmd = [python_exe, str(self.script_path), "--bootstrap-sdk"]
            if embed_token:
                cmd.append("--embed-token")
            if lan_ip:
                cmd.extend(["--lan", str(lan_ip)])
            if mac_address:
                cmd.extend(["--mac", str(mac_address)])
            if token:
                cmd.extend(["--token", str(token)])

            with self._lock:
                self._status["phase"] = "compiling"
                self._status["percent"] = 40
                self._status["message"] = "Компиляция Java, DEX и упаковка ресурсов..."

            env = os.environ.copy()
            env["PYTHONNOUSERSITE"] = "1"

            proc = subprocess.run(
                cmd,
                cwd=str(self.base_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                creationflags=NO_WINDOW,
            )

            if proc.returncode != 0:
                err_msg = (proc.stderr or proc.stdout or "Неизвестная ошибка сборщика").strip()
                lines = err_msg.splitlines()
                short_err = lines[-1] if lines else "Ошибка сборки"
                with self._lock:
                    self._status["is_building"] = False
                    self._status["phase"] = "failed"
                    self._status["percent"] = 0
                    self._status["message"] = "Сборка завершилась ошибкой"
                    self._status["error"] = short_err
                return

            with self._lock:
                self._status["is_building"] = False
                self._status["phase"] = "complete"
                self._status["percent"] = 100
                self._status["message"] = "APK успешно скомпилирован и подписан!"
                self._status["error"] = None
                self._status["last_built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        except Exception as ex:
            with self._lock:
                self._status["is_building"] = False
                self._status["phase"] = "failed"
                self._status["percent"] = 0
                self._status["message"] = "Ошибка процесса сборки"
                self._status["error"] = str(ex)
        finally:
            with self._lock:
                self._is_building = False
