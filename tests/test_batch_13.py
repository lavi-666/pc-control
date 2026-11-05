"""
Batch 13: Wake-on-LAN расширенная адресация, широковещательные подсети, реле
Циклы 301-325.
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

def run_batch_13():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 301. WOL на loopback 127.0.0.1
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["127.0.0.1"]})
    results.append({"cycle": 301, "name": "WOL Target Loopback 127.0.0.1", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 302. WOL на подсеть 192.168.0.255
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["192.168.0.255"]})
    results.append({"cycle": 302, "name": "WOL Target Subnet 192.168.0.255", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 303. WOL на подсеть 192.168.1.255
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["192.168.1.255"]})
    results.append({"cycle": 303, "name": "WOL Target Subnet 192.168.1.255", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 304. WOL на Class A 10.255.255.255
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["10.255.255.255"]})
    results.append({"cycle": 304, "name": "WOL Target Class A 10.255.255.255", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 305. WOL на Class B 172.16.255.255
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["172.16.255.255"]})
    results.append({"cycle": 305, "name": "WOL Target Class B 172.16.255.255", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 306. WOL на глобальный broadcast 255.255.255.255
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["255.255.255.255"]})
    results.append({"cycle": 306, "name": "WOL Target Global 255.255.255.255", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 307. WOL на конкретный IP хоста 192.168.0.101
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["192.168.0.101"]})
    results.append({"cycle": 307, "name": "WOL Target Direct Host IP", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 308. WOL мульти-таргет: 3 адреса
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["127.0.0.1", "192.168.0.255", "255.255.255.255"]})
    results.append({"cycle": 308, "name": "WOL Multiple Heterogeneous Targets", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 309. WOL с некорректным IP адресом в списке (не крашит сервер)
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["999.999.999.999"]})
    results.append({"cycle": 309, "name": "WOL Invalid IP Handled Gracefully", "category": "WOL", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 310. WOL с 0.0.0.0
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["0.0.0.0"]})
    results.append({"cycle": 310, "name": "WOL Target 0.0.0.0", "category": "WOL", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 311. WOL target с пробелами " 192.168.0.255 "
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": [" 192.168.0.255 "]})
    results.append({"cycle": 311, "name": "WOL Target Padded Whitespace", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 312. WOL с дубликатами таргетов
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF", "targets": ["127.0.0.1", "127.0.0.1"]})
    results.append({"cycle": 312, "name": "WOL Duplicate Targets Ingestion", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 313. WOL с MAC в формате 00:00:00:00:00:00
    r = make_req("/api/wol", method="POST", data={"mac": "00:00:00:00:00:00"})
    results.append({"cycle": 313, "name": "WOL All Zeros MAC Format", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 314. WOL с MAC в формате FF:FF:FF:FF:FF:FF
    r = make_req("/api/wol", method="POST", data={"mac": "FF:FF:FF:FF:FF:FF"})
    results.append({"cycle": 314, "name": "WOL All Fs Broadcast MAC Format", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 315. WOL со смешанным регистром a1-b2-CD-34-EF-56
    r = make_req("/api/wol", method="POST", data={"mac": "a1-b2-CD-34-EF-56"})
    results.append({"cycle": 315, "name": "WOL Mixed Case MAC Format", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 316. WOL с пробелами внутри дефисов "A1 - B2 - CD - 34 - EF - 56" -> убираются
    r = make_req("/api/wol", method="POST", data={"mac": "A1 - B2 - CD - 34 - EF - 56"})
    results.append({"cycle": 316, "name": "WOL Spaced Delimiters MAC", "category": "WOL", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 317. Downloaded relay must be valid Python with this installation's settings.
    import ast
    from core.config import load_app_config
    r_relay = make_req("/download/wol_relay.py")
    relay_settings = {}
    relay_valid = False
    try:
        tree = ast.parse(r_relay["data"].decode("utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ("DEFAULT_MAC", "PORT"):
                        relay_settings[target.id] = node.value.value
        cfg = load_app_config()
        relay_valid = (r_relay["status"] == 200 and
                       relay_settings.get("DEFAULT_MAC") == cfg.get("mac_address", "AA-BB-CC-DD-EE-FF") and
                       relay_settings.get("PORT") == int(cfg.get("relay_port", 5050)))
    except (ValueError, SyntaxError, UnicodeError):
        pass
    results.append({"cycle": 317, "name": "WOL Relay Configured Download", "category": "WOL", "passed": relay_valid, "detail": f"configured={relay_valid}"})

    # 318. /api/wol OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/api/wol", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 318, "name": "WOL API CORS OPTIONS", "category": "WOL", "passed": r_opt.getcode() == 204, "detail": f"code={r_opt.getcode()}"})

    # 319. /api/wol без токена -> 401
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF"}, token=None)
    results.append({"cycle": 319, "name": "WOL API Missing Auth 401", "category": "WOL", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 320. /api/wol с неверным токеном -> 401
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF"}, token="wrong")
    results.append({"cycle": 320, "name": "WOL API Invalid Auth 401", "category": "WOL", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 321. Проверка структуры ответа /api/wol {"ok": true, "sent": int}
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF"})
    wd = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 321, "name": "WOL Response JSON Schema", "category": "WOL", "passed": wd.get("ok") is True and isinstance(wd.get("sent"), int), "detail": f"sent={wd.get('sent')}"})

    # 322. Число отправленных пакетов sent > 0
    results.append({"cycle": 322, "name": "WOL Sent Count Greater Than Zero", "category": "WOL", "passed": wd.get("sent", 0) > 0, "detail": f"count={wd.get('sent')}"})

    # 323. Логирование wake_on_lan в actions_log.jsonl
    with open("actions_log.jsonl", "r", encoding="utf-8") as f:
        log_txt = f.read()
    results.append({"cycle": 323, "name": "Actions Log wake_on_lan Recorded", "category": "WOL", "passed": "wake_on_lan" in log_txt, "detail": "found in log"})

    # 324. Идемпотентность серии из 5 вызовов /api/wol
    wol_series = all(make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF"})["status"] == 200 for _ in range(5))
    results.append({"cycle": 324, "name": "WOL Consecutive Execution Series", "category": "WOL", "passed": wol_series, "detail": f"all_200={wol_series}"})

    # 325. Время ответа /api/wol < 600ms (включает 3 повтора UDP с интервалом 50ms)
    t0 = time.perf_counter()
    r = make_req("/api/wol", method="POST", data={"mac": "AA-BB-CC-DD-EE-FF"})
    dt = (time.perf_counter() - t0) * 1000
    results.append({"cycle": 325, "name": "WOL Execution Latency < 600ms", "category": "WOL", "passed": dt < 600.0 and r["status"] == 200, "detail": f"dt={dt:.1f}ms"})

    return results

if __name__ == "__main__":
    b = run_batch_13()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 13 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
