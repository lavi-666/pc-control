"""
Runs the Android input code (pure-Java part) on the desktop JDK of the portable SDK:
  1. gesture / keyboard / protocol logic tests (android_app/test/.../PcInputJvmTests.java)
  2. end-to-end: real PcInputClient (Java) -> HTTP chunked stream -> Werkzeug -> InputSession.
Skipped when the portable JDK is not installed.
"""

import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from flask import Flask
from werkzeug.serving import make_server

from core.config import get_auth_token
from modules import input_controller
from modules.input_engine import RecordingBackend

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "android_app" / "src" / "com" / "pccontrol" / "remote"
TEST_SRC = BASE / "android_app" / "test" / "com" / "pccontrol" / "remote" / "PcInputJvmTests.java"
PURE_JAVA = ["PcInputProtocol.java", "PcInputClient.java", "PcTouchpadEngine.java", "PcKeyboardLogic.java",
             "PcSvgPath.java", "PcIcons.java", "PcAudioGain.java"]


def _find_jdk():
    for root in (BASE / ".android_sdk" / "jdk",):
        for javac in root.glob("**/bin/javac.exe"):
            java = javac.parent / "java.exe"
            if java.exists():
                return javac, java
    javac, java = shutil.which("javac"), shutil.which("java")
    if javac and java:
        return Path(javac), Path(java)
    return None, None


JAVAC, JAVA = _find_jdk()


@unittest.skipIf(JAVAC is None, "JDK not available")
class AndroidInputJvmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pcc_jvm_")
        sources = [str(SRC / f) for f in PURE_JAVA] + [str(TEST_SRC)]
        res = subprocess.run([str(JAVAC), "-encoding", "UTF-8", "-d", cls.tmp] + sources,
                             capture_output=True, text=True, timeout=180)
        if res.returncode != 0:
            raise AssertionError("javac failed:\n" + res.stdout + res.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_java(self, *args, timeout=60):
        return subprocess.run([str(JAVA), "-Dfile.encoding=UTF-8", "-cp", self.tmp,
                               "com.pccontrol.remote.PcInputJvmTests", *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=timeout)

    def test_gesture_keyboard_protocol_logic(self):
        res = self.run_java()
        print("\n" + res.stdout.strip())
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("FAILED=0", res.stdout)

    def test_e2e_java_client_to_server(self):
        backend = RecordingBackend()
        input_controller.set_input_backend_factory(lambda: backend)
        app = Flask("jvm_e2e")
        app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
        app.register_blueprint(input_controller.input_bp)
        server = make_server("127.0.0.1", 0, app, threaded=True)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            res = self.run_java("e2e", f"http://127.0.0.1:{server.server_port}", get_auth_token())
        finally:
            server.shutdown()
            input_controller.set_input_backend_factory(None)
        print("\n" + res.stdout.strip())
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        ev = backend.snapshot()

        moves = [e for e in ev if e[0] == "move_rel"]
        self.assertEqual(sum(e[1] for e in moves), 200)
        self.assertEqual(sum(e[2] for e in moves), -200)
        print(f"[jvm-e2e] 200 move events -> {len(moves)} frames after coalescing")

        def idx(item):
            self.assertIn(item, ev)
            return ev.index(item)

        # strict ordering of everything that is not pointer motion
        order = [
            idx(("button", 1, True)), idx(("button", 1, False)), idx(("wheel", -120, 0)),
            idx(("key", 0xA2, True, False)), idx(("key", 0x43, True, False)),
            idx(("key", 0x43, False, False)), idx(("key", 0xA2, False, False)),
            idx(("unicode", 0x0416, True)), idx(("unicode", 0x0416, False)),
        ]
        self.assertEqual(order, sorted(order))
        typed = "".join(chr(e[1]) for e in ev if e[0] == "unicode" and e[2])
        self.assertIn("Привіт, 世界 😀", typed)
        self.assertIn(("move_abs", 32768, 16384, 1), ev)
        hk = [e for e in ev if e[0] == "key" and e[1] in (0xA4, 0x09)]
        self.assertEqual(hk, [("key", 0xA4, True, False), ("key", 0x09, True, False),
                              ("key", 0x09, False, False), ("key", 0xA4, False, False)])
        # backspace held 1.6 s: server-side typematic repeat, then exactly one release
        bs_down = [e for e in ev if e == ("key", 0x08, True, False)]
        bs_up = [e for e in ev if e == ("key", 0x08, False, False)]
        self.assertGreaterEqual(len(bs_down), 5)
        self.assertEqual(len(bs_up), 1)
        self.assertGreater(ev.index(bs_up[0]), ev.index(bs_down[-1]))
        # nothing left pressed
        held = {}
        for e in ev:
            if e[0] == "key":
                held[e[1]] = e[2]
            elif e[0] == "button":
                held[("b", e[1])] = e[2]
        self.assertFalse(any(held.values()), f"stuck inputs: {held}")

    def test_e2e_network_drop_reconnect_and_resync(self):
        """Wi-Fi drop while a key is held: server releases it, client reconnects and re-sends it."""
        import socket
        import time

        backend = RecordingBackend()
        input_controller.set_input_backend_factory(lambda: backend)
        app = Flask("jvm_reconnect")
        app.register_blueprint(input_controller.input_bp)
        server = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        # Minimal TCP proxy that can cut all live connections (simulated network drop).
        lsock = socket.socket()
        lsock.bind(("127.0.0.1", 0))
        lsock.listen(16)
        pairs = []

        def pipe(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            for x in (a, b):
                try:
                    x.close()
                except OSError:
                    pass

        def accept_loop():
            while True:
                try:
                    c, _ = lsock.accept()
                except OSError:
                    return
                u = socket.create_connection(("127.0.0.1", server.server_port))
                pairs.append((c, u))
                threading.Thread(target=pipe, args=(c, u), daemon=True).start()
                threading.Thread(target=pipe, args=(u, c), daemon=True).start()

        threading.Thread(target=accept_loop, daemon=True).start()
        proc = subprocess.Popen([str(JAVA), "-cp", self.tmp, "com.pccontrol.remote.PcInputJvmTests", "reconnect",
                                 f"http://127.0.0.1:{lsock.getsockname()[1]}", get_auth_token()],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            line = proc.stdout.readline()
            self.assertIn("READY_HELD", line)
            deadline = time.monotonic() + 3
            while ("key", 0x41, True, False) not in backend.snapshot() and time.monotonic() < deadline:
                time.sleep(0.01)
            for c, u in list(pairs):  # cut the network
                for x in (c, u):
                    try:
                        x.shutdown(socket.SHUT_RDWR)
                        x.close()
                    except OSError:
                        pass
            out, _ = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
            lsock.close()
            server.shutdown()
            input_controller.set_input_backend_factory(None)
        print("\n" + out.strip())
        self.assertEqual(proc.returncode, 0, out)
        a_events = [e for e in backend.snapshot() if e[0] == "key" and e[1] == 0x41]
        self.assertEqual(a_events, [
            ("key", 0x41, True, False),   # first session: pressed
            ("key", 0x41, False, False),  # connection lost: released by the server (no stuck key)
            ("key", 0x41, True, False),   # reconnected: still under the finger -> resync
            ("key", 0x41, False, False),  # finger lifted
        ])


if __name__ == "__main__":
    unittest.main()
