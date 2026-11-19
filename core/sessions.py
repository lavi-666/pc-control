"""Per-device session tokens (plan 5.2, QA A-10).

Before, the password was the only key and it was valid forever on every phone/browser that ever
logged in. Now every login / QR pairing gets its own token:

    pcs1_<43 random url-safe chars>

* Only sha256(token) is stored, in DATA_DIR/logs/sessions.json (logs/ survives updates and the
  uninstaller's "keep settings"), under an inter-process lock: the control panel (port 5055)
  lists and revokes sessions while the server runs.
* A session expires after IDLE_EXPIRY_DAYS without use; last_seen is written at most once a minute.
* Revoked / expired sessions are refused; open streams of a revoked session are closed
  (input stream sockets, H.264 / MJPEG / audio generators — see on_revoked / is_revoked).
* The password keeps working as before (old APKs, scripts) while config.json
  "legacy_password_auth" is not false (default: true).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from core.config import LOGS_DIR, InterProcessRLock

PREFIX = "pcs1_"
IDLE_EXPIRY_DAYS = 180
IDLE_EXPIRY = IDLE_EXPIRY_DAYS * 86400
TOUCH_INTERVAL = 60        # s between last_seen writes for one session
MAX_SESSIONS = 200         # oldest revoked / expired entries are pruned beyond this
NAME_MAX = 64

_lock = threading.RLock()
_file_lock = InterProcessRLock(LOGS_DIR / "sessions.lock")
_cache = {"mtime": None, "size": None, "data": None, "checked": 0.0}
_listeners: list = []
_known_revoked: set[str] = set()
_watcher_started = False


def sessions_file() -> Path:
    return LOGS_DIR / "sessions.json"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _empty() -> dict:
    return {"schema": 1, "sessions": []}


def _read_disk() -> dict:
    path = sessions_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sessions"), list):
            return data
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        pass
    return _empty()


def _write_disk(data: dict) -> None:
    path = sessions_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)
    _remember(data)


def _stat():
    try:
        st = sessions_file().stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None, None


def _remember(data: dict) -> None:
    mtime, size = _stat()
    with _lock:
        _cache.update(mtime=mtime, size=size, data=data, checked=time.monotonic())


def _load(max_age: float = 1.0) -> dict:
    """Cached copy; the file is re-read when it changed (the panel may have revoked something)."""
    with _lock:
        if _cache["data"] is not None and time.monotonic() - _cache["checked"] < max_age:
            return _cache["data"]
    mtime, size = _stat()
    with _lock:
        if _cache["data"] is not None and (mtime, size) == (_cache["mtime"], _cache["size"]):
            _cache["checked"] = time.monotonic()
            return _cache["data"]
    data = _read_disk()
    with _lock:
        _cache.update(mtime=mtime, size=size, data=data, checked=time.monotonic())
    return data


def _alive(rec: dict, now: float) -> bool:
    return not rec.get("revoked") and now - float(rec.get("last_seen") or rec.get("created") or 0) < IDLE_EXPIRY


def _prune(sessions: list, now: float) -> list:
    if len(sessions) <= MAX_SESSIONS:
        return sessions
    dead = sorted((s for s in sessions if not _alive(s, now)), key=lambda s: float(s.get("last_seen") or 0))
    drop = {id(s) for s in dead[:len(sessions) - MAX_SESSIONS]}
    kept = [s for s in sessions if id(s) not in drop]
    if len(kept) > MAX_SESSIONS:  # still too many live ones: drop the least recently used
        kept.sort(key=lambda s: float(s.get("last_seen") or 0))
        kept = kept[len(kept) - MAX_SESSIONS:]
    return kept


def clean_name(name) -> str:
    text = "".join(ch for ch in str(name or "") if ch.isprintable()).strip()
    return text[:NAME_MAX] or "Device"


def create(name: str = "", ip: str = "", kind: str = "password") -> tuple[str, dict]:
    """New session -> (token, public record). The token itself is never stored."""
    token = PREFIX + secrets.token_urlsafe(32)
    now = time.time()
    rec = {
        "id": secrets.token_hex(8),
        "hash": _hash(token),
        "name": clean_name(name),
        "kind": kind if kind in ("password", "pairing") else "password",
        "created": now,
        "last_seen": now,
        "last_ip": str(ip or "")[:64],
        "revoked": False,
    }
    with _file_lock:
        data = _read_disk()
        data["sessions"] = _prune(data["sessions"] + [rec], now)
        _write_disk(data)
    return token, public(rec)


def lookup(token: str, ip: str = "") -> dict | None:
    """Valid (not revoked, not expired) session for this token, else None. Updates last_seen."""
    if not isinstance(token, str) or not token.startswith(PREFIX) or len(token) > 128:
        return None
    h = _hash(token)
    now = time.time()
    rec = None
    for s in _load()["sessions"]:
        if secrets.compare_digest(str(s.get("hash", "")), h):
            rec = s
            break
    if rec is None or not _alive(rec, now):
        return None
    if now - float(rec.get("last_seen") or 0) >= TOUCH_INTERVAL or (ip and rec.get("last_ip") != ip):
        try:
            _touch(rec["id"], ip, now)
        except Exception:
            pass
    return rec


def _touch(sid: str, ip: str, now: float) -> None:
    with _file_lock:
        data = _read_disk()
        for s in data["sessions"]:
            if s.get("id") == sid:
                s["last_seen"] = now
                if ip:
                    s["last_ip"] = str(ip)[:64]
                break
        else:
            return
        _write_disk(data)


def public(rec: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    last = float(rec.get("last_seen") or rec.get("created") or 0)
    state = "revoked" if rec.get("revoked") else ("expired" if now - last >= IDLE_EXPIRY else "active")
    return {
        "id": rec.get("id", ""),
        "name": rec.get("name", ""),
        "kind": rec.get("kind", "password"),
        "created": int(float(rec.get("created") or 0)),
        "last_seen": int(last),
        "last_ip": rec.get("last_ip", ""),
        "state": state,
        "expires": int(last + IDLE_EXPIRY),
    }


def list_sessions(include_dead: bool = False) -> list[dict]:
    now = time.time()
    out = [public(s, now) for s in _load(max_age=0)["sessions"]]
    if not include_dead:
        out = [s for s in out if s["state"] == "active"]
    out.sort(key=lambda s: s["last_seen"], reverse=True)
    return out


def revoke(sid: str | None = None, all_sessions: bool = False) -> int:
    """Revokes one session (by id) or all. Returns how many were revoked now."""
    changed = []
    with _file_lock:
        data = _read_disk()
        for s in data["sessions"]:
            if not s.get("revoked") and (all_sessions or s.get("id") == sid):
                s["revoked"] = True
                s["revoked_at"] = time.time()
                changed.append(s.get("id"))
        if changed:
            _write_disk(data)
    if changed:
        _notify(set(changed))
    return len(changed)


def is_revoked(sid: str | None) -> bool:
    """True when this session id was revoked or expired (streams poll it between chunks)."""
    if not sid:
        return False
    now = time.time()
    for s in _load()["sessions"]:
        if s.get("id") == sid:
            return not _alive(s, now)
    return True  # unknown id (file deleted / pruned) = no longer valid


# ---------- revocation listeners (open input streams are closed through them) ----------
def on_revoked(callback) -> None:
    """callback(set_of_session_ids) after a revocation (this process, or the panel's via the file)."""
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def _notify(ids: set) -> None:
    with _lock:
        _known_revoked.update(ids)
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(set(ids))
        except Exception:
            pass


def _revoked_ids() -> set:
    now = time.time()
    return {s.get("id") for s in _load(max_age=0)["sessions"] if not _alive(s, now)}


def start_watcher(interval: float = 2.0) -> None:
    """Background thread of the server: notices revocations made by the control panel."""
    global _watcher_started
    with _lock:
        if _watcher_started:
            return
        _watcher_started = True
        _known_revoked.update(_revoked_ids())

    def loop():
        while True:
            time.sleep(interval)
            try:
                dead = _revoked_ids()
                with _lock:
                    new = dead - _known_revoked
                if new:
                    _notify(new)
            except Exception:
                pass

    threading.Thread(target=loop, name="session-watcher", daemon=True).start()


def revocable(iterable, sid: str | None, check_every: float = 0.5):
    """Wraps a streaming response body: stops it once the session is revoked."""
    if not sid:
        yield from iterable
        return
    it = iter(iterable)
    last = 0.0
    try:
        for chunk in it:
            now = time.monotonic()
            if now - last >= check_every:
                last = now
                if is_revoked(sid):
                    break
            yield chunk
    finally:
        close = getattr(it, "close", None)
        if close is not None:
            close()


def _reset_for_tests() -> None:
    global _watcher_started
    with _lock:
        _cache.update(mtime=None, size=None, data=None, checked=0.0)
        _known_revoked.clear()
