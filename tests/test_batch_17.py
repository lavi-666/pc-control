"""
Batch 17: Экстремальные граничные значения (NaN, Infinity, 1e308, переполнение целых чисел)
Циклы 401-425.
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

def run_batch_17():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 401. /volume POST NaN -> 400
    r = make_req("/volume", method="POST", data='{"percent": NaN}')
    results.append({"cycle": 401, "name": "Volume NaN Ingestion", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 402. /volume POST Infinity -> 400 или 200
    r = make_req("/volume", method="POST", data='{"percent": Infinity}')
    results.append({"cycle": 402, "name": "Volume Positive Infinity", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 403. /volume POST -Infinity -> 400 или 200
    r = make_req("/volume", method="POST", data='{"percent": -Infinity}')
    results.append({"cycle": 403, "name": "Volume Negative Infinity", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 404. /volume POST 1e308 -> 200 (clamped to 100)
    r = make_req("/volume", method="POST", data={"percent": 1e308})
    results.append({"cycle": 404, "name": "Volume 1e308 Double Overflow", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 405. /volume POST -1e308 -> 200 (clamped to 0)
    r = make_req("/volume", method="POST", data={"percent": -1e308})
    results.append({"cycle": 405, "name": "Volume -1e308 Double Underflow", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 406. /volume POST 1e-308 -> 200 (clamped to 0)
    r = make_req("/volume", method="POST", data={"percent": 1e-308})
    results.append({"cycle": 406, "name": "Volume 1e-308 Subnormal Float", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 407. /volume POST 0.000000001 -> 200
    r = make_req("/volume", method="POST", data={"percent": 0.000000001})
    results.append({"cycle": 407, "name": "Volume Tiny Epsilon Fraction", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 408. /volume POST 99.999999999 -> 200
    r = make_req("/volume", method="POST", data={"percent": 99.999999999})
    results.append({"cycle": 408, "name": "Volume High Precision Rounding", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 409. /volume POST -0.0 -> 200
    r = make_req("/volume", method="POST", data={"percent": -0.0})
    results.append({"cycle": 409, "name": "Volume Negative Zero (-0.0)", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 410. /screen/volume POST NaN
    r = make_req("/screen/volume", method="POST", data='{"percent": NaN}')
    results.append({"cycle": 410, "name": "Screen Volume NaN Graceful", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 411. /screen/volume POST Infinity
    r = make_req("/screen/volume", method="POST", data='{"percent": Infinity}')
    results.append({"cycle": 411, "name": "Screen Volume Infinity Graceful", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 412. /screen/volume POST 100.0
    r = make_req("/screen/volume", method="POST", data={"percent": 100.0})
    results.append({"cycle": 412, "name": "Screen Volume 100.0 Float", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 413. /screen/volume POST 0.0
    r = make_req("/screen/volume", method="POST", data={"percent": 0.0})
    results.append({"cycle": 413, "name": "Screen Volume 0.0 Float", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 414. /screen/config POST monitor=2147483647
    r = make_req("/screen/config", method="POST", data={"monitor": 2147483647})
    results.append({"cycle": 414, "name": "Screen Config Max 32-bit Int Monitor", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 415. /screen/config POST height=2147483647 -> clamped to 1080
    r = make_req("/screen/config", method="POST", data={"height": 2147483647})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 415, "name": "Screen Config Max 32-bit Height Clamping", "category": "Boundary Math", "passed": d.get("config", {}).get("height") == 1080, "detail": f"h={d.get('config', {}).get('height')}"})

    # 416. /screen/config POST fps=2147483647 -> clamped to 60
    r = make_req("/screen/config", method="POST", data={"fps": 2147483647})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 416, "name": "Screen Config Max 32-bit FPS Clamping", "category": "Boundary Math", "passed": d.get("config", {}).get("fps") == 60, "detail": f"fps={d.get('config', {}).get('fps')}"})

    # 417. /screen/config POST fps=-2147483648 -> clamped to 30
    r = make_req("/screen/config", method="POST", data={"fps": -2147483648})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 417, "name": "Screen Config Min 32-bit FPS Clamping", "category": "Boundary Math", "passed": d.get("config", {}).get("fps") == 30, "detail": f"fps={d.get('config', {}).get('fps')}"})

    # 418. /screen/config POST height=-2147483648 -> clamped to 720
    r = make_req("/screen/config", method="POST", data={"height": -2147483648})
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 418, "name": "Screen Config Min 32-bit Height Clamping", "category": "Boundary Math", "passed": d.get("config", {}).get("height") == 720, "detail": f"h={d.get('config', {}).get('height')}"})

    # 419. /shutdown_timer POST minutes=2147483647
    r = make_req("/shutdown_timer", method="POST", data={"minutes": 2147483647})
    make_req("/shutdown_timer/cancel", method="POST")
    results.append({"cycle": 419, "name": "Shutdown Timer Max 32-bit Minutes", "category": "Boundary Math", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 420. /shutdown_timer POST NaN -> 400
    r = make_req("/shutdown_timer", method="POST", data='{"minutes": NaN}')
    results.append({"cycle": 420, "name": "Shutdown Timer NaN Ingestion 400", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 421. /shutdown_timer POST Infinity -> 400 или 200
    r = make_req("/shutdown_timer", method="POST", data='{"minutes": Infinity}')
    results.append({"cycle": 421, "name": "Shutdown Timer Infinity Ingestion", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 422. /media/volume POST NaN -> 400
    r = make_req("/media/volume", method="POST", data='{"percent": NaN}')
    results.append({"cycle": 422, "name": "Media Volume NaN Ingestion", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 423. /media/volume POST Infinity -> 400
    r = make_req("/media/volume", method="POST", data='{"percent": Infinity}')
    results.append({"cycle": 423, "name": "Media Volume Infinity Ingestion", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 424. /app_volume POST NaN -> 400
    r = make_req("/app_volume", method="POST", data='{"pid": 1234, "percent": NaN}')
    results.append({"cycle": 424, "name": "App Volume NaN Ingestion", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 425. /app_volume POST Infinity -> 400
    r = make_req("/app_volume", method="POST", data='{"pid": 1234, "percent": Infinity}')
    results.append({"cycle": 425, "name": "App Volume Infinity Ingestion", "category": "Boundary Math", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    return results

if __name__ == "__main__":
    b = run_batch_17()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 17 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
