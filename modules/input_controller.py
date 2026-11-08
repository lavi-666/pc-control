"""
PC Control — Модуль удалённого управления мышью, клавиатурой и микрофоном (Input Controller).
Обеспечивает низколатентный ввод SendInput для Windows и приём звука микрофона Android-телефона.
"""

import atexit
import ctypes
from ctypes import wintypes
import json
import os
import platform
import socket
import struct
import sys
import threading
import time
from typing import Any
from flask import Blueprint, Response, jsonify, request

from core.auth import check_token
from core.logger import log_action, log_error
from modules.system import _attach_input_desktop
from modules.input_engine import (
    DEFAULT_REPEAT_DELAY,
    DEFAULT_REPEAT_PERIOD,
    DEFAULT_WATCHDOG_TIMEOUT,
    PROTOCOL_VERSION,
    InputBackend,
    InputSession,
    ProtocolError,
    RecordingBackend,
    SessionTicker,
    run_stream,
)

input_bp = Blueprint("input_controller", __name__)

IS_WINDOWS = platform.system() == "Windows"

# Константы SendInput Windows API
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

# Флаги событий мыши
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

# Флаги событий клавиатуры
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# Виртуальные клавиши Windows (Virtual Key Codes)
VK_MAP = {
    "backspace": 0x08, "back": 0x08,
    "tab": 0x09,
    "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "lshift": 0xA0, "rshift": 0xA1,
    "ctrl": 0x11, "control": 0x11, "lctrl": 0xA2, "rctrl": 0xA3,
    "alt": 0x12, "lalt": 0xA4, "ralt": 0xA5,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22,
    "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "prtsc": 0x2C,
    "insert": 0x2D, "del": 0x2E, "delete": 0x2E,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

# Расширенные клавиши Windows (Extended Keys: стрелки, Del, Home, End, Win и др.)
EXTENDED_VKS = {
    0x21, 0x22,  # pageup, pagedown
    0x23, 0x24,  # end, home
    0x25, 0x26, 0x27, 0x28,  # left, up, right, down
    0x2D, 0x2E,  # insert, delete
    0x5B, 0x5C,  # lwin, rwin
    0xA3, 0xA5,  # rctrl, ralt
}

# Инициализация ctypes структур SendInput
if IS_WINDOWS:
    ULONG_PTR = wintypes.WPARAM

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTUnion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUnion)]


_input_lock = threading.Lock()
_held_keys: set[int] = set()
_held_mouse_buttons: set[str] = set()


def _send_inputs(inputs: list) -> int:
    """Выполняет вызов Windows user32.SendInput с привязкой к активному десктопу."""
    if not IS_WINDOWS or not inputs:
        return 0
    try:
        _attach_input_desktop()
        user32 = ctypes.windll.user32
        arr = (INPUT * len(inputs))(*inputs)
        return user32.SendInput(len(inputs), ctypes.byref(arr), ctypes.sizeof(INPUT))
    except Exception as e:
        log_error("send_inputs", e)
        return 0


def _get_virtual_desktop_metrics() -> tuple[int, int, int, int]:
    """Возвращает виртуальные координаты рабочего стола (SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CX, SM_CY)."""
    if not IS_WINDOWS:
        return (0, 0, 1920, 1080)
    try:
        user32 = ctypes.windll.user32
        vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        if vw > 0 and vh > 0:
            return (vx, vy, vw, vh)
    except Exception:
        pass
    return (0, 0, 1920, 1080)


_monitor_cache: dict[str, Any] = {"t": 0.0, "mons": None}
_monitor_cache_lock = threading.Lock()
_MONITOR_CACHE_TTL = 2.0


def _get_mss_monitors() -> list | None:
    """Список мониторов MSS (тот же порядок, что и у захвата экрана) с кэшем на 2 с.
    Раньше mss.MSS() создавался на КАЖДОЕ абсолютное движение мыши (несколько мс на событие)."""
    now = time.monotonic()
    with _monitor_cache_lock:
        if _monitor_cache["mons"] is not None and now - _monitor_cache["t"] < _MONITOR_CACHE_TTL:
            return _monitor_cache["mons"]
    try:
        import mss
        with mss.MSS() as sct:
            mons = [dict(m) for m in sct.monitors]
    except Exception:
        mons = None
    with _monitor_cache_lock:
        _monitor_cache["mons"] = mons
        _monitor_cache["t"] = now
    return mons


def _get_monitor_bounds(monitor_idx: int) -> tuple[int, int, int, int]:
    """Возвращает прямоугольник (left, top, width, height) для указанного монитора MSS."""
    mons = _get_mss_monitors()
    if mons:
        if 0 < monitor_idx < len(mons):
            m = mons[monitor_idx]
        else:
            m = mons[0]  # 0 = все мониторы (общий прямоугольник)
        return (m["left"], m["top"], m["width"], m["height"])
    return _get_virtual_desktop_metrics()


def _normalized_to_absolute(nx: float, ny: float, monitor_idx: int) -> tuple[int, int]:
    """Нормализованная точка монитора (0..1) -> координаты SendInput 0..65535 виртуального стола."""
    # Мониторы запрашиваются первыми: mss включает DPI-awareness процесса,
    # после чего GetSystemMetrics возвращает физические пиксели в той же системе координат.
    m_left, m_top, m_w, m_h = _get_monitor_bounds(monitor_idx)
    vx, vy, vw, vh = _get_virtual_desktop_metrics()
    pixel_x = m_left + max(0.0, min(1.0, nx)) * max(0, m_w - 1)
    pixel_y = m_top + max(0.0, min(1.0, ny)) * max(0, m_h - 1)
    norm_x = int(round(((pixel_x - vx) * 65535.0) / max(1.0, float(vw - 1))))
    norm_y = int(round(((pixel_y - vy) * 65535.0) / max(1.0, float(vh - 1))))
    return max(0, min(65535, norm_x)), max(0, min(65535, norm_y))


def mouse_move_relative(dx: float, dy: float, sensitivity: float = 1.0, accel: bool = True) -> bool:
    """Относительное перемещение курсора мыши для тачпада."""
    if not IS_WINDOWS:
        return True
    with _input_lock:
        factor = max(0.1, min(5.0, sensitivity))
        # Нелинейное ускорение (Mouse Acceleration curve) для коротких и быстрых движений
        dist = (dx * dx + dy * dy) ** 0.5
        accel_factor = 1.0
        if accel:
            if dist > 30:
                accel_factor = 1.6
            elif dist > 15:
                accel_factor = 1.3
            elif dist > 5:
                accel_factor = 1.1

        idx = int(round(dx * factor * accel_factor))
        idy = int(round(dy * factor * accel_factor))

        if idx == 0 and idy == 0:
            if dx != 0:
                idx = 1 if dx > 0 else -1
            if dy != 0:
                idy = 1 if dy > 0 else -1

        inp = INPUT(
            type=INPUT_MOUSE,
            u=_INPUTUnion(mi=MOUSEINPUT(dx=idx, dy=idy, mouseData=0, dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=0))
        )
        return _send_inputs([inp]) > 0


def mouse_move_normalized(nx: float, ny: float, monitor_idx: int = 1) -> bool:
    """Абсолютное перемещение курсора мыши с точной нормализацией виртуального экрана."""
    if not IS_WINDOWS:
        return True
    norm_x, norm_y = _normalized_to_absolute(nx, ny, monitor_idx)
    with _input_lock:
        inp = INPUT(
            type=INPUT_MOUSE,
            u=_INPUTUnion(
                mi=MOUSEINPUT(
                    dx=norm_x,
                    dy=norm_y,
                    mouseData=0,
                    dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                    time=0,
                    dwExtraInfo=0
                )
            )
        )
        return _send_inputs([inp]) > 0


def mouse_button_event(button: str, is_down: bool) -> bool:
    """Событие нажатия или отпускания кнопки мыши ('left', 'right', 'middle')."""
    if not IS_WINDOWS:
        return True
    with _input_lock:
        b = button.lower().strip()
        if b == "right":
            flags = MOUSEEVENTF_RIGHTDOWN if is_down else MOUSEEVENTF_RIGHTUP
        elif b == "middle":
            flags = MOUSEEVENTF_MIDDLEDOWN if is_down else MOUSEEVENTF_MIDDLEUP
        else:
            flags = MOUSEEVENTF_LEFTDOWN if is_down else MOUSEEVENTF_LEFTUP

        if is_down:
            _held_mouse_buttons.add(b)
        else:
            _held_mouse_buttons.discard(b)

        inp = INPUT(
            type=INPUT_MOUSE,
            u=_INPUTUnion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0))
        )
        return _send_inputs([inp]) > 0


def mouse_click(button: str = "left", double: bool = False) -> bool:
    """Одиночный или двойной клик кнопки мыши."""
    if not IS_WINDOWS:
        return True
    b = button.lower().strip()
    if b == "right":
        down_f, up_f = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    elif b == "middle":
        down_f, up_f = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
    else:
        down_f, up_f = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP

    with _input_lock:
        seq = [
            INPUT(type=INPUT_MOUSE, u=_INPUTUnion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_f, time=0, dwExtraInfo=0))),
            INPUT(type=INPUT_MOUSE, u=_INPUTUnion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_f, time=0, dwExtraInfo=0))),
        ]
        if double:
            seq.extend([
                INPUT(type=INPUT_MOUSE, u=_INPUTUnion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_f, time=0, dwExtraInfo=0))),
                INPUT(type=INPUT_MOUSE, u=_INPUTUnion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_f, time=0, dwExtraInfo=0))),
            ])
        return _send_inputs(seq) > 0


def mouse_scroll(dy: int) -> bool:
    """Прокрутка колеса мыши (WHEEL)."""
    if not IS_WINDOWS or dy == 0:
        return True
    with _input_lock:
        # В Windows один щелчок колеса = WHEEL_DELTA = 120
        delta = int(dy * 120)
        inp = INPUT(
            type=INPUT_MOUSE,
            u=_INPUTUnion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=delta, dwFlags=MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=0))
        )
        return _send_inputs([inp]) > 0


def keyboard_key_event(vk_code: int, is_down: bool, extended: bool = False) -> bool:
    """Событие нажатия или отпускания клавиши по виртуальному коду (VK)."""
    if not IS_WINDOWS or vk_code <= 0:
        return True
    with _input_lock:
        flags = 0
        if not is_down:
            flags |= KEYEVENTF_KEYUP
        if extended or vk_code in EXTENDED_VKS:
            flags |= KEYEVENTF_EXTENDEDKEY

        if is_down:
            _held_keys.add(vk_code)
        else:
            _held_keys.discard(vk_code)

        inp = INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTUnion(ki=KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0))
        )
        return _send_inputs([inp]) > 0


def keyboard_text_unicode(text: str) -> bool:
    """Ввод произвольного Unicode-текста (русский, украинский, английский, символы) через UTF-16."""
    if not IS_WINDOWS or not text:
        return True
    with _input_lock:
        seq = []
        # Windows KEYEVENTF_UNICODE передает 16-битные кодовые единицы UTF-16 в wScan
        for ch in text:
            utf16_bytes = ch.encode("utf-16-le")
            for i in range(0, len(utf16_bytes), 2):
                code = int.from_bytes(utf16_bytes[i:i + 2], byteorder="little")
                seq.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0))))
                seq.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))))
        return _send_inputs(seq) > 0


def keyboard_hotkey(keys: list[str]) -> bool:
    """Выполнение горячей комбинации клавиш (например, ['ctrl', 'c'], ['alt', 'tab'], ['win', 'd'])."""
    if not IS_WINDOWS or not keys:
        return True
    vk_list = []
    for k in keys:
        name = k.lower().strip()
        vk = VK_MAP.get(name)
        if not vk and len(name) == 1:
            vk = ord(name.upper())
        if vk:
            vk_list.append(vk)

    if not vk_list:
        return False

    with _input_lock:
        seq = []
        # Нажимаем все клавиши по порядку
        for vk in vk_list:
            seq.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))))
        # Отпускаем в обратном порядке
        for vk in reversed(vk_list):
            seq.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))))
        return _send_inputs(seq) > 0


def release_all_inputs():
    """Сбрасывает все удерживаемые клавиши и кнопки мыши во избежание залипания при отключении."""
    if not IS_WINDOWS:
        return
    with _input_lock:
        seq = []
        # Отпускаем мышь
        for b in list(_held_mouse_buttons):
            if b == "right":
                up_f = MOUSEEVENTF_RIGHTUP
            elif b == "middle":
                up_f = MOUSEEVENTF_MIDDLEUP
            else:
                up_f = MOUSEEVENTF_LEFTUP
            seq.append(INPUT(type=INPUT_MOUSE, u=_INPUTUnion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_f, time=0, dwExtraInfo=0))))
        _held_mouse_buttons.clear()

        # Отпускаем все зажатые клавиши и стандартные модификаторы
        all_to_release = set(_held_keys) | {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x10, 0x11, 0x12}
        for vk in all_to_release:
            flags = KEYEVENTF_KEYUP
            if vk in EXTENDED_VKS:
                flags |= KEYEVENTF_EXTENDEDKEY
            seq.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0))))
        _held_keys.clear()

        if seq:
            _send_inputs(seq)


# ---------------------------------------------------------------------------
# БИНАРНЫЙ ПОТОК ВВОДА (одно постоянное соединение на клиента, см. modules/input_engine.py)
# ---------------------------------------------------------------------------
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_HWHEEL = 0x01000
MAPVK_VK_TO_VSC_EX = 4

INPUT_STREAM_IDLE_TIMEOUT = 12.0  # клиент шлёт PING каждую секунду; тишина 12 с = мёртвое соединение


class SendInputBackend(InputBackend):
    """Реальный ввод Windows через SendInput.
    Клавиши отправляются с VK и аппаратным скан-кодом (MapVirtualKeyW), как у физической
    клавиатуры: так комбинации и клавиши работают и в обычных приложениях, и в играх."""

    def __init__(self):
        self._scan_cache: dict[int, tuple[int, bool]] = {}

    @staticmethod
    def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0):
        return INPUT(type=INPUT_MOUSE, u=_INPUTUnion(mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=0)))

    def _send(self, inputs: list):
        with _input_lock:
            _send_inputs(inputs)

    def move_rel(self, dx, dy):
        self._send([self._mouse(MOUSEEVENTF_MOVE, dx, dy)])

    def move_abs(self, x, y, monitor):
        ax, ay = _normalized_to_absolute(x / 65535.0, y / 65535.0, monitor)
        self._send([self._mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)])

    def button(self, button, down):
        data = 0
        if button == 1:
            flags = MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
        elif button == 2:
            flags = MOUSEEVENTF_RIGHTDOWN if down else MOUSEEVENTF_RIGHTUP
        elif button == 3:
            flags = MOUSEEVENTF_MIDDLEDOWN if down else MOUSEEVENTF_MIDDLEUP
        else:
            flags = MOUSEEVENTF_XDOWN if down else MOUSEEVENTF_XUP
            data = 1 if button == 4 else 2
        self._send([self._mouse(flags, data=data)])

    def wheel(self, vertical, horizontal):
        seq = []
        if vertical:
            seq.append(self._mouse(MOUSEEVENTF_WHEEL, data=vertical))
        if horizontal:
            seq.append(self._mouse(MOUSEEVENTF_HWHEEL, data=horizontal))
        if seq:
            self._send(seq)

    def _scan_for(self, vk: int) -> tuple[int, bool]:
        cached = self._scan_cache.get(vk)
        if cached is None:
            sc = 0
            try:
                sc = int(ctypes.windll.user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX))
            except Exception:
                sc = 0
            ext = (sc & 0xFF00) in (0xE000, 0xE100)
            cached = (sc & 0xFF, ext)
            self._scan_cache[vk] = cached
        return cached

    def key(self, vk, down, extended):
        scan, scan_ext = self._scan_for(vk)
        flags = 0 if down else KEYEVENTF_KEYUP
        if extended or scan_ext or vk in EXTENDED_VKS:
            flags |= KEYEVENTF_EXTENDEDKEY
        if down:
            _held_keys.add(vk)
        else:
            _held_keys.discard(vk)
        self._send([INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)))])

    def unicode(self, code_point, down):
        units = chr(code_point).encode("utf-16-le")
        flags = KEYEVENTF_UNICODE | (0 if down else KEYEVENTF_KEYUP)
        seq = []
        for i in range(0, len(units), 2):
            code = int.from_bytes(units[i:i + 2], "little")
            seq.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags, time=0, dwExtraInfo=0))))
        self._send(seq)


_input_backend_factory = None
_active_input_sessions: set = set()
_active_input_sessions_lock = threading.Lock()


def set_input_backend_factory(factory) -> None:
    """Подмена бэкенда ввода (тесты / сухой прогон). None = реальный SendInput."""
    global _input_backend_factory
    _input_backend_factory = factory


def _make_input_backend() -> InputBackend:
    if _input_backend_factory is not None:
        return _input_backend_factory()
    if IS_WINDOWS:
        return SendInputBackend()
    return RecordingBackend()


def _keyboard_repeat_timing() -> tuple[float, float]:
    """Задержка и частота автоповтора как в настройках клавиатуры Windows."""
    delay, period = DEFAULT_REPEAT_DELAY, DEFAULT_REPEAT_PERIOD
    if IS_WINDOWS:
        try:
            val = wintypes.DWORD()
            spi = ctypes.windll.user32.SystemParametersInfoW
            if spi(0x0016, 0, ctypes.byref(val), 0):  # SPI_GETKEYBOARDDELAY: 0..3
                delay = 0.25 * (min(3, val.value) + 1)
            if spi(0x000A, 0, ctypes.byref(val), 0):  # SPI_GETKEYBOARDSPEED: 0..31 -> ~2.5..30 cps
                cps = 2.5 + (min(31, val.value) / 31.0) * 27.5
                period = 1.0 / cps
        except Exception:
            pass
    return delay, period


def _release_all_input_sessions():
    with _active_input_sessions_lock:
        sessions = list(_active_input_sessions)
    for s in sessions:
        try:
            s.close()
        except Exception:
            pass


atexit.register(_release_all_input_sessions)


@input_bp.route("/api/input/info", methods=["GET"])
def api_input_info():
    """Возможности потока ввода. Клиент вызывает перед открытием /api/input/stream."""
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401
    delay, period = _keyboard_repeat_timing()
    mons = _get_mss_monitors() or []
    with _active_input_sessions_lock:
        n = len(_active_input_sessions)
    return jsonify({
        "protocol": PROTOCOL_VERSION,
        "stream": "/api/input/stream",
        "repeat_delay_ms": int(delay * 1000),
        "repeat_period_ms": int(period * 1000),
        "watchdog_ms": int(DEFAULT_WATCHDOG_TIMEOUT * 1000),
        "idle_timeout_ms": int(INPUT_STREAM_IDLE_TIMEOUT * 1000),
        "monitors": [{"index": i, "left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]} for i, m in enumerate(mons)],
        "active_sessions": n,
    })


@input_bp.route("/api/input/stream", methods=["POST"])
def api_input_stream():
    """Постоянный поток событий ввода (chunked POST, бинарные кадры input_engine).
    Тело читается напрямую из wsgi.input: request.stream ограничен MAX_CONTENT_LENGTH (1 МБ)
    и оборвал бы долгую сессию управления."""
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    env = request.environ
    raw = env.get("wsgi.input")
    remaining = None
    if not env.get("wsgi.input_terminated"):
        remaining = request.content_length
        if remaining is None:
            return jsonify({"message": "Chunked transfer encoding or Content-Length required"}), 411

    sock = env.get("werkzeug.socket")
    if sock is not None:
        try:
            sock.settimeout(INPUT_STREAM_IDLE_TIMEOUT)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    def read_exact(n: int):
        nonlocal remaining
        if remaining is not None and remaining < n:
            return None
        buf = bytearray()
        while len(buf) < n:
            chunk = raw.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        if remaining is not None:
            remaining -= n
        return bytes(buf)

    delay, period = _keyboard_repeat_timing()
    session = InputSession(_make_input_backend(), repeat_delay=delay, repeat_period=period)
    ticker = SessionTicker(session)
    with _active_input_sessions_lock:
        _active_input_sessions.add(session)
    ticker.start()
    started = time.monotonic()
    reason = "error"
    status = 200
    try:
        reason = run_stream(read_exact, session)
    except ProtocolError as e:
        reason = f"protocol_error: {e}"
        status = 400
    except (OSError, ValueError) as e:  # socket timeout / reset / closed stream
        reason = f"connection: {type(e).__name__}"
    finally:
        session.close()
        ticker.stop()
        with _active_input_sessions_lock:
            _active_input_sessions.discard(session)
        log_action("input_stream_closed", {
            "reason": reason,
            "frames": session.frames,
            "seconds": round(time.monotonic() - started, 1),
            "watchdog_releases": session.watchdog_releases,
        })
    return jsonify({"ok": status == 200, "reason": reason, "frames": session.frames}), status


# ---------------------------------------------------------------------------
# АУДИОКОНВЕЙЕР: ПЕРЕДАЧА МИКРОФОНА ТЕЛЕФОНА НА ПК (PHONE MIC -> WINDOWS)
# ---------------------------------------------------------------------------
_mic_playback_stream = None
_mic_playback_pa = None
_mic_playback_lock = threading.Lock()
_mic_active = False
_mic_virtual_detected = False
_mic_active_device_name = "No Virtual Audio Cable installed"


def _get_target_mic_playback_device() -> tuple[Any, int, str, bool]:
    """Находит виртуальное устройство Windows для приёма микрофона телефона.
    Строго требует виртуальный кабель (CABLE Input / VB-Audio / Virtual Audio Cable / Voicemeeter),
    чтобы звук микрофона телефона был доступен в приложениях Windows (игры, Discord, Zoom)
    и не воспроизводился через динамики ПК (предотвращение эха)."""
    try:
        try:
            import pyaudiowpatch as pa
        except ImportError:
            import pyaudio as pa
        p = pa.PyAudio()
        dev_count = p.get_device_count()

        for i in range(dev_count):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxOutputChannels", 0) > 0:
                    name = info.get("name", "")
                    name_l = name.lower()
                    if any(v in name_l for v in ("cable input", "vb-audio", "virtual audio", "voicemeeter in", "line in")):
                        return (p, i, f"Virtual: {name}", True)
            except Exception:
                continue

        # Виртуальный кабель не найден
        return (p, -1, "No Virtual Audio Cable installed", False)
    except Exception as e:
        log_error("get_target_mic_playback_device", e)
        return (None, -1, f"Audio subsystem error: {e}", False)


def _ensure_mic_playback_open(sample_rate: int = 16000, channels: int = 1):
    """Гарантирует открытый выходной поток воспроизведения микрофона в виртуальный кабель Windows."""
    global _mic_playback_stream, _mic_playback_pa, _mic_active, _mic_virtual_detected, _mic_active_device_name
    with _mic_playback_lock:
        if _mic_playback_stream is not None:
            return _mic_playback_stream
        try:
            p, dev_idx, dev_name, is_virt = _get_target_mic_playback_device()
            _mic_virtual_detected = is_virt
            _mic_active_device_name = dev_name

            if not is_virt or dev_idx < 0 or p is None:
                log_action("mic_playback_no_virtual_cable", {"device": dev_name})
                if p:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                return None

            _mic_playback_pa = p

            try:
                import pyaudiowpatch as pa
            except ImportError:
                import pyaudio as pa

            kwargs = {
                "format": pa.paInt16,
                "channels": channels,
                "rate": sample_rate,
                "output": True,
                "output_device_index": dev_idx,
                "frames_per_buffer": 1024,
            }

            _mic_playback_stream = p.open(**kwargs)
            _mic_active = True
            log_action("mic_playback_started", {"device": dev_name, "rate": sample_rate})
            return _mic_playback_stream
        except Exception as e:
            log_error("mic_playback_open_err", e)
            return None


def _close_mic_playback():
    """Закрывает и освобождает устройство воспроизведения микрофона."""
    global _mic_playback_stream, _mic_playback_pa, _mic_active
    with _mic_playback_lock:
        _mic_active = False
        if _mic_playback_stream:
            try:
                _mic_playback_stream.stop_stream()
                _mic_playback_stream.close()
            except Exception:
                pass
            _mic_playback_stream = None
        if _mic_playback_pa:
            try:
                _mic_playback_pa.terminate()
            except Exception:
                pass
            _mic_playback_pa = None


# ---------------------------------------------------------------------------
# HTTP ENDPOINTS: МЫШЬ, КЛАВИАТУРА И МИКРОФОН
# ---------------------------------------------------------------------------
@input_bp.route("/api/mouse", methods=["POST"])
def api_mouse():
    """Эндпоинт управления курсором мыши, кликами и прокруткой с телефона."""
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid JSON"}), 400

    # Поддержка пакета событий {"events": [...]} для минимальной задержки
    events = data.get("events")
    if isinstance(events, list):
        success = True
        for ev in events:
            if isinstance(ev, dict):
                _handle_single_mouse_event(ev)
        return jsonify({"ok": True, "processed": len(events)})

    ok = _handle_single_mouse_event(data)
    return jsonify({"ok": ok})


def _handle_single_mouse_event(ev: dict) -> bool:
    action = ev.get("action", "")
    if action == "move_rel":
        dx = float(ev.get("dx", 0))
        dy = float(ev.get("dy", 0))
        sens = float(ev.get("sensitivity", 1.0))
        accel = bool(ev.get("accel", True))
        return mouse_move_relative(dx, dy, sens, accel)

    elif action == "move_norm":
        nx = float(ev.get("x", 0.0))
        ny = float(ev.get("y", 0.0))
        mon = int(ev.get("monitor", 1))
        return mouse_move_normalized(nx, ny, mon)

    elif action in ("click", "left_click"):
        btn = ev.get("button", "left")
        return mouse_click(btn, double=False)

    elif action == "double_click":
        btn = ev.get("button", "left")
        return mouse_click(btn, double=True)

    elif action == "right_click":
        return mouse_click("right", double=False)

    elif action == "down":
        btn = ev.get("button", "left")
        return mouse_button_event(btn, is_down=True)

    elif action == "up":
        btn = ev.get("button", "left")
        return mouse_button_event(btn, is_down=False)

    elif action == "scroll":
        dy = int(ev.get("dy", 0))
        return mouse_scroll(dy)

    elif action == "release_all":
        release_all_inputs()
        return True

    return False


@input_bp.route("/api/keyboard", methods=["POST"])
def api_keyboard():
    """Эндпоинт отправки клавиш, Unicode-текста и горячих комбинаций с телефона."""
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid JSON"}), 400

    action = data.get("action", "")

    if action == "key_down":
        vk = int(data.get("vk", 0))
        if not vk and "key" in data:
            vk = VK_MAP.get(str(data["key"]).lower(), 0)
        return jsonify({"ok": keyboard_key_event(vk, is_down=True)})

    elif action == "key_up":
        vk = int(data.get("vk", 0))
        if not vk and "key" in data:
            vk = VK_MAP.get(str(data["key"]).lower(), 0)
        return jsonify({"ok": keyboard_key_event(vk, is_down=False)})

    elif action in ("key_press", "press"):
        vk = int(data.get("vk", 0))
        if not vk and "key" in data:
            name = str(data["key"]).lower().strip()
            vk = VK_MAP.get(name, 0)
            if not vk and len(name) == 1:
                vk = ord(name.upper())
        if vk:
            keyboard_key_event(vk, is_down=True)
            time.sleep(0.01)
            keyboard_key_event(vk, is_down=False)
            return jsonify({"ok": True})
        return jsonify({"ok": False, "message": "Unknown key"}), 400

    elif action == "text":
        text = str(data.get("text", ""))
        return jsonify({"ok": keyboard_text_unicode(text)})

    elif action == "hotkey":
        keys = data.get("keys", [])
        if isinstance(keys, list):
            return jsonify({"ok": keyboard_hotkey(keys)})
        return jsonify({"ok": False, "message": "keys must be an array"}), 400

    elif action == "release_all":
        release_all_inputs()
        return jsonify({"ok": True})

    return jsonify({"ok": False, "message": "Unknown action"}), 400


@input_bp.route("/api/mic/stream", methods=["POST"])
def api_mic_stream():
    """Приём потокового бинарного аудиопотока микрофона телефона (16-bit PCM mono)."""
    if not check_token(allow_stream_query=True):
        return jsonify({"message": "Unauthorized"}), 401

    rate = int(request.args.get("rate", 16000))
    channels = int(request.args.get("channels", 1))

    stream = _ensure_mic_playback_open(sample_rate=rate, channels=channels)
    if not stream:
        return jsonify({
            "ok": False,
            "virtual_cable_detected": False,
            "message": "Виртуальный аудиокабель (VB-CABLE) не обнаружен на ПК. Для передачи микрофона в Windows требуется установить VB-CABLE (CABLE Input)."
        }), 400

    try:
        # Потоковое чтение PCM-чанков из тела HTTP-запроса
        while True:
            chunk = request.stream.read(1024)
            if not chunk:
                break
            with _mic_playback_lock:
                if _mic_playback_stream:
                    _mic_playback_stream.write(chunk, exception_on_underflow=False)
        return jsonify({"ok": True})
    except Exception as e:
        log_error("mic_stream_err", e)
        return jsonify({"ok": False, "message": str(e)}), 500


@input_bp.route("/api/mic/status", methods=["GET", "POST"])
def api_mic_status():
    """Проверка и управление статусом передачи микрофона телефона на ПК."""
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    global _mic_virtual_detected, _mic_active_device_name

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        enable = bool(data.get("enable", False))
        if not enable:
            _close_mic_playback()
        else:
            rate = int(data.get("rate", 16000))
            _ensure_mic_playback_open(sample_rate=rate, channels=1)
    else:
        # При GET запросе обновляем статус обнаружения виртуального кабеля
        if not _mic_active:
            p, _, name, is_virt = _get_target_mic_playback_device()
            _mic_virtual_detected = is_virt
            _mic_active_device_name = name
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass

    return jsonify({
        "active": _mic_active,
        "virtual_cable_detected": _mic_virtual_detected,
        "target_device": _mic_active_device_name,
        "instructions": "Для использования переданного голоса в качестве микрофона в Windows выберите виртуальный кабель (VB-CABLE / Virtual Audio Cable) в звуковых устройствах."
    })
