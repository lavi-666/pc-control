"""
PC Control — Журналирование действий и ошибок.
"""

import json
import threading
import time
import traceback
from core.config import ERROR_LOG_FILE, LOG_FILE

_log_file_lock = threading.Lock()

# Ротация: раньше журналы росли бесконечно (actions_log.jsonl > 1 МБ, а /history читает его
# целиком на каждый запрос). При превышении лимита оставляем свежий «хвост» файла.
_ACTIONS_MAX_BYTES = 2 * 1024 * 1024
_ERRORS_MAX_BYTES = 1024 * 1024
_KEEP_FRACTION = 0.5
_writes_since_check = {"actions": 0, "errors": 0}


def _trim_file_locked(path, max_bytes: int):
    """Обрезает файл до последних max_bytes*_KEEP_FRACTION байт по границе строки. Вызывать под _log_file_lock."""
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        keep = int(max_bytes * _KEEP_FRACTION)
        with open(path, "rb") as f:
            f.seek(-keep, 2)
            tail = f.read()
        nl = tail.find(b"\n")
        if nl >= 0:
            tail = tail[nl + 1:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(tail)
        tmp.replace(path)
    except Exception:
        pass


def _maybe_rotate_locked(kind: str, path, max_bytes: int):
    _writes_since_check[kind] += 1
    if _writes_since_check[kind] >= 100:
        _writes_since_check[kind] = 0
        _trim_file_locked(path, max_bytes)


def log_action(name: str, extra: dict | None = None):
    entry = {"ts": int(time.time()), "action": name}
    if extra:
        entry.update(extra)
    try:
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with _log_file_lock:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
            _maybe_rotate_locked("actions", LOG_FILE, _ACTIONS_MAX_BYTES)
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
            _maybe_rotate_locked("errors", err_path, _ERRORS_MAX_BYTES)
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
