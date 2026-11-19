"""
PC Control — запуск команд с правами администратора (UAC).

Вынесено из scripts/control_panel.py. Панель импортирует эти функции под прежними именами.
"""

from __future__ import annotations

import platform
import subprocess
from core.winpaths import sys_exe  # QA R-14: full System32 paths

NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0


def run_elevated_command(target: str, params: str = "", work_dir: str = "", show: bool = True, timeout: int = 120) -> tuple[bool, str, str]:
    """
    Запуск команды/процесса с запросом прав администратора (UAC) без ожидания завершения.
    Работает и там, где прямой ShellExecuteW заблокирован (Python из Microsoft Store/MSIX):
    запасной путь — COM Shell.Application через powershell.exe.

    Возвращает (ok, code, message).
    """
    if platform.system() != "Windows":
        return False, "ERR_NOT_SUPPORTED", "UAC elevation is only supported on Windows."

    # Способ 1: прямой ShellExecuteW
    try:
        import ctypes
        from ctypes import wintypes
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.ShellExecuteW.argtypes = [
            wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = wintypes.HINSTANCE
        hwnd = ctypes.windll.user32.GetForegroundWindow() or None
        ctypes.set_last_error(0)
        res = shell32.ShellExecuteW(hwnd, "runas", target, params, work_dir or None, 1 if show else 0)
        last_err = ctypes.get_last_error()
        res_val = int(res) if res is not None else 0
        if res_val > 32:
            return True, "OK", "Elevation launched successfully via ShellExecuteW"
        if last_err == 1223:  # ERROR_CANCELLED — пользователь отклонил UAC
            return False, "ERR_UAC_DENIED", "Запрос прав администратора (UAC) был отклонен пользователем."
    except Exception:
        pass

    # Способ 2: Shell.Application COM через powershell.exe
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
        proc = subprocess.run(
            [sys_exe("powershell.exe"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
        )
        out = proc.stdout.strip()
        if "UAC_OK" in out:
            return True, "OK", "Команда с правами администратора успешно запущена."
        if "UAC_CANCELLED" in out:
            return False, "ERR_UAC_DENIED", "Запрос прав администратора (UAC) был отклонен пользователем."
        err_line = next((l for l in out.splitlines() if l.startswith("UAC_ERROR:")), out or proc.stderr.strip())
        return False, "ERR_UAC_FAILED", f"Не удалось повысить привилегии: {err_line}"
    except subprocess.TimeoutExpired:
        return False, "ERR_UAC_TIMEOUT", "Истекло время ожидания подтверждения запроса прав администратора (UAC)."
    except Exception as e:
        return False, "ERR_UAC_EXCEPTION", f"Сбой вызова механизма UAC: {e}"


def run_elevated_and_wait(target: str, params: str = "", work_dir: str = "", timeout: int = 180) -> tuple[bool, str, str, int | None]:
    """Запуск с правами администратора С ОЖИДАНИЕМ завершения и кодом возврата.
    Возвращает (ok, code, message, exit_code)."""
    if platform.system() != "Windows":
        return False, "ERR_NOT_SUPPORTED", "UAC elevation is only supported on Windows.", None
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040 | 0x00000100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.hwnd = ctypes.windll.user32.GetForegroundWindow() or None
    info.lpVerb = "runas"
    info.lpFile = target
    info.lpParameters = params
    info.lpDirectory = work_dir or None
    info.nShow = 0  # SW_HIDE: вывод идёт в журнал
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        if err == 1223:
            return False, "ERR_UAC_DENIED", "Запрос прав администратора (UAC) был отклонен пользователем.", None
        return False, "ERR_UAC_FAILED", f"Не удалось запустить с правами администратора (код Windows {err}).", None
    if not info.hProcess:
        return False, "ERR_UAC_FAILED", "Процесс с правами администратора не был создан.", None
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000)) != 0:
            return False, "ERR_UAC_TIMEOUT", "Настройка не завершилась за отведённое время.", None
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value == 0, ("OK" if code.value == 0 else "ERR_EXIT_CODE"), f"exit code {code.value}", int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)
