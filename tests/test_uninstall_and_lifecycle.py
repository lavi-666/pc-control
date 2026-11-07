"""
PC Control — Комплексный аудит жизненного цикла:
Тестирование Uninstall.exe во всех 6 обязательных сценариях (в изолированной песочнице),
а также тестирование портативности, путей с кириллицей/пробелами, QR-кода и сборки APK.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UNINSTALL_EXE = BASE_DIR / "Uninstall.exe"
BUILD_APK_PY = BASE_DIR / "scripts" / "build_apk.py"


class TestUninstallAndLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Убеждаемся, что Uninstall.exe собран
        if not UNINSTALL_EXE.is_file():
            csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
            if not csc.is_file():
                csc = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
            cmd = [
                str(csc),
                "/nologo",
                "/optimize+",
                "/target:winexe",
                f"/win32icon:{BASE_DIR / 'pc_control.ico'}",
                f"/out:{UNINSTALL_EXE}",
                str(BASE_DIR / "scripts" / "Uninstall.cs"),
            ]
            subprocess.run(cmd, check=True, cwd=BASE_DIR)
        assert UNINSTALL_EXE.is_file(), "Uninstall.exe must exist"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="pc_control_test_")
        self.sandbox = Path(self.temp_dir.name)
        self.logs_dir = self.sandbox / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _write_mock_state(self, state: dict):
        f = self.sandbox / "mock_windows_state.json"
        f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_mock_state(self) -> dict:
        f = self.sandbox / "mock_windows_state.json"
        if not f.is_file():
            return {}
        return json.loads(f.read_text(encoding="utf-8-sig"))

    def _write_journal(self, journal: dict):
        f = self.logs_dir / "system_state_journal.json"
        f.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_uninstall(self, *extra_args) -> subprocess.CompletedProcess:
        report_file = self.sandbox / "uninstall_report.json"
        cmd = [
            str(UNINSTALL_EXE),
            "--silent",
            "--no-self-delete",
            "--sandbox-dir",
            str(self.sandbox),
            "--report-file",
            str(report_file),
            *extra_args,
        ]
        return subprocess.run(
            cmd,
            cwd=str(self.sandbox),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def _read_report(self) -> dict:
        report_file = self.sandbox / "uninstall_report.json"
        if report_file.is_file():
            return json.loads(report_file.read_text(encoding="utf-8-sig"))
        return {}

    # ------------------ Сценарий 1 ------------------
    def test_scenario_1_untouched_setting(self):
        """Сценарий 1: если настройка не менялась программой, деинсталлятор её не трогает."""
        initial_mock = {
            "registry": {
                r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device": {
                    "key_exists": True,
                    "values": {"DevicePasswordLessBuildVersion": 2},
                },
                r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power": {
                    "key_exists": True,
                    "values": {"HiberbootEnabled": 1},
                },
            },
            "firewall_rules": {},
            "shortcuts": {},
        }
        self._write_mock_state(initial_mock)

        # В журнале записано только изменение Hiberboot (Windows Hello не менялся программой)
        journal = {
            "schema_version": 1,
            "application": "PC Control",
            "entries": {
                "registry.hiberboot": {
                    "component_id": "registry.hiberboot",
                    "category": "registry",
                    "description": "Быстрый запуск",
                    "original_state": {
                        "hive": "HKLM",
                        "subkey": r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
                        "value_name": "HiberbootEnabled",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 1,
                    },
                    "applied_state": {
                        "hive": "HKLM",
                        "subkey": r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
                        "value_name": "HiberbootEnabled",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 0,
                    },
                }
            },
        }
        self._write_journal(journal)

        res = self._run_uninstall()
        self.assertEqual(res.returncode, 0)

        after_state = self._read_mock_state()
        hello_val = (
            after_state.get("registry", {})
            .get(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device", {})
            .get("values", {})
            .get("DevicePasswordLessBuildVersion")
        )
        self.assertEqual(hello_val, 2, "Неизменённый параметр Windows Hello должен остаться нетронутым (2)")

        report = self._read_report()
        comp_ids = [c["component_id"] for c in report.get("components", [])]
        self.assertNotIn("registry.windows_hello", comp_ids)

    # ------------------ Сценарий 2 ------------------
    def test_scenario_2_revert_modified_settings(self):
        """Сценарий 2: если настройка была изменена программой, деинсталлятор возвращает её в исходное значение."""
        # Текущее состояние: значения изменены программой на 0, создано правило брандмауэра
        initial_mock = {
            "registry": {
                r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device": {
                    "key_exists": True,
                    "values": {"DevicePasswordLessBuildVersion": 0},
                },
                r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power": {
                    "key_exists": True,
                    "values": {"HiberbootEnabled": 0},
                },
            },
            "firewall_rules": {
                "PC Control Server": {"port": 5000, "action": "allow"},
            },
            "shortcuts": {},
        }
        self._write_mock_state(initial_mock)

        # Журнал фиксирует, что изначально было 2 и 1, а правила брандмауэра не существовало
        journal = {
            "schema_version": 1,
            "application": "PC Control",
            "entries": {
                "registry.windows_hello": {
                    "component_id": "registry.windows_hello",
                    "category": "registry",
                    "description": "Windows Hello",
                    "original_state": {
                        "hive": "HKLM",
                        "subkey": r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device",
                        "value_name": "DevicePasswordLessBuildVersion",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 2,
                    },
                    "applied_state": {
                        "hive": "HKLM",
                        "subkey": r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device",
                        "value_name": "DevicePasswordLessBuildVersion",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 0,
                    },
                },
                "registry.hiberboot": {
                    "component_id": "registry.hiberboot",
                    "category": "registry",
                    "description": "Быстрый запуск",
                    "original_state": {
                        "hive": "HKLM",
                        "subkey": r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
                        "value_name": "HiberbootEnabled",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 1,
                    },
                    "applied_state": {
                        "hive": "HKLM",
                        "subkey": r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
                        "value_name": "HiberbootEnabled",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 0,
                    },
                },
                "firewall.server": {
                    "component_id": "firewall.server",
                    "category": "firewall",
                    "description": "Брандмауэр порт 5000",
                    "original_state": {"rule_name": "PC Control Server", "existed": False},
                    "applied_state": {"rule_name": "PC Control Server", "existed": True, "port": 5000},
                },
            },
        }
        self._write_journal(journal)

        res = self._run_uninstall()
        self.assertEqual(res.returncode, 0)

        after_state = self._read_mock_state()
        hello_val = (
            after_state.get("registry", {})
            .get(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device", {})
            .get("values", {})
            .get("DevicePasswordLessBuildVersion")
        )
        hiber_val = (
            after_state.get("registry", {})
            .get(r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power", {})
            .get("values", {})
            .get("HiberbootEnabled")
        )
        fw_rules = after_state.get("firewall_rules", {})

        self.assertEqual(hello_val, 2, "Windows Hello должен быть возвращён в исходное значение 2")
        self.assertEqual(hiber_val, 1, "Hiberboot должен быть возвращён в исходное значение 1")
        self.assertNotIn("PC Control Server", fw_rules, "Созданное правило брандмауэра должно быть удалено")

        report = self._read_report()
        for comp in report.get("components", []):
            if comp["category"] == "registry":
                self.assertEqual(comp["execution_result"], "RESTORED")
            elif comp["category"] == "firewall":
                self.assertEqual(comp["execution_result"], "RULE_REMOVED")

    # ------------------ Сценарий 3 ------------------
    def test_scenario_3_conflict_detection_and_policies(self):
        """Сценарий 3: если настройка была изменена программой, а затем пользователем вручную, деинсталлятор обрабатывает конфликт."""
        # Исходно было 2 -> программа поставила 0 -> пользователь вручную переставил в 1!
        initial_mock = {
            "registry": {
                r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device": {
                    "key_exists": True,
                    "values": {"DevicePasswordLessBuildVersion": 1},
                }
            },
            "firewall_rules": {},
            "shortcuts": {},
        }
        journal = {
            "schema_version": 1,
            "application": "PC Control",
            "entries": {
                "registry.windows_hello": {
                    "component_id": "registry.windows_hello",
                    "category": "registry",
                    "description": "Windows Hello",
                    "original_state": {
                        "hive": "HKLM",
                        "subkey": r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device",
                        "value_name": "DevicePasswordLessBuildVersion",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 2,
                    },
                    "applied_state": {
                        "hive": "HKLM",
                        "subkey": r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device",
                        "value_name": "DevicePasswordLessBuildVersion",
                        "key_existed": True,
                        "value_existed": True,
                        "value": 0,
                    },
                }
            },
        }

        # 3A: Политика по умолчанию (--conflict-policy keep)
        self._write_mock_state(initial_mock)
        self._write_journal(journal)
        res_keep = self._run_uninstall("--conflict-policy", "keep")
        self.assertEqual(res_keep.returncode, 0)

        state_after_keep = self._read_mock_state()
        val_keep = (
            state_after_keep.get("registry", {})
            .get(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device", {})
            .get("values", {})
            .get("DevicePasswordLessBuildVersion")
        )
        self.assertEqual(val_keep, 1, "Политика keep обязана сохранить пользовательское ручное значение 1")

        report_keep = self._read_report()
        self.assertTrue(report_keep.get("conflicts_detected"))
        comp_keep = report_keep["components"][0]
        self.assertTrue(comp_keep["has_conflict"])
        self.assertEqual(comp_keep["execution_result"], "CONFLICT_KEPT")

        # 3B: Явная политика отката (--conflict-policy restore)
        self._write_mock_state(initial_mock)
        self._write_journal(journal)
        res_restore = self._run_uninstall("--conflict-policy", "restore")
        self.assertEqual(res_restore.returncode, 0)

        state_after_restore = self._read_mock_state()
        val_restore = (
            state_after_restore.get("registry", {})
            .get(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device", {})
            .get("values", {})
            .get("DevicePasswordLessBuildVersion")
        )
        self.assertEqual(val_restore, 2, "Политика restore принудительно восстанавливает исходное значение 2")

        report_restore = self._read_report()
        self.assertTrue(report_restore.get("conflicts_detected"))
        comp_restore = report_restore["components"][0]
        self.assertEqual(comp_restore["execution_result"], "CONFLICT_RESTORED")

    # ------------------ Сценарий 4 ------------------
    def test_scenario_4_missing_or_corrupted_journal(self):
        """Сценарий 4: если журнал повреждён или отсутствует, деинсталлятор не трогает чужие настройки и удаляет только гарантированно свои."""
        initial_mock = {
            "registry": {
                r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device": {
                    "key_exists": True,
                    "values": {"DevicePasswordLessBuildVersion": 0},
                }
            },
            "firewall_rules": {
                "PC Control Server": {"port": 5000, "action": "allow"},
            },
            "shortcuts": {},
        }

        # 4A: Отсутствующий журнал
        self._write_mock_state(initial_mock)
        journal_file = self.logs_dir / "system_state_journal.json"
        if journal_file.is_file():
            journal_file.unlink()

        res_missing = self._run_uninstall()
        self.assertEqual(res_missing.returncode, 0)

        state_after_missing = self._read_mock_state()
        hello_val = (
            state_after_missing.get("registry", {})
            .get(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device", {})
            .get("values", {})
            .get("DevicePasswordLessBuildVersion")
        )
        self.assertEqual(hello_val, 0, "При отсутствии журнала деинсталлятор НЕ должен угадывать дефолты реестра!")
        self.assertNotIn("PC Control Server", state_after_missing.get("firewall_rules", {}), "Своё правило брандмауэра должно быть удалено")

        report_missing = self._read_report()
        self.assertEqual(report_missing.get("journal_status"), "missing")

        # 4B: Повреждённый журнал
        self._write_mock_state(initial_mock)
        journal_file.write_text("{CORRUPTED_SYNTAX_JSON", encoding="utf-8")

        res_corrupt = self._run_uninstall()
        self.assertEqual(res_corrupt.returncode, 0)

        report_corrupt = self._read_report()
        self.assertEqual(report_corrupt.get("journal_status"), "corrupted")

    # ------------------ Сценарий 5 ------------------
    def test_scenario_5_idempotency_repeated_run(self):
        """Сценарий 5: повторный запуск деинсталлятора завершается без ошибок."""
        initial_mock = {
            "registry": {},
            "firewall_rules": {},
            "shortcuts": {},
        }
        self._write_mock_state(initial_mock)
        self._write_journal({"schema_version": 1, "entries": {}})

        # Первый запуск
        res1 = self._run_uninstall()
        self.assertEqual(res1.returncode, 0)

        # Второй запуск на том же месте
        res2 = self._run_uninstall()
        self.assertEqual(res2.returncode, 0)

    # ------------------ Сценарий 6 ------------------
    def test_scenario_6_process_termination_safety(self):
        """Сценарий 6: деинсталлятор завершает только процессы этого проекта."""
        # В песочнице реальные процессы системы не завершаются
        res = self._run_uninstall("--dry-run")
        self.assertEqual(res.returncode, 0)
        report = self._read_report()
        self.assertTrue(report.get("dry_run"))
        self.assertEqual(report.get("stopped_processes"), [])

    # ------------------ Тест путей с пробелами, кириллицей и сборки APK ------------------
    def test_cyrillic_spaces_path_and_apk_build(self):
        """Проверка портативности: запуск и сборка APK в директории с пробелами и кириллицей."""
        cyrillic_root = self.sandbox / "Тестовая Папка Проекта" / "PC Control Тест"
        cyrillic_root.mkdir(parents=True, exist_ok=True)

        # Копируем компоненты для автономного запуска и сборки APK
        shutil.copytree(BASE_DIR / "android_app", cyrillic_root / "android_app")
        shutil.copytree(BASE_DIR / "scripts", cyrillic_root / "scripts")
        shutil.copytree(BASE_DIR / "core", cyrillic_root / "core")
        shutil.copytree(BASE_DIR / "web", cyrillic_root / "web")
        shutil.copy2(BASE_DIR / "server.py", cyrillic_root / "server.py")

        # Проверяем сборку APK через scripts/build_apk.py в кириллической папке
        apk_target = cyrillic_root / "PC_Control.apk"
        cmd = [
            sys.executable,
            str(cyrillic_root / "scripts" / "build_apk.py"),
            "--token",
            "test-audit-token",
            "--lan",
            "192.168.1.123",
            "--mac",
            "AA-BB-CC-DD-EE-FF",
        ]
        res = subprocess.run(
            cmd,
            cwd=str(cyrillic_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.assertEqual(res.returncode, 0, f"APK build in Cyrillic folder failed: {res.stderr}\n{res.stdout}")
        self.assertTrue(apk_target.is_file(), "PC_Control.apk must be successfully compiled and signed")
        self.assertGreater(apk_target.stat().st_size, 10000, "PC_Control.apk size must be valid")

        # Проверяем, что параметры вшиты в assets/index.html внутри собранного APK
        with zipfile.ZipFile(apk_target, "r") as z:
            index_html = z.read("assets/index.html").decode("utf-8")
            self.assertIn("192.168.1.123", index_html)
            self.assertIn("AA-BB-CC-DD-EE-FF", index_html)
            self.assertIn("test-audit-token", index_html)


if __name__ == "__main__":
    unittest.main()
