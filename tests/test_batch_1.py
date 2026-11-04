"""
Комплексный автоматизированный тест-сьют: 150 уникальных циклов тестирования
для PC Control (сервер, API, Wake-on-LAN, многопоточность, фаззинг, граничные значения).
"""
import concurrent.futures
import json
import os
import random
import socket
import string
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "http://127.0.0.1:5000"
from pathlib import Path as _P
import sys as _S
_ROOT_DIR = str(_P(__file__).resolve().parent.parent)
if _ROOT_DIR not in _S.path:
    _S.path.insert(0, _ROOT_DIR)
from core.config import get_auth_token
import os as _os
import sys as _S
from pathlib import Path as _P
_ROOT_DIR = str(_P(__file__).resolve().parent.parent)
if _ROOT_DIR not in _S.path:
    _S.path.insert(0, _ROOT_DIR)
from core.config import get_auth_token
TOKEN = _os.environ.get("PC_REMOTE_TOKEN") or get_auth_token()

def make_req(path, method="GET", data=None, token=TOKEN, headers=None, timeout=5):
    url = BASE_URL + path
    hdrs = {}
    if token is not None:
        hdrs["X-Auth-Token"] = token
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            if "Content-Type" not in hdrs:
                hdrs["Content-Type"] = "application/json"
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            return {
                "status": resp.getcode(),
                "headers": dict(resp.headers),
                "data": content,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {
            "status": e.code,
            "headers": dict(e.headers),
            "data": e.read(),
            "error": str(e),
        }
    except Exception as e:
        return {
            "status": -1,
            "headers": {},
            "data": b"",
            "error": str(e),
        }


# ==================== BATCH 1: ЦИКЛЫ 1-25 (Happy Path & Базовые контракты) ====================
def run_batch_1():
    results = []
    
    # 1. GET /status (нормальный запрос с токеном)
    r = make_req("/status")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 1,
        "name": "Status Happy Path",
        "category": "Happy Path",
        "passed": r["status"] == 200 and d.get("status") == "online" and "hostname" in d,
        "detail": f"status={r['status']}, hostname={d.get('hostname')}"
    })

    # 2. GET / (главная страница)
    r = make_req("/")
    results.append({
        "cycle": 2,
        "name": "Index HTML",
        "category": "Happy Path",
        "passed": r["status"] == 200 and b"PC Control" in r["data"] and b"<!doctype html>" in r["data"].lower(),
        "detail": f"status={r['status']}, len={len(r['data'])}"
    })

    # 3. GET /download/apk (скачивание APK)
    r = make_req("/download/apk")
    results.append({
        "cycle": 3,
        "name": "Download APK Happy Path",
        "category": "Happy Path",
        "passed": r["status"] == 200 and r["headers"].get("Content-Type") == "application/vnd.android.package-archive" and len(r["data"]) > 50000,
        "detail": f"status={r['status']}, bytes={len(r['data'])}"
    })

    # 4. GET /download/wol_relay.py (скачивание реле-скрипта)
    r = make_req("/download/wol_relay.py")
    results.append({
        "cycle": 4,
        "name": "Download WOL Relay Happy Path",
        "category": "Happy Path",
        "passed": r["status"] == 200 and b"WOL Relay" in r["data"],
        "detail": f"status={r['status']}, bytes={len(r['data'])}"
    })

    # 5. GET /favicon.ico (иконка сайта)
    r = make_req("/favicon.ico")
    results.append({
        "cycle": 5,
        "name": "Favicon ICO",
        "category": "Happy Path",
        "passed": r["status"] in (200, 204),
        "detail": f"status={r['status']}"
    })

    # 6. GET /volume (чтение громкости системы)
    r = make_req("/volume")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 6,
        "name": "Get System Volume",
        "category": "Happy Path",
        "passed": r["status"] == 200 and "percent" in d and isinstance(d["percent"], int),
        "detail": f"percent={d.get('percent')}, muted={d.get('muted')}"
    })

    # 7. POST /volume (установка громкости 50%)
    r = make_req("/volume", method="POST", data={"percent": 50})
    results.append({
        "cycle": 7,
        "name": "Set System Volume 50%",
        "category": "Happy Path",
        "passed": r["status"] == 200 and b"50%" in r["data"],
        "detail": f"status={r['status']}"
    })

    # 8. GET /screen/volume (чтение локальной громкости потока)
    r = make_req("/screen/volume")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 8,
        "name": "Get Stream Volume",
        "category": "Happy Path",
        "passed": r["status"] == 200 and "percent" in d,
        "detail": f"percent={d.get('percent')}"
    })

    # 9. POST /screen/volume (установка локальной громкости 75%)
    r = make_req("/screen/volume", method="POST", data={"percent": 75, "muted": False})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 9,
        "name": "Set Stream Volume 75%",
        "category": "Happy Path",
        "passed": r["status"] == 200 and d.get("percent") == 75,
        "detail": f"res={d}"
    })

    # 10. GET /screen/monitors (список мониторов)
    r = make_req("/screen/monitors")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 10,
        "name": "Get Screen Monitors",
        "category": "Happy Path",
        "passed": r["status"] == 200 and "monitors" in d and len(d["monitors"]) >= 1,
        "detail": f"monitors_count={len(d.get('monitors', []))}"
    })

    # 11. POST /screen/config (настройка экрана 1080p, 60 FPS)
    r = make_req("/screen/config", method="POST", data={"monitor": 1, "height": 1080, "fps": 60})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 11,
        "name": "Set Screen Config 1080p 60FPS",
        "category": "Happy Path",
        "passed": r["status"] == 200 and d.get("config", {}).get("height") == 1080 and d.get("config", {}).get("fps") == 60,
        "detail": f"cfg={d.get('config')}"
    })

    # 12. GET /history (история действий)
    r = make_req("/history")
    d = json.loads(r["data"]) if r["status"] == 200 else None
    results.append({
        "cycle": 12,
        "name": "Get History List",
        "category": "Happy Path",
        "passed": r["status"] == 200 and isinstance(d, list),
        "detail": f"count={len(d) if isinstance(d, list) else 0}"
    })

    # 13. GET /keyboard/languages (список языков ввода)
    r = make_req("/keyboard/languages")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 13,
        "name": "Get Keyboard Languages",
        "category": "Happy Path",
        "passed": r["status"] == 200 and "languages" in d and isinstance(d["languages"], list),
        "detail": f"langs={len(d.get('languages', []))}"
    })

    # 14. GET /processes (список процессов)
    r = make_req("/processes")
    d = json.loads(r["data"]) if r["status"] == 200 else None
    results.append({
        "cycle": 14,
        "name": "Get Process List",
        "category": "Happy Path",
        "passed": r["status"] == 200 and isinstance(d, list) and len(d) > 0,
        "detail": f"proc_count={len(d) if isinstance(d, list) else 0}"
    })

    # 15. GET /app_volumes (список аудио-приложений)
    r = make_req("/app_volumes")
    d = json.loads(r["data"]) if r["status"] == 200 else None
    results.append({
        "cycle": 15,
        "name": "Get App Volumes",
        "category": "Happy Path",
        "passed": r["status"] == 200 and isinstance(d, list),
        "detail": f"sessions_count={len(d) if isinstance(d, list) else 0}"
    })

    # 16. GET /media/now (YouTube Music активный трек)
    r = make_req("/media/now")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 16,
        "name": "Get Media Now",
        "category": "Happy Path",
        "passed": r["status"] == 200 and "available" in d,
        "detail": f"available={d.get('available')}, title={d.get('title')}"
    })

    # 17. GET /media/queue (очередь треков)
    r = make_req("/media/queue")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 17,
        "name": "Get Media Queue",
        "category": "Happy Path",
        "passed": r["status"] == 200 and "tracks" in d and "history" in d,
        "detail": f"tracks={len(d.get('tracks', []))}, hist={len(d.get('history', []))}"
    })

    # 18. POST /media/mode (режим воспроизведения normal)
    r = make_req("/media/mode", method="POST", data={"mode": "normal"})
    results.append({
        "cycle": 18,
        "name": "Set Media Mode Normal",
        "category": "Happy Path",
        "passed": r["status"] == 200,
        "detail": f"status={r['status']}"
    })

    # 19. POST /api/wol (корректная отправка Wake-on-LAN)
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF"})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 19,
        "name": "Wake-on-LAN Valid MAC",
        "category": "Happy Path",
        "passed": r["status"] == 200 and d.get("ok") is True and d.get("sent", 0) > 0,
        "detail": f"sent={d.get('sent')}"
    })

    # 20. OPTIONS /action (CORS preflight)
    r = make_req("/action", method="OPTIONS")
    results.append({
        "cycle": 20,
        "name": "CORS Preflight OPTIONS /action",
        "category": "Happy Path",
        "passed": r["status"] == 204 and r["headers"].get("Access-Control-Allow-Origin") == "*",
        "detail": f"status={r['status']}, allow_origin={r['headers'].get('Access-Control-Allow-Origin')}"
    })

    # 21. OPTIONS /webrtc/offer (CORS preflight)
    r = make_req("/webrtc/offer", method="OPTIONS")
    results.append({
        "cycle": 21,
        "name": "CORS Preflight OPTIONS /webrtc/offer",
        "category": "Happy Path",
        "passed": r["status"] == 204 and "X-Auth-Token" in r["headers"].get("Access-Control-Allow-Headers", ""),
        "detail": f"status={r['status']}"
    })

    # 22. GET /shutdown_timer/status (статус таймера)
    r = make_req("/shutdown_timer/status")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({
        "cycle": 22,
        "name": "Shutdown Timer Status",
        "category": "Happy Path",
        "passed": r["status"] == 200 and "active" in d,
        "detail": f"active={d.get('active')}"
    })

    # 23. POST /shutdown_timer/cancel (отмена несуществующего таймера)
    r = make_req("/shutdown_timer/cancel", method="POST")
    results.append({
        "cycle": 23,
        "name": "Shutdown Timer Cancel Noop",
        "category": "Happy Path",
        "passed": r["status"] == 200,
        "detail": f"status={r['status']}"
    })

    # 24. Token Auth via URL Query Param (?token=TOKEN)
    r = make_req("/status?token=" + TOKEN, token=None)
    results.append({
        "cycle": 24,
        "name": "Token in Query Param",
        "category": "Happy Path",
        "passed": r["status"] == 200,
        "detail": f"status={r['status']}"
    })

    # 25. Token Auth via JSON Body
    r = make_req("/screen/volume", method="POST", data={"token": TOKEN, "percent": 50}, token=None)
    results.append({
        "cycle": 25,
        "name": "Token in JSON Body",
        "category": "Happy Path",
        "passed": r["status"] == 200,
        "detail": f"status={r['status']}"
    })

    return results

if __name__ == "__main__":
    b1 = run_batch_1()
    passed = sum(1 for x in b1 if x["passed"])
    print(f"Batch 1 Results: {passed}/{len(b1)} passed")
    for r in b1:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
