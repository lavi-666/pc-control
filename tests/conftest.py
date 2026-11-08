"""
Изоляция тестов от рабочего сервера и настроек пользователя.

Раньше интеграционные тесты (tests/test_batch_*.py) обращались к РАБОЧЕМУ серверу
http://127.0.0.1:5000 и вместе с тестами в процессе писали в настоящий config.json:
выключали звук трансляции (stream_volume 37 %, muted), меняли параметры трансляции, сценарии,
меняли и возвращали пароль, переводили рабочий сервер в тестовый режим (при сбое теста он
так и оставался в нём — трансляция и звук на телефоне заменялись заглушками).

Теперь перед тестами создаётся временная папка данных (копия config.json с отдельным паролем
и свободным портом) и запускается ОТДЕЛЬНЫЙ сервер. Все тесты работают только с ним.
"""

import atexit
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_DATA_DIR = Path(tempfile.mkdtemp(prefix="pcc_test_data_"))
_PORT = _free_port()
_TOKEN = "test-" + secrets.token_hex(8)

_cfg = {}
try:
    _cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
except Exception:
    pass
_cfg.update({"token": _TOKEN, "port": _PORT})
(_DATA_DIR / "config.json").write_text(json.dumps(_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
for _name in ("launch_presets.json", "listening_history.json"):
    if (BASE / _name).exists():
        shutil.copy2(BASE / _name, _DATA_DIR / _name)

# До импорта любых модулей проекта (conftest загружается раньше тестовых модулей)
os.environ["PC_CONTROL_DATA_DIR"] = str(_DATA_DIR)
os.environ["PC_REMOTE_TOKEN"] = _TOKEN
os.environ["PC_CONTROL_TEST_BASE_URL"] = f"http://127.0.0.1:{_PORT}"
os.environ["PC_CONTROL_TEST_PORT"] = str(_PORT)

_server = None


def _stop_server():
    global _server
    if _server is not None and _server.poll() is None:
        _server.terminate()
        try:
            _server.wait(10)
        except Exception:
            _server.kill()
    _server = None
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


def pytest_sessionstart(session):
    global _server
    env = dict(os.environ)
    env["PC_CONTROL_TEST_MODE"] = "1"  # без watchdog и без реальных действий при старте
    _server = subprocess.Popen(
        [sys.executable, str(BASE / "server.py")],
        cwd=str(BASE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    atexit.register(_stop_server)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/status", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("isolated test server did not start")


def pytest_sessionfinish(session, exitstatus):
    _stop_server()
