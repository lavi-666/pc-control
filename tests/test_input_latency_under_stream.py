"""
Mouse input latency on the PC while the H.264 screen stream is running.

Video capture + encoding run in Python threads; if they starved the input thread
(GIL), relative mouse moves would be applied in bursts = a jerky cursor. A separate
sender process writes MOUSE_REL frames every 8 ms (like a 120 Hz touch screen) over the
real chunked HTTP stream; the server timestamps every backend call.

Windows only (real screen capture + encoder); skipped elsewhere or without PyAV.
"""

import json
import statistics
import subprocess
import sys
import threading
import time
import unittest
import urllib.request

RUN = sys.platform == "win32"
try:
    import av  # noqa: F401
except Exception:  # pragma: no cover
    RUN = False

SENDER = r"""
import socket, struct, sys, time, json
port, tok, n, interval = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
H = struct.Struct("<BBH")
def fr(t, p=b""): return H.pack(t, 0, len(p)) + p
s = socket.create_connection(("127.0.0.1", port))
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
s.sendall(("POST /api/input/stream HTTP/1.1\r\nHost: x\r\nX-Auth-Token: " + tok +
           "\r\nContent-Type: application/octet-stream\r\nTransfer-Encoding: chunked\r\n\r\n").encode())
def chunk(b): s.sendall(("%x\r\n" % len(b)).encode() + b + b"\r\n")
chunk(fr(1, struct.pack("<H", 1)))
time.sleep(0.2)
sent = {}
nxt = time.perf_counter()
for i in range(1, n + 1):
    nxt += interval
    while True:
        r = nxt - time.perf_counter()
        if r <= 0: break
        if r > 0.002: time.sleep(r - 0.0015)
    sent[i] = time.perf_counter()
    chunk(fr(0x10, struct.pack("<hh", 0, i)))
chunk(fr(3)); s.sendall(b"0\r\n\r\n"); time.sleep(0.3); s.close()
print(json.dumps(sent))
"""


@unittest.skipUnless(RUN, "needs Windows screen capture and PyAV")
class InputLatencyUnderVideoStream(unittest.TestCase):

    def test_mouse_moves_are_not_delayed_by_video_encoding(self):
        from flask import Flask
        from werkzeug.serving import make_server
        from core.config import get_auth_token
        from modules import input_controller
        from modules.input_engine import InputBackend
        from modules.streaming import streaming_bp

        class TimedBackend(InputBackend):
            def __init__(self):
                self.t = []

            def move_rel(self, dx, dy):
                self.t.append((dy, time.perf_counter()))

        backend = TimedBackend()
        input_controller.set_input_backend_factory(lambda: backend)
        app = Flask("latency_under_stream")
        app.register_blueprint(input_controller.input_bp)
        app.register_blueprint(streaming_bp)
        srv = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        tok = get_auth_token()
        stop = threading.Event()
        video = {"bytes": 0}

        def reader():
            req = urllib.request.Request(
                f"http://127.0.0.1:{srv.server_port}/screen/h264_stream?height=1080&fps=60",
                headers={"X-Auth-Token": tok})
            with urllib.request.urlopen(req, timeout=15) as r:
                while not stop.is_set():
                    d = r.read(65536)
                    if not d:
                        break
                    video["bytes"] += len(d)

        threading.Thread(target=reader, daemon=True).start()
        try:
            deadline = time.monotonic() + 10
            while video["bytes"] < 200_000 and time.monotonic() < deadline:
                time.sleep(0.1)
            if video["bytes"] < 200_000:
                self.skipTest("screen stream did not start (no capture/encoder in this session)")
            out = subprocess.run([sys.executable, "-c", SENDER, str(srv.server_port), tok, "500", str(1 / 125)],
                                 capture_output=True, text=True, timeout=60).stdout
            time.sleep(0.3)
        finally:
            stop.set()
            srv.shutdown()
            input_controller.set_input_backend_factory(None)

        sent = {int(k): v for k, v in json.loads(out).items()}
        lat = sorted((t - sent[i]) * 1000 for i, t in backend.t if i in sent)
        self.assertEqual(len(lat), 500, "every move must arrive")
        order = [i for i, _ in backend.t]
        self.assertEqual(order, sorted(order), "moves must be applied in order")
        p50 = statistics.median(lat)
        p99 = lat[int(len(lat) * 0.99) - 1]
        print(f"\n[latency] video {video['bytes'] // 1024} KiB, input p50 {p50:.2f} ms, p99 {p99:.2f} ms, max {lat[-1]:.2f} ms")
        self.assertLess(p50, 5.0)
        self.assertLess(p99, 20.0)


if __name__ == "__main__":
    unittest.main()
