"""
PC Control — Модуль управления питанием ПК, таймером выключения и Wake-on-LAN.
"""

import binascii
import math
import platform
import socket
import subprocess
import threading
import time
from flask import Blueprint, jsonify, request
from core.auth import check_token
from core.config import NO_WINDOW, is_safe_test_mode, load_app_config
from core.logger import log_action, log_error

power_bp = Blueprint("power", __name__)

_shutdown_lock = threading.Lock()
_shutdown_cancel = threading.Event()
_shutdown_deadline = None  # unix timestamp срабатывания таймера
_shutdown_gen = 0


def do_shutdown_now():
    if is_safe_test_mode():
        print("[SAFE_TEST_MODE] do_shutdown_now() suppressed — PC is protected.")
        return
    system = platform.system()
    if system == "Windows":
        subprocess.run(["shutdown", "/s", "/f", "/t", "0"], check=False, creationflags=NO_WINDOW)
    elif system == "Darwin":
        subprocess.run(["osascript", "-e", 'tell app "System Events" to shut down'], check=False)
    else:
        subprocess.run(["sudo", "shutdown", "now"], check=False)


def _delayed_shutdown(seconds: int, my_gen: int, cancel_ev: threading.Event, safe_scheduled: bool = False):
    global _shutdown_deadline
    wait_sec = min(float(seconds), 31536000.0)
    cancelled = cancel_ev.wait(wait_sec)
    with _shutdown_lock:
        if cancelled or _shutdown_gen != my_gen:
            return
        _shutdown_deadline = None
    if safe_scheduled or is_safe_test_mode():
        log_action("shutdown_after_timer")
        return
    do_shutdown_now()
    log_action("shutdown_after_timer")


def _default_wol_targets() -> list[str]:
    targets = ["255.255.255.255", "192.168.0.255", "192.168.1.255"]
    try:
        cfg = load_app_config() or {}
        lan_ip = str(cfg.get("lan_ip") or "").strip()
        parts = lan_ip.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
            if bcast not in targets:
                targets.insert(1, bcast)
            if lan_ip not in targets:
                targets.append(lan_ip)
    except Exception:
        pass
    return targets


def send_wol_magic_packet(mac_str="AA:BB:CC:DD:EE:FF", targets=None):
    """Генерирует и отправляет UDP Magic Packet на широковещательные адреса."""
    clean_mac = mac_str.replace(":", "").replace("-", "").replace(".", "").replace(" ", "").strip()
    if len(clean_mac) != 12:
        raise ValueError(f"Неверный MAC-адрес: {mac_str}")
    hw_addr = binascii.unhexlify(clean_mac)
    magic_packet = b"\xff" * 6 + hw_addr * 16

    if not targets or not isinstance(targets, (list, str)):
        targets = _default_wol_targets()
    elif isinstance(targets, str):
        targets = [t.strip() for t in targets.split(",") if t.strip()]
    else:
        targets = [str(t).strip() for t in targets if isinstance(t, (str, int, float)) and str(t).strip()]
        if not targets:
            targets = _default_wol_targets()

    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            for t in targets:
                for port in (9, 7):
                    try:
                        s.sendto(magic_packet, (t, port))
                        sent += 1
                    except Exception:
                        pass
            time.sleep(0.05)
    return sent


@power_bp.route("/action", methods=["POST"])
def action():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    act = data.get("action", "")

    if is_safe_test_mode() or request.headers.get("X-Safe-Mode") == "1":
        if act in ("shutdown", "sleep", "reboot", "lock"):
            log_action(act)
            return jsonify({"message": f"[SAFE_MODE] Команда '{act}' успешно сымитирована (система защищена)"})

    system = platform.system()
    try:
        if act == "shutdown":
            do_shutdown_now()
            log_action("shutdown")
            return jsonify({"message": "Команда выключения отправлена"})

        elif act == "sleep":
            if system == "Windows":
                subprocess.run(
                    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                    check=False, creationflags=NO_WINDOW,
                )
            elif system == "Darwin":
                subprocess.run(["pmset", "sleepnow"], check=False)
            else:
                subprocess.run(["systemctl", "suspend"], check=False)
            log_action("sleep")
            return jsonify({"message": "Команда сна отправлена"})

        elif act == "reboot":
            if system == "Windows":
                subprocess.run(["shutdown", "/r", "/f", "/t", "0"], check=False, creationflags=NO_WINDOW)
            elif system == "Darwin":
                subprocess.run(["osascript", "-e", 'tell app "System Events" to restart'], check=False)
            else:
                subprocess.run(["sudo", "reboot"], check=False)
            log_action("reboot")
            return jsonify({"message": "Команда перезагрузки отправлена"})

        elif act == "lock":
            if system == "Windows":
                subprocess.run(
                    ["rundll32.exe", "user32.dll,LockWorkStation"],
                    check=False, creationflags=NO_WINDOW,
                )
            elif system == "Darwin":
                subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to keystroke "q" using {control down, command down}'],
                    check=False,
                )
            else:
                subprocess.run(["loginctl", "lock-session"], check=False)
            log_action("lock")
            return jsonify({"message": "Экран заблокирован"})

        else:
            return jsonify({"message": "Неизвестное действие"}), 400

    except Exception as e:
        log_error("action", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500


@power_bp.route("/shutdown_timer", methods=["POST"])
def shutdown_timer():
    global _shutdown_deadline, _shutdown_cancel, _shutdown_gen
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    try:
        raw_m = data.get("minutes", 0)
        if isinstance(raw_m, bool) or raw_m is None:
            return jsonify({"message": "Параметр 'minutes' должен быть положительным целым числом"}), 400
        v = float(raw_m)
        if math.isnan(v) or math.isinf(v):
            return jsonify({"message": "Параметр 'minutes' должен быть положительным целым числом"}), 400
        minutes = int(v)
    except (ValueError, TypeError, OverflowError):
        return jsonify({"message": "Параметр 'minutes' должен быть положительным целым числом"}), 400

    if minutes <= 0:
        return jsonify({"message": "Время таймера должно быть больше нуля (минут)"}), 400
    minutes = min(minutes, 525600)

    safe_req = is_safe_test_mode() or request.headers.get("X-Safe-Mode") == "1"
    with _shutdown_lock:
        _shutdown_cancel.set()
        _shutdown_gen += 1
        my_gen = _shutdown_gen
        cancel_ev = threading.Event()
        _shutdown_cancel = cancel_ev
        _shutdown_deadline = time.time() + minutes * 60

    threading.Thread(
        target=_delayed_shutdown,
        args=(minutes * 60, my_gen, cancel_ev, safe_req),
        daemon=True,
    ).start()

    log_action("schedule_shutdown", {"minutes": minutes})
    return jsonify({"message": f"ПК выключится через {minutes} мин (без предупреждений)"})


@power_bp.route("/shutdown_timer/cancel", methods=["POST"])
def cancel_shutdown_timer():
    global _shutdown_deadline, _shutdown_gen
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    with _shutdown_lock:
        _shutdown_gen += 1
        _shutdown_cancel.set()
        _shutdown_deadline = None
    log_action("cancel_shutdown")
    return jsonify({"message": "Отложенное выключение отменено"})


@power_bp.route("/shutdown_timer/status")
def shutdown_timer_status():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    with _shutdown_lock:
        deadline = _shutdown_deadline
    if deadline is None:
        return jsonify({"active": False})
    remaining = int(deadline - time.time())
    if remaining <= 0:
        return jsonify({"active": False})
    return jsonify({"active": True, "remaining": remaining})


@power_bp.route("/api/wol", methods=["POST"])
def api_wake_on_lan():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"ok": False, "message": "Ожидается JSON с параметром 'mac'"}), 400
    mac = data.get("mac")
    if not mac or not isinstance(mac, str) or not mac.strip():
        return jsonify({"ok": False, "message": "Параметр 'mac' обязателен"}), 400
    mac = mac.strip()
    targets = data.get("targets") or _default_wol_targets()
    try:
        count = send_wol_magic_packet(mac, targets)
        log_action("wake_on_lan", {"mac": mac, "sent": count})
        return jsonify({"ok": True, "message": f"Magic Packet отправлен ({count} пакетов)", "sent": count})
    except (ValueError, binascii.Error) as e:
        return jsonify({"ok": False, "message": f"Неверный MAC-адрес: {e}"}), 400
    except Exception as e:
        log_error("wake_on_lan", e)
        return jsonify({"ok": False, "message": f"Ошибка отправки WOL: {e}"}), 500
