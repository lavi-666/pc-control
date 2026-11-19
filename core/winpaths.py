"""Full paths of Windows system tools (QA R-14).

CreateProcess / ShellExecute look for a bare "powershell.exe" / "taskkill" in the current folder
first - the program folder, which the user can write to. A planted powershell.exe there would run
(even elevated, after an ordinary UAC prompt). These helpers always point into %SystemRoot%.
"""

from __future__ import annotations

import os
from pathlib import Path

_SPECIAL = {
    "powershell": Path("WindowsPowerShell") / "v1.0" / "powershell.exe",
    "powershell.exe": Path("WindowsPowerShell") / "v1.0" / "powershell.exe",
}


def system32() -> Path:
    return Path(os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows") / "System32"


def sys_exe(name: str) -> str:
    """'taskkill' -> 'C:\\Windows\\System32\\taskkill.exe' (falls back to the bare name off Windows
    or when the file is missing, so nothing breaks on unusual systems)."""
    key = name.lower()
    rel = _SPECIAL.get(key) or Path(key if key.endswith(".exe") else key + ".exe")
    full = system32() / rel
    if os.name == "nt" and full.is_file():
        return str(full)
    return name
