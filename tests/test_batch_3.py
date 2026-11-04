"""
Batch 3: Некорректные данные, неверные типы, спецсимволы, XSS/SQLi, эмодзи, симуляция действий в безопасном режиме
Циклы 51-75.
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

def run_batch_3():
    # Активируем безопасный режим на сервере
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 51. /volume POST со строкой percent="fifty" -> 400
    r = make_req("/volume", method="POST", data={"percent": "fifty"})
    results.append({"cycle": 51, "name": "Volume String Value 'fifty'", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 52. /volume POST со списком percent=[50] -> 400
    r = make_req("/volume", method="POST", data={"percent": [50]})
    results.append({"cycle": 52, "name": "Volume List Value [50]", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 53. /volume POST со словарем percent={"val": 50} -> 400
    r = make_req("/volume", method="POST", data={"percent": {"val": 50}})
    results.append({"cycle": 53, "name": "Volume Dict Value", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 54. /volume POST с SQLi строкой -> 400
    r = make_req("/volume", method="POST", data={"percent": "' OR 1=1; --"})
    results.append({"cycle": 54, "name": "Volume SQLi Injection", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 55. /volume POST с XSS строкой -> 400
    r = make_req("/volume", method="POST", data={"percent": "<script>alert(1)</script>"})
    results.append({"cycle": 55, "name": "Volume XSS String", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 56. /volume POST с эмодзи -> 400
    r = make_req("/volume", method="POST", data={"percent": "🔊🔥🎉"})
    results.append({"cycle": 56, "name": "Volume Emoji String", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 57. /volume POST с длинной строкой (10k символов) -> 400
    r = make_req("/volume", method="POST", data={"percent": "A" * 10000})
    results.append({"cycle": 57, "name": "Volume 10k String Length", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 58. /action POST со строкой SQLi -> 400
    r = make_req("/action", method="POST", data={"action": "' OR '1'='1"})
    results.append({"cycle": 58, "name": "Action SQLi Injection", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 59. /action POST с XSS строкой -> 400
    r = make_req("/action", method="POST", data={"action": "<img src=x onerror=alert(1)>"})
    results.append({"cycle": 59, "name": "Action XSS String", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 60. /action POST с неизвестным действием -> 400
    r = make_req("/action", method="POST", data={"action": "fly_to_mars"})
    results.append({"cycle": 60, "name": "Action Unknown Command", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 61. /action POST с числом вместо строки -> 400
    r = make_req("/action", method="POST", data={"action": 12345})
    results.append({"cycle": 61, "name": "Action Integer Type", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 62. /action POST с null/None -> 400
    r = make_req("/action", method="POST", data={"action": None})
    results.append({"cycle": 62, "name": "Action Null Value", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 63. /action POST shutdown в SAFE_MODE (должен вернуть 200 симуляцию, не трогать ОС)
    r = make_req("/action", method="POST", data={"action": "shutdown"})
    results.append({"cycle": 63, "name": "Action Simulated Shutdown (Safe)", "category": "Safe Action", "passed": r["status"] == 200 and b"SAFE_MODE" in r["data"], "detail": f"status={r['status']}"})

    # 64. /action POST sleep в SAFE_MODE (должен вернуть 200 симуляцию, не трогать ОС)
    r = make_req("/action", method="POST", data={"action": "sleep"})
    results.append({"cycle": 64, "name": "Action Simulated Sleep (Safe)", "category": "Safe Action", "passed": r["status"] == 200 and b"SAFE_MODE" in r["data"], "detail": f"status={r['status']}"})

    # 65. /action POST reboot в SAFE_MODE (должен вернуть 200 симуляцию, не трогать ОС)
    r = make_req("/action", method="POST", data={"action": "reboot"})
    results.append({"cycle": 65, "name": "Action Simulated Reboot (Safe)", "category": "Safe Action", "passed": r["status"] == 200 and b"SAFE_MODE" in r["data"], "detail": f"status={r['status']}"})

    # 66. /action POST lock в SAFE_MODE (должен вернуть 200 симуляцию, не трогать ОС)
    r = make_req("/action", method="POST", data={"action": "lock"})
    results.append({"cycle": 66, "name": "Action Simulated Lock (Safe)", "category": "Safe Action", "passed": r["status"] == 200 and b"SAFE_MODE" in r["data"], "detail": f"status={r['status']}"})

    # 67. /screen/config POST monitor="left" (мягкий откат без 500)
    r = make_req("/screen/config", method="POST", data={"monitor": "left"})
    results.append({"cycle": 67, "name": "Screen Config Invalid Monitor String", "category": "Invalid Data", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 68. /screen/config POST height="huge" (мягкий откат без 500)
    r = make_req("/screen/config", method="POST", data={"height": "huge"})
    results.append({"cycle": 68, "name": "Screen Config Invalid Height String", "category": "Invalid Data", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 69. /screen/config POST fps="ultra" (мягкий откат без 500)
    r = make_req("/screen/config", method="POST", data={"fps": "ultra"})
    results.append({"cycle": 69, "name": "Screen Config Invalid FPS String", "category": "Invalid Data", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 70. /app_volume POST pid="not_a_pid" -> 400
    r = make_req("/app_volume", method="POST", data={"pid": "not_a_pid", "percent": 50})
    results.append({"cycle": 70, "name": "App Volume String PID", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 71. /app_volume POST percent="loud" -> 400
    r = make_req("/app_volume", method="POST", data={"pid": 1234, "percent": "loud"})
    results.append({"cycle": 71, "name": "App Volume String Percent", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 72. /app_volume/mute POST pid="foo" -> 400
    r = make_req("/app_volume/mute", method="POST", data={"pid": "foo"})
    results.append({"cycle": 72, "name": "App Volume Mute String PID", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 73. /shutdown_timer POST minutes="one hour" -> 400
    r = make_req("/shutdown_timer", method="POST", data={"minutes": "one hour"})
    results.append({"cycle": 73, "name": "Shutdown Timer String Minutes", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 74. /shutdown_timer POST minutes="0.5" -> 400
    r = make_req("/shutdown_timer", method="POST", data={"minutes": "0.5"})
    results.append({"cycle": 74, "name": "Shutdown Timer Float String Minutes", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 75. /shutdown_timer POST minutes=None -> 400
    r = make_req("/shutdown_timer", method="POST", data={"minutes": None})
    results.append({"cycle": 75, "name": "Shutdown Timer Null Minutes", "category": "Invalid Data", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    return results

if __name__ == "__main__":
    b3 = run_batch_3()
    passed = sum(1 for x in b3 if x["passed"])
    print(f"Batch 3 Results: {passed}/{len(b3)} passed")
    for r in b3:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
