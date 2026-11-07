"""
PC Control — Модуль проверки и установки обновлений (Update Manager).
Интегрируется с GitHub Releases и full_update.py с защитой от повреждения
пользовательских файлов config.json и launch_presets.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class UpdateManager:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.status_file = self.base_dir / "logs" / "update_status.json"

    def check_updates(self) -> Dict[str, Any]:
        """Проверяет наличие новых релизов на GitHub."""
        try:
            from scripts.full_update import check
            return check(self.base_dir)
        except Exception as ex:
            return {
                "ok": False,
                "has_update": False,
                "error_code": "ERR_UPDATE_CHECK",
                "message": f"Не удалось проверить обновления: {ex}",
            }

    def get_update_status(self) -> Dict[str, Any]:
        """Возвращает текущую фазу процесса обновления из файла статуса."""
        if self.status_file.is_file():
            try:
                return json.loads(self.status_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"phase": "idle", "message": "Обновление не запущено"}

    def prepare_update(self, port: int, restart_server: bool = True) -> Dict[str, Any]:
        """Запускает фоновый процесс загрузки и применения обновления."""
        try:
            from scripts.full_update import prepare
            return prepare(self.base_dir, port=port, restart_server=restart_server)
        except Exception as ex:
            return {
                "ok": False,
                "error_code": "ERR_UPDATE_PREPARE",
                "message": f"Ошибка подготовки обновления: {ex}",
            }
