"""
PC Control — параметры входа Windows: Windows Hello (PasswordLess), netplwiz, «Варианты входа».

Вынесено из scripts/control_panel.py.
"""

from __future__ import annotations

import platform
import time

from core.launcher.elevation import run_elevated_and_wait
from core.winpaths import sys_exe  # QA R-14: full System32 paths

_HELLO_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device"


def get_windows_hello_status() -> dict:
    """Состояние HKLM\\...\\PasswordLess\\Device\\DevicePasswordLessBuildVersion:
    2 или отсутствует → включено (флажок в netplwiz скрыт); 0 → выключено."""
    if platform.system() != "Windows":
        return {"supported": False, "enabled": False, "raw_value": None}
    try:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _HELLO_KEY) as k:
                val, _ = winreg.QueryValueEx(k, "DevicePasswordLessBuildVersion")
                enabled = int(val) != 0
                raw_val = int(val)
        except Exception:
            enabled = True
            raw_val = None
        return {"supported": True, "enabled": enabled, "raw_value": raw_val}
    except Exception as e:
        return {"supported": False, "enabled": False, "raw_value": None, "error": str(e)}


def set_windows_hello_state(enabled: bool) -> tuple[bool, str]:
    """Устанавливает DevicePasswordLessBuildVersion (2 — включено, 0 — выключено) через UAC
    и проверяет фактическое значение в реестре."""
    if platform.system() != "Windows":
        return False, "Изменение параметров Windows Hello поддерживается только в ОС Windows."

    target_val = 2 if enabled else 0
    current = get_windows_hello_status()
    if current.get("supported") and current.get("enabled") == enabled:
        return True, f"Настройка Windows Hello уже {'включена' if enabled else 'отключена'}."

    try:
        from core.system_state import capture_windows_hello_before_change
        capture_windows_hello_before_change(enabled)
    except Exception:
        pass

    ps_cmd = (
        f"$p = 'HKLM:\\{_HELLO_KEY}'; "
        f"if (-not (Test-Path $p)) {{ New-Item -Path $p -Force | Out-Null }}; "
        f"Set-ItemProperty -Path $p -Name 'DevicePasswordLessBuildVersion' -Value {target_val} -Type DWord"
    )
    # Ждём завершения команды: раньше запуск шёл без ожидания, и если пользователь подтверждал окно UAC
    # дольше 3 секунд, панель сообщала «значение реестра не изменилось», хотя изменение потом проходило.
    ok, code, msg, _exit = run_elevated_and_wait(
        sys_exe("powershell.exe"), f'-NoProfile -NonInteractive -WindowStyle Hidden -Command "{ps_cmd}"', "", timeout=120
    )
    if not ok and code in ("ERR_UAC_DENIED", "ERR_UAC_FAILED", "ERR_NOT_SUPPORTED"):
        return False, msg

    for _ in range(15):  # до 3 секунд
        time.sleep(0.2)
        if get_windows_hello_status().get("enabled") == enabled:
            return True, f"Windows Hello успешно {'включен' if enabled else 'отключен'}."
    return False, ("Значение реестра не изменилось. Возможно, действуют групповые политики Windows "
                   "или изменение заблокировано системой.")


def _shell_open(target: str, params: str | None = None) -> int:
    import ctypes
    return int(ctypes.windll.shell32.ShellExecuteW(None, "open", target, params, None, 1))


def launch_netplwiz() -> tuple[bool, str]:
    """Открывает только системную утилиту netplwiz (или control userpasswords2), ничего не меняя."""
    if platform.system() != "Windows":
        return False, "Утилита netplwiz доступна только в ОС Windows."
    try:
        res = _shell_open("netplwiz.exe")
        if res > 32:
            return True, "Системное окно netplwiz успешно открыто."
        if _shell_open("control.exe", "userpasswords2") > 32:
            return True, "Системное окно netplwiz (userpasswords2) открыто."
        return False, f"Не удалось открыть netplwiz (код ошибки {res})."
    except Exception as e:
        return False, f"Ошибка при запуске netplwiz: {e}"


def open_signin_settings() -> tuple[bool, str]:
    """Открывает «Параметры → Учётные записи → Варианты входа» (ms-settings:signinoptions)."""
    if platform.system() != "Windows":
        return False, "Параметры Windows доступны только в ОС Windows."
    try:
        res = _shell_open("ms-settings:signinoptions")
        if res > 32:
            return True, "Раздел параметров входа Windows открыт."
        return False, f"Не удалось открыть параметры входа (код ошибки {res})."
    except Exception as e:
        return False, f"Ошибка при открытии параметров входа: {e}"
