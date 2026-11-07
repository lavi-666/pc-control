"""
PC Control — Модуль удалённого управления мышью, клавиатурой и микрофоном (Input Controller).
Обеспечивает низколатентный ввод SendInput для Windows и приём звука микрофона Android-телефона.
"""

import ctypes
from ctypes import wintypes
import json
import os
import platform
import struct
import sys
import threading
import time
from typing import Any
from flask import Blueprint, Response, jsonify, request

from core.auth import check_token
from core.logger import log_action, log_error
from modules.system import _attach_input_desktop

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


def _get_monitor_bounds(monitor_idx: int) -> tuple[int, int, int, int]:
    """Возвращает прямоугольник (left, top, width, height) для указанного монитора MSS."""
    try:
        import mss
        with mss.MSS() as sct:
            mons = sct.monitors
            if monitor_idx > 0 and monitor_idx < len(mons):
                m = mons[monitor_idx]
                return (m["left"], m["top"], m["width"], m["height"])
            elif len(mons) > 0:
                # 0 = All monitors (bounding box)
                m = mons[0]
                return (m["left"], m["top"], m["width"], m["height"])
    except Exception:
        pass
    return _get_virtual_desktop_metrics()


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
    with _input_lock:
        vx, vy, vw, vh = _get_virtual_desktop_metrics()
        m_left, m_top, m_w, m_h = _get_monitor_bounds(monitor_idx)

        # Вычисляем абсолютные пиксельные координаты точки касания
        pixel_x = m_left + max(0.0, min(1.0, nx)) * m_w
        pixel_y = m_top + max(0.0, min(1.0, ny)) * m_h

        # Преобразуем в нормализованные координаты Windows SendInput (0..65535)
        norm_x = int(round(((pixel_x - vx) * 65535.0) / max(1.0, float(vw - 1))))
        norm_y = int(round(((pixel_y - vy) * 65535.0) / max(1.0, float(vh - 1))))

        norm_x = max(0, min(65535, norm_x))
        norm_y = max(0, min(65535, norm_y))

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
        if extended:
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
    """Ввод произвольного Unicode-текста (русский, украинский, английский, символы)."""
    if not IS_WINDOWS or not text:
        return True
    with _input_lock:
        seq = []
        for ch in text:
            code = ord(ch)
            # SendInput KEYEVENTF_UNICODE передаёт символ в wScan
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
            seq.append(INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))))
        _held_keys.clear()

        if seq:
            _send_inputs(seq)


# ---------------------------------------------------------------------------
# АУДИОКОНВЕЙЕР: ПЕРЕДАЧА МИКРОФОНА ТЕЛЕФОНА НА ПК (PHONE MIC -> WINDOWS)
# ---------------------------------------------------------------------------
_mic_playback_stream = None
_mic_playback_pa = None
_mic_playback_lock = threading.Lock()
_mic_active = False
_mic_active_device_name = "System Output / Virtual Cable"


def _get_target_mic_playback_device() -> tuple[Any, int, str]:
    """Находит подходящее целевое устройство Windows для воспроизведения микрофона с телефона.
    Приоритет: виртуальное устройство (CABLE Input / VB-Audio / Virtual Audio Cable) -> системный Default Output."""
    import pyaudiowpatch as pa
    p = pa.PyAudio()
    dev_count = p.get_device_count()

    virtual_cand = None
    default_cand = None

    for i in range(dev_count):
        try:
            info = p.get_device_info_by_index(i)
            if info.get("maxOutputChannels", 0) > 0:
                name = info.get("name", "")
                name_l = name.lower()
                if any(v in name_l for v in ("cable input", "vb-audio", "virtual audio", "voicemeeter in")):
                    virtual_cand = (i, name)
                    break
                if default_cand is None and "mapper" not in name_l:
                    default_cand = (i, name)
        except Exception:
            continue

    if virtual_cand:
        return (p, virtual_cand[0], f"Virtual: {virtual_cand[1]}")
    elif default_cand:
        return (p, default_cand[0], f"Default: {default_cand[1]}")
    else:
        # Fallback на системное устройство по умолчанию
        try:
            d_out = p.get_default_output_device_info()
            return (p, d_out["index"], d_out["name"])
        except Exception:
            return (p, -1, "System Audio Output")


def _ensure_mic_playback_open(sample_rate: int = 16000, channels: int = 1):
    """Гарантирует открытый выходной поток воспроизведения микрофона телефона."""
    global _mic_playback_stream, _mic_playback_pa, _mic_active, _mic_active_device_name
    with _mic_playback_lock:
        if _mic_playback_stream is not None:
            return _mic_playback_stream
        try:
            import pyaudiowpatch as pa
            p, dev_idx, dev_name = _get_target_mic_playback_device()
            _mic_playback_pa = p
            _mic_active_device_name = dev_name

            kwargs = {
                "format": pa.paInt16,
                "channels": channels,
                "rate": sample_rate,
                "output": True,
                "frames_per_buffer": 1024,
            }
            if dev_idx >= 0:
                kwargs["output_device_index"] = dev_idx

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
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    rate = int(request.args.get("rate", 16000))
    channels = int(request.args.get("channels", 1))

    stream = _ensure_mic_playback_open(sample_rate=rate, channels=channels)
    if not stream:
        return jsonify({"ok": False, "message": "Could not initialize Windows audio output"}), 500

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

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        enable = bool(data.get("enable", False))
        if not enable:
            _close_mic_playback()
        else:
            rate = int(data.get("rate", 16000))
            _ensure_mic_playback_open(sample_rate=rate, channels=1)

    return jsonify({
        "active": _mic_active,
        "target_device": _mic_active_device_name,
        "instructions": "Для использования переданного голоса в качестве микрофона в Windows выберите виртуальный кабель (VB-CABLE / Virtual Audio Cable) в звуковых устройствах."
    })
