"""
PC Control — Модуль системных функций: раскладки клавиатуры, процессы, скриншоты и лаунчер CS2.
"""

import csv
import functools
import io
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file
from core.auth import check_token
from core.config import CHROME, NO_WINDOW, SCREENSHOTS_DIR, is_safe_test_mode
from core.logger import log_action, log_error

system_bp = Blueprint("system", __name__)

# Константы переключения раскладок Windows
WM_INPUTLANGCHANGEREQUEST = 0x0050
HWND_BROADCAST = 0xFFFF
LOCALE_SNATIVELANGUAGENAME = 0x04
LOCALE_SISO639LANGNAME = 0x59
LOCALE_SNAME = 0x5C

_DEFAULT_DESKTOP_HANDLE = None
_desktop_lock = threading.Lock()


@functools.lru_cache(maxsize=1)
def _user32_layouts():
    import ctypes
    from ctypes import wintypes

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    u.OpenDesktopW.restype = ctypes.c_void_p
    u.SetThreadDesktop.argtypes = [ctypes.c_void_p]
    u.SetThreadDesktop.restype = wintypes.BOOL
    u.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    u.GetKeyboardLayoutList.restype = ctypes.c_int
    u.GetKeyboardLayout.argtypes = [wintypes.DWORD]
    u.GetKeyboardLayout.restype = ctypes.c_void_p
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetShellWindow.argtypes = []
    u.GetShellWindow.restype = wintypes.HWND
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.PostMessageW.restype = wintypes.BOOL
    u.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, wintypes.UINT]
    u.ActivateKeyboardLayout.restype = ctypes.c_void_p
    return u


def _attach_input_desktop():
    global _DEFAULT_DESKTOP_HANDLE
    if platform.system() != "Windows":
        return
    try:
        u = _user32_layouts()
        with _desktop_lock:
            if not _DEFAULT_DESKTOP_HANDLE:
                _DEFAULT_DESKTOP_HANDLE = u.OpenDesktopW("Default", 0, False, 0x01FF)
        if _DEFAULT_DESKTOP_HANDLE:
            u.SetThreadDesktop(_DEFAULT_DESKTOP_HANDLE)
    except Exception:
        pass


def _switch_keyboard_layout():
    import ctypes
    from ctypes import wintypes

    _attach_input_desktop()
    user32 = ctypes.windll.user32
    VK_LWIN = 0x5B
    VK_SPACE = 0x20
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1
    ULONG_PTR = wintypes.WPARAM

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
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
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUnion)]

    def key_input(vk, flags=0):
        return INPUT(type=INPUT_KEYBOARD, u=_INPUTUnion(ki=KEYBDINPUT(vk, 0, flags, 0, 0)))

    sequence = [
        key_input(VK_LWIN),
        key_input(VK_SPACE),
        key_input(VK_SPACE, KEYEVENTF_KEYUP),
        key_input(VK_LWIN, KEYEVENTF_KEYUP),
    ]
    arr = (INPUT * len(sequence))(*sequence)
    sent = user32.SendInput(len(sequence), ctypes.byref(arr), ctypes.sizeof(INPUT))
    if sent != len(sequence):
        raise OSError("SendInput не смог отправить нажатия клавиш")


def _locale_info(langid: int, lctype: int) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(85)
    n = ctypes.windll.kernel32.GetLocaleInfoW(langid, lctype, buf, len(buf))
    return buf.value if n else ""


def _hkl_id(hkl: int) -> str:
    return format(hkl, "x")


def _installed_layouts() -> list[dict]:
    import ctypes
    _attach_input_desktop()
    u = _user32_layouts()
    count = u.GetKeyboardLayoutList(0, None)
    arr = (ctypes.c_void_p * max(count, 1))()
    count = u.GetKeyboardLayoutList(count, arr)

    layouts = []
    for raw in arr[:count]:
        hkl = raw or 0
        langid = hkl & 0xFFFF
        native = _locale_info(langid, LOCALE_SNATIVELANGUAGENAME)
        layouts.append({
            "id": _hkl_id(hkl),
            "abbr": (_locale_info(langid, LOCALE_SISO639LANGNAME) or format(langid, "04x")).upper(),
            "name": (native[:1].upper() + native[1:]) if native else format(langid, "04x"),
            "locale": _locale_info(langid, LOCALE_SNAME),
        })

    by_name: dict[str, list[dict]] = {}
    for l in layouts:
        by_name.setdefault(l["name"], []).append(l)
    for same in by_name.values():
        if len(same) > 1:
            for i, l in enumerate(same, 1):
                l["name"] += f" · раскладка {i}"
    return layouts


def _current_layout() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes
    _attach_input_desktop()
    u = _user32_layouts()

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    hwnd = u.GetForegroundWindow() or 0
    if not hwnd:
        hwnd = u.FindWindowW("Shell_TrayWnd", None) or u.GetShellWindow() or 0
    if not hwnd:
        return 0, (u.GetKeyboardLayout(0) or 0)

    thread_id = u.GetWindowThreadProcessId(hwnd, None)
    gui = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui)):
        focus_hwnd = gui.hwndFocus or gui.hwndActive
        if focus_hwnd:
            focus_tid = u.GetWindowThreadProcessId(focus_hwnd, None)
            if focus_tid:
                thread_id = focus_tid
                hwnd = focus_hwnd

    hkl = u.GetKeyboardLayout(thread_id) or 0
    if not hkl:
        tray = u.FindWindowW("Shell_TrayWnd", None)
        if tray:
            hkl = u.GetKeyboardLayout(u.GetWindowThreadProcessId(tray, None)) or 0
    return hwnd, hkl


def _match_layout_id(hkl: int, layouts: list[dict]) -> str | None:
    if not hkl:
        return layouts[0]["id"] if layouts else None
    exact = _hkl_id(hkl)
    if any(l["id"] == exact for l in layouts):
        return exact
    langid = hkl & 0xFFFF
    for l in layouts:
        if (int(l["id"], 16) & 0xFFFF) == langid:
            return l["id"]
    return exact


def _set_layout(hkl: int) -> bool:
    import ctypes
    _attach_input_desktop()
    u = _user32_layouts()
    hwnd, current = _current_layout()
    if current and (current == hkl or (current & 0xFFFF) == (hkl & 0xFFFF)):
        return True

    bits = ctypes.sizeof(ctypes.c_void_p) * 8
    lparam = hkl - (1 << bits) if hkl >= (1 << (bits - 1)) else hkl

    fg = u.GetForegroundWindow() or 0
    tray = u.FindWindowW("Shell_TrayWnd", None) or 0
    targets = []
    for w in (hwnd, fg, tray):
        if w and w not in targets:
            targets.append(w)

    posted = False
    for w in targets:
        if u.PostMessageW(w, WM_INPUTLANGCHANGEREQUEST, 0, lparam):
            posted = True

    if not posted:
        u.PostMessageW(HWND_BROADCAST, WM_INPUTLANGCHANGEREQUEST, 0, lparam)

    u.ActivateKeyboardLayout(hkl, 0)

    target_langid = hkl & 0xFFFF
    for i in range(8):
        time.sleep(0.05)
        _, now_hkl = _current_layout()
        if now_hkl == hkl or (now_hkl & 0xFFFF) == target_langid:
            return True
        if i == 3:
            u.PostMessageW(HWND_BROADCAST, WM_INPUTLANGCHANGEREQUEST, 0, lparam)

    if tray:
        tray_hkl = u.GetKeyboardLayout(u.GetWindowThreadProcessId(tray, None)) or 0
        if tray_hkl == hkl or (tray_hkl & 0xFFFF) == target_langid:
            return True
    return False


@system_bp.route("/keyboard/switch_language", methods=["POST"])
def switch_language():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"message": "Доступно только на Windows"}), 400
    if is_safe_test_mode():
        log_action("switch_language")
        return jsonify({"message": "Раскладка переключена"})
    try:
        _switch_keyboard_layout()
        log_action("switch_language")
        return jsonify({"message": "Раскладка переключена"})
    except Exception as e:
        log_error("switch_language", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@system_bp.route("/keyboard/languages")
def keyboard_languages():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"message": "Доступно только на Windows"}), 400
    try:
        layouts = _installed_layouts()
        _, current = _current_layout()
        current_id = _match_layout_id(current, layouts)
        return jsonify({"current": current_id, "languages": layouts})
    except Exception as e:
        log_error("keyboard_languages", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@system_bp.route("/keyboard/set_language", methods=["POST"])
def keyboard_set_language():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"message": "Доступно только на Windows"}), 400
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    lang_id = str(data.get("id", "")).lower()
    try:
        layouts = _installed_layouts()
        target = next((l for l in layouts if l["id"] == lang_id), None)
        if target is None:
            return jsonify({"message": "Этот язык не установлен в Windows"}), 400

        if is_safe_test_mode():
            log_action("set_language", {"lang": target["locale"] or target["abbr"]})
            return jsonify({"message": f"Язык ввода: {target['name']}", "current": target["id"]})

        applied = _set_layout(int(lang_id, 16))
        _, current = _current_layout()
        current_id = _match_layout_id(current, layouts) or target["id"]
        if not applied:
            return jsonify({
                "message": "Активное окно не приняло смену языка (возможно, оно запущено от имени администратора)",
                "current": current_id,
            }), 409

        log_action("set_language", {"lang": target["locale"] or target["abbr"]})
        return jsonify({"message": f"Язык ввода: {target['name']}", "current": target["id"]})
    except Exception as e:
        log_error("set_language", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


# ---------- Скриншот ----------

@system_bp.route("/screenshot")
def screenshot():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    try:
        from PIL import ImageGrab
        _attach_input_desktop()
        img = ImageGrab.grab(all_screens=True)
        now = time.time()
        ms = int((now % 1) * 1000)
        filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}_{ms:03d}.png"
        path = SCREENSHOTS_DIR / filename
        img.save(path, "PNG")
        data_bytes = path.read_bytes()
        try:
            files = sorted(SCREENSHOTS_DIR.glob("screenshot_*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
            for old_f in files[20:]:
                try:
                    old_f.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        log_action("screenshot")
        return send_file(io.BytesIO(data_bytes), mimetype="image/png", as_attachment=True, download_name=filename)
    except Exception as e:
        log_error("screenshot", e)
        return jsonify({"message": f"Не удалось сделать скриншот: {e}"}), 500


# ---------- Процессы (просмотр и завершение) ----------

HIDDEN_PROCESSES = {
    "system idle process", "system", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe",
    "dwm.exe", "fontdrvhost.exe", "wudfhost.exe", "runtimebroker.exe",
    "dllhost.exe", "conhost.exe", "sihost.exe", "taskhostw.exe", "ctfmon.exe",
    "searchindexer.exe", "searchapp.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "spoolsv.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "backgroundtaskhost.exe",
    "applicationframehost.exe", "audiodg.exe", "wmiprvse.exe", "lsm.exe",
    "smartscreen.exe", "systemsettings.exe", "systemsettingsbroker.exe",
    "usernotificationswindowhost.exe", "widgets.exe", "widgetservice.exe",
    "crashpadhandler.exe", "wmiapsrv.exe", "wudfrd.exe", "wersvc.exe",
    "wscript.exe", "cscript.exe", "taskhost.exe", "spoolsystem.exe",
    "unsecapp.exe", "wlanext.exe", "amdrsserv.exe", "npm.exe",
    "nvcontainer.exe", "nvdisplay.container.exe", "nvidia web helper.exe",
    "igfxem.exe", "igfxhk.exe", "igfxtray.exe", "hpqtoaster.exe",
    "openconsole.exe", "explorer.exe",
}

_procs_cache: dict = {"time": 0.0, "data": []}
_procs_lock = threading.Lock()


@system_bp.route("/processes")
def processes():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    now = time.time()
    with _procs_lock:
        if (now - _procs_cache["time"]) < 1.0 and _procs_cache["data"]:
            return jsonify(_procs_cache["data"])

    procs = []
    seen = set()
    try:
        for p in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                info = p.info
                name = info.get("name")
                pid = info.get("pid")
                if not name or pid is None or pid <= 0:
                    continue
                lname = name.lower()
                if lname in HIDDEN_PROCESSES or "svchost" in lname:
                    continue
                key = (lname, pid)
                if key in seen:
                    continue
                seen.add(key)
                procs.append({
                    "name": name,
                    "pid": pid,
                    "create_time": info.get("create_time", 0.0)
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        # Резервный фоллбэк на tasklist, если psutil дал сбой
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, creationflags=NO_WINDOW,
        )
        for row in csv.reader(result.stdout.strip().splitlines()):
            if len(row) >= 2:
                name, pid_str = row[0].strip(), row[1].strip()
                if not name or not pid_str.isdigit():
                    continue
                lname = name.lower()
                if lname in HIDDEN_PROCESSES or "svchost" in lname:
                    continue
                pid_int = int(pid_str)
                key = (lname, pid_int)
                if key in seen:
                    continue
                seen.add(key)
                procs.append({"name": name, "pid": pid_int, "create_time": 0.0})

    procs.sort(key=lambda p: p["name"].lower())
    with _procs_lock:
        _procs_cache["time"] = now
        _procs_cache["data"] = procs
    log_action("list_processes")
    return jsonify(procs)


@system_bp.route("/processes/kill", methods=["POST"])
def kill_process():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_pid = data.get("pid")
    expected_name = str(data.get("expected_name") or data.get("name") or "").strip().lower()
    expected_create_time = data.get("create_time")

    if raw_pid is None or isinstance(raw_pid, bool):
        return jsonify({"message": "Не указан или некорректный PID"}), 400
    try:
        pid = int(raw_pid)
        if pid <= 0:
            return jsonify({"message": "Нельзя завершать системный PID <= 0"}), 400
    except (ValueError, TypeError, OverflowError):
        return jsonify({"message": "Не указан или некорректный PID"}), 400

    if pid == os.getpid():
        return jsonify({"message": "Нельзя завершать процесс самого сервера"}), 400

    if pid in (0, 4):
        return jsonify({"ok": False, "message": "Запрещено завершать критический системный процесс"}), 403

    CRITICAL_SYSTEM_NAMES = {
        "system", "system idle process", "registry", "smss.exe", "csrss.exe",
        "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "dwm.exe"
    }

    if expected_name and expected_name in CRITICAL_SYSTEM_NAMES:
        return jsonify({"ok": False, "message": f"Запрещено завершать критический системный процесс {expected_name}"}), 403

    try:
        proc = psutil.Process(pid)
        actual_name = proc.name()
        actual_create_time = proc.create_time()

        if actual_name.lower() in CRITICAL_SYSTEM_NAMES:
            return jsonify({"ok": False, "message": f"Запрещено завершать критический системный процесс {actual_name}"}), 403

        # Защита от PID recycling: сверяем имя и время создания процесса
        if expected_name and expected_name != actual_name.lower():
            return jsonify({
                "ok": False,
                "message": f"PID {pid} уже переиспользован другим процессом ({actual_name} вместо {expected_name}). Операция отменена."
            }), 409

        if expected_create_time is not None:
            try:
                exp_ct = float(expected_create_time)
                if exp_ct > 0 and abs(actual_create_time - exp_ct) > 2.0:
                    return jsonify({
                        "ok": False,
                        "message": f"Процесс {actual_name} (PID {pid}) был перезапущен с момента выборки. Операция отменена во избежание ошибки."
                    }), 409
            except (ValueError, TypeError):
                pass

        if is_safe_test_mode() or request.headers.get("X-Safe-Mode") == "1":
            log_action("kill_process", {"pid": pid, "simulated": True})
            return jsonify({"ok": True, "message": f"[SAFE_MODE] Завершение процесса {pid} сымитировано"})

        # Пытаемся завершить корректно (SIGTERM/terminate), при необходимости форсированно (kill)
        try:
            proc.terminate()
            proc.wait(timeout=0.3)
        except (psutil.TimeoutExpired, psutil.AccessDenied):
            try:
                proc.kill()
                proc.wait(timeout=0.3)
            except Exception:
                # Если psutil не справился из-за привилегий, используем taskkill
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, creationflags=NO_WINDOW)

        is_alive = False
        try:
            is_alive = proc.is_running()
        except psutil.NoSuchProcess:
            is_alive = False

        with _procs_lock:
            _procs_cache["time"] = 0.0
            _procs_cache["data"] = []

        log_action("kill_process", {"pid": pid, "name": actual_name, "success": not is_alive})
        if not is_alive:
            return jsonify({
                "ok": True,
                "pid": pid,
                "message": f"Процесс {actual_name} (PID {pid}) успешно завершён"
            })
        else:
            return jsonify({
                "ok": False,
                "pid": pid,
                "message": f"Недостаточно прав для завершения процесса {actual_name} (PID {pid})"
            }), 403

    except psutil.NoSuchProcess:
        with _procs_lock:
            _procs_cache["time"] = 0.0
            _procs_cache["data"] = []
        return jsonify({
            "ok": True,
            "pid": pid,
            "message": f"Процесс PID {pid} уже был завершён ранее"
        })
    except psutil.AccessDenied:
        return jsonify({
            "ok": False,
            "pid": pid,
            "message": f"Отказано в доступе при попытке завершить процесс PID {pid}. Требуются права администратора."
        }), 403
    except Exception as e:
        # Резервный вызов taskkill
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True, text=True, creationflags=NO_WINDOW,
        )
        with _procs_lock:
            _procs_cache["time"] = 0.0
            _procs_cache["data"] = []
        log_action("kill_process", {"pid": pid, "fallback": True})
        ok = result.returncode == 0
        message = (result.stdout or result.stderr or "").strip()
        return jsonify({
            "ok": ok,
            "pid": pid,
            "message": message if message else ("Процесс завершён" if ok else "Не удалось завершить процесс")
        })


def get_windows_hello_status() -> dict:
    """
    Проверяет реальное состояние настройки Windows Hello PasswordLess в реестре Windows.
    HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\PasswordLess\\Device
    DevicePasswordLessBuildVersion:
      2 (или отсутствует по умолчанию в Win10/11) -> Enabled (Windows Hello required for MS accounts, netplwiz checkbox hidden)
      0 -> Disabled (Windows Hello requirement disabled, netplwiz checkbox visible)
    """
    if platform.system() != "Windows":
        return {"supported": False, "enabled": False, "raw_value": None}
    try:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device") as k:
                val, _ = winreg.QueryValueEx(k, "DevicePasswordLessBuildVersion")
                enabled = (int(val) != 0)
                raw_val = int(val)
        except FileNotFoundError:
            enabled = True
            raw_val = None
        except Exception:
            enabled = True
            raw_val = None

        return {
            "supported": True,
            "enabled": enabled,
            "raw_value": raw_val,
        }
    except Exception as e:
        return {"supported": False, "enabled": False, "raw_value": None, "error": str(e)}


def run_elevated_command(target: str, params: str = "", work_dir: str = "", show: bool = True, timeout: int = 120) -> tuple[bool, str, str]:
    """
    Выполняет запуск команды/процесса с запросом прав администратора (UAC) в Windows.
    Решает проблему песочниц (включая Microsoft Store/MSIX Python, где прямой Win32 ShellExecute
    блокируется ядром ОС с кодом 5 ERROR_ACCESS_DENIED или кодом 50 без вывода окна UAC).
    
    Обеспечивает гарантированное появление системного окна подтверждения UAC на экране пользователя.
    
    Возвращает:
        (ok: bool, code: str, message: str)
    """
    if platform.system() != "Windows":
        return False, "ERR_NOT_SUPPORTED", "UAC elevation is only supported on Windows."

    # Способ 1: Прямой ShellExecuteW (работает в стандартном Win32 Python)
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        shell32.ShellExecuteW.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = ctypes.c_void_p

        hwnd = user32.GetForegroundWindow() or None
        ctypes.set_last_error(0)
        res = shell32.ShellExecuteW(
            hwnd,
            "runas",
            target,
            params,
            work_dir or None,
            1 if show else 0,
        ) or 0
        last_err = ctypes.get_last_error()
        if res > 32:
            return True, "OK", "Elevation launched successfully via ShellExecuteW"
        if last_err == 1223:  # ERROR_CANCELLED — пользователь явно нажал «Нет» в окне UAC
            return False, "ERR_UAC_DENIED", "Запрос прав администратора (UAC) был отклонен пользователем."
    except Exception:
        res = 0

    # Способ 2: Shell.Application COM через powershell.exe
    # Этот способ работает из любого окружения (включая Store/MSIX Python и фоновые службы),
    # так как обращается к COM-серверу Проводника (Explorer Shell) на интерактивном рабочем столе пользователя.
    t_esc = target.replace("'", "''")
    p_esc = params.replace("'", "''")
    w_esc = work_dir.replace("'", "''")
    n_show = 1 if show else 0

    ps_script = (
        f"$ErrorActionPreference = 'Stop'; "
        f"try {{ "
        f"  $sh = New-Object -ComObject Shell.Application; "
        f"  $sh.ShellExecute('{t_esc}', '{p_esc}', '{w_esc}', 'runas', {n_show}); "
        f"  Write-Output 'UAC_OK'; "
        f"}} catch {{ "
        f"  $msg = $_.Exception.Message; "
        f"  if ($msg -match '0x800704C7' -or $msg -match '1223' -or $msg -match 'canceled' -or $msg -match 'cancel' -or $msg -match 'отменен' -or $msg -match 'отклон') {{ "
        f"    Write-Output 'UAC_CANCELLED'; "
        f"  }} else {{ "
        f"    Write-Output ('UAC_ERROR:' + $msg); "
        f"  }} "
        f"  exit 1; "
        f"}}"
    )

    try:
        proc = subprocess.run([
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden",
            "-Command", ps_script
        ], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)

        out = proc.stdout.strip()
        if "UAC_OK" in out:
            return True, "OK", "Команда с правами администратора успешно запущена."
        elif "UAC_CANCELLED" in out:
            return False, "ERR_UAC_DENIED", "Запрос прав администратора (UAC) был отклонен пользователем."
        else:
            err_line = next((l for l in out.splitlines() if l.startswith("UAC_ERROR:")), out or proc.stderr.strip())
            return False, "ERR_UAC_FAILED", f"Не удалось повысить привилегии: {err_line}"

    except subprocess.TimeoutExpired:
        return False, "ERR_UAC_TIMEOUT", "Истекло время ожидания подтверждения запроса прав администратора (UAC)."
    except Exception as e:
        return False, "ERR_UAC_EXCEPTION", f"Сбой вызова механизма UAC: {e}"


def set_windows_hello_state(enabled: bool) -> tuple[bool, str]:
    """
    Устанавливает DevicePasswordLessBuildVersion (2 = Включено, 0 = Отключено).
    Запрашивает права администратора (UAC) через run_elevated_command.
    После выполнения обязательно проверяет фактическое значение в реестре!
    """
    if platform.system() != "Windows":
        return (False, "Изменение параметров Windows Hello поддерживается только в ОС Windows.")

    target_val = 2 if enabled else 0
    current_status = get_windows_hello_status()
    if current_status.get("supported") and current_status.get("enabled") == enabled:
        return (True, f"Настройка Windows Hello уже {'включена' if enabled else 'отключена'}.")

    try:
        from core.system_state import capture_windows_hello_before_change
        capture_windows_hello_before_change(enabled)
    except Exception:
        pass

    ps_cmd = (
        f"$p = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\PasswordLess\\Device'; "
        f"if (-not (Test-Path $p)) {{ New-Item -Path $p -Force | Out-Null }}; "
        f"Set-ItemProperty -Path $p -Name 'DevicePasswordLessBuildVersion' -Value {target_val} -Type DWord"
    )

    ok, code, msg = run_elevated_command(
        "powershell.exe",
        f'-NoProfile -NonInteractive -WindowStyle Hidden -Command "{ps_cmd}"',
        show=False
    )
    if not ok:
        return (False, msg)

    # Ждём до 3 секунд и проверяем фактическое значение в реестре
    for _ in range(15):
        time.sleep(0.2)
        new_status = get_windows_hello_status()
        if new_status.get("enabled") == enabled:
            return (True, f"Windows Hello успешно {'включен' if enabled else 'отключен'}.")

    return (False, "Значение реестра не изменилось. Возможно, действуют групповые политики Windows или изменение заблокировано системой.")


def launch_netplwiz() -> tuple[bool, str]:
    """
    Запускает только системную утилиту netplwiz.exe (или control userpasswords2).
    НЕ изменяет никаких учетных данных или системных параметров.
    """
    if platform.system() != "Windows":
        return (False, "Утилита netplwiz доступна только в ОС Windows.")
    try:
        import ctypes
        res = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            "netplwiz.exe",
            None,
            None,
            1  # SW_SHOWNORMAL
        )
        if res > 32:
            return (True, "Системное окно netplwiz успешно открыто.")
        else:
            res2 = ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                "control.exe",
                "userpasswords2",
                None,
                1
            )
            if res2 > 32:
                return (True, "Системное окно netplwiz (userpasswords2) открыто.")
            return (False, f"Не удалось открыть netplwiz (код ошибки {res}).")
    except Exception as e:
        return (False, f"Ошибка при запуске netplwiz: {e}")


def open_signin_settings() -> tuple[bool, str]:
    """
    Открывает системный раздел «Параметры -> Учетные записи -> Варианты входа» (ms-settings:signinoptions).
    """
    if platform.system() != "Windows":
        return (False, "Параметры Windows доступны только в ОС Windows.")
    try:
        import ctypes
        res = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            "ms-settings:signinoptions",
            None,
            None,
            1
        )
        if res > 32:
            return (True, "Раздел параметров входа Windows открыт.")
        return (False, f"Не удалось открыть параметры входа (код ошибки {res}).")
    except Exception as e:
        return (False, f"Ошибка при открытии параметров входа: {e}")


@system_bp.route("/windows_hello", methods=["GET"])
@system_bp.route("/system/windows_hello", methods=["GET"])
def api_get_windows_hello():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    return jsonify(get_windows_hello_status())


@system_bp.route("/windows_hello", methods=["POST"])
@system_bp.route("/system/windows_hello", methods=["POST"])
def api_set_windows_hello():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    if is_safe_test_mode() or request.headers.get("X-Safe-Mode") == "1":
        log_action(f"set_windows_hello_{enabled}")
        return jsonify({"ok": True, "enabled": enabled, "message": f"[SAFE_MODE] Windows Hello {'включен' if enabled else 'отключен'}"})
    ok, msg = set_windows_hello_state(enabled)
    new_status = get_windows_hello_status()
    if ok:
        log_action(f"set_windows_hello_{enabled}")
        return jsonify({"ok": True, "enabled": new_status.get("enabled"), "message": msg})
    return jsonify({"ok": False, "enabled": new_status.get("enabled"), "message": msg}), 400


@system_bp.route("/netplwiz", methods=["POST"])
@system_bp.route("/system/netplwiz", methods=["POST"])
def api_launch_netplwiz():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if is_safe_test_mode() or request.headers.get("X-Safe-Mode") == "1":
        log_action("launch_netplwiz")
        return jsonify({"ok": True, "message": "[SAFE_MODE] Запуск netplwiz.exe"})
    ok, msg = launch_netplwiz()
    if ok:
        log_action("launch_netplwiz")
        return jsonify({"ok": True, "message": msg})
    return jsonify({"ok": False, "message": msg}), 500


@system_bp.route("/signin_settings", methods=["POST"])
@system_bp.route("/system/signin_settings", methods=["POST"])
def api_open_signin_settings():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if is_safe_test_mode() or request.headers.get("X-Safe-Mode") == "1":
        log_action("open_signin_settings")
        return jsonify({"ok": True, "message": "[SAFE_MODE] Открытие параметров входа"})
    ok, msg = open_signin_settings()
    if ok:
        log_action("open_signin_settings")
        return jsonify({"ok": True, "message": msg})
    return jsonify({"ok": False, "message": msg}), 500
