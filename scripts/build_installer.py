"""
PC Control — Скрипт сборки автономного установщика PC-Control-Setup.exe.
Упаковывает файлы дистрибутива во встроенный ZIP-ресурс и компилирует
автономный установщик C# с помощью стандартного csc.exe.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "dist"
INSTALLER_CS = BASE_DIR / "scripts" / "Installer.cs"
OUT_SETUP_EXE = BASE_DIR / "PC-Control-Setup.exe"

ROOT_FILES = (
    "Launcher.exe",
    "Uninstall.exe",
    "unstaller.exe",
    "PC_Control.apk",
    "version.json",
    "pc_control.ico",
    "server.py",
    "open_app.pyw",
    "requirements.txt",
    "requirements-runtime.lock",
    "runtime-source.json",
    "config.example.json",
    "README.md",
    "README.ru.md",
    "LICENSE",
    "launcher.bat",
    "start_server.bat",
    "stop_server.bat",
    "change_password.bat",
    "uninstall.bat",
)

SOURCE_EXTENSIONS = {
    ".py", ".pyw", ".cs", ".bat", ".cmd", ".ps1", ".vbs", ".html", ".css", ".js", ".png", ".ico", ".json"
}


def ensure_binaries():
    csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc.is_file():
        csc = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")

    # 1. Launcher.exe
    launcher_exe = BASE_DIR / "Launcher.exe"
    if not launcher_exe.is_file():
        print("Compiling Launcher.exe...", flush=True)
        subprocess.run(
            [
                str(csc), "/nologo", "/optimize+", "/target:winexe",
                f"/win32icon:{BASE_DIR / 'pc_control.ico'}",
                f"/out:{launcher_exe}",
                str(BASE_DIR / "scripts" / "Launcher.cs"),
            ],
            check=True,
            cwd=str(BASE_DIR),
        )

    # 2. unstaller.exe and Uninstall.exe
    unstaller_exe = BASE_DIR / "unstaller.exe"
    uninstall_exe = BASE_DIR / "Uninstall.exe"
    uninstall_cs = BASE_DIR / "scripts" / "Uninstall.cs"
    need_compile_uninst = not unstaller_exe.is_file() or not uninstall_exe.is_file()
    if not need_compile_uninst and uninstall_cs.is_file():
        need_compile_uninst = (uninstall_cs.stat().st_mtime > unstaller_exe.stat().st_mtime)

    if need_compile_uninst:
        print("Compiling unstaller.exe and Uninstall.exe...", flush=True)
        subprocess.run(
            [
                str(csc), "/nologo", "/optimize+", "/target:winexe",
                f"/win32icon:{BASE_DIR / 'pc_control.ico'}",
                f"/out:{unstaller_exe}",
                "/r:System.IO.Compression.FileSystem.dll",
                "/r:System.IO.Compression.dll",
                str(uninstall_cs),
            ],
            check=True,
            cwd=str(BASE_DIR),
        )
        shutil.copy2(unstaller_exe, uninstall_exe)

    # 3. Streamer
    streamer_exe = BASE_DIR / "tools" / "streamer.exe"
    if not streamer_exe.is_file():
        cargo_release = BASE_DIR / "streamer_rs" / "target" / "release" / "streamer.exe"
        if cargo_release.is_file():
            streamer_exe.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cargo_release, streamer_exe)


def build_installer(output_path: Path = OUT_SETUP_EXE) -> Path:
    ensure_binaries()
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc.is_file():
        csc = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")

    with tempfile.TemporaryDirectory(prefix="pccontrol_setup_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        payload_zip = tmp_path / "payload.zip"

        print("Creating payload archive...", flush=True)
        # Собираем список файлов для упаковки
        paths: list[Path] = []
        for name in ROOT_FILES:
            p = BASE_DIR / name
            if p.is_file():
                paths.append(p)

        streamer_exe = BASE_DIR / "tools" / "streamer.exe"
        if streamer_exe.is_file():
            paths.append(streamer_exe)

        # Bundling runtime is optional (for offline release artifacts) to keep the repository installer < 2 MB
        include_runtime = os.environ.get("PCCONTROL_BUNDLE_RUNTIME", "").strip().lower() in ("1", "true", "yes")
        if include_runtime:
            runtime_dir = BASE_DIR / "runtime"
            if runtime_dir.is_dir():
                for p in runtime_dir.rglob("*"):
                    if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"):
                        paths.append(p)

        for folder in ("core", "modules", "scripts", "web"):
            f_dir = BASE_DIR / folder
            if f_dir.is_dir():
                for p in f_dir.rglob("*"):
                    if (
                        p.is_file()
                        and p.suffix.lower() in SOURCE_EXTENSIONS
                        and "__pycache__" not in p.parts
                    ):
                        paths.append(p)

        with zipfile.ZipFile(payload_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(set(paths)):
                rel = p.relative_to(BASE_DIR).as_posix()
                zf.write(p, "PC_Control/" + rel)

        print(f"Payload archive size: {payload_zip.stat().st_size // 1024} KB", flush=True)

        print(f"Compiling {output_path.name} via csc.exe...", flush=True)
        cmd = [
            str(csc),
            "/nologo",
            "/optimize+",
            "/target:winexe",
            f"/win32icon:{BASE_DIR / 'pc_control.ico'}",
            "/r:System.IO.Compression.FileSystem.dll",
            "/r:System.IO.Compression.dll",
            f"/resource:{payload_zip},PCControlPayload",
            f"/out:{output_path}",
            str(INSTALLER_CS),
        ]
        subprocess.run(cmd, check=True, cwd=str(BASE_DIR))

    sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Successfully generated standalone installer: {output_path} ({size_mb:.2f} MB)", flush=True)
    print(f"SHA-256: {sha}", flush=True)
    return output_path


if __name__ == "__main__":
    build_installer()
