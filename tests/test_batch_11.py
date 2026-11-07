"""
Batch 11: Управление процессами Windows, фильтрация системных процессов, taskkill
Циклы 251-275.
"""
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

def run_batch_11():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 251. /processes GET список процессов
    r = make_req("/processes")
    plist = json.loads(r["data"]) if r["status"] == 200 else []
    results.append({"cycle": 251, "name": "Processes List Format", "category": "Processes", "passed": r["status"] == 200 and isinstance(plist, list) and len(plist) > 0, "detail": f"count={len(plist)}"})

    # 252. /processes без токена -> 401
    r = make_req("/processes", token=None)
    results.append({"cycle": 252, "name": "Processes Missing Auth 401", "category": "Processes", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 253. Маскировка svchost.exe
    has_svchost = any("svchost" in p.get("name", "").lower() for p in plist)
    results.append({"cycle": 253, "name": "Processes Exclude svchost.exe", "category": "Processes", "passed": not has_svchost, "detail": f"masked={not has_svchost}"})

    # 254. Маскировка system idle process
    has_idle = any("idle" in p.get("name", "").lower() for p in plist)
    results.append({"cycle": 254, "name": "Processes Exclude System Idle Process", "category": "Processes", "passed": not has_idle, "detail": f"masked={not has_idle}"})

    # 255. Маскировка dwm.exe
    has_dwm = any(p.get("name", "").lower() == "dwm.exe" for p in plist)
    results.append({"cycle": 255, "name": "Processes Exclude dwm.exe", "category": "Processes", "passed": not has_dwm, "detail": f"masked={not has_dwm}"})

    # 256. Маскировка lsass.exe
    has_lsass = any(p.get("name", "").lower() == "lsass.exe" for p in plist)
    results.append({"cycle": 256, "name": "Processes Exclude lsass.exe", "category": "Processes", "passed": not has_lsass, "detail": f"masked={not has_lsass}"})

    # 257. Маскировка csrss.exe
    has_csrss = any(p.get("name", "").lower() == "csrss.exe" for p in plist)
    results.append({"cycle": 257, "name": "Processes Exclude csrss.exe", "category": "Processes", "passed": not has_csrss, "detail": f"masked={not has_csrss}"})

    # 258. Сортировка по имени без учета регистра
    names = [p.get("name", "").lower() for p in plist]
    sorted_names = sorted(names)
    results.append({"cycle": 258, "name": "Processes Alphabetical Sorting", "category": "Processes", "passed": names == sorted_names, "detail": f"sorted={names == sorted_names}"})

    # 259. Отсутствие дубликатов (name, pid)
    seen = set()
    has_dups = False
    for p in plist:
        pair = (p.get("name", "").lower(), p.get("pid"))
        if pair in seen:
            has_dups = True
            break
        seen.add(pair)
    results.append({"cycle": 259, "name": "Processes Unique (name, pid) Pairs", "category": "Processes", "passed": not has_dups, "detail": f"unique={not has_dups}"})

    # 260. /processes OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/processes", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 260, "name": "Processes CORS OPTIONS", "category": "Processes", "passed": r_opt.getcode() == 204, "detail": f"code={r_opt.getcode()}"})

    # 261. /processes HEAD контракт
    r_head = make_req("/processes", method="HEAD")
    results.append({"cycle": 261, "name": "Processes HEAD Request", "category": "Processes", "passed": r_head["status"] == 200, "detail": f"status={r_head['status']}"})

    # 262. /processes/kill без токена -> 401
    r = make_req("/processes/kill", method="POST", data={"pid": 1234}, token=None)
    results.append({"cycle": 262, "name": "Processes Kill Missing Auth 401", "category": "Processes", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 263. /processes/kill пустой словарь {} -> 400
    r = make_req("/processes/kill", method="POST", data={})
    results.append({"cycle": 263, "name": "Processes Kill Missing PID 400", "category": "Processes", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 264. /processes/kill pid="abc" -> 400
    r = make_req("/processes/kill", method="POST", data={"pid": "abc"})
    results.append({"cycle": 264, "name": "Processes Kill String PID 400", "category": "Processes", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 265. /processes/kill pid=None -> 400
    r = make_req("/processes/kill", method="POST", data={"pid": None})
    results.append({"cycle": 265, "name": "Processes Kill Null PID 400", "category": "Processes", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 266. /processes/kill pid=0 -> 400
    r = make_req("/processes/kill", method="POST", data={"pid": 0})
    results.append({"cycle": 266, "name": "Processes Kill PID 0 Forbidden", "category": "Processes", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 267. /processes/kill pid=-100 -> 400
    r = make_req("/processes/kill", method="POST", data={"pid": -100})
    results.append({"cycle": 267, "name": "Processes Kill Negative PID 400", "category": "Processes", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 268. /processes/kill pid=99999999 (мягкое завершение с ответом)
    r = make_req("/processes/kill", method="POST", data={"pid": 99999999})
    results.append({"cycle": 268, "name": "Processes Kill Non-existent PID Graceful", "category": "Processes", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 269. /processes/kill OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/processes/kill", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 269, "name": "Processes Kill CORS OPTIONS", "category": "Processes", "passed": r_opt.getcode() == 204, "detail": f"code={r_opt.getcode()}"})

    # 270. Логирование list_processes в actions_log.jsonl
    with open("actions_log.jsonl", "r", encoding="utf-8") as f:
        log_txt = f.read()
    results.append({"cycle": 270, "name": "Actions Log list_processes Logged", "category": "Processes", "passed": "list_processes" in log_txt, "detail": "found in log"})

    # 271. Логирование kill_process в actions_log.jsonl
    results.append({"cycle": 271, "name": "Actions Log kill_process Logged", "category": "Processes", "passed": "kill_process" in log_txt, "detail": "found in log"})

    # 272. 5 последовательных запросов к /processes
    mult_ok = all(make_req("/processes")["status"] == 200 for _ in range(5))
    results.append({"cycle": 272, "name": "Processes Multiple Iterations", "category": "Processes", "passed": mult_ok, "detail": f"ok={mult_ok}"})

    # 273. Проверка полей каждого процесса (pid >= 1, name не пустой)
    valid_procs = all(int(p.get("pid", 0)) > 0 and bool(p.get("name")) for p in plist)
    results.append({"cycle": 273, "name": "Processes Non-zero PID Integrity", "category": "Processes", "passed": valid_procs, "detail": f"valid={valid_procs}"})

    # 274. Наличие собственного сервера в списке процессов (python или pythonw)
    has_python = any("python" in p.get("name", "").lower() for p in plist)
    results.append({"cycle": 274, "name": "Processes Discovery Detects python", "category": "Processes", "passed": has_python, "detail": f"found={has_python}"})

    # 275. Время ответа /processes < 500ms
    t0 = time.perf_counter()
    r = make_req("/processes")
    dt = (time.perf_counter() - t0) * 1000
    results.append({"cycle": 275, "name": "Processes Response Latency < 500ms", "category": "Processes", "passed": dt < 500 and r["status"] == 200, "detail": f"latency={dt:.1f}ms"})

    return results

if __name__ == "__main__":
    b = run_batch_11()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 11 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
