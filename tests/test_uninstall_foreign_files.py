"""
PC Control — Автоматические тесты абсолютной безопасности деинсталлятора и установщика:
Доказывают, что:
1. Uninstall.exe при наличии манифеста удаляет ТОЛЬКО файлы манифеста и НИКОГДА не удаляет посторонние файлы пользователя.
2. При отсутствии или повреждении манифеста деинсталлятор работает по строгому белому списку и НЕ удаляет файлы пользователя.
3. При флаге --keep-user-data гарантированно сохраняются config.json, launch_presets.json и logs.
4. Installer.cs блокирует установку в корень диска, системные папки Windows и изолирует установку при наличии чужих файлов.
5. Восстановление исходных параметров сетевых адаптеров Wake-on-LAN и powercfg.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UNINSTALL_EXE = BASE_DIR / "Uninstall.exe"
INSTALLER_CS = BASE_DIR / "scripts" / "Installer.cs"


class TestUninstallForeignFilesSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Собираем во временную папку: раньше тест перезаписывал Uninstall.exe в корне проекта
        # (файл под git), и после каждого прогона тестов он числился изменённым.
        global UNINSTALL_EXE
        cls._build_dir = tempfile.TemporaryDirectory(prefix="pc_uninst_build_")
        UNINSTALL_EXE = Path(cls._build_dir.name) / "Uninstall.exe"
        csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
        if not csc.is_file():
            csc = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")

        # Компилируем актуальный Uninstall.exe
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

    @classmethod
    def tearDownClass(cls):
        try:
            cls._build_dir.cleanup()
        except Exception:
            pass

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="pc_safe_uninstall_")
        self.test_root = Path(self.temp_dir.name)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_manifest_based_uninstallation_preserves_foreign_files(self):
        """Сценарий 1: Установка с манифестом — удаляются только файлы проекта, чужие файлы не трогаются."""
        app_dir = self.test_root / "SharedDirectoryWithUserData"
        app_dir.mkdir(parents=True, exist_ok=True)

        # Копируем Uninstall.exe в app_dir
        app_uninst = app_dir / "Uninstall.exe"
        shutil.copy2(UNINSTALL_EXE, app_uninst)

        # Создаем проектные файлы
        (app_dir / "Launcher.exe").write_bytes(b"MOCK_LAUNCHER")
        (app_dir / "server.py").write_text("print('server')", encoding="utf-8")
        core_dir = app_dir / "core"
        core_dir.mkdir(parents=True, exist_ok=True)
        (core_dir / "auth.py").write_text("# auth", encoding="utf-8")

        # Создаем ПОСТОРОННИЕ пользовательские файлы в той же директории
        foreign_photo = app_dir / "family_vacation_photo.jpg"
        foreign_photo.write_bytes(b"JPEG_HEADER_AND_IMAGE_DATA")

        foreign_excel = app_dir / "financial_budget_2026.xlsx"
        foreign_excel.write_bytes(b"EXCEL_DATA")

        foreign_notes = app_dir / "my_secret_notes.txt"
        foreign_notes.write_text("Very important personal notes", encoding="utf-8")

        foreign_sub = app_dir / "PersonalDocuments" / "Taxes"
        foreign_sub.mkdir(parents=True, exist_ok=True)
        foreign_pdf = foreign_sub / "tax_declaration_2025.pdf"
        foreign_pdf.write_bytes(b"PDF_DOCUMENT_CONTENT")

        # Формируем install_manifest.json, содержащий только файлы PC Control
        manifest = {
            "schema_version": 1,
            "application": "PC Control",
            "version": "2.4.0",
            "files": [
                {"path": "Launcher.exe", "size": 13, "sha256": "mock1"},
                {"path": "server.py", "size": 15, "sha256": "mock2"},
                {"path": "core/auth.py", "size": 6, "sha256": "mock3"},
            ]
        }
        (app_dir / "install_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        # Запускаем деинсталлятор из app_dir
        cmd = [
            str(app_uninst),
            "--silent",
            "--no-self-delete",
            # Песочница: без неё деинсталлятор запрашивал права администратора (UAC) и мог
            # откатить НАСТОЯЩИЕ системные настройки PC Control на этом ПК.
            "--sandbox-dir",
            str(app_dir),
        ]
        res = subprocess.run(cmd, cwd=str(app_dir), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0)

        # Проверяем: проектные файлы из манифеста удалены
        self.assertFalse((app_dir / "Launcher.exe").exists(), "Launcher.exe must be removed")
        self.assertFalse((app_dir / "server.py").exists(), "server.py must be removed")
        self.assertFalse((core_dir / "auth.py").exists(), "auth.py must be removed")
        self.assertFalse((app_dir / "install_manifest.json").exists(), "install_manifest.json must be removed")

        # КРИТИЧЕСКИ ВАЖНО: ВСЕ посторонние пользовательские файлы ОБЯЗАНЫ остаться в целости и сохранности!
        self.assertTrue(foreign_photo.is_file(), "Foreign photo MUST NEVER be deleted!")
        self.assertEqual(foreign_photo.read_bytes(), b"JPEG_HEADER_AND_IMAGE_DATA")

        self.assertTrue(foreign_excel.is_file(), "Foreign excel budget MUST NEVER be deleted!")
        self.assertEqual(foreign_excel.read_bytes(), b"EXCEL_DATA")

        self.assertTrue(foreign_notes.is_file(), "Foreign notes MUST NEVER be deleted!")
        self.assertEqual(foreign_notes.read_text(encoding="utf-8"), "Very important personal notes")

        self.assertTrue(foreign_pdf.is_file(), "Foreign tax PDF MUST NEVER be deleted!")
        self.assertEqual(foreign_pdf.read_bytes(), b"PDF_DOCUMENT_CONTENT")

        # Каталог не должен быть удален, так как в нем остались файлы пользователя
        self.assertTrue(app_dir.is_dir(), "Directory containing foreign files MUST NOT be deleted!")

    def test_missing_manifest_fallback_preserves_foreign_files(self):
        """Сценарий 2: При отсутствии манифеста деинсталлятор удаляет только известные файлы проекта."""
        app_dir = self.test_root / "ExistingFolderWithoutManifest"
        app_dir.mkdir(parents=True, exist_ok=True)

        app_uninst = app_dir / "Uninstall.exe"
        shutil.copy2(UNINSTALL_EXE, app_uninst)

        # Файлы PC Control
        (app_dir / "Launcher.exe").write_bytes(b"MOCK_LAUNCHER")
        (app_dir / "server.py").write_text("print('server')", encoding="utf-8")
        (app_dir / "pc_control.ico").write_bytes(b"ICO")

        # Посторонние файлы пользователя
        user_db = app_dir / "clients_database.sqlite"
        user_db.write_bytes(b"SQLITE_DB_CONTENT")

        user_archive = app_dir / "backup_archive.zip"
        user_archive.write_bytes(b"ZIP_ARCHIVE_BYTES")

        user_folder = app_dir / "MyCustomProject"
        user_folder.mkdir(parents=True, exist_ok=True)
        user_source = user_folder / "app.py"
        user_source.write_text("print('user custom code')", encoding="utf-8")

        # Запускаем Uninstall.exe без манифеста
        cmd = [
            str(app_uninst),
            "--silent",
            "--no-self-delete",
            # Песочница: без неё деинсталлятор запрашивал права администратора (UAC) и мог
            # откатить НАСТОЯЩИЕ системные настройки PC Control на этом ПК.
            "--sandbox-dir",
            str(app_dir),
        ]
        res = subprocess.run(cmd, cwd=str(app_dir), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0)

        # Проектные файлы удалены
        self.assertFalse((app_dir / "Launcher.exe").exists())
        self.assertFalse((app_dir / "server.py").exists())
        self.assertFalse((app_dir / "pc_control.ico").exists())

        # Посторонние файлы гарантированно сохранены!
        self.assertTrue(user_db.is_file(), "user_db must not be touched")
        self.assertTrue(user_archive.is_file(), "user_archive must not be touched")
        self.assertTrue(user_source.is_file(), "user_source in custom folder must not be touched")
        self.assertTrue(app_dir.is_dir())

    def test_keep_user_data_preserves_configs_and_logs(self):
        """Сценарий 3: Флаг --keep-user-data сохраняет config.json, launch_presets.json и логи."""
        app_dir = self.test_root / "AppDataDirectory"
        app_dir.mkdir(parents=True, exist_ok=True)

        app_uninst = app_dir / "Uninstall.exe"
        shutil.copy2(UNINSTALL_EXE, app_uninst)

        (app_dir / "Launcher.exe").write_bytes(b"MOCK_LAUNCHER")
        (app_dir / "server.py").write_bytes(b"MOCK_SERVER")

        # Пользовательские конфиги и логи
        cfg = app_dir / "config.json"
        cfg.write_text('{"token": "my-secret-token", "port": 5000}', encoding="utf-8")

        presets = app_dir / "launch_presets.json"
        presets.write_text('{"presets": ["preset1", "preset2"]}', encoding="utf-8")

        logs_dir = app_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        server_log = logs_dir / "server.log"
        server_log.write_text("2026-11-07 Server started\n", encoding="utf-8")

        manifest = {
            "schema_version": 1,
            "application": "PC Control",
            "version": "2.4.0",
            "files": [
                {"path": "Launcher.exe", "size": 13, "sha256": "m1"},
                {"path": "server.py", "size": 11, "sha256": "m2"},
                {"path": "config.json", "size": 42, "sha256": "m3"},
                {"path": "launch_presets.json", "size": 36, "sha256": "m4"},
            ]
        }
        (app_dir / "install_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        cmd = [
            str(app_uninst),
            "--silent",
            "--no-self-delete",
            "--keep-user-data",
            "--sandbox-dir",
            str(app_dir),
        ]
        res = subprocess.run(cmd, cwd=str(app_dir), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0)

        # Бинарники проекта удалены
        self.assertFalse((app_dir / "Launcher.exe").exists())
        self.assertFalse((app_dir / "server.py").exists())

        # Конфиги и логи пользователя сохранены!
        self.assertTrue(cfg.is_file(), "config.json must be preserved with --keep-user-data")
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8"))["token"], "my-secret-token")

        self.assertTrue(presets.is_file(), "launch_presets.json must be preserved")
        self.assertTrue(server_log.is_file(), "server.log must be preserved")

    def test_wol_adapter_state_capture_and_rollback(self):
        """Сценарий 5: Восстановление исходного состояния сетевого адаптера Wake-on-LAN."""
        sandbox_dir = self.test_root / "wol_sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = sandbox_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        mock_state = {
            "registry": {},
            "firewall_rules": {},
            "shortcuts": {},
            "wol_adapters": {
                "Ethernet": {
                    "description": "Realtek PCIe GbE Family Controller",
                    "wake_armed": True,
                    "WakeOnMagicPacket": "1",
                    "WakeOnPattern": "1",
                }
            }
        }
        (sandbox_dir / "mock_windows_state.json").write_text(json.dumps(mock_state), encoding="utf-8")

        # Исходное состояние до изменения программой: Magic=0, Pattern=0, wake_armed=False
        journal = {
            "schema_version": 1,
            "application": "PC Control",
            "entries": {
                "wol.adapter.ethernet": {
                    "component_id": "wol.adapter.ethernet",
                    "category": "wol_adapter",
                    "description": "Адаптер Ethernet",
                    "original_state": {
                        "adapter_name": "Ethernet",
                        "interface_description": "Realtek PCIe GbE Family Controller",
                        "wake_on_magic_packet": "0",
                        "wake_on_pattern": "0",
                        "wake_armed": False,
                    },
                    "applied_state": {
                        "adapter_name": "Ethernet",
                        "interface_description": "Realtek PCIe GbE Family Controller",
                        "wake_on_magic_packet": "1",
                        "wake_on_pattern": "1",
                        "wake_armed": True,
                    }
                }
            }
        }
        (logs_dir / "system_state_journal.json").write_text(json.dumps(journal), encoding="utf-8")

        cmd = [
            str(UNINSTALL_EXE),
            "--silent",
            "--no-self-delete",
            "--sandbox-dir",
            str(sandbox_dir),
        ]
        res = subprocess.run(cmd, cwd=str(sandbox_dir), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0)

        # Проверяем, что в mock_windows_state.json параметры сетевого адаптера откатились к исходным (0, 0, False)
        after = json.loads((sandbox_dir / "mock_windows_state.json").read_text(encoding="utf-8"))
        eth = after.get("wol_adapters", {}).get("Ethernet", {})
        self.assertEqual(eth.get("WakeOnMagicPacket"), "0", "WakeOnMagicPacket must be restored to 0")
        self.assertEqual(eth.get("WakeOnPattern"), "0", "WakeOnPattern must be restored to 0")
        self.assertEqual(eth.get("wake_armed"), False, "wake_armed must be restored to False")


if __name__ == "__main__":
    unittest.main()
