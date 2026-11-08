"""
REAL Windows end-to-end test of PC Control mouse/keyboard input:
binary frames -> HTTP chunked stream -> Werkzeug -> InputSession -> SendInput -> a Tk test window.

It moves the real cursor and types into its own window, therefore it is opt-in:
    set PCC_REAL_INPUT_E2E=1 && python -m pytest tests/test_input_real_e2e.py -s
Keyboard input is only sent while the test window is the foreground window
(checked before every step), so nothing can be typed into another application.
"""

import ctypes
import os
import socket
import struct
import sys
import threading
import time
import unittest
from ctypes import wintypes

RUN = os.environ.get("PCC_REAL_INPUT_E2E") == "1" and sys.platform == "win32"


@unittest.skipUnless(RUN, "real input E2E is opt-in: set PCC_REAL_INPUT_E2E=1 (Windows only)")
class RealWindowsInputE2E(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from werkzeug.serving import make_server
        from core.config import get_auth_token
        from modules import input_controller
        import tkinter as tk

        cls.ic = input_controller
        input_controller.set_input_backend_factory(None)  # real SendInput
        cls.mons = input_controller._get_mss_monitors()     # enables per-monitor DPI awareness first
        app = Flask("real_e2e")
        app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
        app.register_blueprint(input_controller.input_bp)
        cls.server = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.token = get_auth_token()
        cls.user32 = ctypes.windll.user32
        cls.user32.GetForegroundWindow.restype = wintypes.HWND
        cls.orig_cursor = cls.cursor()

        cls.events = []
        root = tk.Tk()
        root.title("PC Control input E2E")
        root.geometry("640x420+120+120")
        root.attributes("-topmost", True)
        cls.root = root
        cls.entry = tk.Entry(root, font=("Segoe UI", 14))
        cls.entry.place(x=20, y=20, width=600, height=40)
        cls.click_btn = tk.Button(root, text="Click me", command=lambda: cls.events.append("click"))
        cls.click_btn.place(x=20, y=80, width=200, height=60)
        cls.click_btn.bind("<Double-Button-1>", lambda e: cls.events.append("double"))
        cls.rbtn = tk.Label(root, text="Right click", bg="#ddd")
        cls.rbtn.place(x=240, y=80, width=180, height=60)
        cls.rbtn.bind("<Button-3>", lambda e: cls.events.append("right"))
        cls.drag = tk.Canvas(root, bg="#eef")
        cls.drag.place(x=440, y=80, width=180, height=60)
        cls.drag.bind("<B1-Motion>", lambda e: cls.events.append("drag-move"))
        cls.drag.bind("<ButtonRelease-1>", lambda e: cls.events.append("drag-release"))
        cls.listbox = tk.Listbox(root)
        for i in range(300):
            cls.listbox.insert("end", f"line {i}")
        cls.listbox.place(x=20, y=160, width=600, height=240)
        cls.pump(0.5)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.user32.SetCursorPos(*cls.orig_cursor)
            cls.root.destroy()
        finally:
            cls.server.shutdown()

    # ------------------------------------------------------------------ helpers
    @classmethod
    def pump(cls, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            cls.root.update()
            time.sleep(0.005)

    @classmethod
    def cursor(cls):
        pt = wintypes.POINT()
        cls.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def open_stream(self):
        s = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall((f"POST /api/input/stream HTTP/1.1\r\nHost: x\r\nX-Auth-Token: {self.token}\r\n"
                   "Content-Type: application/octet-stream\r\nTransfer-Encoding: chunked\r\n\r\n").encode())
        return s

    @staticmethod
    def send(s, *frames):
        data = b"".join(frames)
        s.sendall(b"%x\r\n" % len(data) + data + b"\r\n")

    @staticmethod
    def f(t, payload=b""):
        return struct.pack("<BBH", t, 0, len(payload)) + payload

    def key(self, vk, down):
        return self.f(0x20, struct.pack("<HBB", vk, 1 if down else 0, 0))

    def btn(self, b, down):
        return self.f(0x12, struct.pack("<BB", b, 1 if down else 0))

    def abs_to_widget(self, widget, fx=0.5, fy=0.5):
        x = widget.winfo_rootx() + int(widget.winfo_width() * fx)
        y = widget.winfo_rooty() + int(widget.winfo_height() * fy)
        m = self.mons[0]
        nx = round((x - m["left"]) / max(1, m["width"] - 1) * 65535)
        ny = round((y - m["top"]) / max(1, m["height"] - 1) * 65535)
        return self.f(0x11, struct.pack("<HHB", nx, ny, 0)), (x, y)

    def toplevel_hwnd(self):
        return int(self.root.wm_frame(), 16)

    def require_foreground(self, s):
        # Clicking our own topmost window is the legitimate way to make it foreground.
        frame, _ = self.abs_to_widget(self.entry, 0.9, 0.5)
        self.send(s, frame, self.btn(1, True), self.btn(1, False))
        self.pump(0.3)
        fg = self.user32.GetForegroundWindow()
        if fg != self.toplevel_hwnd():
            self.skipTest(f"test window is not foreground (fg={fg}), keyboard steps skipped for safety")
        self.entry.focus_set()
        self.pump(0.1)

    def end(self, s):
        self.send(s, self.f(0x03))
        s.sendall(b"0\r\n\r\n")
        s.close()

    # ------------------------------------------------------------------ tests
    def test_1_absolute_move_and_click(self):
        s = self.open_stream()
        self.events.clear()
        frame, (x, y) = self.abs_to_widget(self.click_btn)
        self.send(s, frame)
        self.pump(0.15)
        cx, cy = self.cursor()
        self.assertLessEqual(abs(cx - x), 2, f"cursor x {cx} vs {x}")
        self.assertLessEqual(abs(cy - y), 2, f"cursor y {cy} vs {y}")
        self.send(s, self.btn(1, True), self.btn(1, False))
        self.pump(0.3)
        self.assertIn("click", self.events)
        self.end(s)

    def test_2_relative_move(self):
        s = self.open_stream()
        frame, _ = self.abs_to_widget(self.listbox)
        self.send(s, frame)
        self.pump(0.1)
        x0, y0 = self.cursor()
        for _ in range(10):
            self.send(s, self.f(0x10, struct.pack("<hh", 6, 4)))
        self.pump(0.2)
        x1, y1 = self.cursor()
        self.assertGreater(x1 - x0, 20)
        self.assertGreater(y1 - y0, 10)
        self.end(s)

    def test_3_double_right_click_drag_scroll(self):
        s = self.open_stream()
        self.events.clear()
        frame, _ = self.abs_to_widget(self.click_btn)
        self.send(s, frame, self.btn(1, True), self.btn(1, False), self.btn(1, True), self.btn(1, False))
        self.pump(0.3)
        self.assertIn("double", self.events)
        frame, _ = self.abs_to_widget(self.rbtn)
        self.send(s, frame, self.btn(2, True), self.btn(2, False))
        self.pump(0.3)
        self.assertIn("right", self.events)
        # Tk may have opened nothing for the label; press Escape-free: drag inside the canvas
        frame_a, _ = self.abs_to_widget(self.drag, 0.2, 0.5)
        frame_b, _ = self.abs_to_widget(self.drag, 0.8, 0.5)
        self.send(s, frame_a, self.btn(1, True))
        self.pump(0.05)
        self.send(s, frame_b)
        self.pump(0.05)
        self.send(s, self.btn(1, False))
        self.pump(0.3)
        self.assertIn("drag-move", self.events)
        self.assertIn("drag-release", self.events)
        frame, _ = self.abs_to_widget(self.listbox)
        self.send(s, frame)
        self.pump(0.1)
        top0 = self.listbox.yview()[0]
        for _ in range(9):  # 9 * -40 = 3 wheel notches down (accumulated by the server)
            self.send(s, self.f(0x13, struct.pack("<hh", -40, 0)))
        self.pump(0.3)
        self.assertGreater(self.listbox.yview()[0], top0)
        self.end(s)

    def test_4_keyboard_unicode_hotkeys_repeat(self):
        s = self.open_stream()
        self.require_foreground(s)
        self.entry.delete(0, "end")
        self.send(s, self.f(0x22, "Hello Привіт ґЄї Ёж €😀".encode("utf-8")))
        self.pump(0.4)
        self.assertEqual(self.entry.get(), "Hello Привіт ґЄї Ёж €😀")

        # keyboard path: unicode press + release per key
        self.require_foreground(s)
        self.entry.icursor("end")
        for ch in "щ!":
            self.send(s, self.f(0x21, struct.pack("<IB", ord(ch), 1)), self.f(0x21, struct.pack("<IB", ord(ch), 0)))
        self.pump(0.3)
        self.assertTrue(self.entry.get().endswith("щ!"), self.entry.get())

        # Ctrl+C as a real VK chord (held Ctrl + physical C).
        # 1) layout independent: the window receives VK_C (keycode 67) with Ctrl held.
        keylog = []
        bid = self.entry.bind("<KeyPress>", lambda ev: keylog.append((ev.keycode, ev.state & 0x4)), add="+")
        # 2) functional: Tk maps shortcuts by character, so (exactly like a physical keyboard)
        #    Ctrl+C only works in Tk while a Latin layout is active -> activate US for this thread.
        prev_hkl = self.user32.GetKeyboardLayout(0)
        us_hkl = self.user32.LoadKeyboardLayoutW("00000409", 0)
        self.user32.ActivateKeyboardLayout(us_hkl, 0)
        try:
            self.require_foreground(s)
            self.root.clipboard_clear()
            self.entry.select_range(0, "end")
            self.pump(0.05)
            self.send(s, self.key(0xA2, True), self.key(0x43, True), self.key(0x43, False), self.key(0xA2, False))
            self.pump(0.4)
            self.assertIn((67, 0x4), keylog, f"VK_C with Ctrl not received: {keylog}")
            self.assertEqual(self.root.clipboard_get(), self.entry.get())
        finally:
            self.user32.ActivateKeyboardLayout(prev_hkl, 0)
            self.entry.unbind("<KeyPress>", bid)

        # HOTKEY frame Ctrl+V pastes into the field
        self.require_foreground(s)
        self.root.clipboard_clear()
        self.root.clipboard_append("PASTE_OK")
        self.entry.delete(0, "end")
        self.pump(0.05)
        self.send(s, self.f(0x23, struct.pack("<BHH", 2, 0xA2, 0x56)))
        self.pump(0.4)
        self.assertEqual(self.entry.get(), "PASTE_OK")
        self.assertFalse(self.user32.GetAsyncKeyState(0xA2) & 0x8000, "ctrl stuck after hotkey")

        # Backspace held 1.3 s -> server typematic repeat deletes many characters
        self.require_foreground(s)
        self.entry.delete(0, "end")
        self.entry.insert(0, "x" * 80)
        self.entry.icursor("end")
        self.pump(0.1)
        self.send(s, self.key(0x08, True))
        self.pump(1.3)
        self.send(s, self.key(0x08, False))
        self.pump(0.3)
        remaining = len(self.entry.get())
        self.assertLess(remaining, 75, f"autorepeat deleted only {80 - remaining} chars")
        self.assertGreater(remaining, 0)
        self.assertFalse(self.user32.GetAsyncKeyState(0x08) & 0x8000, "backspace stuck")
        print(f"\n[real-e2e] backspace held 1.3 s deleted {80 - remaining} characters")
        self.end(s)

    def test_5_abrupt_disconnect_releases_modifiers(self):
        s = self.open_stream()
        self.require_foreground(s)
        self.send(s, self.key(0xA0, True))  # hold Shift
        self.pump(0.15)
        self.assertTrue(self.user32.GetAsyncKeyState(0xA0) & 0x8000, "shift should be down")
        s.close()  # phone vanished without END
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and self.user32.GetAsyncKeyState(0xA0) & 0x8000:
            self.pump(0.05)
        self.assertFalse(self.user32.GetAsyncKeyState(0xA0) & 0x8000, "shift stuck after disconnect")

    def test_6_cursor_is_drawn_into_captured_frames(self):
        """Regression: the H.264 capture (BitBlt) had no mouse pointer at all, so on the phone
        the cursor was invisible / only guessable from hover effects."""
        import av
        from modules.streaming import _FastDIBSection

        import tkinter as tk

        # Flat-coloured topmost window under the pointer
        flat = tk.Toplevel(self.root)
        flat.overrideredirect(True)
        flat.geometry(f"240x240+{self.root.winfo_rootx() + 200}+{self.root.winfo_rooty() + 100}")
        flat.configure(bg="#3070b0")
        flat.attributes("-topmost", True)
        self.pump(0.4)
        x = flat.winfo_rootx() + 100
        y = flat.winfo_rooty() + 100
        self.user32.SetCursorPos(x, y)
        self.pump(0.3)
        left, top, w, h = x - 40, y - 40, 96, 96
        cap = _FastDIBSection(left, top, w, h)
        try:
            vf = av.VideoFrame(w, h, "bgra")

            def grab(draw):
                cap.draw_cursor_enabled = draw
                self.assertTrue(cap.grab_into(vf))
                arr = vf.to_ndarray()
                return arr.reshape(h, w, 4)[:, :, :3].astype(int)

            plain = grab(False)
            # несколько кадров подряд: раньше курсор был только в первом (cbSize обнулялся)
            for _ in range(3):
                grab(True)
            with_cursor = grab(True)
            # without the pointer the 96x96 region is the flat canvas colour
            self.assertLess(int(abs(plain - plain[2, 2]).sum()), 3 * w * h // 50)
            diff = abs(with_cursor - plain).sum(axis=2)
            ys, xs = (diff > 30).nonzero()
            self.assertGreater(len(xs), 20, "pointer not drawn into the frame")
            # pointer pixels start at its hotspot (screen pos - capture origin = 40,40)
            self.assertLessEqual(abs(int(xs.min()) - 40), 16)
            self.assertLessEqual(abs(int(ys.min()) - 40), 16)
            print(f"\n[real-e2e] pointer drawn: {len(xs)} px changed, bbox x {xs.min()}..{xs.max()} y {ys.min()}..{ys.max()}")
        finally:
            cap.close()
            flat.destroy()


if __name__ == "__main__":
    unittest.main()
