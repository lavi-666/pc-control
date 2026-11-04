"""
Batch 14: Стандарты протокола HTTP, MIME-типы, Content-Disposition, методы и заголовки
Циклы 326-350.
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

def run_batch_14():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 326. GET / Content-Type содержит text/html
    r = make_req("/")
    ct = r["headers"].get("Content-Type", "")
    results.append({"cycle": 326, "name": "Index HTML MIME Content-Type", "category": "HTTP Standards", "passed": "text/html" in ct, "detail": f"Content-Type={ct}"})

    # 327. GET /favicon.ico MIME image/x-icon
    r = make_req("/favicon.ico")
    ct_ico = r["headers"].get("Content-Type", "")
    results.append({"cycle": 327, "name": "Favicon MIME image/x-icon", "category": "HTTP Standards", "passed": "image/x-icon" in ct_ico or "image/vnd.microsoft.icon" in ct_ico, "detail": f"Content-Type={ct_ico}"})

    # 328. HEAD /favicon.ico -> 200
    r = make_req("/favicon.ico", method="HEAD")
    results.append({"cycle": 328, "name": "Favicon HEAD Request 200", "category": "HTTP Standards", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 329. GET /download/apk MIME application/vnd.android.package-archive
    r = make_req("/download/apk")
    ct_apk = r["headers"].get("Content-Type", "")
    results.append({"cycle": 329, "name": "Download APK MIME Type", "category": "HTTP Standards", "passed": "vnd.android.package-archive" in ct_apk, "detail": f"Content-Type={ct_apk}"})

    # 330. GET /download/apk Content-Disposition
    cd_apk = r["headers"].get("Content-Disposition", "")
    results.append({"cycle": 330, "name": "Download APK Content-Disposition", "category": "HTTP Standards", "passed": "attachment" in cd_apk and "PC_Control.apk" in cd_apk, "detail": f"cd={cd_apk}"})

    # 331. HEAD /download/apk Content-Length > 50000
    r = make_req("/download/apk", method="HEAD")
    cl_apk = int(r["headers"].get("Content-Length", 0))
    results.append({"cycle": 331, "name": "Download APK HEAD Content-Length", "category": "HTTP Standards", "passed": r["status"] == 200 and cl_apk > 50000, "detail": f"length={cl_apk}"})

    # 332. GET /download/wol_relay.py Content-Disposition
    r = make_req("/download/wol_relay.py")
    cd_relay = r["headers"].get("Content-Disposition", "")
    results.append({"cycle": 332, "name": "Download WOL Relay Content-Disposition", "category": "HTTP Standards", "passed": "attachment" in cd_relay and "wol_relay.py" in cd_relay, "detail": f"cd={cd_relay}"})

    # 333. HEAD /download/wol_relay.py -> 200
    r = make_req("/download/wol_relay.py", method="HEAD")
    results.append({"cycle": 333, "name": "Download WOL Relay HEAD Request", "category": "HTTP Standards", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 334. GET /status MIME application/json
    r = make_req("/status")
    results.append({"cycle": 334, "name": "Status MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 335. GET /history MIME application/json
    r = make_req("/history")
    results.append({"cycle": 335, "name": "History MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 336. GET /volume MIME application/json
    r = make_req("/volume")
    results.append({"cycle": 336, "name": "Volume MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 337. GET /app_volumes MIME application/json
    r = make_req("/app_volumes")
    results.append({"cycle": 337, "name": "App Volumes MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 338. GET /media/queue MIME application/json
    r = make_req("/media/queue")
    results.append({"cycle": 338, "name": "Media Queue MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 339. GET /keyboard/languages MIME application/json
    r = make_req("/keyboard/languages")
    results.append({"cycle": 339, "name": "Keyboard Languages MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 340. GET /shutdown_timer/status MIME application/json
    r = make_req("/shutdown_timer/status")
    results.append({"cycle": 340, "name": "Shutdown Timer Status MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 341. GET /api/safe_mode MIME application/json
    r = make_req("/api/safe_mode")
    results.append({"cycle": 341, "name": "Safe Mode MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 342. GET /screen/monitors MIME application/json
    r = make_req("/screen/monitors")
    results.append({"cycle": 342, "name": "Screen Monitors MIME application/json", "category": "HTTP Standards", "passed": "application/json" in r["headers"].get("Content-Type", ""), "detail": f"ct={r['headers'].get('Content-Type')}"})

    # 343. Несуществующий путь 404
    r = make_req("/invalid_path_random_404")
    results.append({"cycle": 343, "name": "Unknown Path 404", "category": "HTTP Standards", "passed": r["status"] == 404, "detail": f"status={r['status']}"})

    # 344. Несуществующий вложенный путь 404
    r = make_req("/api/unknown/subpath/404")
    results.append({"cycle": 344, "name": "Unknown Nested Subpath 404", "category": "HTTP Standards", "passed": r["status"] == 404, "detail": f"status={r['status']}"})

    # 345. Method Not Allowed на /status (POST -> 405)
    r = make_req("/status", method="POST", data={})
    results.append({"cycle": 345, "name": "Status POST Method Not Allowed", "category": "HTTP Standards", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 346. Method Not Allowed на /shutdown_timer/status (POST -> 405)
    r = make_req("/shutdown_timer/status", method="POST", data={})
    results.append({"cycle": 346, "name": "Shutdown Timer Status POST Method Not Allowed", "category": "HTTP Standards", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 347. Method Not Allowed на /app_volumes (POST -> 405)
    r = make_req("/app_volumes", method="POST", data={})
    results.append({"cycle": 347, "name": "App Volumes POST Method Not Allowed", "category": "HTTP Standards", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 348. Method Not Allowed на /media/queue (POST -> 405)
    r = make_req("/media/queue", method="POST", data={})
    results.append({"cycle": 348, "name": "Media Queue POST Method Not Allowed", "category": "HTTP Standards", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 349. Method Not Allowed на /media/now (POST -> 405)
    r = make_req("/media/now", method="POST", data={})
    results.append({"cycle": 349, "name": "Media Now POST Method Not Allowed", "category": "HTTP Standards", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 350. Method Not Allowed на /keyboard/languages (POST -> 405)
    r = make_req("/keyboard/languages", method="POST", data={})
    results.append({"cycle": 350, "name": "Keyboard Languages POST Method Not Allowed", "category": "HTTP Standards", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    return results

if __name__ == "__main__":
    b = run_batch_14()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 14 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
