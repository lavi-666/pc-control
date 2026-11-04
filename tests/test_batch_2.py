"""
Batch 2: Граничные значения (0, -1, максимум, минимум, пустые строки, null/None)
Циклы 26-50.
"""
import json
import urllib.error
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
    hdrs = {"X-Safe-Mode": "1"}
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
            return {"status": resp.getcode(), "headers": dict(resp.headers), "data": content, "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "headers": dict(e.headers), "data": e.read(), "error": str(e)}
    except Exception as e:
        return {"status": -1, "headers": {}, "data": b"", "error": str(e)}

def run_batch_2():
    # Активируем безопасный режим на сервере, чтобы гарантировать отсутствие ребутов/выключений
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 26. /volume POST percent = 0
    r = make_req("/volume", method="POST", data={"percent": 0})
    results.append({"cycle": 26, "name": "Volume Boundary 0", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 27. /volume POST percent = 100
    r = make_req("/volume", method="POST", data={"percent": 100})
    results.append({"cycle": 27, "name": "Volume Boundary 100", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 28. /volume POST percent = -1 (должен зажаться в 0, без падения сервера)
    r = make_req("/volume", method="POST", data={"percent": -1})
    results.append({"cycle": 28, "name": "Volume Boundary -1 (Clamping)", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 29. /volume POST percent = 101 (должен зажаться в 100)
    r = make_req("/volume", method="POST", data={"percent": 101})
    results.append({"cycle": 29, "name": "Volume Boundary 101 (Clamping)", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 30. /volume POST percent = 999999999999 (экстремальный максимум)
    r = make_req("/volume", method="POST", data={"percent": 999999999999})
    results.append({"cycle": 30, "name": "Volume Extreme Max", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 31. /volume POST percent = -999999999999 (экстремальный минимум)
    r = make_req("/volume", method="POST", data={"percent": -999999999999})
    results.append({"cycle": 31, "name": "Volume Extreme Min", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 32. /volume POST percent = 50.7 (дробное число)
    r = make_req("/volume", method="POST", data={"percent": 50.7})
    results.append({"cycle": 32, "name": "Volume Float 50.7", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 33. /volume POST percent = 0.0
    r = make_req("/volume", method="POST", data={"percent": 0.0})
    results.append({"cycle": 33, "name": "Volume Float 0.0", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 34. /screen/volume POST percent = 0
    r = make_req("/screen/volume", method="POST", data={"percent": 0})
    results.append({"cycle": 34, "name": "Screen Volume Boundary 0", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 35. /screen/volume POST percent = 100
    r = make_req("/screen/volume", method="POST", data={"percent": 100})
    results.append({"cycle": 35, "name": "Screen Volume Boundary 100", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 36. /screen/volume POST percent = -50 (clamp to 0)
    r = make_req("/screen/volume", method="POST", data={"percent": -50})
    results.append({"cycle": 36, "name": "Screen Volume Clamping Min", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 37. /screen/volume POST percent = 200 (clamp to 100)
    r = make_req("/screen/volume", method="POST", data={"percent": 200})
    results.append({"cycle": 37, "name": "Screen Volume Clamping Max", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 38. /screen/volume POST percent = None/null
    r = make_req("/screen/volume", method="POST", data={"percent": None})
    results.append({"cycle": 38, "name": "Screen Volume Null", "category": "Boundary", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 39. /screen/volume POST пустой json {}
    r = make_req("/screen/volume", method="POST", data={})
    results.append({"cycle": 39, "name": "Screen Volume Empty JSON", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 40. /screen/config POST monitor = -1 (должен сбросить на 0, не упасть)
    r = make_req("/screen/config", method="POST", data={"monitor": -1})
    results.append({"cycle": 40, "name": "Screen Config Monitor -1", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 41. /screen/config POST height = 0
    r = make_req("/screen/config", method="POST", data={"height": 0})
    results.append({"cycle": 41, "name": "Screen Config Height 0", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 42. /screen/config POST fps = 0
    r = make_req("/screen/config", method="POST", data={"fps": 0})
    results.append({"cycle": 42, "name": "Screen Config FPS 0", "category": "Boundary", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 43. /screen/config POST fps = 999 (должен ограничить 60 FPS)
    r = make_req("/screen/config", method="POST", data={"fps": 999})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 43, "name": "Screen Config FPS Max Limit", "category": "Boundary", "passed": r["status"] == 200 and d.get("config", {}).get("fps") == 60, "detail": f"fps={d.get('config', {}).get('fps')}"})

    # 44. /shutdown_timer POST minutes = 0 (ДОЛЖЕН отклонить с 400, чтобы случайно не выключить ПК!)
    r = make_req("/shutdown_timer", method="POST", data={"minutes": 0})
    make_req("/shutdown_timer/cancel", method="POST") # на всякий случай отменяем
    results.append({"cycle": 44, "name": "Shutdown Timer Minutes = 0 Protection", "category": "Boundary", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 45. /shutdown_timer POST minutes = -5 (ДОЛЖЕН отклонить с 400!)
    r = make_req("/shutdown_timer", method="POST", data={"minutes": -5})
    make_req("/shutdown_timer/cancel", method="POST") # на всякий случай отменяем
    results.append({"cycle": 45, "name": "Shutdown Timer Negative Minutes Protection", "category": "Boundary", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 46. /processes/kill POST пустой словарь {}
    r = make_req("/processes/kill", method="POST", data={})
    results.append({"cycle": 46, "name": "Processes Kill Empty Dict", "category": "Boundary", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 47. /processes/kill POST pid = 0 (системный PID Idle, нельзя убивать!)
    r = make_req("/processes/kill", method="POST", data={"pid": 0})
    results.append({"cycle": 47, "name": "Processes Kill PID 0 Protection", "category": "Boundary", "passed": r["status"] in (400, 403, 500), "detail": f"status={r['status']}"})

    # 48. /processes/kill POST pid = -1
    r = make_req("/processes/kill", method="POST", data={"pid": -1})
    results.append({"cycle": 48, "name": "Processes Kill PID -1", "category": "Boundary", "passed": r["status"] in (400, 403, 500), "detail": f"status={r['status']}"})

    # 49. /keyboard/set_language POST id = "" (пустая строка)
    r = make_req("/keyboard/set_language", method="POST", data={"id": ""})
    results.append({"cycle": 49, "name": "Keyboard Set Language Empty ID", "category": "Boundary", "passed": r["status"] in (400, 404), "detail": f"status={r['status']}"})

    # 50. /api/wol POST mac = "" (пустая строка)
    r = make_req("/api/wol", method="POST", data={"mac": ""})
    results.append({"cycle": 50, "name": "Wake-on-LAN Empty MAC", "category": "Boundary", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    return results

if __name__ == "__main__":
    b2 = run_batch_2()
    passed = sum(1 for x in b2 if x["passed"])
    print(f"Batch 2 Results: {passed}/{len(b2)} passed")
    for r in b2:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
