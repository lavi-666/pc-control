"""Production HTTP server for PC Control (QA A-13).

The Werkzeug development server starts a new thread for every connection without any limit:
hundreds of slow or idle connections ("slowloris") grow the process until it stops answering.

Cheroot (the CherryPy WSGI server, pure Python) is used instead of waitress on purpose:
waitress reads the WHOLE request body before calling the application, but two endpoints read
an endless chunked POST body while it is still arriving — /api/input/stream (mouse/keyboard
frames) and /api/mic/stream (phone microphone PCM). Under waitress they would never start
(waitress also rejects the hop-by-hop "Connection: close" header of the H.264 stream).
Cheroot hands the body to the application as a stream and writes every response chunk to the
socket immediately, so the MJPEG / H.264 / audio streams keep their latency.

Limits:
  * fixed pool of worker threads (http_threads, default 48); each long stream holds one;
  * bounded queue of accepted connections, socket timeout 15 s (> the 12 s input idle timeout);
  * a new connection waits in cheroot's selector WITHOUT a thread until it sends data, and the
    number of such waiting / idle keep-alive connections is capped (select() limit on Windows);
  * concurrency limiter (WSGI middleware): at most http_per_ip requests in flight per client IP
    and http_threads - 4 in total; the rest get 503 + Retry-After. GET /status from this PC
    bypasses the limiter, so the reserved threads always answer watchdog.pyw (QA R-7) and the
    server is not restarted in the middle of a stream.
Values can be tuned in config.json (http_threads, http_queue, http_timeout, http_keepalive_limit,
http_per_ip) and are clamped to sane ranges.

Fallback: config.json "http_server": "werkzeug" (or PC_CONTROL_HTTP_SERVER=werkzeug), or cheroot
missing from an older private runtime -> the previous Werkzeug server, so the server still starts.
"""

from __future__ import annotations

import os
import sys
import threading

DEFAULTS = {
    "http_threads": 48,         # concurrent requests incl. long streams (video, audio, input, mic)
    "http_queue": 256,          # accepted connections waiting for a free worker
    "http_timeout": 15,         # seconds of socket silence before a connection is dropped
    "http_keepalive_limit": 64, # idle keep-alive connections kept open
    "http_per_ip": 16,          # requests in flight from one client address
}
_RANGES = {
    "http_threads": (12, 100),
    "http_queue": (16, 4096),
    "http_timeout": (13, 300),  # must stay above INPUT_STREAM_IDLE_TIMEOUT (12 s)
    "http_keepalive_limit": (4, 1024),
    "http_per_ip": (4, 100),
}
RESERVED_THREADS = 4  # kept free for loopback /status (watchdog) and short requests

# Connections waiting in cheroot's selector (idle keep-alive + new ones without data yet).
# select() on Windows is limited to 512 sockets; workers hold at most http_threads more.
MAX_WAITING_CONNECTIONS = 400

_LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def server_limits(cfg: dict | None = None) -> dict:
    """Effective limits: config.json values clamped to _RANGES, defaults otherwise."""
    cfg = cfg or {}
    out = {}
    for key, default in DEFAULTS.items():
        try:
            val = int(cfg.get(key, default))
        except (TypeError, ValueError, OverflowError):
            val = default
        lo, hi = _RANGES[key]
        out[key] = max(lo, min(hi, val))
    return out


def cheroot_available() -> bool:
    try:
        import cheroot.wsgi  # noqa: F401
        return True
    except Exception:
        return False


def choose_backend(cfg: dict | None = None) -> str:
    """'cheroot' when installed and not switched off, else 'werkzeug'."""
    forced = (os.environ.get("PC_CONTROL_HTTP_SERVER") or "").strip().lower()
    if not forced:
        forced = str((cfg or {}).get("http_server") or "").strip().lower()
    if forced == "werkzeug":
        return "werkzeug"
    return "cheroot" if cheroot_available() else "werkzeug"


class ConcurrencyLimiter:
    """WSGI middleware: caps requests in flight per client IP and in total.

    A request holds its slot until the response iterable is closed, so endless streams count for
    their whole life. Also sets wsgi.input_terminated for chunked bodies (input_controller would
    answer 411 without it; cheroot sets it itself, the middleware just guarantees it)."""

    def __init__(self, app, per_ip: int, total: int):
        self.app = app
        self.per_ip = int(per_ip)
        self.total = int(total)
        self._lock = threading.Lock()
        self._by_ip: dict[str, int] = {}
        self._active = 0

    def snapshot(self) -> dict:
        with self._lock:
            return {"active": self._active, "by_ip": dict(self._by_ip)}

    @staticmethod
    def _exempt(environ) -> bool:
        return (environ.get("REMOTE_ADDR") in _LOOPBACK and environ.get("PATH_INFO") == "/status"
                and environ.get("REQUEST_METHOD") in ("GET", "HEAD"))

    def _release(self, ip: str):
        with self._lock:
            self._active -= 1
            n = self._by_ip.get(ip, 1) - 1
            if n <= 0:
                self._by_ip.pop(ip, None)
            else:
                self._by_ip[ip] = n

    def __call__(self, environ, start_response):
        if "chunked" in (environ.get("HTTP_TRANSFER_ENCODING") or "").lower():
            environ["wsgi.input_terminated"] = True
        if self._exempt(environ):
            return self.app(environ, start_response)
        ip = environ.get("REMOTE_ADDR") or "?"
        with self._lock:
            busy_ip = self._by_ip.get(ip, 0) >= self.per_ip
            busy_all = self._active >= self.total
            if not (busy_ip or busy_all):
                self._active += 1
                self._by_ip[ip] = self._by_ip.get(ip, 0) + 1
        if busy_ip or busy_all:
            body = b'{"ok":false,"message":"Server busy, retry shortly"}'
            start_response("503 Service Unavailable", [
                ("Content-Type", "application/json"), ("Content-Length", str(len(body))),
                ("Retry-After", "2"), ("Connection", "close")])
            return [body]
        try:
            result = self.app(environ, start_response)
        except BaseException:
            self._release(ip)
            raise
        return _ClosingIterator(result, lambda: self._release(ip))


class _ClosingIterator:
    def __init__(self, result, on_close):
        self._result = result
        self._it = iter(result)
        self._on_close = on_close
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            close = getattr(self._result, "close", None)
            if close is not None:
                close()
        finally:
            self._on_close()


def make_cheroot_server(app, host: str, port: int, cfg: dict | None = None):
    """Builds (does not start) a cheroot server with PC Control limits."""
    from cheroot import wsgi

    limits = server_limits(cfg)

    class _Gateway(wsgi.Gateway_10):
        def get_environ(self):
            env = super().get_environ()
            # Raw connection socket: /api/input/stream sets its own idle timeout + TCP_NODELAY
            # (under Werkzeug the same socket is published as "werkzeug.socket").
            try:
                env["pcc.socket"] = self.req.conn.socket
            except Exception:
                pass
            return env

    class _Server(wsgi.Server):
        def process_conn(self, conn):
            # Cheroot hands a NEW connection straight to a worker thread, which then waits up to
            # `timeout` for the request line: silent connections would block every worker.
            # A new connection first waits in the selector (no thread) until it has data.
            if not getattr(conn, "_pcc_seen", False):
                conn._pcc_seen = True
                try:
                    waiting = self._connections._num_connections
                except Exception:
                    waiting = 0
                if waiting >= MAX_WAITING_CONNECTIONS:
                    # select() on Windows handles at most 512 sockets: refuse instead of failing.
                    try:
                        conn.close()
                    except Exception:
                        pass
                    return
                try:
                    self._connections.put(conn)
                    return
                except Exception:
                    pass  # unknown cheroot internals: dispatch as cheroot does itself
            super().process_conn(conn)

    limiter = ConcurrencyLimiter(app, limits["http_per_ip"], limits["http_threads"] - RESERVED_THREADS)
    server = _Server(
        (host, int(port)),
        limiter,
        numthreads=limits["http_threads"],
        server_name="PC-Control",  # Server header without the library name / version
        request_queue_size=64,  # listen() backlog
        timeout=limits["http_timeout"],
        shutdown_timeout=3,
        accepted_queue_size=limits["http_queue"],
        accepted_queue_timeout=5,
    )
    server.gateway = _Gateway
    server.keep_alive_conn_limit = limits["http_keepalive_limit"]
    server.software = "PC-Control"  # SERVER_SOFTWARE without the library version
    server.max_request_header_size = 64 * 1024
    server.max_request_body_size = 0  # endless streams; Flask MAX_CONTENT_LENGTH limits the rest
    server.pcc_limiter = limiter
    return server


def serve(app, host: str, port: int, cfg: dict | None = None, log=None) -> str:
    """Runs the HTTP server until it stops. Returns the backend name that was used.
    A port that cannot be bound raises OSError (callers exit with an error, as before)."""
    backend = choose_backend(cfg)
    if log:
        try:
            log(backend, server_limits(cfg) if backend == "cheroot" else {})
        except Exception:
            pass
    if backend == "cheroot":
        server = make_cheroot_server(app, host, port, cfg)
        try:
            server.prepare()  # binds the socket: OSError here = port busy
        except BaseException:
            try:
                server.stop()
            except Exception:
                pass
            raise
        try:
            server.serve()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                server.stop()
            except Exception:
                pass
        return backend
    app.run(host=host, port=int(port), threaded=True)
    return backend


if __name__ == "__main__":  # pragma: no cover - manual check
    print(choose_backend(), server_limits(), file=sys.stderr)
