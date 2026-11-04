"""
PC Control - Watchdog Supervisor Process.
Monitors server health, performs intelligent restart on failures,
and prevents crash-looping (max 5 restarts within 2.5 minutes).
Respects manual server stops.
"""

import ctypes
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
PING_TIMEOUT_SEC = 3
MAX_CONSECUTIVE_FAILURES = 2
MAX_CRASHES_WINDOW_SEC = 150  # 2.5 minutes
MAX_CRASHES_LIMIT = 5

MUTEX_NAME = "Local\\PCControlWatchdogMutex"


def _read_server_port() -> int:
    try:
        with open(BASE_DIR / "config.json", "r", encoding="utf-8") as f:
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
    conn = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", SERVER_PORT, timeout=PING_TIMEOUT_SEC)
        conn.request("GET", "/status")
        resp = conn.getresponse()
        raw = resp.read(512)
        if resp.status == 200:
            try:
                data = json.loads(raw.decode("utf-8", errors="ignore"))
                if data.get("status") == "online":
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


def spawn_server():
    pythonw = BASE_DIR / "venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    subprocess.Popen(
        [str(pythonw), str(SERVER_SCRIPT)],
        cwd=str(BASE_DIR),
        creationflags=NO_WINDOW,
        close_fds=True,
    )


def main():
    if is_already_running():
        return

    log("Supervisor started. Server health monitoring active (30s interval).")

    time.sleep(10)

    consecutive_failures = 0
    healthy_streak = 0
    crash_timestamps: list[float] = []

    while True:
        # 1. Check manual stop flag
        if FLAG_MANUAL_STOP.exists():
            log("Manual server stop detected. Supervisor terminating without restart.")
            break

        # 2. Ping server
        ok, msg = ping_server()
        if ok:
            consecutive_failures = 0
            healthy_streak += 1
            if healthy_streak >= 2 and crash_timestamps:
                crash_timestamps.clear()
            for _ in range(CHECK_INTERVAL_SEC):
                if FLAG_MANUAL_STOP.exists():
                    break
                time.sleep(1)
            continue

        healthy_streak = 0
        consecutive_failures += 1
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
                "Supervisor shutting down to prevent crash-loop."
            )
            break

        log(f"Initiating smart server restart (crash #{len(crash_timestamps)} within 2.5 min)...")

        old_pid = find_server_pid_on_port()
        if old_pid:
            log(f"Terminating hanging server process on port {SERVER_PORT} (PID {old_pid}).")
            terminate_pid(old_pid)

        if not wait_for_port_free(SERVER_PORT, max_wait=5.0):
            log(f"Warning: Port {SERVER_PORT} did not free up in time, retrying cleanup.")
            old_pid = find_server_pid_on_port()
            if old_pid:
                terminate_pid(old_pid)
            time.sleep(1.0)

        spawn_server()
        log("New server.py instance launched.")

        consecutive_failures = 0
        time.sleep(8)


if __name__ == "__main__":
    main()
