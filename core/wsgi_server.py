"""Production HTTP server for PC Control (QA A-13).

The Werkzeug development server starts a new thread for every connection without any limit:
hundreds of slow or idle connections ("slowloris") grow the process until it stops answering.

Cheroot (the CherryPy WSGI server, pure Python) is used instead of waitress on purpose:
waitress reads the WHOLE request body before calling the application, but two endpoints read
an endless chunked POST body while it is still arriving — /api/input/stream (mouse/keyboard
frames) and /api/mic/stream (phone microphone PCM). Under waitress they would never start.
Cheroot hands the body to the application as a stream (wsgi.input + wsgi.input_terminated for
chunked bodies) and writes every response chunk to the socket immediately, so the MJPEG / H.264 /
audio streams keep their latency.

Limits: a fixed pool of worker threads (each long stream holds one, ordinary requests are short),
a bounded queue of accepted connections, a socket timeout for idle / slow clients, a cap on
idle keep-alive connections and on connections waiting for their first bytes. A new connection
waits in cheroot's selector without a thread until it sends data, so silent connections cannot
occupy the workers. Values can be tuned in config.json (http_threads, http_queue,
http_timeout, http_keepalive_limit) but are clamped to sane ranges.

If cheroot is not installed (an older private runtime that was created before this dependency),
the server falls back to the Werkzeug server with the previous behaviour, so it still starts.
PC_CONTROL_HTTP_SERVER=werkzeug forces the fallback (diagnostics).
"""

from __future__ import annotations

import os
import sys

DEFAULTS = {
    "http_threads": 64,         # concurrent requests incl. long streams (video, audio, input, mic)
    "http_queue": 256,          # accepted connections waiting for a free worker
    "http_timeout": 20,         # seconds of socket silence before a connection is dropped
    "http_keepalive_limit": 64, # idle keep-alive connections kept open
}
# Connections waiting in cheroot's selector (idle keep-alive + new ones without data yet).
# select() on Windows is limited to 512 sockets; workers hold at most http_threads more.
MAX_WAITING_CONNECTIONS = 400

_RANGES = {
    "http_threads": (8, 100),
    "http_queue": (16, 4096),
    "http_timeout": (5, 300),
    "http_keepalive_limit": (4, 1024),
}


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


def choose_backend() -> str:
    """'cheroot' when installed and not overridden, else 'werkzeug'."""
    forced = (os.environ.get("PC_CONTROL_HTTP_SERVER") or "").strip().lower()
    if forced == "werkzeug":
        return "werkzeug"
    return "cheroot" if cheroot_available() else "werkzeug"


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
            # `timeout` for the request line: 64 silent connections would block every worker.
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

    server = _Server(
        (host, int(port)),
        app,
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
    return server


def serve(app, host: str, port: int, cfg: dict | None = None, log=None) -> str:
    """Runs the HTTP server until it stops. Returns the backend name that was used.
    A port that cannot be bound raises OSError (callers exit with an error, as before)."""
    backend = choose_backend()
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
