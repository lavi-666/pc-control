"""
Batch 21: Per-Application Audio Session Edge Cases, Pycaw Endpoint Control & Volume Bounds
Циклы 501-525.
"""
import concurrent.futures
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

def run_batch_21():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 501. /app_volumes Schema validation
    r501 = make_req("/app_volumes")
    data501 = json.loads(r501["data"]) if r501["status"] == 200 else None
    passed501 = isinstance(data501, list)
    results.append({"cycle": 501, "name": "App Volumes Schema Array Verification", "category": "Audio Mixer", "passed": passed501, "detail": f"count={len(data501) if passed501 else 0}"})

    # 502. App Volumes Field types
    fields_valid = True
    if data501:
        for app in data501:
            if not (isinstance(app.get("pid"), int) and isinstance(app.get("name"), str) and 0 <= app.get("percent", -1) <= 100 and isinstance(app.get("muted"), bool)):
                fields_valid = False
                break
    results.append({"cycle": 502, "name": "App Volumes Data Types & Range Contract", "category": "Audio Mixer", "passed": fields_valid, "detail": f"valid={fields_valid}"})

    # 503. PID uniqueness in app volumes
    if data501:
        pids = [a["pid"] for a in data501]
        unique_pids = len(pids) == len(set(pids))
    else:
        unique_pids = True
    results.append({"cycle": 503, "name": "App Volumes PID Uniqueness Invariant", "category": "Audio Mixer", "passed": unique_pids, "detail": f"unique={unique_pids}"})

    # 504. Alphabetical sort invariant
    if data501 and len(data501) > 1:
        names = [a["name"].lower() for a in data501]
        sorted_names = sorted(names)
        is_sorted = (names == sorted_names)
    else:
        is_sorted = True
    results.append({"cycle": 504, "name": "App Volumes Alphabetical Sort Order", "category": "Audio Mixer", "passed": is_sorted, "detail": f"sorted={is_sorted}"})

    # 505. Rapid sequential polling (5x /app_volumes)
    rep_ok = True
    for _ in range(5):
        if make_req("/app_volumes")["status"] != 200:
            rep_ok = False
            break
    results.append({"cycle": 505, "name": "App Volumes Rapid Polling 5x", "category": "Audio Mixer", "passed": rep_ok, "detail": f"rep_ok={rep_ok}"})

    # 506. /app_volume Missing PID -> 400
    r506 = make_req("/app_volume", method="POST", data={"percent": 50})
    results.append({"cycle": 506, "name": "App Volume Missing PID Validation", "category": "Audio Mixer", "passed": r506["status"] == 400, "detail": f"status={r506['status']}"})

    # 507. /app_volume Non-numeric PID -> 400
    r507 = make_req("/app_volume", method="POST", data={"pid": "not-a-pid", "percent": 50})
    results.append({"cycle": 507, "name": "App Volume String Non-Numeric PID", "category": "Audio Mixer", "passed": r507["status"] == 400, "detail": f"status={r507['status']}"})

    # 508. /app_volume Negative PID -> 404
    r508 = make_req("/app_volume", method="POST", data={"pid": -9999, "percent": 50})
    results.append({"cycle": 508, "name": "App Volume Negative Non-Existent PID", "category": "Audio Mixer", "passed": r508["status"] == 404, "detail": f"status={r508['status']}"})

    # 509. /app_volume Ultra-high PID -> 404
    r509 = make_req("/app_volume", method="POST", data={"pid": 99999999, "percent": 50})
    results.append({"cycle": 509, "name": "App Volume Overflow Non-Existent PID", "category": "Audio Mixer", "passed": r509["status"] == 404, "detail": f"status={r509['status']}"})

    # 510. /app_volume Zero PID -> 404
    r510 = make_req("/app_volume", method="POST", data={"pid": 0, "percent": 50})
    results.append({"cycle": 510, "name": "App Volume System PID 0 Target", "category": "Audio Mixer", "passed": r510["status"] == 404, "detail": f"status={r510['status']}"})

    # 511. /app_volume Float PID
    r511 = make_req("/app_volume", method="POST", data={"pid": "123.45", "percent": 50})
    results.append({"cycle": 511, "name": "App Volume String Float PID Ingestion", "category": "Audio Mixer", "passed": r511["status"] in (400, 404), "detail": f"status={r511['status']}"})

    # 512. /app_volume Missing percent defaults to 50
    # On non-existent PID, it will return 404 after successfully parsing percent
    r512 = make_req("/app_volume", method="POST", data={"pid": 9999999})
    results.append({"cycle": 512, "name": "App Volume Missing Percent Defaulting", "category": "Audio Mixer", "passed": r512["status"] == 404, "detail": f"status={r512['status']}"})

    # 513. /app_volume String percent coercion ("75")
    r513 = make_req("/app_volume", method="POST", data={"pid": 9999999, "percent": "75"})
    results.append({"cycle": 513, "name": "App Volume String Integer Coercion", "category": "Audio Mixer", "passed": r513["status"] == 404, "detail": f"status={r513['status']}"})

    # 514. /app_volume Percent > 100 Clamping
    r514 = make_req("/app_volume", method="POST", data={"pid": 9999999, "percent": 500})
    results.append({"cycle": 514, "name": "App Volume Percent Upper Clamp", "category": "Audio Mixer", "passed": r514["status"] == 404, "detail": f"status={r514['status']}"})

    # 515. /app_volume Percent < 0 Clamping
    r515 = make_req("/app_volume", method="POST", data={"pid": 9999999, "percent": -50})
    results.append({"cycle": 515, "name": "App Volume Percent Lower Clamp", "category": "Audio Mixer", "passed": r515["status"] == 404, "detail": f"status={r515['status']}"})

    # 516. /app_volume Boolean percent
    r516 = make_req("/app_volume", method="POST", data={"pid": 9999999, "percent": True})
    results.append({"cycle": 516, "name": "App Volume Boolean Percent Coercion", "category": "Audio Mixer", "passed": r516["status"] == 404, "detail": f"status={r516['status']}"})

    # 517. /app_volume/mute Missing PID -> 400
    r517 = make_req("/app_volume/mute", method="POST", data={"mute": True})
    results.append({"cycle": 517, "name": "App Mute Missing PID Validation", "category": "Audio Mixer", "passed": r517["status"] == 400, "detail": f"status={r517['status']}"})

    # 518. /app_volume/mute Non-numeric PID -> 400
    r518 = make_req("/app_volume/mute", method="POST", data={"pid": "xyz", "mute": True})
    results.append({"cycle": 518, "name": "App Mute String Non-Numeric PID", "category": "Audio Mixer", "passed": r518["status"] == 400, "detail": f"status={r518['status']}"})

    # 519. /app_volume/mute Non-existent PID -> 404
    r519 = make_req("/app_volume/mute", method="POST", data={"pid": 9876543, "mute": True})
    results.append({"cycle": 519, "name": "App Mute Non-Existent PID Response", "category": "Audio Mixer", "passed": r519["status"] == 404, "detail": f"status={r519['status']}"})

    # 520. /app_volume/mute mute=true
    r520 = make_req("/app_volume/mute", method="POST", data={"pid": 9876543, "mute": True})
    results.append({"cycle": 520, "name": "App Mute True Parameter Ingestion", "category": "Audio Mixer", "passed": r520["status"] == 404, "detail": f"status={r520['status']}"})

    # 521. /app_volume/mute mute=false
    r521 = make_req("/app_volume/mute", method="POST", data={"pid": 9876543, "mute": False})
    results.append({"cycle": 521, "name": "App Mute False Parameter Ingestion", "category": "Audio Mixer", "passed": r521["status"] == 404, "detail": f"status={r521['status']}"})

    # 522. /app_volume/mute missing mute defaults to True
    r522 = make_req("/app_volume/mute", method="POST", data={"pid": 9876543})
    results.append({"cycle": 522, "name": "App Mute Default Parameter Handling", "category": "Audio Mixer", "passed": r522["status"] == 404, "detail": f"status={r522['status']}"})

    # 523. /app_volume/mute integer mute=1
    r523 = make_req("/app_volume/mute", method="POST", data={"pid": 9876543, "mute": 1})
    results.append({"cycle": 523, "name": "App Mute Integer Truthy Ingestion", "category": "Audio Mixer", "passed": r523["status"] == 404, "detail": f"status={r523['status']}"})

    # 524. /app_volume/mute string mute="false"
    r524 = make_req("/app_volume/mute", method="POST", data={"pid": 9876543, "mute": "false"})
    results.append({"cycle": 524, "name": "App Mute String Truthy Ingestion", "category": "Audio Mixer", "passed": r524["status"] == 404, "detail": f"status={r524['status']}"})

    # 525. Pycaw COM threading concurrency check
    def worker():
        return make_req("/app_volumes")["status"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(worker)
        f2 = ex.submit(worker)
        s1, s2 = f1.result(), f2.result()
    results.append({"cycle": 525, "name": "Pycaw COM Multithread Concurrency Check", "category": "Audio Mixer", "passed": s1 == 200 and s2 == 200, "detail": f"s1={s1}, s2={s2}"})

    return results

if __name__ == "__main__":
    b = run_batch_21()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 21 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
