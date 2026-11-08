"""
Tests of the binary input stream (modules/input_engine.py + /api/input/stream).

Uses a recording backend, so these tests never move the real mouse or press real keys.
Real Windows input is covered by tests/test_input_real_e2e.py (opt-in).
"""

import socket
import struct
import threading
import time
import unittest

from flask import Flask
from werkzeug.serving import make_server

from core.config import get_auth_token
from modules import input_controller
from modules.input_engine import (
    FRAME_END, FRAME_HELLO, FRAME_HOTKEY, FRAME_KEY, FRAME_MOUSE_ABS, FRAME_MOUSE_BTN,
    FRAME_MOUSE_REL, FRAME_PING, FRAME_RELEASE_ALL, FRAME_SCROLL, FRAME_TEXT, FRAME_UNICODE,
    InputSession, ProtocolError, RecordingBackend, encode_frame, run_stream,
)


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def key(vk, down, ext=0):
    return encode_frame(FRAME_KEY, struct.pack("<HBB", vk, 1 if down else 0, ext))


def btn(b, down):
    return encode_frame(FRAME_MOUSE_BTN, struct.pack("<BB", b, 1 if down else 0))


def uni(cp, down):
    return encode_frame(FRAME_UNICODE, struct.pack("<IB", cp, 1 if down else 0))


def feed(session, data: bytes) -> str:
    pos = [0]

    def read_exact(n):
        if pos[0] + n > len(data):
            return None
        chunk = data[pos[0]:pos[0] + n]
        pos[0] += n
        return chunk

    return run_stream(read_exact, session)


class InputEngineTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.backend = RecordingBackend()
        self.s = InputSession(self.backend, clock=self.clock, repeat_delay=0.5,
                              repeat_period=0.05, watchdog_timeout=3.0)

    def test_event_order_is_preserved(self):
        data = (encode_frame(FRAME_HELLO, struct.pack("<H", 1))
                + encode_frame(FRAME_MOUSE_REL, struct.pack("<hh", 5, -3))
                + btn(1, True)
                + encode_frame(FRAME_MOUSE_REL, struct.pack("<hh", 10, 0))
                + btn(1, False)
                + encode_frame(FRAME_MOUSE_ABS, struct.pack("<HHB", 32768, 100, 2)))
        self.assertEqual(feed(self.s, data), "eof")
        self.assertEqual(self.backend.snapshot(), [
            ("move_rel", 5, -3), ("button", 1, True), ("move_rel", 10, 0),
            ("button", 1, False), ("move_abs", 32768, 100, 2),
        ])
        self.assertEqual(self.s.client_version, 1)

    def test_duplicate_press_and_release_are_suppressed(self):
        feed(self.s, key(0x41, True) + key(0x41, True) + key(0x41, False) + key(0x41, False)
             + btn(2, False) + btn(2, True) + btn(2, True) + btn(2, False))
        self.assertEqual(self.backend.snapshot(), [
            ("key", 0x41, True, False), ("key", 0x41, False, False),
            ("button", 2, True), ("button", 2, False),
        ])

    def test_autorepeat_while_held_and_stops_on_release(self):
        feed(self.s, key(0x08, True))  # backspace
        self.s.tick()
        self.assertEqual(len(self.backend.snapshot()), 1)  # no repeat before delay
        self.clock.t += 0.5
        self.s.tick()
        self.clock.t += 0.05
        self.s.tick()
        self.clock.t += 0.05
        self.s.tick()
        downs = [e for e in self.backend.snapshot() if e == ("key", 0x08, True, False)]
        self.assertEqual(len(downs), 4)  # initial + 3 typematic repeats
        feed(self.s, key(0x08, False))
        n = len(self.backend.snapshot())
        self.clock.t += 1.0
        self.s.tick()
        self.assertEqual(len(self.backend.snapshot()), n)
        self.assertEqual(self.backend.snapshot()[-1], ("key", 0x08, False, False))

    def test_modifiers_never_autorepeat(self):
        feed(self.s, key(0xA2, True))
        self.clock.t += 2.0
        self.s.last_seen = self.clock.t
        self.s.tick()
        self.assertEqual(self.backend.snapshot(), [("key", 0xA2, True, False)])

    def test_unicode_hold_repeats_and_release(self):
        feed(self.s, uni(0x0416, True))  # Cyrillic ZHE
        self.clock.t += 0.6
        self.s.tick()
        feed(self.s, uni(0x0416, False))
        ev = self.backend.snapshot()
        self.assertEqual(ev[0], ("unicode", 0x0416, True))
        self.assertIn(("unicode", 0x0416, True), ev[1:-1])
        self.assertEqual(ev[-1], ("unicode", 0x0416, False))

    def test_text_unicode_ru_uk_emoji_and_enter(self):
        feed(self.s, encode_frame(FRAME_TEXT, "Aж їґ€😀\n".encode("utf-8")))
        ev = self.backend.snapshot()
        typed = [e[1] for e in ev if e[0] == "unicode" and e[2]]
        self.assertEqual("".join(chr(c) for c in typed), "Aж їґ€😀")
        self.assertEqual(ev[-2:], [("key", 0x0D, True, False), ("key", 0x0D, False, False)])
        # every press has a matching release
        self.assertEqual(sum(1 for e in ev if e[0] == "unicode" and e[2]),
                         sum(1 for e in ev if e[0] == "unicode" and not e[2]))

    def test_hotkey_press_order_and_reverse_release(self):
        feed(self.s, encode_frame(FRAME_HOTKEY, struct.pack("<BHHH", 3, 0xA2, 0xA0, 0x1B)))
        self.assertEqual(self.backend.snapshot(), [
            ("key", 0xA2, True, False), ("key", 0xA0, True, False), ("key", 0x1B, True, False),
            ("key", 0x1B, False, False), ("key", 0xA0, False, False), ("key", 0xA2, False, False),
        ])

    def test_hotkey_does_not_release_latched_modifier(self):
        feed(self.s, key(0xA2, True) + encode_frame(FRAME_HOTKEY, struct.pack("<BHH", 2, 0xA2, 0x43)))
        self.assertEqual(self.backend.snapshot(), [
            ("key", 0xA2, True, False), ("key", 0x43, True, False), ("key", 0x43, False, False),
        ])
        self.assertIn(0xA2, self.s.held_keys)

    def test_scroll_accumulates_to_whole_wheel_ticks(self):
        for _ in range(5):
            feed(self.s, encode_frame(FRAME_SCROLL, struct.pack("<hh", -40, 0)))
        feed(self.s, encode_frame(FRAME_SCROLL, struct.pack("<hh", 0, 250)))
        self.assertEqual(self.backend.snapshot(), [
            ("wheel", -120, 0), ("wheel", 0, 240),
        ])

    def test_watchdog_releases_stuck_inputs_when_client_goes_silent(self):
        feed(self.s, key(0xA2, True) + key(0x43, True) + btn(1, True) + uni(0x44, True))
        self.clock.t += 2.0
        self.s.tick()
        self.assertTrue(self.s.has_held_inputs())  # still within timeout
        self.clock.t += 1.5
        self.s.tick()
        self.assertFalse(self.s.has_held_inputs())
        self.assertEqual(self.s.watchdog_releases, 1)
        tail = self.backend.snapshot()[-4:]
        self.assertEqual(tail, [("unicode", 0x44, False), ("key", 0x43, False, False),
                                ("key", 0xA2, False, False), ("button", 1, False)])

    def test_ping_keeps_held_key_alive(self):
        feed(self.s, btn(1, True))
        for _ in range(10):
            self.clock.t += 1.0
            feed(self.s, encode_frame(FRAME_PING))
            self.s.tick()
        self.assertEqual(self.s.held_buttons, {1})

    def test_end_frame_and_close_release_everything(self):
        res = feed(self.s, key(0x10, True) + btn(3, True) + encode_frame(FRAME_END) + key(0x41, True))
        self.assertEqual(res, "end")
        self.assertFalse(self.s.has_held_inputs())
        self.assertNotIn(("key", 0x41, True, False), self.backend.snapshot())

    def test_release_all_frame(self):
        feed(self.s, key(0x11, True) + btn(1, True) + encode_frame(FRAME_RELEASE_ALL))
        self.assertFalse(self.s.has_held_inputs())

    def test_protocol_errors(self):
        for bad in (encode_frame(FRAME_MOUSE_REL, b"\x01"), key(0, True), btn(9, True),
                    uni(0xD800, True), encode_frame(FRAME_HOTKEY, b"\x02\x41\x00")):
            s = InputSession(RecordingBackend(), clock=self.clock)
            with self.assertRaises(ProtocolError):
                feed(s, bad)
        with self.assertRaises(ProtocolError):
            feed(InputSession(RecordingBackend()), struct.pack("<BBH", FRAME_TEXT, 0, 60000))

    def test_unknown_frame_type_is_skipped(self):
        feed(self.s, encode_frame(0x7F, b"abc") + btn(1, True))
        self.assertEqual(self.backend.snapshot(), [("button", 1, True)])


class InputStreamHttpTests(unittest.TestCase):
    """Real HTTP/1.1 chunked stream through the Werkzeug server used by PC Control."""

    @classmethod
    def setUpClass(cls):
        cls.backend = RecordingBackend()
        input_controller.set_input_backend_factory(lambda: cls.backend)
        app = Flask("test_input_stream")
        app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # same limit as server.py
        app.register_blueprint(input_controller.input_bp)
        cls.server = make_server("127.0.0.1", 0, app, threaded=True)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.token = get_auth_token()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        input_controller.set_input_backend_factory(None)

    def setUp(self):
        with self.backend.lock:
            self.backend.events.clear()

    def open_stream(self, token=None):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        head = (f"POST /api/input/stream HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                f"X-Auth-Token: {token if token is not None else self.token}\r\n"
                "Content-Type: application/octet-stream\r\nTransfer-Encoding: chunked\r\n\r\n")
        s.sendall(head.encode("ascii"))
        return s

    @staticmethod
    def chunk(s, data: bytes):
        s.sendall(b"%x\r\n" % len(data) + data + b"\r\n")

    def wait_for(self, n, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.backend.snapshot()) >= n:
                return True
            time.sleep(0.001)
        return False

    def read_response(self, s):
        s.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            part = s.recv(4096)
            if not part:
                break
            data += part
        return data

    def test_info_endpoint(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/input/info", headers={"X-Auth-Token": self.token})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        import json
        info = json.loads(r.read())
        self.assertEqual(info["protocol"], 1)
        self.assertGreater(info["repeat_period_ms"], 0)
        c.request("GET", "/api/input/info")
        self.assertEqual(c.getresponse().status, 401)

    def test_stream_requires_token(self):
        s = self.open_stream(token="wrong-token")
        self.chunk(s, btn(1, True))
        resp = self.read_response(s)
        s.close()
        self.assertIn(b" 401 ", resp.split(b"\r\n", 1)[0] + b" ")
        self.assertEqual(self.backend.snapshot(), [])

    def test_frames_are_applied_immediately_not_at_end_of_request(self):
        s = self.open_stream()
        self.chunk(s, encode_frame(FRAME_HELLO, struct.pack("<H", 1)))
        latencies = []
        for i in range(50):
            t0 = time.perf_counter()
            self.chunk(s, encode_frame(FRAME_MOUSE_REL, struct.pack("<hh", 1, i)))
            self.assertTrue(self.wait_for(i + 1), "frame was not applied while stream open")
            latencies.append(time.perf_counter() - t0)
        self.chunk(s, encode_frame(FRAME_END))
        s.sendall(b"0\r\n\r\n")
        resp = self.read_response(s)
        s.close()
        self.assertIn(b"200", resp.split(b"\r\n", 1)[0])
        latencies.sort()
        median_ms = latencies[len(latencies) // 2] * 1000
        p95_ms = latencies[int(len(latencies) * 0.95)] * 1000
        print(f"\n[input-stream] loopback frame->apply latency: median {median_ms:.2f} ms, p95 {p95_ms:.2f} ms")
        self.assertLess(median_ms, 20.0)
        self.assertEqual([e[2] for e in self.backend.snapshot()], list(range(50)))

    def test_long_session_exceeds_max_content_length(self):
        """A control session must survive more than MAX_CONTENT_LENGTH (1 MB) of input."""
        s = self.open_stream()
        frame = encode_frame(FRAME_MOUSE_REL, struct.pack("<hh", 1, 1))
        batch = frame * 4096  # 32 KB
        for _ in range(40):  # 1.25 MB
            self.chunk(s, batch)
        self.chunk(s, encode_frame(FRAME_END))
        s.sendall(b"0\r\n\r\n")
        resp = self.read_response(s)
        s.close()
        self.assertIn(b"200", resp.split(b"\r\n", 1)[0])
        self.assertEqual(len(self.backend.snapshot()), 40 * 4096)

    def test_abrupt_disconnect_releases_held_keys_and_buttons(self):
        s = self.open_stream()
        self.chunk(s, key(0xA2, True) + key(0x56, True) + btn(1, True))
        self.assertTrue(self.wait_for(3))
        s.close()  # phone lost Wi-Fi / app killed
        self.assertTrue(self.wait_for(6))
        ev = self.backend.snapshot()
        self.assertIn(("key", 0x56, False, False), ev)
        self.assertIn(("key", 0xA2, False, False), ev)
        self.assertIn(("button", 1, False), ev)

    def test_two_parallel_sessions_are_independent(self):
        a = self.open_stream()
        b = self.open_stream()
        self.chunk(a, btn(1, True))
        self.chunk(b, key(0x41, True))
        self.assertTrue(self.wait_for(2))
        b.close()
        self.assertTrue(self.wait_for(3))
        self.assertNotIn(("button", 1, False), self.backend.snapshot())
        self.chunk(a, btn(1, False) + encode_frame(FRAME_END))
        a.sendall(b"0\r\n\r\n")
        self.read_response(a)
        a.close()
        self.assertIn(("button", 1, False), self.backend.snapshot())


if __name__ == "__main__":
    unittest.main()
