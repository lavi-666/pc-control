"""Server identity proof for automatic route selection in the app (USB / tethering / LAN / Tailscale).

The phone must never send the saved password to an address before it knows that address is the
same PC Control server it is paired with (a deep link, a stale DHCP address, another app listening
on 127.0.0.1 on the phone, another PC on the cable). The app asks GET /status?nonce=<random> WITHOUT
the password; this server answers with

    proof = HMAC-SHA256(route_key, "pcc-route|<nonce>|<instance>")

route_key is NOT the password: it is HMAC(random secret of this installation, password), handed to
the app only after it has authenticated (GET /api/route/key). So the proof cannot be used to
brute-force the password offline, it changes when the password changes, and only a client that
already knows the password could have learned it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
from pathlib import Path

from core.config import BASE_DIR, LOGS_DIR, get_auth_token

_NONCE_RE = re.compile(r"^[0-9a-fA-F]{16,128}$")
_lock = threading.Lock()
_secret_cache: bytes | None = None


def instance_id(base_dir: Path | None = None) -> str:
    """Same value /status has always reported as "instance" (sha256 of the install folder)."""
    root = (base_dir or BASE_DIR).resolve()
    return hashlib.sha256(str(root).lower().rstrip("\\/").encode("utf-8")).hexdigest()


def _secret_file() -> Path:
    # logs/ is per-installation runtime data that updates keep (like config.lock).
    return LOGS_DIR / "route_secret.key"


def _load_secret() -> bytes:
    global _secret_cache
    with _lock:
        if _secret_cache is not None:
            return _secret_cache
        path = _secret_file()
        try:
            raw = path.read_text(encoding="ascii").strip()
            if re.fullmatch(r"[0-9a-f]{64}", raw):
                _secret_cache = bytes.fromhex(raw)
                return _secret_cache
        except (OSError, UnicodeError):
            pass
        value = secrets.token_bytes(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(value.hex(), encoding="ascii")
            os.replace(tmp, path)
        except OSError:
            pass  # still usable for this process; the app re-fetches the key after a restart
        _secret_cache = value
        return value


def route_key(token: str | None = None) -> str:
    """Key the app uses to verify this server; "" when no password is configured."""
    tok = get_auth_token() if token is None else str(token)
    if not tok:
        return ""
    return hmac.new(_load_secret(), b"route-key|" + tok.encode("utf-8"), hashlib.sha256).hexdigest()


def valid_nonce(nonce: str) -> bool:
    return bool(nonce) and bool(_NONCE_RE.match(nonce))


def proof(nonce: str, instance: str, key: str | None = None) -> str:
    """HMAC proof for /status?nonce=…; "" for an invalid nonce or when no password is set."""
    k = route_key() if key is None else key
    if not k or not valid_nonce(nonce):
        return ""
    msg = f"pcc-route|{nonce}|{instance}".encode("utf-8")
    return hmac.new(k.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _reset_cache_for_tests() -> None:
    global _secret_cache
    with _lock:
        _secret_cache = None
