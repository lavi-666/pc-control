"""Per-client registry of long streaming responses (QA R-4).

When the phone changes its route (USB cable pulled -> Wi-Fi, Wi-Fi -> Tailscale) it opens a new
/screen/h264_stream or /audio while the old response is still blocked writing to a dead socket.
Before, the old one kept running ~1.5 min: two captures, two encoders (NVENC sessions!), DIB and
timeBeginPeriod. Now:

  * a new stream with the same key stops the previous one: its stop flag is set (checked between
    chunks) and its socket is shut down (the next write fails);
  * every stream socket gets a write timeout (STREAM_WRITE_TIMEOUT), so a client that vanished
    without a FIN is detected within ~10 s even without a new stream.

Key: the X-Stream-Client header (new apps: a per-process id + role) + the stream kind. Without the
header the H.264 stream falls back to the device session (one screen view per app); audio does not,
because older apps play PC sound and the screen-view sound as two parallel /audio streams of the same
session (they would stop each other). Without a key nothing is registered (old behaviour + timeout).
"""

from __future__ import annotations

import re
import socket
import threading

STREAM_WRITE_TIMEOUT = 10.0  # s: a write that makes no progress this long ends the stream
_CLIENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")

_lock = threading.Lock()
_active: dict[str, "StreamHandle"] = {}


class StreamHandle:
    __slots__ = ("key", "stop", "sock", "_released")

    def __init__(self, key: str | None, sock=None):
        self.key = key
        self.stop = threading.Event()
        self.sock = sock
        self._released = False

    def kick(self) -> None:
        """Stops this stream from another thread (a newer stream of the same client)."""
        self.stop.set()
        s = self.sock
        if s is not None and not self._released:
            # shutdown() only, never close(): the socket belongs to the HTTP server, and cheroot stops
            # the WHOLE server when it later finds the handle closed (WinError 10038, checked live).
            # A stream that is between writes ends at once (the next send fails / the stop flag); a
            # write already blocked on the dead route ends by the socket write timeout (~10 s) -
            # on Windows shutdown() does not wake a send() that waits for buffer space.
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.key is None:
            return
        with _lock:
            if _active.get(self.key) is self:
                del _active[self.key]


def request_socket(environ):
    """The client socket of the current request (cheroot: pcc.socket, Werkzeug: werkzeug.socket)."""
    return environ.get("pcc.socket") or environ.get("werkzeug.socket")


def set_write_timeout(sock, seconds: float = STREAM_WRITE_TIMEOUT) -> None:
    if sock is None:
        return
    try:
        sock.settimeout(seconds)
    except OSError:
        pass


def stream_key(kind: str, client_header: str | None, session_id: str | None,
               session_fallback: bool) -> str | None:
    client = (client_header or "").strip()
    if client and _CLIENT_RE.match(client):
        return f"client:{client}:{kind}"
    if session_fallback and session_id:
        return f"sid:{session_id}:{kind}"
    return None


def claim(key: str | None, sock=None) -> StreamHandle:
    """Registers a new stream; the previous stream with the same key is stopped."""
    handle = StreamHandle(key, sock)
    if key is None:
        return handle
    with _lock:
        old = _active.get(key)
        _active[key] = handle
    if old is not None:
        old.kick()
    return handle


def guarded(iterable, handle: StreamHandle):
    """Wraps a streaming body: ends it once a newer stream of the same client took over."""
    it = iter(iterable)
    try:
        for chunk in it:
            if handle.stop.is_set():
                break
            yield chunk
    finally:
        handle.release()
        close = getattr(it, "close", None)
        if close is not None:
            close()


def active_keys() -> list[str]:
    with _lock:
        return sorted(_active)


def _reset_for_tests() -> None:
    with _lock:
        _active.clear()
