"""
PC Control — Единый источник информации о версии приложения.
"""
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "version.json"


def get_version_info() -> dict:
    if VERSION_FILE.is_file():
        try:
            return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": "2.4.0", "version_tuple": [2, 4, 0, 0], "name": "PC Control"}


def get_version() -> str:
    return str(get_version_info().get("version", "2.4.0"))


__version__ = get_version()
