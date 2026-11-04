"""
Batch 22: Гетерогенная параллельная нагрузка (Mixed-Workload Concurrency), синхронизация блокировок и гонки данных
Циклы 526-550.
"""
import concurrent.futures
import json
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

def make_req(path, method="GET", data=None, token=TOKEN, headers=None, timeout=8):
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

def run_batch_22():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # Phase 1: 25 concurrent mixed operations
    tasks = []
    for i in range(5):
        tasks.append(("/volume", "POST", {"percent": 40 + i * 5}))
        tasks.append(("/screen/config", "POST", {"fps": 30 if i % 2 == 0 else 60, "height": 720}))
        tasks.append(("/status", "GET", None))
        tasks.append(("/api/safe_mode", "POST", {"enabled": True}))
        tasks.append(("/audio", "GET", None))

    def run_task(item):
        p, m, d = item
        return make_req(p, method=m, data=d)

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as ex:
        futures = [ex.submit(run_task, t) for t in tasks]
        responses = [f.result() for f in futures]

    # 526. Mixed Concurrency No Timeout
    timed_out = any(r["status"] == -1 for r in responses)
    results.append({"cycle": 526, "name": "Mixed Concurrency 25-Thread No Timeout", "category": "Concurrency Stress", "passed": not timed_out, "detail": f"timed_out={timed_out}"})

    # 527. Mixed Concurrency 100% Success Rate
    successes = sum(1 for r in responses if r["status"] == 200)
    results.append({"cycle": 527, "name": "Mixed Concurrency 100% Status 200 Rate", "category": "Concurrency Stress", "passed": successes == len(responses), "detail": f"successes={successes}/{len(responses)}"})

    # 528. Screen Config Lock State Consistency
    r_cfg = make_req("/screen/config", method="POST", data={"fps": 30})
    data_cfg = json.loads(r_cfg["data"]).get("config", {}) if r_cfg["status"] == 200 else {}
    valid_cfg = (data_cfg.get("fps") in (30, 60)) and (data_cfg.get("height") in (720, 1080, 480))
    results.append({"cycle": 528, "name": "Screen Config State Post-Race Invariant", "category": "Concurrency Stress", "passed": valid_cfg, "detail": f"cfg={data_cfg}"})

    # 529. Master Volume Lock State Consistency
    r_vol = make_req("/volume")
    data_vol = json.loads(r_vol["data"]) if r_vol["status"] == 200 else {}
    vol_in_bounds = (0 <= data_vol.get("percent", -1) <= 100)
    results.append({"cycle": 529, "name": "Volume State Post-Race Range [0-100]", "category": "Concurrency Stress", "passed": vol_in_bounds, "detail": f"pct={data_vol.get('percent')}"})

    # 530. Safe Mode Flag Integrity
    r_sm = make_req("/api/safe_mode")
    data_sm = json.loads(r_sm["data"]) if r_sm["status"] == 200 else {}
    results.append({"cycle": 530, "name": "Safe Mode Flag Boolean Invariant", "category": "Concurrency Stress", "passed": data_sm.get("safe_mode") is True, "detail": f"safe_mode={data_sm.get('safe_mode')}"})

    # 531-540. Rapid Interleaved Volume Up/Down + Mute Toggles across 10 threads
    toggle_tasks = []
    for j in range(10):
        if j % 2 == 0:
            toggle_tasks.append(("/mute", "POST", {"mute": True}))
        else:
            toggle_tasks.append(("/mute", "POST", {"mute": False}))

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex_mute:
        m_futs = [ex_mute.submit(run_task, t) for t in toggle_tasks]
        m_res = [f.result() for f in m_futs]

    for idx, r in enumerate(m_res):
        c_num = 531 + idx
        results.append({
            "cycle": c_num,
            "name": f"Interleaved Mute Toggle Worker #{idx+1}",
            "category": "Concurrency Stress",
            "passed": r["status"] == 200,
            "detail": f"status={r['status']}"
        })

    # 541-545. Concurrent Log Action Storm (5 threads logging actions simultaneously)
    log_tasks = [
        ("/action", "POST", {"action": "lock"}),
        ("/action", "POST", {"action": "lock"}),
        ("/action", "POST", {"action": "lock"}),
        ("/action", "POST", {"action": "lock"}),
        ("/action", "POST", {"action": "lock"}),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex_log:
        l_futs = [ex_log.submit(run_task, t) for t in log_tasks]
        l_res = [f.result() for f in l_futs]

    for idx, r in enumerate(l_res):
        c_num = 541 + idx
        results.append({
            "cycle": c_num,
            "name": f"Concurrent Safe Action Worker #{idx+1}",
            "category": "Concurrency Stress",
            "passed": r["status"] == 200,
            "detail": f"status={r['status']}"
        })

    # 546-550. Multi-IP Lockout Guard Thread Safety
    # Spoof 5 distinct client IPs via headers and send requests concurrently
    def spoof_ip(ip_num):
        headers = {"X-Forwarded-For": f"192.168.1.{ip_num}"}
        return make_req("/status", headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex_ip:
        ip_futs = [ex_ip.submit(spoof_ip, i) for i in range(101, 106)]
        ip_res = [f.result() for f in ip_futs]

    for idx, r in enumerate(ip_res):
        c_num = 546 + idx
        results.append({
            "cycle": c_num,
            "name": f"Concurrent IP Request Worker #{idx+1}",
            "category": "Concurrency Stress",
            "passed": r["status"] == 200,
            "detail": f"status={r['status']}"
        })

    return results

if __name__ == "__main__":
    b = run_batch_22()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 22 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
