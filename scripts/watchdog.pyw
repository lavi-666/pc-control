"""
PC Control - Watchdog Supervisor Process.
Monitors server health, performs intelligent restart on failures,
and prevents crash-looping (max 5 restarts within 2.5 minutes).
Respects manual server stops.
"""

import ctypes
import hashlib
import datetime
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "watchdog.log"
FLAG_MANUAL_STOP = LOGS_DIR / "manual_stop.flag"
SERVER_SCRIPT = BASE_DIR / "server.py"

CHECK_INTERVAL_SEC = 30
PING_TIMEOUT_SEC = 10
MAX_CONSECUTIVE_FAILURES = 4
MAX_CRASHES_WINDOW_SEC = 150  # 2.5 minutes
MAX_CRASHES_LIMIT = 5
# Сервер, запущенный недавно, ещё может грузиться (после входа в Windows — до минуты и дольше).
# Раньше сторож через ~25 с считал такой сервер зависшим, убивал и запускал заново — по кругу.
STARTUP_GRACE_SEC = 120
# После серии сбоев сторож раньше завершался навсегда, и сервер оставался выключенным до ручного
# запуска. Теперь он делает паузу и пробует снова.
CRASH_LOOP_COOLDOWN_SEC = 600

MUTEX_NAME = "Local\\PCControlWatchdog_" + hashlib.sha256(str(BASE_DIR).lower().encode("utf-8")).hexdigest()


def _read_server_port() -> int:
    try:
        # utf-8-sig: config.json, сохранённый Блокнотом с BOM, раньше не читался — сторож следил
        # за портом 5000 вместо настоящего и перезапускал работающий сервер по кругу.
        with open(BASE_DIR / "config.json", "r", encoding="utf-8-sig") as f:
            return int(json.load(f).get("port", 5000))
    except Exception:
        return 5000


SERVER_PORT = _read_server_port()
NO_WINDOW = 0x08000000


def log(msg: str):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


_mutex_handle = None


def is_already_running() -> bool:
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return True
    return False


def ping_server() -> tuple[bool, str]:
    global SERVER_PORT
    SERVER_PORT = _read_server_port()
    conn = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", SERVER_PORT, timeout=PING_TIMEOUT_SEC)
        conn.request("GET", "/status")
        resp = conn.getresponse()
        raw = resp.read(512)
        if resp.status == 200:
            try:
                data = json.loads(raw.decode("utf-8", errors="ignore"))
                if data.get("status") == "online" and data.get("instance") == hashlib.sha256(str(BASE_DIR.resolve()).lower().rstrip("\\/").encode("utf-8")).hexdigest():
                    return True, "ok"
            except Exception:
                pass
            return False, "unexpected_health_response"
        return False, f"status_{resp.status}"
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def find_server_pid_on_port(port: int | None = None) -> int | None:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            creationflags=NO_WINDOW,
            text=True,
            timeout=3,
        )
        target = f":{port or SERVER_PORT} "
        for line in out.splitlines():
            if target in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = int(parts[-1])
                    if pid > 0:
                        return pid
    except Exception:
        pass
    return None


def terminate_pid(pid: int):
    try:
        import psutil
        process = psutil.Process(pid)
        cwd = Path(process.cwd())
        if not any((cwd / arg).resolve() == SERVER_SCRIPT.resolve()
                   for arg in process.cmdline()[1:] if not arg.startswith("-")):
            log(f"Refusing to terminate unrelated process {pid}.")
            return
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            creationflags=NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        pass


def wait_for_port_free(port: int | None = None, max_wait: float = 5.0) -> bool:
    port = port or SERVER_PORT
    t0 = time.time()
    while (time.time() - t0) < max_wait:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(0.3)
            s.connect(("127.0.0.1", port))
            s.close()
            time.sleep(0.3)
        except Exception:
            return True
        finally:
            s.close()
    return False


def starting_server_age() -> float | None:
    """Возраст (с) самого молодого процесса server.py этой установки, если он ещё в периоде запуска."""
    try:
        import psutil
        target = SERVER_SCRIPT.resolve()
        youngest = None
        for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                if not (process.info.get("name") or "").lower().startswith("python"):
                    continue
                args = [a for a in (process.info.get("cmdline") or [])[1:] if not a.startswith("-")]
                if not any(Path(a).name == "server.py" for a in args):
                    continue
                cwd = Path(process.cwd())
                if not any((cwd / a).resolve() == target for a in args):
                    continue
                age = time.time() - float(process.info.get("create_time") or 0)
                youngest = age if youngest is None else min(youngest, age)
            except Exception:
                continue
        return youngest if youngest is not None and youngest < STARTUP_GRACE_SEC else None
    except Exception:
        return None


def spawn_server():
    pythonw = BASE_DIR / "runtime" / "pythonw.exe"
    if not pythonw.exists():
        pythonw = BASE_DIR / "venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    # Вывод сервера — в те же журналы, что и при запуске из панели (раньше терялся: причину
    # падения сервера, перезапущенного сторожем, было не узнать).
    out_f = err_f = None
    try:
        out_f = open(LOGS_DIR / "server_stdout.log", "a", encoding="utf-8", errors="replace")
        err_f = open(LOGS_DIR / "server_stderr.log", "a", encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        subprocess.Popen(
            [str(pythonw), "-E", "-s", str(SERVER_SCRIPT)],
            cwd=str(BASE_DIR),
            creationflags=NO_WINDOW,
            close_fds=True,
            stdout=out_f or subprocess.DEVNULL,
            stderr=err_f or subprocess.DEVNULL,
        )
    finally:
        for f in (out_f, err_f):
            try:
                if f:
                    f.close()
            except Exception:
                pass


def boot_time() -> float:
    """Unix time of the last Windows start (GetTickCount64)."""
    try:
        kernel = ctypes.windll.kernel32
        kernel.GetTickCount64.restype = ctypes.c_ulonglong
        return time.time() - kernel.GetTickCount64() / 1000.0
    except Exception:
        return 0.0


def drop_stale_manual_stop_flag() -> None:
    """QA L-3: a «stopped manually» flag from a previous Windows session (e.g. written by an update
    before a reboot) kept the server off after the next logon. Only a Stop in THIS session counts."""
    try:
        if FLAG_MANUAL_STOP.exists() and FLAG_MANUAL_STOP.stat().st_mtime < boot_time():
            FLAG_MANUAL_STOP.unlink()
            log("Removed a manual-stop flag left from before this Windows start.")
    except OSError:
        pass


def server_port_open(timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _read_server_port()), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    if is_already_running():
        return

    drop_stale_manual_stop_flag()
    log("Supervisor started. Server health monitoring active (30s interval).")

    time.sleep(10)

    consecutive_failures = 0
    healthy_streak = 0
    crash_timestamps: list[float] = []
    grace_logged = False

    while True:
        # 1. Check manual stop flag
        if FLAG_MANUAL_STOP.exists():
            log("Manual server stop detected. Supervisor terminating without restart.")
            break

        # 2. Ping server
        ok, msg = ping_server()
        if ok:
            consecutive_failures = 0
            grace_logged = False
            healthy_streak += 1
            if healthy_streak >= 2 and crash_timestamps:
                crash_timestamps.clear()
            for i in range(CHECK_INTERVAL_SEC):
                if FLAG_MANUAL_STOP.exists():
                    break
                # QA L-15: notice a dead server within seconds, not after the next 30-s check
                if i % 3 == 2 and not server_port_open():
                    break
                time.sleep(1)
            continue

        healthy_streak = 0
        age = starting_server_age()
        if age is not None:
            # Сервер ещё запускается — это не сбой; ждём, не трогая его.
            if not grace_logged:
                log(f"Server process is still starting ({int(age)} s old); waiting up to {STARTUP_GRACE_SEC} s.")
                grace_logged = True
            consecutive_failures = 0
            time.sleep(5)
            continue
        consecutive_failures += 1
        if find_server_pid_on_port() is None and not server_port_open():
            # QA L-15: no server process at all (crashed / killed) - restart now instead of after
            # 4 more failed checks (~54 s before).
            consecutive_failures = MAX_CONSECUTIVE_FAILURES
        log(f"Health check {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES} failed: {msg}")

        if consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            time.sleep(5)
            continue

        # 3. Server failed 2 consecutive checks - prepare restart
        if FLAG_MANUAL_STOP.exists():
            log("Server stopped manually. Cancelling restart.")
            break

        now = time.time()
        crash_timestamps = [t for t in crash_timestamps if (now - t) < MAX_CRASHES_WINDOW_SEC]
        crash_timestamps.append(now)

        if len(crash_timestamps) >= MAX_CRASHES_LIMIT:
            log(
                f"CRITICAL ERROR: {len(crash_timestamps)} consecutive crashes detected within 2.5 minutes. "
                f"Pausing restarts for {CRASH_LOOP_COOLDOWN_SEC // 60} minutes to prevent a crash-loop."
            )
            crash_timestamps.clear()
            consecutive_failures = 0
            for _ in range(CRASH_LOOP_COOLDOWN_SEC):
                if FLAG_MANUAL_STOP.exists():
                    break
                time.sleep(1)
            continue

        # Панель или autostart сейчас запускают сервер — не запускаем второй параллельно
        lock = try_acquire_start_lock()
        if lock is None:
            log("Another PC Control process is starting the server right now - not restarting it.")
            crash_timestamps.pop()  # это не сбой сервера
            consecutive_failures = 0
            time.sleep(5)
            continue
        try:
            if ping_server()[0] or starting_server_age() is not None:
                crash_timestamps.pop()  # пока проверяли, сервер запустил другой процесс
                consecutive_failures = 0
                continue
            # Ручная остановка могла прийти, пока мы проверяли сервер (раньше сторож запускал
            # сервер уже после «Остановить»)
            if FLAG_MANUAL_STOP.exists():
                log("Server stopped manually. Cancelling restart.")
                break
            log(f"Initiating smart server restart (crash #{len(crash_timestamps)} within 2.5 min)...")
            restart_server()
        finally:
            release_start_lock(lock)
        consecutive_failures = 0
        time.sleep(8)


def is_own_server_pid(pid: int) -> bool:
    """The process is THIS installation's server.py (never terminate another program)."""
    try:
        import psutil
        cmd = " ".join(psutil.Process(pid).cmdline()).lower()
        return str(SERVER_SCRIPT).lower() in cmd
    except Exception:
        return False


def start_via_panel_logic():
    """QA L-15: the port is held by ANOTHER program. The panel's start logic picks a free port (and
    saves it), so the server does not crash on the busy port over and over."""
    global SERVER_PORT
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        from scripts.control_panel import _start_server_process_locked
        ok, code, title, details = _start_server_process_locked(clear_manual_stop=False)
        log(f"Started through the panel logic: ok={ok} {code} {title} - {' '.join(str(details).split())[:300]}")
    except Exception as e:
        log(f"Could not start through the panel logic: {e}")
    SERVER_PORT = _read_server_port()


def restart_server():
    old_pid = find_server_pid_on_port()
    if old_pid and not is_own_server_pid(old_pid):
        log(f"Port {SERVER_PORT} is used by another program (PID {old_pid}) - not touching it; "
            f"starting the server on a free port.")
        if FLAG_MANUAL_STOP.exists():
            log("Server stopped manually. Cancelling restart.")
            return
        start_via_panel_logic()
        return
    if old_pid:
        log(f"Terminating hanging server process on port {SERVER_PORT} (PID {old_pid}).")
        terminate_pid(old_pid)

    if not wait_for_port_free(SERVER_PORT, max_wait=5.0):
        log(f"Warning: Port {SERVER_PORT} did not free up in time, retrying cleanup.")
        old_pid = find_server_pid_on_port()
        if old_pid and is_own_server_pid(old_pid):
            terminate_pid(old_pid)
        time.sleep(1.0)

    if FLAG_MANUAL_STOP.exists():  # «Остановить» нажали во время очистки — не запускаем
        log("Server stopped manually. Cancelling restart.")
        return
    try:
        spawn_server()
        log("New server.py instance launched.")
    except Exception as e:
        # Сбой запуска не должен завершать самого сторожа — попробуем на следующем круге.
        log(f"Could not launch server.py: {e}")


def start_lock_name() -> str:
    """Тот же мьютекс «запуск сервера», что и в control_panel.start_lock_name()."""
    key = str(BASE_DIR).lower()
    data_dir = os.environ.get("PC_CONTROL_DATA_DIR") or ""
    if data_dir:
        key += "|" + os.path.normcase(os.path.abspath(data_dir))
    return "Local\\PCControlServerStart_" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def try_acquire_start_lock(wait_ms: int = 0):
    """Хэндл захваченного мьютекса; None — его держит другой процесс. Без kernel32 — False (работаем как раньше)."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.WaitForSingleObject.restype = ctypes.c_uint32
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.CreateMutexW(None, False, start_lock_name())
        if not h:
            return False
        if k32.WaitForSingleObject(h, wait_ms) in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED
            return h
        k32.CloseHandle(h)
        return None
    except Exception:
        return False


def release_start_lock(handle) -> None:
    if not handle:
        return
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.ReleaseMutex(handle)
        k32.CloseHandle(handle)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pythonw без консоли: иначе причина остановки сторожа терялась бы
        import traceback
        log(f"Supervisor stopped by an unexpected error: {exc}\n{traceback.format_exc()}")
