"""
PC Control — Модуль диагностики и управления деинсталлятором (Diagnostic Manager).
Обеспечивает чтение системного журнала, просмотр и очистку логов,
выгрузку диагностического пакета и запуск Uninstall.exe.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0


class DiagnosticManager:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.actions_log = self.base_dir / "actions_log.jsonl"
        self.error_log = self.logs_dir / "error_log.txt"
        self.uninstaller_exe = self.base_dir / "Uninstall.exe"

    def get_system_journal_status(self) -> Dict[str, Any]:
        """Возвращает статус журнала системных изменений Windows."""
        try:
            from core.system_state import load_journal
            journal, status = load_journal(self.base_dir)
            entries = journal.get("entries", {})
            return {
                "status": status,
                "entries_count": len(entries),
                "entries": entries,
                "updated_at": journal.get("updated_at"),
            }
        except Exception as ex:
            return {"status": "error", "error": str(ex), "entries_count": 0}

    def get_recent_errors(self, max_lines: int = 50) -> List[str]:
        """Возвращает последние строки журнала ошибок."""
        if not self.error_log.is_file():
            return []
        try:
            lines = self.error_log.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-max_lines:]
        except Exception:
            return []

    def clear_logs(self) -> bool:
        """Очищает временные флаги и файлы логов."""
        try:
            for f in self.logs_dir.glob("*.log"):
                try:
                    f.unlink()
                except Exception:
                    pass
            for f in self.logs_dir.glob("*.flag"):
                try:
                    f.unlink()
                except Exception:
                    pass
            if self.error_log.is_file():
                self.error_log.write_text("", encoding="utf-8")
            if self.actions_log.is_file():
                self.actions_log.write_text("", encoding="utf-8")
            return True
        except Exception:
            return False

    def export_diagnostic_bundle(self) -> Dict[str, Any]:
        """Формирует структурированный отчёт о состоянии компонентов."""
        journal_info = self.get_system_journal_status()
        errors = self.get_recent_errors(30)

        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "os": platform.platform(),
            "python": platform.python_version(),
            "install_dir": str(self.base_dir),
            "uninstaller_available": self.uninstaller_exe.is_file(),
            "system_state_journal": journal_info,
            "recent_errors": errors,
        }
        return report

    def launch_uninstaller(self) -> Tuple[bool, str]:
        """Запускает графический интерфейс Uninstall.exe."""
        if not self.uninstaller_exe.is_file():
            # Если бинарник не собран, проверяем bat-скрипт
            uninst_bat = self.base_dir / "uninstall.bat"
            if uninst_bat.is_file():
                subprocess.Popen(["cmd.exe", "/c", str(uninst_bat)], cwd=str(self.base_dir))
                return True, "Запущен скрипт деинсталляции uninstall.bat."
            return False, "Исполняемый файл Uninstall.exe не найден."

        try:
            subprocess.Popen([str(self.uninstaller_exe)], cwd=str(self.base_dir))
            return True, "Интерфейс деинсталлятора успешно запущен."
        except Exception as ex:
            return False, f"Ошибка запуска деинсталлятора: {ex}"
