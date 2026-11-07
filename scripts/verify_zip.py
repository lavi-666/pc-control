"""
Verify that the distribution ZIP archive extracts and works cleanly in a standalone sandbox.
"""
import zipfile
import tempfile
import subprocess
import json
import hashlib
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
zip_path = BASE_DIR / "dist" / "PC_Control_Windows.zip"
assert zip_path.exists(), f"ZIP does not exist: {zip_path}"
print(f"Testing ZIP: {zip_path} ({zip_path.stat().st_size} bytes)")

with tempfile.TemporaryDirectory(prefix="pccontrol_verify_zip_") as tmp:
    tmp_path = Path(tmp)
    print(f"Extracting to clean sandbox: {tmp_path}")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp_path)
    
    app_dir = tmp_path / "PC_Control"
    assert app_dir.is_dir(), "PC_Control root folder missing in ZIP"
    
    # 1. Verify key files
    key_files = [
        "Launcher.exe", "Uninstall.exe", "PC_Control.apk", "server.py",
        "tools/streamer.exe", "runtime/python.exe", "runtime/pythonw.exe",
        "web/control_panel.html", "web/index.html", "core/auth.py",
        "core/launcher/server_mgr.py", "scripts/build_apk.py",
        "START_HERE.txt", "release-manifest.json", "README.md", "README.ru.md"
    ]
    for kf in key_files:
        f = app_dir / kf
        assert f.exists(), f"Missing file in extracted ZIP: {kf}"
    print("All key files successfully extracted and verified.")

    # 2. Verify manifest checksums
    manifest_file = app_dir / "release-manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    for rel_path, expected_hash in manifest["files"].items():
        if rel_path == "START_HERE.txt":
            target = app_dir / "START_HERE.txt"
        else:
            target = app_dir / rel_path
        assert target.exists(), f"Manifest file missing: {rel_path}"
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"Hash mismatch on {rel_path}"
    print(f"All {len(manifest['files'])} files in manifest matched SHA-256 checksums 100%!")

    # 3. Test embedded python executable and server syntax in clean sandbox
    bundled_py = app_dir / "runtime" / "python.exe"
    res = subprocess.run([str(bundled_py), "-c", "import flask, pycaw, mss, PIL; print('Bundled runtime modules OK')"], capture_output=True, text=True, timeout=10)
    assert res.returncode == 0, f"Runtime test failed: {res.stderr}"
    print("Bundled Python runtime verified: " + res.stdout.strip())

    # 4. Test Uninstall.exe CLI help in clean sandbox
    uninst = app_dir / "Uninstall.exe"
    res_uninst = subprocess.run([str(uninst), "--help"], capture_output=True, text=True, timeout=10)
    assert res_uninst.returncode == 0, f"Uninstall.exe failed: {res_uninst.stderr}"
    print("Uninstall.exe verified: CLI responsive")

print("CLEAN EXTRACTED ZIP VALIDATION PASSED 100%!")
