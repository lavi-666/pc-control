"""Build the complete Windows distribution without local settings or signing keys."""
from pathlib import Path
import hashlib
import zipfile

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_FILES = (
    "Launcher.exe", "PC_Control.apk", "pc_control.ico", "server.py", "open_app.pyw",
    "requirements.txt", "config.example.json", "README.md", "README.ru.md", "LICENSE",
    "launcher.bat", "start_server.bat", "stop_server.bat", "change_password.bat", "uninstall.bat",
)
SOURCE_EXTENSIONS = {".py", ".pyw", ".cs", ".bat", ".cmd", ".ps1", ".vbs", ".html", ".css", ".js", ".png", ".ico"}


def package(base_dir=BASE_DIR):
    base_dir = Path(base_dir)
    paths = [base_dir / name for name in ROOT_FILES]
    paths.append(base_dir / "tools" / "streamer.exe")
    for folder in ("core", "modules", "scripts", "web"):
        paths.extend(p for p in (base_dir / folder).rglob("*")
                     if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS
                     and "__pycache__" not in p.parts)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Required release file is missing: {path}")
        if not path.resolve().is_relative_to(base_dir.resolve()):
            raise ValueError(f"Release file escapes project: {path}")
    output_dir = base_dir / "dist"
    output_dir.mkdir(exist_ok=True)
    archive = output_dir / "PC_Control_Windows.zip"
    temp_archive = output_dir / "PC_Control_Windows.zip.tmp"
    with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(set(paths)):
            zf.write(path, "PC_Control/" + path.relative_to(base_dir).as_posix())
        zf.writestr("PC_Control/launch_presets.json", "[]\n")
        zf.writestr("PC_Control/START_HERE.txt", (
            "Extract the complete PC_Control folder, then run Launcher.exe.\n"
            "Keep the scripts, core, modules, tools and web folders next to Launcher.exe.\n"
            "The launcher will guide you through Python/dependency setup. Python 3.12 x64 is recommended.\n"
            "Use Network settings and Change password in the launcher; no config.json editing is required.\n"
            "Install PC_Control.apk on Android, then set the PC address and password in the app.\n"
            "\nРаспакуйте папку PC_Control целиком и запустите Launcher.exe.\n"
            "Настройте сеть и пароль через панель. Не переносите Launcher.exe отдельно от остальных файлов.\n"
        ))
    with zipfile.ZipFile(temp_archive) as zf:
        if zf.testzip() is not None:
            raise ValueError("Release archive failed CRC verification")
    temp_archive.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Created {archive} ({archive.stat().st_size} bytes)")
    return archive


if __name__ == "__main__":
    package()
