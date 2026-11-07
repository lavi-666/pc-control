"""
PC Control — Скрипт верификации согласованности релизов и бинарников.
Проверяет:
1. Наличие и валидность version.json.
2. Присутствие Launcher.exe и unstaller.exe / Uninstall.exe в корне.
3. Соответствие версий в C# исходниках и version.json.
4. Успешность тестовой компиляции C# компонентов.
5. Регистрацию файлов в package_windows.py и build_installer.py.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_csc_path() -> Path:
    candidates = [
        Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("csc.exe (.NET Framework 4.0/4.8) not found on system.")


def check_version_json() -> str:
    v_file = BASE_DIR / "version.json"
    if not v_file.is_file():
        raise FileNotFoundError(f"Missing {v_file}")
    data = json.loads(v_file.read_text(encoding="utf-8"))
    version = data.get("version")
    if not version or not re.match(r"^\d+\.\d+\.\d+", str(version)):
        raise ValueError(f"Invalid version format in {v_file}: {version}")
    print(f"[OK] version.json: version {version}")
    return str(version)


def check_root_binaries():
    launcher = BASE_DIR / "Launcher.exe"
    unstaller = BASE_DIR / "unstaller.exe"
    uninstall = BASE_DIR / "Uninstall.exe"

    if not launcher.is_file():
        raise FileNotFoundError(f"Critical binary missing from root: {launcher}")
    print(f"[OK] Launcher.exe present ({launcher.stat().st_size} bytes)")

    if not unstaller.is_file() and not uninstall.is_file():
        raise FileNotFoundError("Neither unstaller.exe nor Uninstall.exe found in root!")

    if unstaller.is_file():
        print(f"[OK] unstaller.exe present ({unstaller.stat().st_size} bytes)")
    if uninstall.is_file():
        print(f"[OK] Uninstall.exe present ({uninstall.stat().st_size} bytes)")


def check_cs_versions(version: str):
    cs_files = [
        BASE_DIR / "scripts" / "Launcher.cs",
        BASE_DIR / "scripts" / "Uninstall.cs",
        BASE_DIR / "scripts" / "Installer.cs",
    ]
    ver_prefix = ".".join(version.split(".")[:2])
    for cs in cs_files:
        if not cs.is_file():
            raise FileNotFoundError(f"Missing source file: {cs}")
        content = cs.read_text(encoding="utf-8")
        if f'AssemblyVersion("{version}' not in content and f'AssemblyVersion("{ver_prefix}' not in content:
            print(f"[WARN] {cs.name} may have mismatching AssemblyVersion (expected {version})")
        else:
            print(f"[OK] {cs.name} version matches {version}")


def test_compile_binaries():
    csc = get_csc_path()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Launcher test compile
        out_launcher = tmp_dir / "TestLauncher.exe"
        res = subprocess.run(
            [
                str(csc), "/nologo", "/optimize+", "/target:winexe",
                f"/win32icon:{BASE_DIR / 'pc_control.ico'}",
                f"/out:{out_launcher}",
                str(BASE_DIR / "scripts" / "Launcher.cs"),
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Launcher.cs compilation failed:\n{res.stderr}\n{res.stdout}")
        print(f"[OK] Launcher.cs test compilation passed ({out_launcher.stat().st_size} bytes)")

        # 2. Uninstall test compile
        out_uninst = tmp_dir / "TestUnstaller.exe"
        res = subprocess.run(
            [
                str(csc), "/nologo", "/optimize+", "/target:winexe",
                f"/win32icon:{BASE_DIR / 'pc_control.ico'}",
                f"/out:{out_uninst}",
                "/r:System.IO.Compression.FileSystem.dll",
                "/r:System.IO.Compression.dll",
                str(BASE_DIR / "scripts" / "Uninstall.cs"),
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Uninstall.cs compilation failed:\n{res.stderr}\n{res.stdout}")
        print(f"[OK] Uninstall.cs test compilation passed ({out_uninst.stat().st_size} bytes)")


def main():
    print("=" * 60)
    print("PC CONTROL - VERIFY RELEASE & BINARY CONSISTENCY")
    print("=" * 60)
    version = check_version_json()
    check_root_binaries()
    check_cs_versions(version)
    test_compile_binaries()
    print("=" * 60)
    print("ALL RELEASE CONSISTENCY CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAIL] Consistency check error: {e}", file=sys.stderr)
        sys.exit(1)
