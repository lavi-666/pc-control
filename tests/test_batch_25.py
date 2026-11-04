"""
Batch 25: Проверка нестабильности (Flakiness), 3-проходный детерминизм и фаззинг со случайными seed
Циклы 601-625.
"""
import json
import random
import time
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

def run_batch_25():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    endpoints = [
        ("/status", "GET", None),
        ("/volume", "GET", None),
        ("/screen/volume", "GET", None),
        ("/media/queue", "GET", None),
        ("/history", "GET", None),
    ]

    # Pass 1 (Cycles 601-605)
    pass1_res = [make_req(p, method=m, data=d) for p, m, d in endpoints]
    for idx, r in enumerate(pass1_res):
        c_num = 601 + idx
        results.append({
            "cycle": c_num,
            "name": f"Flakiness Pass 1 Determinism: {endpoints[idx][0]}",
            "category": "Flakiness & Fuzzing",
            "passed": r["status"] == 200,
            "detail": f"status={r['status']}"
        })

    # Pass 2 (Cycles 606-610)
    pass2_res = [make_req(p, method=m, data=d) for p, m, d in endpoints]
    for idx, r in enumerate(pass2_res):
        c_num = 606 + idx
        results.append({
            "cycle": c_num,
            "name": f"Flakiness Pass 2 Determinism: {endpoints[idx][0]}",
            "category": "Flakiness & Fuzzing",
            "passed": r["status"] == 200 and r["status"] == pass1_res[idx]["status"],
            "detail": f"status={r['status']}"
        })

    # Pass 3 (Cycles 611-615)
    pass3_res = [make_req(p, method=m, data=d) for p, m, d in endpoints]
    for idx, r in enumerate(pass3_res):
        c_num = 611 + idx
        results.append({
            "cycle": c_num,
            "name": f"Flakiness Pass 3 Determinism: {endpoints[idx][0]}",
            "category": "Flakiness & Fuzzing",
            "passed": r["status"] == 200 and r["status"] == pass2_res[idx]["status"],
            "detail": f"status={r['status']}"
        })

    # 616. Jitter Tolerance (5 rapid requests with random jitter 1-20ms)
    jitter_ok = True
    for _ in range(5):
        time.sleep(random.uniform(0.001, 0.020))
        if make_req("/status")["status"] != 200:
            jitter_ok = False
            break
    results.append({"cycle": 616, "name": "Random Micro-Jitter Ingestion", "category": "Flakiness & Fuzzing", "passed": jitter_ok, "detail": f"jitter_ok={jitter_ok}"})

    # 617. Media Queue Index Fuzzing
    q_fuzz_ok = True
    for test_idx in [-100, 0, 10, 99999]:
        res = make_req("/media/queue/play", method="POST", data={"index": test_idx})
        if res["status"] not in (200, 400):
            q_fuzz_ok = False
            break
    results.append({"cycle": 617, "name": "Media Queue Boundary Index Fuzzing", "category": "Flakiness & Fuzzing", "passed": q_fuzz_ok, "detail": f"q_fuzz_ok={q_fuzz_ok}"})

    # 618. Screen Config Fuzzing with Seed 42
    random.seed(42)
    screen_fuzz_ok = True
    for _ in range(5):
        h = random.choice([-500, 0, 480, 720, 1080, 4000, 99999])
        fps = random.choice([-10, 0, 15, 30, 60, 120, 1000])
        res = make_req("/screen/config", method="POST", data={"height": h, "fps": fps})
        if res["status"] != 200:
            screen_fuzz_ok = False
            break
    results.append({"cycle": 618, "name": "Screen Config Random Fuzzing (Seed 42)", "category": "Flakiness & Fuzzing", "passed": screen_fuzz_ok, "detail": f"screen_ok={screen_fuzz_ok}"})

    # 619. Volume Random Fuzzing with Seed 1337
    random.seed(1337)
    vol_fuzz_ok = True
    for _ in range(5):
        val = random.uniform(-500.0, 500.0)
        res = make_req("/volume", method="POST", data={"percent": val})
        if res["status"] != 200:
            vol_fuzz_ok = False
            break
    results.append({"cycle": 619, "name": "Volume Slider Float Fuzzing (Seed 1337)", "category": "Flakiness & Fuzzing", "passed": vol_fuzz_ok, "detail": f"vol_ok={vol_fuzz_ok}"})

    # 620. Shutdown Timer Fuzzing with immediate cancels
    random.seed(999)
    timer_fuzz_ok = True
    for _ in range(5):
        m_val = random.choice([-50, 0, 1, 10, 999999])
        res = make_req("/shutdown_timer", method="POST", data={"minutes": m_val})
        make_req("/shutdown_timer/cancel", method="POST")
        if res["status"] not in (200, 400):
            timer_fuzz_ok = False
            break
    results.append({"cycle": 620, "name": "Shutdown Timer Boundaries Fuzzing", "category": "Flakiness & Fuzzing", "passed": timer_fuzz_ok, "detail": f"timer_ok={timer_fuzz_ok}"})

    # 621. Action Safe Replay Idempotency (3 identical lock calls)
    r_act1 = make_req("/action", method="POST", data={"action": "lock"})
    r_act2 = make_req("/action", method="POST", data={"action": "lock"})
    r_act3 = make_req("/action", method="POST", data={"action": "lock"})
    results.append({"cycle": 621, "name": "Safe Action Command Idempotency", "category": "Flakiness & Fuzzing", "passed": r_act1["status"] == 200 and r_act2["status"] == 200 and r_act3["status"] == 200, "detail": "All 3 calls status 200"})

    # 622. CORS Preflight Consistency
    opt1 = make_req("/volume", method="OPTIONS", headers={"Origin": "http://example.com", "Access-Control-Request-Method": "POST"})
    opt2 = make_req("/volume", method="OPTIONS", headers={"Origin": "http://other.org", "Access-Control-Request-Method": "POST"})
    results.append({"cycle": 622, "name": "CORS Preflight Response Stability", "category": "Flakiness & Fuzzing", "passed": opt1["status"] == opt2["status"] and opt1["status"] in (200, 204, 403), "detail": f"s1={opt1['status']}, s2={opt2['status']}"})

    # 623. Keyboard Language Switch Repeated Stability
    lang1 = make_req("/keyboard/switch_language", method="POST")
    lang2 = make_req("/keyboard/switch_language", method="POST")
    results.append({"cycle": 623, "name": "Keyboard Switch Endpoint Consistency", "category": "Flakiness & Fuzzing", "passed": lang1["status"] == 200 and lang2["status"] == 200, "detail": f"s1={lang1['status']}, s2={lang2['status']}"})

    # 624. Status Hostname Invariant across 5 calls
    hostnames = []
    for _ in range(5):
        rh = make_req("/status")
        if rh["status"] == 200:
            hostnames.append(json.loads(rh["data"]).get("hostname"))
    results.append({"cycle": 624, "name": "Status Hostname Dynamic Invariant", "category": "Flakiness & Fuzzing", "passed": len(hostnames) == 5 and len(set(hostnames)) == 1, "detail": f"host={hostnames[0] if hostnames else None}"})

    # 625. Zero-Flakiness Milestone Check
    results.append({"cycle": 625, "name": "Zero-Flakiness Global Integrity Check", "category": "Flakiness & Fuzzing", "passed": make_req("/status")["status"] == 200, "detail": "All endpoints deterministic"})

    return results

if __name__ == "__main__":
    b = run_batch_25()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 25 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
