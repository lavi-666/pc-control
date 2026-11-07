"""
PC Control — Модуль управления серверными процессами (Server Manager).
Обеспечивает запуск, остановку, перезапуск и мониторинг состояния server.py,
watchdog.pyw и wol_relay.py с защитой от гонок и зависших процессов.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0


class ServerManager:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.manual_stop_flag = self.logs_dir / "manual_stop.flag"

    def get_python_executables(self) -> Tuple[Path, Path]:
        """Возвращает (pythonw_path, python_path) для запуска процессов."""
        runtime_dir = self.base_dir / "runtime"
        pythonw = runtime_dir / "pythonw.exe"
        python = runtime_dir / "python.exe"

        if pythonw.is_file() and python.is_file():
            return pythonw, python

        current_exe = Path(sys.executable)
        current_w = current_exe.with_name("pythonw.exe")
        if current_w.is_file():
            return current_w, current_exe
        return current_exe, current_exe

    def is_port_listening(self, host: str, port: int, timeout: float = 0.5) -> bool:
        """Проверяет, открыт ли сокет на указанном хосте и порту."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                return sock.connect_ex((host, port)) == 0
        except Exception:
            return False

    def query_server_health(self, port: int, timeout: float = 1.0) -> Tuple[bool, Dict[str, Any]]:
        """Опрашивает HTTP-эндпоинт /status сервера."""
        url = f"http://127.0.0.1:{port}/status"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PCControl-Manager/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return (data.get("status") == "online", data)
        except Exception:
            return (False, {})

    def get_owned_processes(self) -> List[Any]:
        """Находит все запущенные процессы, принадлежащие данной установке PC Control."""
        try:
            import psutil
        except ImportError:
            return []

        owned = []
        norm_base = str(self.base_dir).lower().rstrip("\\/") + "\\"
        scripts_to_check = {
            (self.base_dir / "server.py").resolve(),
            (self.base_dir / "scripts" / "watchdog.pyw").resolve(),
            (self.base_dir / "scripts" / "wol_relay.py").resolve(),
            (self.base_dir / "tools" / "streamer.exe").resolve(),
        }

        current_pid = os.getpid()

        for proc in psutil.process_iter(["pid", "exe", "cmdline"]):
            if proc.pid == current_pid:
                continue
            try:
                exe = proc.info.get("exe") or ""
                cmdline = proc.info.get("cmdline") or []

                is_owned = False
                if exe and str(Path(exe).resolve()).lower().startswith(norm_base):
                    # Исполняемый файл находится внутри нашей папки
                    is_owned = True
                elif exe and Path(exe).name.lower().startswith("python"):
                    # Проверяем аргументы командной строки
                    for arg in cmdline[1:]:
                        if arg.startswith("-"):
                            continue
                        try:
                            resolved_arg = (Path(proc.cwd()) / arg).resolve()
                            if resolved_arg in scripts_to_check:
                                is_owned = True
                                break
                        except Exception:
                            pass

                if is_owned:
                    owned.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return owned

    def start(self, port: int) -> Tuple[bool, str, str, str]:
        """Запускает server.py и фоновый watchdog.pyw."""
        # 1. Снимаем флаг ручной остановки
        if self.manual_stop_flag.exists():
            try:
                self.manual_stop_flag.unlink()
            except Exception:
                pass

        # 2. Проверяем, не запущен ли сервер уже
        alive, info = self.query_server_health(port, timeout=0.8)
        if alive:
            return True, "ALREADY_RUNNING", "Сервер уже работает", f"Сервер PC Control активен на порту {port}"

        if self.is_port_listening("127.0.0.1", port):
            return False, "PORT_OCCUPIED", "Порт занят", f"Порт {port} уже занят другим процессом. Выберите другой порт в настройках."

        pythonw, python = self.get_python_executables()
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        for k in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(k, None)

        server_script = self.base_dir / "server.py"
        watchdog_script = self.base_dir / "scripts" / "watchdog.pyw"

        try:
            # Запускаем основной сервер
            subprocess.Popen(
                [str(pythonw), "-E", "-s", str(server_script)],
                cwd=str(self.base_dir),
                env=env,
                creationflags=NO_WINDOW,
            )

            # Ожидаем готовности сокета до 15 секунд
            deadline = time.monotonic() + 15
            started = False
            while time.monotonic() < deadline:
                alive, _ = self.query_server_health(port, timeout=0.5)
                if alive:
                    started = True
                    break
                time.sleep(0.3)

            if not started:
                # Если сервер не ответил, проверяем logs/error_log.txt
                err_file = self.logs_dir / "error_log.txt"
                detail = ""
                if err_file.is_file():
                    try:
                        detail = "\n" + err_file.read_text(encoding="utf-8", errors="replace")[-300:]
                    except Exception:
                        pass
                return False, "START_TIMEOUT", "Таймаут запуска", f"Сервер не ответил на порту {port} за 15 секунд.{detail}"

            # Запускаем сторожевой процесс watchdog
            if watchdog_script.is_file():
                try:
                    subprocess.Popen(
                        [str(pythonw), "-E", "-s", str(watchdog_script)],
                        cwd=str(self.base_dir),
                        env=env,
                        creationflags=NO_WINDOW,
                    )
                except Exception:
                    pass

            return True, "OK", "Сервер запущен", f"Сервер успешно запущен на порту {port}"
        except Exception as e:
            return False, "ERROR", "Ошибка запуска", str(e)

    def stop(self, port: int) -> Tuple[bool, str, str, str]:
        """Останавливает сервер и фоновые процессы."""
        # 1. Устанавливаем флаг ручной остановки, чтобы watchdog не перезапустил сервер
        try:
            self.manual_stop_flag.write_text("manual_stop", encoding="ascii")
        except Exception:
            pass

        owned = self.get_owned_processes()
        errors = []

        # 2. Пытаемся корректно завершить процессы
        for proc in owned:
            try:
                proc.terminate()
            except Exception as e:
                errors.append(str(e))

        # Ждем завершения до 5 секунд
        deadline = time.monotonic() + 5
        for proc in owned:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                proc.wait(timeout=remaining)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        # 3. Проверяем, освобождён ли порт
        port_free = not self.is_port_listening("127.0.0.1", port, timeout=0.5)
        if port_free:
            return True, "OK", "Сервер остановлен", "Все процессы сервера успешно остановлены"
        return False, "PORT_STILL_LISTENING", "Порт не освобождён", f"Процессы остановлены, но порт {port} остаётся занятым"

    def restart(self, port: int) -> Tuple[bool, str, str, str]:
        """Перезапускает сервер."""
        self.stop(port)
        time.sleep(1.0)
        return self.start(port)
