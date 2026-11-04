"""
PC Control — Журналирование действий и ошибок.
"""

import json
import threading
import time
import traceback
from core.config import ERROR_LOG_FILE, LOG_FILE

_log_file_lock = threading.Lock()

def log_action(name: str, extra: dict | None = None):
    entry = {"ts": int(time.time()), "action": name}
    if extra:
        entry.update(extra)
    try:
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with _log_file_lock:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        log_error("log_action", e)


def log_error(context: str, exc: Exception):
    """Пишет полный traceback в error_log.txt."""
    err_path = ERROR_LOG_FILE
    try:
        with _log_file_lock:
            with open(err_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} [{context}] ---\n")
                f.write(traceback.format_exc())
    except Exception:
        pass


def get_history(limit: int = 500) -> list:
    if not LOG_FILE.exists() or limit <= 0:
        return []
    try:
        with _log_file_lock:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
    except Exception:
        return []
    entries = []
    for l in lines[-limit:]:
        l_str = l.strip()
        if l_str:
            try:
                entries.append(json.loads(l_str))
            except Exception:
                pass
    return list(reversed(entries))
