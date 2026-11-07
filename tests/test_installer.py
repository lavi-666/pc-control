"""
PC Control — Автоматические тесты установщика PC-Control-Setup.exe.
Проверяет распаковку, установку в директории с пробелами и кириллицей,
регистрацию программы и последующее удаление через Uninstall.exe.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SETUP_EXE = BASE_DIR / "PC-Control-Setup.exe"


class TestInstaller(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SETUP_EXE.is_file():
            from scripts.build_installer import build_installer
            build_installer(SETUP_EXE)
        assert SETUP_EXE.is_file(), "PC-Control-Setup.exe must exist"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="pccontrol_inst_test_")
        self.sandbox = Path(self.temp_dir.name)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_installer_help_flag(self):
        """Проверка работы флага --help в CLI установщика."""
        cmd = [str(SETUP_EXE), "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(res.returncode, 0)
        self.assertIn("PC Control Setup", res.stdout)
        self.assertIn("Usage:", res.stdout)

    def test_silent_installation_in_cyrillic_path(self):
        """Проверка тихой установки в папку с пробелами и кириллицей."""
        target_dir = self.sandbox / "Тестовая Программа" / "PC Control Установка"
        cmd = [
            str(SETUP_EXE),
            "/SILENT",
            "/NORUN",
            f"/DIR={target_dir}",
            "--sandbox-dir",
            str(self.sandbox),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"Installer failed: {res.stderr}\n{res.stdout}")
        self.assertIn("Installation successfully completed", res.stdout)

        # Проверяем распакованные файлы
        expected_files = [
            target_dir / "Launcher.exe",
            target_dir / "Uninstall.exe",
            target_dir / "PC_Control.apk",
            target_dir / "server.py",
            target_dir / "web" / "index.html",
            target_dir / "core" / "auth.py",
            target_dir / "scripts" / "control_panel.py",
        ]
        for f in expected_files:
            self.assertTrue(f.is_file(), f"Expected installed file missing: {f}")

        # Проверяем mock-регистрацию деинсталлятора в песочнице
        reg_file = self.sandbox / "mock_uninstall_reg.json"
        self.assertTrue(reg_file.is_file(), "Mock uninstall registration must be created")
        reg_data = json.loads(reg_file.read_text(encoding="utf-8-sig"))
        self.assertEqual(reg_data.get("installed_app", {}).get("name"), "PC Control")

        # Теперь проверяем удаление установленной копии через её собственный Uninstall.exe
        uninst_exe = target_dir / "Uninstall.exe"
        self.assertTrue(uninst_exe.is_file())
        uninst_cmd = [
            str(uninst_exe),
            "--silent",
            "--no-self-delete",
            "--sandbox-dir",
            str(self.sandbox),
        ]
        uninst_res = subprocess.run(uninst_cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(uninst_res.returncode, 0, f"Uninstall failed: {uninst_res.stderr}\n{uninst_res.stdout}")
        self.assertFalse(reg_file.is_file(), "Uninstall registration must be removed upon uninstallation")


if __name__ == "__main__":
    unittest.main()
