"""Build the complete Windows distribution without local settings or signing keys."""
from pathlib import Path
import hashlib
import zipfile
import json
import shutil
import subprocess

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_FILES = (
    "Launcher.exe", "Uninstall.exe", "unstaller.exe", "PC_Control.apk", "version.json", "pc_control.ico", "server.py", "open_app.pyw",
    "requirements.txt", "requirements-runtime.lock", "runtime-source.json", "config.example.json", "README.md", "README.ru.md", "LICENSE",
    "launcher.bat", "start_server.bat", "stop_server.bat", "change_password.bat", "uninstall.bat",
)
SOURCE_EXTENSIONS = {".py", ".pyw", ".cs", ".bat", ".cmd", ".ps1", ".vbs", ".html", ".css", ".js", ".png", ".ico", ".json"}


def package(base_dir=BASE_DIR):
    base_dir = Path(base_dir)
    paths = [base_dir / name for name in ROOT_FILES]
    update_guide = base_dir / 'docs/FULL_PROJECT_UPDATES.ru.md'
    if update_guide.is_file():
        paths.append(update_guide)
    paths.append(base_dir / "tools" / "streamer.exe")
    paths.extend(base_dir / 'runtime' / name for name in ('python.exe', 'pythonw.exe', 'pccontrol-runtime.json'))
    paths.extend(p for p in (base_dir / 'runtime').rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))
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
    start_here = (
            "Extract the complete PC_Control folder, then run Launcher.exe.\n"
            "Keep the scripts, core, modules, tools and web folders next to Launcher.exe.\n"
            "Python and all application libraries are included. No system Python or pip installation is needed.\n"
            "Use Network settings and Change password in the launcher; no config.json editing is required.\n"
            "Install PC_Control.apk on Android, then set the PC address and password in the app.\n"
            "\nРаспакуйте папку PC_Control целиком и запустите Launcher.exe.\n"
            "Настройте сеть и пароль через панель. Не переносите Launcher.exe отдельно от остальных файлов.\n"
        )
    files = {path.relative_to(base_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}
    files['START_HERE.txt'] = hashlib.sha256(start_here.encode('utf-8')).hexdigest()
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=base_dir, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        revision = ''
    material = json.dumps({'files': files, 'revision': revision}, sort_keys=True, separators=(',', ':')).encode()
    manifest = {'schema': 1, 'files': files, 'revision': revision, 'build_id': hashlib.sha256(material).hexdigest()}
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode('utf-8')
    (output_dir / 'release-manifest.json').write_bytes(manifest_bytes)
    archive = output_dir / "PC_Control_Windows.zip"
    temp_archive = output_dir / "PC_Control_Windows.zip.tmp"
    with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('PC_Control/release-manifest.json', manifest_bytes)
        for path in sorted(set(paths)):
            zf.write(path, "PC_Control/" + path.relative_to(base_dir).as_posix())
        zf.writestr("PC_Control/launch_presets.json", "[]\n")
        zf.writestr("PC_Control/START_HERE.txt", start_here)
    with zipfile.ZipFile(temp_archive) as zf:
        if zf.testzip() is not None:
            raise ValueError("Release archive failed CRC verification")
        for name, expected in files.items():
            with zf.open('PC_Control/' + name) as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected:
                raise ValueError(f'Source changed during packaging: {name}. Rebuild the archive.')
    temp_archive.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Created {archive} ({archive.stat().st_size} bytes)")

    portable_archive = output_dir / "PC-Control-Portable.zip"
    shutil.copy2(archive, portable_archive)
    p_digest = hashlib.sha256(portable_archive.read_bytes()).hexdigest()
    portable_archive.with_suffix(".zip.sha256").write_text(f"{p_digest}  {portable_archive.name}\n", encoding="utf-8")
    print(f"Created {portable_archive} ({portable_archive.stat().st_size} bytes)")
    return portable_archive


if __name__ == "__main__":
    package()
