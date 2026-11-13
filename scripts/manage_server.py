"""Shared CLI entry point for legacy start/stop shortcuts.

Действие `autostart` — для запуска при входе в Windows (планировщик заданий, ярлык автозагрузки,
start_server.bat). Сразу после входа Windows ещё «просыпается»: антивирус проверяет файлы, сеть
поднимается, импорт библиотек занимает десятки секунд. Раньше единственная попытка `start` в такой
момент завершалась ошибкой (проверка библиотек не успевала → «библиотеки не установлены») и сервер
оставался выключенным до ручного запуска. Теперь autostart ждёт готовности, повторяет попытки с
нарастающей паузой несколько минут и записывает каждую попытку с причиной в logs/autostart.log.
"""
import argparse
import ctypes
import hashlib
import os
import sys
import time
from pathlib import Path

try:
    from scripts.control_panel import (BASE_DIR, start_server_process, stop_server_process, restart_server_process,
                                       clean_browser_profiles)
    from scripts import control_panel as _panel
except ImportError:
    from control_panel import BASE_DIR, start_server_process, stop_server_process, restart_server_process, clean_browser_profiles
    import control_panel as _panel

AUTOSTART_LOG = BASE_DIR / "logs" / "autostart.log"
AUTOSTART_TOTAL_SEC = 10 * 60          # сколько всего пытаться после входа в Windows
AUTOSTART_BACKOFF = (10, 20, 30, 60)   # паузы между попытками (последняя повторяется)
AUTOSTART_STARTUP_TIMEOUT = 60.0       # ожидание ответа сервера в одной попытке («холодный» старт дольше обычного)
AUTOSTART_DEPS_TIMEOUT = 120.0         # проверка библиотек на «холодном» старте
AUTOSTART_BOOT_WAIT = 120.0            # сколько ещё ждать уже запущенный, но не ответивший сервер
AUTOSTART_NETWORK_WAIT = 60.0          # ожидание сетевого адреса (сервер слушает 0.0.0.0, поэтому не бесконечно)
MAX_DEFINITE_DEPS_FAILURES = 2         # библиотек точно нет — повторять бессмысленно


def stop_owned_helpers():
    """Terminate only helpers whose executable/script belongs to this copy."""
    import psutil
    failures = []
    owned_executables = {(BASE_DIR / 'Launcher.exe').resolve(), (BASE_DIR / 'tools/streamer.exe').resolve(),
                         (BASE_DIR / 'tools/media_helper.exe').resolve()}
    panel_script = (BASE_DIR / 'scripts/control_panel.py').resolve()
    for process in psutil.process_iter(['pid', 'exe', 'cmdline']):
        try:
            executable = process.info.get('exe')
            command = process.info.get('cmdline') or []
            owned = bool(executable and Path(executable).resolve() in owned_executables)
            if not owned and executable and Path(executable).name.lower().startswith('python'):
                cwd = Path(process.cwd())
                owned = any((cwd / argument).resolve() == panel_script for argument in command[1:] if not argument.startswith('-'))
            if owned:
                process.terminate()
                process.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        except (psutil.AccessDenied, psutil.TimeoutExpired) as error:
            failures.append(str(error))
    return not failures, '', 'Helpers', '\n'.join(failures) or 'Stopped helpers belonging to this installation'


# ---------------------------------------------------------------------------------------------
# autostart
# ---------------------------------------------------------------------------------------------

def autostart_log(message: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        AUTOSTART_LOG.parent.mkdir(parents=True, exist_ok=True)
        if AUTOSTART_LOG.exists() and AUTOSTART_LOG.stat().st_size > 512 * 1024:
            AUTOSTART_LOG.replace(AUTOSTART_LOG.with_suffix(".log.1"))
        with open(AUTOSTART_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _uptime_sec() -> float | None:
    try:
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:
        return None


_autostart_mutex = None


def _acquire_autostart_mutex() -> bool:
    """Один autostart на установку: задание планировщика и ярлык автозагрузки могут сработать вместе."""
    global _autostart_mutex
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        name = "Local\\PCControlAutostart_" + hashlib.sha256(str(BASE_DIR).lower().encode("utf-8")).hexdigest()
        _autostart_mutex = kernel32.CreateMutexW(None, False, name)
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _runtime_ready() -> tuple[bool, str]:
    """Интерпретатор, которым запускается сервер, на месте и отвечает."""
    import subprocess
    pyw = Path(_panel.get_pythonw_path())
    if not pyw.is_file():
        return False, f"interpreter not found: {pyw}"
    cli = _panel.get_python_cli_path()
    try:
        result = subprocess.run([cli, "-I", "-c", "pass"], capture_output=True, timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            return False, f"interpreter exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "interpreter did not start within 60 s"
    except OSError as e:
        return False, f"interpreter could not be started: {e}"
    return True, ""


def _network_address() -> str:
    try:
        ip = _panel.get_local_ip()
    except Exception:
        ip = ""
    return ip if ip and not ip.startswith("127.") and not ip.startswith("169.254.") else ""


def _manual_stop_since(started_wall: float) -> bool:
    """Пользователь остановил сервер после начала autostart (флаг ручной остановки моложе старта).
    Флаг, оставшийся с прошлого сеанса Windows, не мешает автозапуску."""
    try:
        flag = _panel.LOGS_DIR / "manual_stop.flag"
        return flag.exists() and flag.stat().st_mtime >= started_wall - 1.0
    except OSError:
        return False


def _wait_until(predicate, timeout: float, sleep, clock, step: float = 2.0) -> bool:
    deadline = clock() + timeout
    while True:
        if predicate():
            return True
        if clock() >= deadline:
            return False
        sleep(step)


def autostart(total_sec: float = AUTOSTART_TOTAL_SEC, sleep=time.sleep, clock=time.monotonic) -> int:
    """Запуск сервера при входе в Windows с ожиданием готовности и повторами. Код возврата 0 = сервер отвечает."""
    if not _acquire_autostart_mutex():
        autostart_log("Autostart: another autostart of this installation is already running - exiting.")
        return 0
    uptime = _uptime_sec()
    autostart_log(f"Autostart: begin (pid {os.getpid()}, user {os.environ.get('USERNAME', '?')}, "
                  f"Windows uptime {int(uptime) if uptime is not None else '?'} s, folder {BASE_DIR})")
    deadline = clock() + total_sec
    started_wall = time.time()

    # 1. Встроенный Python готов (после перезагрузки антивирус может держать файлы).
    ready, reason = _runtime_ready()
    while not ready and clock() < deadline:
        autostart_log(f"Autostart: Python runtime is not ready yet ({reason}); waiting 10 s.")
        sleep(10)
        ready, reason = _runtime_ready()
    if not ready:
        autostart_log(f"Autostart: FAILED - Python runtime is not usable: {reason}")
        return 1

    # 2. Сеть: ждём адрес ограниченное время (сервер слушает все адреса и без него).
    if _panel.is_server_running():
        autostart_log("Autostart: the server is already running and answering - nothing to do.")
        _panel.ensure_watchdog_running()
        return 0
    ip = _network_address()
    if not ip:
        autostart_log(f"Autostart: no network address yet; waiting up to {int(AUTOSTART_NETWORK_WAIT)} s.")
        _wait_until(lambda: bool(_network_address()), min(AUTOSTART_NETWORK_WAIT, max(0.0, deadline - clock())),
                    sleep, clock)
        ip = _network_address()
    autostart_log(f"Autostart: network address: {ip or 'none (starting anyway; the server listens on all addresses)'}")

    # 3. Попытки запуска с нарастающей паузой.
    attempt = 0
    definite_deps_failures = 0
    last_reason = ""
    while True:
        if _manual_stop_since(started_wall):
            # «Остановить» в панели во время повторов: раньше следующая попытка снова запускала сервер
            autostart_log("Autostart: the server was stopped manually while autostart was retrying - giving up.")
            return 0
        if _panel.is_server_running():
            autostart_log("Autostart: OK - the server is answering.")
            _panel.ensure_watchdog_running()
            return 0
        if _panel.owned_script_pids("server.py"):
            # Сервер уже запускается (прошлая попытка или watchdog): не убиваем его, а ждём ответа.
            autostart_log(f"Autostart: a server process is already starting; waiting up to {int(AUTOSTART_BOOT_WAIT)} s for it.")
            if _wait_until(_panel.is_server_running, min(AUTOSTART_BOOT_WAIT, max(0.0, deadline - clock())), sleep, clock):
                autostart_log("Autostart: OK - the server finished starting and is answering.")
                _panel.ensure_watchdog_running()
                return 0
            last_reason = "a server process was running but did not answer"
            autostart_log(f"Autostart: {last_reason}; it will be restarted.")
        if clock() >= deadline:
            break

        attempt += 1
        try:
            ok, code, title, details = start_server_process(startup_timeout=AUTOSTART_STARTUP_TIMEOUT,
                                                            deps_timeout=AUTOSTART_DEPS_TIMEOUT,
                                                            clear_manual_stop=False)
        except Exception as e:  # сбой самой попытки не должен прерывать автозапуск
            ok, code, title, details = False, "ERR_EXCEPTION", type(e).__name__, str(e)
        one_line = " ".join(str(details).split())[:400]
        if ok:
            autostart_log(f"Autostart: attempt {attempt}: OK - {one_line}")
            return 0
        last_reason = f"{code}: {title} - {one_line}"
        autostart_log(f"Autostart: attempt {attempt} failed: {last_reason}")

        if code == "ERR_STARTUP_TIMEOUT":
            # Процесс жив и запускается — ждём, а не запускаем второй.
            if _wait_until(_panel.is_server_running, min(AUTOSTART_BOOT_WAIT, max(0.0, deadline - clock())), sleep, clock):
                autostart_log("Autostart: OK - the server finished starting and is answering.")
                return 0
        elif code == "ERR_PYTHON_DEPS_MISSING":
            definite_deps_failures += 1
            if definite_deps_failures >= MAX_DEFINITE_DEPS_FAILURES:
                autostart_log("Autostart: FAILED - required Python libraries are missing. "
                              "Open PC Control (Launcher.exe) and press Install.")
                return 1

        if clock() >= deadline:
            break
        if _manual_stop_since(started_wall):
            autostart_log("Autostart: the server was stopped manually while autostart was retrying - giving up.")
            return 0
        pause = AUTOSTART_BACKOFF[min(attempt - 1, len(AUTOSTART_BACKOFF) - 1)]
        pause = min(pause, max(0.0, deadline - clock()))
        autostart_log(f"Autostart: next attempt in {int(pause)} s.")
        sleep(pause)

    # Не получилось за отведённое время: оставляем сторожа — он продолжит попытки сам.
    if _manual_stop_since(started_wall):  # QA L-2: Stop pressed meanwhile — no watchdog
        autostart_log("Autostart: the server was stopped manually - not starting the watchdog.")
        return 0
    watchdog = _panel.ensure_watchdog_running()
    autostart_log(f"Autostart: FAILED after {attempt} attempt(s): {last_reason or 'unknown reason'}. "
                  + ("The watchdog keeps trying in the background." if watchdog else "The watchdog could not be started."))
    return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "restart", "stop-all", "clean-profiles", "autostart"))
    args = parser.parse_args()
    if args.action == 'autostart':
        return autostart()
    if args.action == 'clean-profiles':
        result = clean_browser_profiles()
        print(result['message'])
        return 0 if result['ok'] else 1
    if args.action == 'stop-all':
        result = stop_server_process()
        if not result[0]:
            print(result[3])
            return 1
        operation = stop_owned_helpers
    else:
        operation = {"start": start_server_process, "stop": stop_server_process,
                     "restart": restart_server_process}[args.action]
    ok, code, title, details = operation()
    print(f"{title}: {details}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
