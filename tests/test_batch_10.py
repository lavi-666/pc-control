"""
Batch 10: Раскладка клавиатуры, локализация, языки Windows, системный статус
Циклы 226-250.
"""
import json
import urllib.error
import urllib.request

BASE_URL = __import__("os").environ.get("PC_CONTROL_TEST_BASE_URL", "http://127.0.0.1:5000")  # изолированный сервер (tests/conftest.py)
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

def run_batch_10():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 226. /keyboard/languages GET структура
    r = make_req("/keyboard/languages")
    kd = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 226, "name": "Keyboard Languages List Structure", "category": "Keyboard", "passed": r["status"] == 200 and "languages" in kd and "current" in kd, "detail": f"status={r['status']}"})

    # 227. /keyboard/languages без токена -> 401
    r = make_req("/keyboard/languages", token=None)
    results.append({"cycle": 227, "name": "Keyboard Languages Missing Auth 401", "category": "Keyboard", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 228. /keyboard/switch_language POST переключение раскладки
    r = make_req("/keyboard/switch_language", method="POST")
    results.append({"cycle": 228, "name": "Keyboard Switch Language Toggle", "category": "Keyboard", "passed": r["status"] in (200, 409), "detail": f"status={r['status']}"})

    # 229. /keyboard/switch_language повторное переключение
    r = make_req("/keyboard/switch_language", method="POST")
    results.append({"cycle": 229, "name": "Keyboard Switch Language Toggle Back", "category": "Keyboard", "passed": r["status"] in (200, 409), "detail": f"status={r['status']}"})

    # 230. /keyboard/set_language с установленным языком (берем первый из списка)
    first_lang = kd.get("languages", [{}])[0].get("id", "00000409")
    r = make_req("/keyboard/set_language", method="POST", data={"id": first_lang})
    results.append({"cycle": 230, "name": "Keyboard Set Language Installed ID", "category": "Keyboard", "passed": r["status"] in (200, 409), "detail": f"status={r['status']}"})

    # 231. /keyboard/set_language в верхнем регистре
    r = make_req("/keyboard/set_language", method="POST", data={"id": str(first_lang).upper()})
    results.append({"cycle": 231, "name": "Keyboard Set Language Uppercase ID", "category": "Keyboard", "passed": r["status"] in (200, 409), "detail": f"status={r['status']}"})

    # 232. /keyboard/set_language с префиксом 0x (не найдет раскладку, вернет 400)
    r = make_req("/keyboard/set_language", method="POST", data={"id": f"0x{first_lang}"})
    results.append({"cycle": 232, "name": "Keyboard Set Language 0x Prefix", "category": "Keyboard", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 233. /keyboard/set_language с неизвестным ID -> 400
    r = make_req("/keyboard/set_language", method="POST", data={"id": "ffffffff"})
    results.append({"cycle": 233, "name": "Keyboard Set Language Unknown ID 400", "category": "Keyboard", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 234. /keyboard/set_language с числовым ID 1033 -> 400 (не найдет)
    r = make_req("/keyboard/set_language", method="POST", data={"id": 1033})
    results.append({"cycle": 234, "name": "Keyboard Set Language Integer ID", "category": "Keyboard", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 235. /keyboard/set_language без токена -> 401
    r = make_req("/keyboard/set_language", method="POST", data={"id": first_lang}, token=None)
    results.append({"cycle": 235, "name": "Keyboard Set Language Missing Auth 401", "category": "Keyboard", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 236. /status контракт: status == "online"
    r = make_req("/status")
    sd = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 236, "name": "Status Endpoint Online Value", "category": "System", "passed": sd.get("status") == "online", "detail": f"status={sd.get('status')}"})

    # 237. /status контракт: hostname не пустой
    results.append({"cycle": 237, "name": "Status Endpoint Hostname Non-empty", "category": "System", "passed": bool(sd.get("hostname")), "detail": f"hostname={sd.get('hostname')}"})

    # 238. /status HEAD контракт
    r_head = make_req("/status", method="HEAD")
    results.append({"cycle": 238, "name": "Status HEAD Request 200", "category": "System", "passed": r_head["status"] == 200, "detail": f"status={r_head['status']}"})

    # 239. /status OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/status", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 239, "name": "Status CORS OPTIONS", "category": "System", "passed": r_opt.getcode() == 204, "detail": f"code={r_opt.getcode()}"})

    # 240. /status с query параметрами
    r = make_req("/status?timestamp=1700000000&foo=bar")
    results.append({"cycle": 240, "name": "Status Query Parameters Ingestion", "category": "System", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 241. Unit test: ctypes GetKeyboardLayoutList
    import ctypes
    user32 = ctypes.windll.user32
    count = user32.GetKeyboardLayoutList(0, None)
    results.append({"cycle": 241, "name": "Win32 GetKeyboardLayoutList Count >= 1", "category": "Keyboard Unit", "passed": count >= 1, "detail": f"count={count}"})

    # 242. Unit test: GetForegroundWindow
    fg_hwnd = user32.GetForegroundWindow()
    results.append({"cycle": 242, "name": "Win32 GetForegroundWindow Int", "category": "Keyboard Unit", "passed": isinstance(fg_hwnd, int), "detail": f"hwnd={fg_hwnd}"})

    # 243. Unit test: GetWindowThreadProcessId
    pid = ctypes.c_ulong()
    tid = user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))
    results.append({"cycle": 243, "name": "Win32 GetWindowThreadProcessId", "category": "Keyboard Unit", "passed": tid >= 0, "detail": f"tid={tid}, pid={pid.value}"})

    # 244. Unit test: GetKeyboardLayout
    hkl = user32.GetKeyboardLayout(tid)
    results.append({"cycle": 244, "name": "Win32 GetKeyboardLayout Handle", "category": "Keyboard Unit", "passed": hkl != 0, "detail": f"hkl={hex(hkl)}"})

    # 245. Unit test: GetKeyboardLayoutNameW
    buf = ctypes.create_unicode_buffer(9)
    res_buf = user32.GetKeyboardLayoutNameW(buf)
    results.append({"cycle": 245, "name": "Win32 GetKeyboardLayoutNameW String", "category": "Keyboard Unit", "passed": res_buf != 0 and len(buf.value) > 0, "detail": f"klid={buf.value}"})

    # 246. Проверка записи set_language в actions_log.jsonl
    with open("actions_log.jsonl", "r", encoding="utf-8") as f:
        log_content = f.read()
    results.append({"cycle": 246, "name": "Actions Log Records Language Action", "category": "Keyboard", "passed": "set_language" in log_content or "switch_language" in log_content, "detail": "found in log"})

    # 247. 3 быстрых последовательных переключения языка
    rapid_ok = True
    for _ in range(3):
        rr = make_req("/keyboard/switch_language", method="POST")
        if rr["status"] not in (200, 409):
            rapid_ok = False
            break
    results.append({"cycle": 247, "name": "Rapid Successive Language Switches", "category": "Keyboard", "passed": rapid_ok, "detail": f"ok={rapid_ok}"})

    # 248. /keyboard/languages после быстрых переключений
    r_after = make_req("/keyboard/languages")
    results.append({"cycle": 248, "name": "Keyboard Languages Consistent Query", "category": "Keyboard", "passed": r_after["status"] == 200, "detail": f"status={r_after['status']}"})

    # 249. /keyboard/switch_language OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/keyboard/switch_language", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 249, "name": "Keyboard Switch Language CORS OPTIONS", "category": "Keyboard", "passed": r_opt.getcode() == 204, "detail": f"status={r_opt.getcode()}"})

    # 250. /keyboard/set_language OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/keyboard/set_language", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 250, "name": "Keyboard Set Language CORS OPTIONS", "category": "Keyboard", "passed": r_opt.getcode() == 204, "detail": f"status={r_opt.getcode()}"})

    return results

if __name__ == "__main__":
    b = run_batch_10()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 10 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
