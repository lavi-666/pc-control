"""
PC Control — проверка библиотек Python в том интерпретаторе, который запускает сервер.

Проверка идёт в отдельном процессе: импорт в долгоживущую панель закэшировал бы устаревшие
модули и смешал окружения. Кэширование — на стороне вызывающего кода.
"""

from __future__ import annotations

import json
import platform
import subprocess

NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

REQUIRED_PACKAGES = [
    ("Flask", "flask"),
    ("Pillow", "PIL"),
    ("pycaw", "pycaw"),
    ("comtypes", "comtypes"),
    ("winsdk", "winsdk"),
    ("psutil", "psutil"),
    ("pyaudiowpatch", "pyaudiowpatch"),
    ("mss", "mss"),
    ("qrcode", "qrcode"),
    ("numpy", "numpy"),
]

_PROBE = """
import importlib, json, sys
result = {'installed_list': [], 'errors': {}, 'missing': [], 'python_version': sys.version.split()[0]}
for name, module in json.loads(sys.argv[1]):
    try:
        importlib.import_module(module)
        if module == 'winsdk':
            importlib.import_module('winsdk.windows.media.control')
        result['installed_list'].append(name)
    except ModuleNotFoundError as exc:
        # Модуль действительно не найден — это «нет библиотеки».
        result['missing'].append(name)
        result['errors'][name] = str(exc)
    except Exception as exc:
        # Модуль есть, но упал при импорте — это не «нет библиотеки». Сюда же ImportError
        # «DLL load failed»: после входа в Windows антивирус может держать .pyd/.dll, и раньше
        # такой временный сбой считался «библиотеки не установлены» — автозапуск сдавался.
        result['errors'][name] = f'{type(exc).__name__}: {exc}'
print(json.dumps(result))
"""

DEFAULT_TIMEOUT = 30.0


def probe(python_cli: str, has_runtime: bool, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Результат проверки. Важно различать:
    - missing      — библиотек действительно нет (ModuleNotFoundError/ImportError): нужна установка;
    - probe_failed — сама проверка не удалась (таймаут на «холодном» старте Windows, сбой процесса,
                     пустой вывод). Раньше это выдавалось за «не установлены все библиотеки»: автозапуск
                     после перезагрузки отказывался запускать сервер, а панель предлагала переустановку."""
    probe_error = ""
    try:
        process = subprocess.run([python_cli, "-I", "-c", _PROBE, json.dumps(REQUIRED_PACKAGES)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=timeout, creationflags=NO_WINDOW)
        if process.returncode:
            raise RuntimeError(process.stderr.strip()[-500:] or f"Python exit code {process.returncode}")
        lines = process.stdout.strip().splitlines()
        if not lines:
            raise RuntimeError("the check printed nothing")
        result = json.loads(lines[-1])
        result.setdefault("missing", list(result.get("errors", {})))
    except subprocess.TimeoutExpired:
        probe_error = f"the library check did not finish in {int(timeout)} s (Windows is still starting up?)"
    except Exception as exc:
        probe_error = f"the library check failed: {exc}"
    if probe_error:
        return {
            "has_venv": has_runtime,
            "installed": False,
            "probe_failed": True,
            "probe_error": probe_error,
            "missing": [],
            "missing_count": 0,
            "broken": [],
            "installed_list": [],
            "details": f"Could not check Python libraries: {probe_error}",
            "python_version": "unavailable",
            "errors": {},
            "interpreter": python_cli,
        }
    missing = list(result["missing"])
    broken = [name for name in result["errors"] if name not in missing]
    if missing:
        details = f"Missing packages ({len(missing)}): {', '.join(missing)}"
    elif broken:
        details = f"Packages failed to load ({len(broken)}): {', '.join(broken)}"
    else:
        details = "All required Python libraries are installed."
    return {
        "has_venv": has_runtime,
        "installed": not missing and not broken,
        "probe_failed": False,
        "probe_error": "",
        "missing": missing,
        "missing_count": len(missing),
        "broken": broken,
        "installed_list": result["installed_list"],
        "details": details,
        "python_version": result["python_version"],
        "errors": result["errors"],
        "interpreter": python_cli,
    }


def definitely_missing(result: dict) -> bool:
    """Библиотек точно нет (а не «проверка не удалась» / «временный сбой импорта»)."""
    return bool(result) and not result.get("probe_failed") and bool(result.get("missing"))
