"""
Тесты целостности и синхронизации исполняемых файлов Launcher.exe и unstaller.exe,
а также системы версионирования version.json.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class TestBinarySyncAndVersioning(unittest.TestCase):
    def test_version_file_structure(self):
        v_file = BASE_DIR / "version.json"
        self.assertTrue(v_file.is_file(), "version.json must exist in root")
        data = json.loads(v_file.read_text(encoding="utf-8"))
        self.assertIn("version", data)
        self.assertTrue(re.match(r"^\d+\.\d+\.\d+", data["version"]))
        self.assertIn("version_tuple", data)
        self.assertEqual(len(data["version_tuple"]), 4)

    def test_core_version_module(self):
        from core.version import get_version, get_version_info, __version__
        self.assertTrue(isinstance(__version__, str))
        self.assertTrue(len(__version__) > 0)
        info = get_version_info()
        self.assertEqual(info.get("version"), __version__)

    def test_root_binaries_exist_and_non_empty(self):
        launcher = BASE_DIR / "Launcher.exe"
        self.assertTrue(launcher.is_file(), "Launcher.exe must exist in root")
        self.assertGreater(launcher.stat().st_size, 1024, "Launcher.exe must not be empty or stub")

        unstaller = BASE_DIR / "unstaller.exe"
        uninstall = BASE_DIR / "Uninstall.exe"
        self.assertTrue(unstaller.is_file() or uninstall.is_file(), "unstaller.exe or Uninstall.exe must exist in root")
        if unstaller.is_file():
            self.assertGreater(unstaller.stat().st_size, 1024, "unstaller.exe must not be empty")
        if uninstall.is_file():
            self.assertGreater(uninstall.stat().st_size, 1024, "Uninstall.exe must not be empty")

    def test_packaging_scripts_include_binaries(self):
        import scripts.package_windows as pw
        import scripts.build_installer as bi

        self.assertIn("Launcher.exe", pw.ROOT_FILES)
        self.assertIn("Launcher.exe", bi.ROOT_FILES)
        self.assertTrue("unstaller.exe" in pw.ROOT_FILES or "Uninstall.exe" in pw.ROOT_FILES)
        self.assertTrue("unstaller.exe" in bi.ROOT_FILES or "Uninstall.exe" in bi.ROOT_FILES)

    def test_no_intermediate_compilation_debris_in_root(self):
        debris = list(BASE_DIR.glob("*.tmp")) + list(BASE_DIR.glob("*.obj")) + list(BASE_DIR.glob("*.pdb"))
        self.assertEqual(debris, [], f"Found unexpected compilation debris in root: {debris}")


if __name__ == "__main__":
    unittest.main()
