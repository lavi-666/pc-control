"""
PC Control - binary low-latency input stream engine.

Design notes (ideas adapted, no code copied - reference projects are GPL/AGPL):
  * Sunshine (src/input.cpp): server-side key state with duplicate press/release
    suppression, server-side autorepeat of the last held key, accumulation of
    high-resolution scroll into whole WHEEL_DELTA ticks, release of everything
    when the client goes away.
  * RustDesk (src/server/input_service.rs): table of held keys and a background
    timer that force-releases keys that were left pressed (stuck-key protection).
  * Moonlight / KDE Connect: one persistent ordered connection per client
    instead of a request per event; compact typed packets.

Wire format (little endian), carried in the body of one long-lived chunked
HTTP POST (/api/input/stream):

    header : u8 type, u8 flags, u16 payload_length
    payload: type specific, see FRAME_* below.

The engine is transport and OS independent: it drives an injectable backend,
so it is fully unit-testable on any platform.
"""

from __future__ import annotations

import struct
import threading
import time
from typing import Callable, Optional

PROTOCOL_VERSION = 1

FRAME_HELLO = 0x01        # u16 protocol version
FRAME_PING = 0x02         # no payload, keeps the session alive
FRAME_END = 0x03          # graceful end of stream
FRAME_RELEASE_ALL = 0x04  # release everything this session holds
FRAME_MOUSE_REL = 0x10    # i16 dx, i16 dy
FRAME_MOUSE_ABS = 0x11    # u16 x, u16 y (0..65535 inside monitor), u8 monitor (0 = all)
FRAME_MOUSE_BTN = 0x12    # u8 button (1 L, 2 R, 3 M, 4 X1, 5 X2), u8 down
FRAME_SCROLL = 0x13       # i16 vertical, i16 horizontal (WHEEL_DELTA = 120 per notch)
FRAME_KEY = 0x20          # u16 vk, u8 down, u8 flags (bit0 = extended)
FRAME_UNICODE = 0x21      # u32 code point, u8 down
FRAME_TEXT = 0x22         # utf-8 text, typed as press+release per character
FRAME_HOTKEY = 0x23       # u8 count, count * u16 vk (press in order, release reversed)

HEADER = struct.Struct("<BBH")
MAX_PAYLOAD = 4096
WHEEL_DELTA = 120

BUTTON_LEFT, BUTTON_RIGHT, BUTTON_MIDDLE, BUTTON_X1, BUTTON_X2 = 1, 2, 3, 4, 5
VALID_BUTTONS = {BUTTON_LEFT, BUTTON_RIGHT, BUTTON_MIDDLE, BUTTON_X1, BUTTON_X2}

# Modifier and lock keys never autorepeat (same rule as Sunshine/Windows).
MODIFIER_VKS = {
    0x10, 0x11, 0x12,              # shift, ctrl, alt
    0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,
    0x5B, 0x5C,                    # win
    0x14, 0x90, 0x91,              # caps, num, scroll lock
}

DEFAULT_REPEAT_DELAY = 0.5
DEFAULT_REPEAT_PERIOD = 1.0 / 30.0
DEFAULT_WATCHDOG_TIMEOUT = 3.5


class ProtocolError(Exception):
    pass


class InputBackend:
    """Interface of an OS input injector. Every call must be non-blocking."""

    def move_rel(self, dx: int, dy: int) -> None: ...
    def move_abs(self, x: int, y: int, monitor: int) -> None: ...
    def button(self, button: int, down: bool) -> None: ...
    def wheel(self, vertical: int, horizontal: int) -> None: ...
    def key(self, vk: int, down: bool, extended: bool) -> None: ...
    def unicode(self, code_point: int, down: bool) -> None: ...


class RecordingBackend(InputBackend):
    """Backend that records calls; used by tests and the dry-run mode."""

    def __init__(self):
        self.events: list[tuple] = []
        self.lock = threading.Lock()

    def _add(self, *ev):
        with self.lock:
            self.events.append(ev)

    def move_rel(self, dx, dy):
        self._add("move_rel", dx, dy)

    def move_abs(self, x, y, monitor):
        self._add("move_abs", x, y, monitor)

    def button(self, button, down):
        self._add("button", button, down)

    def wheel(self, vertical, horizontal):
        self._add("wheel", vertical, horizontal)

    def key(self, vk, down, extended):
        self._add("key", vk, down, extended)

    def unicode(self, code_point, down):
        self._add("unicode", code_point, down)

    def snapshot(self) -> list[tuple]:
        with self.lock:
            return list(self.events)


class InputSession:
    """State machine of one client input stream."""

    def __init__(
        self,
        backend: InputBackend,
        clock: Callable[[], float] = time.monotonic,
        repeat_delay: float = DEFAULT_REPEAT_DELAY,
        repeat_period: float = DEFAULT_REPEAT_PERIOD,
        watchdog_timeout: float = DEFAULT_WATCHDOG_TIMEOUT,
    ):
        self.backend = backend
        self.clock = clock
        self.repeat_delay = repeat_delay
        self.repeat_period = repeat_period
        self.watchdog_timeout = watchdog_timeout
        self.lock = threading.RLock()

        self.held_keys: dict[int, bool] = {}       # vk -> extended
        self.held_unicode: set[int] = set()
        self.held_buttons: set[int] = set()
        self._scroll_v = 0
        self._scroll_h = 0
        self._repeat: Optional[tuple] = None        # ("key", vk, ext) | ("unicode", cp)
        self._repeat_due = 0.0

        self.last_seen = clock()
        self.closed = False
        self.frames = 0
        self.watchdog_releases = 0
        self.client_version = 0

    # ------------------------------------------------------------------ frames
    def handle_frame(self, ftype: int, flags: int, payload: bytes) -> bool:
        """Applies one frame. Returns False when the client ended the stream."""
        with self.lock:
            if self.closed:
                return False
            self.last_seen = self.clock()
            self.frames += 1

            if ftype == FRAME_MOUSE_REL:
                dx, dy = _unpack("<hh", payload)
                if dx or dy:
                    self.backend.move_rel(dx, dy)
            elif ftype == FRAME_MOUSE_ABS:
                x, y, mon = _unpack("<HHB", payload)
                self.backend.move_abs(x, y, mon)
            elif ftype == FRAME_MOUSE_BTN:
                btn, down = _unpack("<BB", payload)
                self._button(btn, bool(down))
            elif ftype == FRAME_SCROLL:
                v, h = _unpack("<hh", payload)
                self._scroll(v, h)
            elif ftype == FRAME_KEY:
                vk, down, kflags = _unpack("<HBB", payload)
                self._key(vk, bool(down), bool(kflags & 0x01))
            elif ftype == FRAME_UNICODE:
                cp, down = _unpack("<IB", payload)
                self._unicode(cp, bool(down))
            elif ftype == FRAME_TEXT:
                self._text(payload.decode("utf-8", errors="replace"))
            elif ftype == FRAME_HOTKEY:
                self._hotkey(payload)
            elif ftype == FRAME_RELEASE_ALL:
                self.release_all()
            elif ftype == FRAME_HELLO:
                (self.client_version,) = _unpack("<H", payload)
            elif ftype == FRAME_PING:
                pass
            elif ftype == FRAME_END:
                self.release_all()
                return False
            # Unknown frame types are skipped for forward compatibility.
            return True

    def _button(self, btn: int, down: bool):
        if btn not in VALID_BUTTONS:
            raise ProtocolError(f"bad mouse button {btn}")
        if down == (btn in self.held_buttons):
            return  # duplicate press/release
        if down:
            self.held_buttons.add(btn)
        else:
            self.held_buttons.discard(btn)
        self.backend.button(btn, down)

    def _scroll(self, v: int, h: int):
        self._scroll_v += v
        self._scroll_h += h
        tv = int(self._scroll_v / WHEEL_DELTA)
        th = int(self._scroll_h / WHEEL_DELTA)
        if tv or th:
            self._scroll_v -= tv * WHEEL_DELTA
            self._scroll_h -= th * WHEEL_DELTA
            self.backend.wheel(tv * WHEEL_DELTA, th * WHEEL_DELTA)

    def _key(self, vk: int, down: bool, extended: bool):
        if not 0 < vk < 0xFF:
            raise ProtocolError(f"bad virtual key {vk}")
        if down:
            if vk in self.held_keys:
                return
            self.held_keys[vk] = extended
            self.backend.key(vk, True, extended)
            if vk not in MODIFIER_VKS:
                self._start_repeat(("key", vk, extended))
        else:
            if vk not in self.held_keys:
                return
            ext = self.held_keys.pop(vk)
            if self._repeat and self._repeat[0] == "key" and self._repeat[1] == vk:
                self._repeat = None
            self.backend.key(vk, False, ext)

    def _unicode(self, cp: int, down: bool):
        if not 0 < cp <= 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
            raise ProtocolError(f"bad code point {cp}")
        if down:
            if cp in self.held_unicode:
                return
            self.held_unicode.add(cp)
            self.backend.unicode(cp, True)
            self._start_repeat(("unicode", cp))
        else:
            if cp not in self.held_unicode:
                return
            self.held_unicode.discard(cp)
            if self._repeat and self._repeat[0] == "unicode" and self._repeat[1] == cp:
                self._repeat = None
            self.backend.unicode(cp, False)

    def _text(self, text: str):
        for ch in text:
            cp = ord(ch)
            if cp in (0x0A, 0x0D):
                self.backend.key(0x0D, True, False)
                self.backend.key(0x0D, False, False)
                continue
            if 0xD800 <= cp <= 0xDFFF:
                continue
            self.backend.unicode(cp, True)
            self.backend.unicode(cp, False)

    def _hotkey(self, payload: bytes):
        if not payload:
            raise ProtocolError("empty hotkey")
        count = payload[0]
        if count == 0 or count > 8 or len(payload) != 1 + 2 * count:
            raise ProtocolError("bad hotkey payload")
        vks = list(struct.unpack_from("<" + "H" * count, payload, 1))
        pressed = []
        for vk in vks:
            if not 0 < vk < 0xFF:
                raise ProtocolError(f"bad virtual key {vk}")
            if vk in self.held_keys:
                continue  # already held (e.g. latched Ctrl): do not toggle it
            self.backend.key(vk, True, False)
            pressed.append(vk)
        for vk in reversed(pressed):
            self.backend.key(vk, False, False)

    def _start_repeat(self, what: tuple):
        self._repeat = what
        self._repeat_due = self.clock() + self.repeat_delay

    # ------------------------------------------------------------------ timers
    def tick(self) -> float:
        """Runs autorepeat and the stuck-input watchdog.
        Returns seconds until the next tick is needed."""
        with self.lock:
            if self.closed:
                return 1.0
            now = self.clock()
            if self.has_held_inputs() and now - self.last_seen > self.watchdog_timeout:
                # Client went silent while holding keys/buttons: never leave them stuck.
                self.watchdog_releases += 1
                self.release_all()
                return 0.25
            wait = 0.25
            if self._repeat is not None:
                if now >= self._repeat_due:
                    kind = self._repeat[0]
                    if kind == "key":
                        _, vk, ext = self._repeat
                        self.backend.key(vk, True, ext)
                    else:
                        self.backend.unicode(self._repeat[1], True)
                    self._repeat_due = max(now, self._repeat_due) + self.repeat_period
                wait = min(wait, max(0.001, self._repeat_due - now))
            if self.has_held_inputs():
                wait = min(wait, max(0.01, self.watchdog_timeout - (now - self.last_seen)))
            return wait

    def has_held_inputs(self) -> bool:
        return bool(self.held_keys or self.held_unicode or self.held_buttons)

    def release_all(self):
        with self.lock:
            self._repeat = None
            for cp in list(self.held_unicode):
                self.backend.unicode(cp, False)
            self.held_unicode.clear()
            # Non-modifiers first, modifiers last (so no accidental hotkeys fire).
            keys = sorted(self.held_keys.items(), key=lambda kv: kv[0] in MODIFIER_VKS)
            for vk, ext in keys:
                self.backend.key(vk, False, ext)
            self.held_keys.clear()
            for btn in sorted(self.held_buttons):
                self.backend.button(btn, False)
            self.held_buttons.clear()
            self._scroll_v = self._scroll_h = 0

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.release_all()
            self.closed = True


def _unpack(fmt: str, payload: bytes) -> tuple:
    try:
        return struct.unpack(fmt, payload)
    except struct.error as e:
        raise ProtocolError(f"bad payload for {fmt}: {len(payload)} bytes") from e


def run_stream(read_exact: Callable[[int], Optional[bytes]], session: InputSession) -> str:
    """Reads frames until EOF/END. read_exact(n) returns exactly n bytes or None on EOF.
    Returns the end reason: "end", "eof"."""
    while True:
        header = read_exact(HEADER.size)
        if header is None:
            return "eof"
        ftype, flags, length = HEADER.unpack(header)
        if length > MAX_PAYLOAD:
            raise ProtocolError(f"payload too large: {length}")
        payload = b""
        if length:
            payload = read_exact(length)
            if payload is None:
                return "eof"
        if not session.handle_frame(ftype, flags, payload):
            return "end"


class SessionTicker(threading.Thread):
    """Drives InputSession.tick() (autorepeat + watchdog) until the session closes."""

    def __init__(self, session: InputSession):
        super().__init__(name="pc-input-ticker", daemon=True)
        self.session = session
        self.wake = threading.Event()

    def run(self):
        while not self.session.closed:
            try:
                wait = self.session.tick()
            except Exception:
                wait = 0.25
            self.wake.wait(wait)
            self.wake.clear()

    def stop(self):
        self.wake.set()


def encode_frame(ftype: int, payload: bytes = b"", flags: int = 0) -> bytes:
    """Helper used by tests and tools to build frames."""
    return HEADER.pack(ftype, flags, len(payload)) + payload
