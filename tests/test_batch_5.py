"""
Batch 5: Ошибки окружения, повреждение файлов, восстановление после сбоев, авторизация, блокировка токенов
Циклы 101-125.
"""
import json
import os
import sys
import time
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

def run_batch_5():
    # Активируем безопасный режим на сервере
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 101. Запрос без токена -> 401
    r = make_req("/history", token=None)
    results.append({"cycle": 101, "name": "Auth Missing Token", "category": "Security/Auth", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 102. Запрос с неверным токеном -> 401
    r = make_req("/history", token="wrong_token_123")
    results.append({"cycle": 102, "name": "Auth Invalid Token", "category": "Security/Auth", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 103. Запрос с токеном с пробелами -> 401
    r = make_req("/history", token=f"  {TOKEN}  ")
    results.append({"cycle": 103, "name": "Auth Token Whitespace Mismatch", "category": "Security/Auth", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 104. Токен в заголовке Authorization: Bearer
    r = make_req("/history", token=None, headers={"Authorization": f"Bearer {TOKEN}"})
    results.append({"cycle": 104, "name": "Auth Bearer Header", "category": "Security/Auth", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 105. Токен в cookie
    r = make_req("/history", token=None, headers={"Cookie": f"token={TOKEN}"})
    results.append({"cycle": 105, "name": "Auth Cookie", "category": "Security/Auth", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 106. Запрос правильного токена после неверного (нет дедлока в auth_guard)
    r = make_req("/history", token=TOKEN)
    results.append({"cycle": 106, "name": "Auth Valid Token Recovery", "category": "Security/Auth", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 107. Тест устойчивости get_history: чтение файла истории
    r = make_req("/history")
    results.append({"cycle": 107, "name": "History Normal Access", "category": "Storage Recovery", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 108. Запись битой строки в actions_log.jsonl и проверка устойчивости get_history
    log_path = "actions_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("{corrupted_json_line_without_closing\n")
        f.write('{"ts": 12345, "action": "test_corrupt_recovery"}\n')

    r = make_req("/history")
    passed_108 = False
    if r["status"] == 200:
        data = json.loads(r["data"])
        passed_108 = any(x.get("action") == "test_corrupt_recovery" for x in data)
    results.append({"cycle": 108, "name": "Corrupted Log Line Fault Tolerance", "category": "Storage Recovery", "passed": passed_108, "detail": f"passed={passed_108}"})

    # 109. Проверка лимита выборки истории
    r = make_req("/history")
    data = json.loads(r["data"]) if r["status"] == 200 else []
    results.append({"cycle": 109, "name": "History Max Limit 500", "category": "Storage Recovery", "passed": len(data) <= 500, "detail": f"count={len(data)}"})

    # 110. Media history чтение
    r = make_req("/media/queue")
    results.append({"cycle": 110, "name": "Media Queue History Access", "category": "Storage Recovery", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 111. Несуществующий статический маршрут -> 404
    r = make_req("/non_existent_page.html")
    results.append({"cycle": 111, "name": "Non-existent Static Route 404", "category": "Environment", "passed": r["status"] == 404, "detail": f"status={r['status']}"})

    # 112. Несуществующее скачивание -> 404
    r = make_req("/download/unknown_archive.zip")
    results.append({"cycle": 112, "name": "Non-existent Download 404", "category": "Environment", "passed": r["status"] == 404, "detail": f"status={r['status']}"})

    # 113. Method Not Allowed: POST на /history -> 405
    r = make_req("/history", method="POST", data={"some": "data"})
    results.append({"cycle": 113, "name": "History POST Method Not Allowed", "category": "HTTP Contract", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 114. Method Not Allowed: GET на /processes/kill -> 405
    r = make_req("/processes/kill", method="GET")
    results.append({"cycle": 114, "name": "Processes Kill GET Method Not Allowed", "category": "HTTP Contract", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 115. Method Not Allowed: GET на /action -> 405
    r = make_req("/action", method="GET")
    results.append({"cycle": 115, "name": "Action GET Method Not Allowed", "category": "HTTP Contract", "passed": r["status"] == 405, "detail": f"status={r['status']}"})

    # 116. Content-Type text/plain на /volume -> 200 или 400 без 500
    r = make_req("/volume", method="POST", data="plain_text_not_json", headers={"Content-Type": "text/plain"})
    results.append({"cycle": 116, "name": "Volume Non-JSON Content-Type", "category": "Environment", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 117. Неполный JSON (обрезанный запрос)
    r = make_req("/volume", method="POST", data='{"percent": ', headers={"Content-Type": "application/json"})
    results.append({"cycle": 117, "name": "Volume Truncated JSON Payload", "category": "Environment", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 118. Большой полезный объем (100KB безопасных данных)
    large_payload = {"percent": 50, "padding": "X" * 102400}
    r = make_req("/volume", method="POST", data=large_payload)
    results.append({"cycle": 118, "name": "Volume 100KB JSON Payload Handling", "category": "Environment", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 119. Пустой POST запрос на /action (0 байт) -> 400
    r = make_req("/action", method="POST", data=b"", headers={"Content-Type": "application/json"})
    results.append({"cycle": 119, "name": "Action Empty 0-byte Body", "category": "Environment", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 120. Юникод в Query параметрах /history?test=ПриветМир
    r = make_req("/history?test=%D0%9F%D1%80%D0%B8%D0%B2%D0%B5%D1%82")
    results.append({"cycle": 120, "name": "Unicode Query Parameters", "category": "Environment", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 121. Несуществующий язык раскладки /keyboard/set_language -> 400
    r = make_req("/keyboard/set_language", method="POST", data={"id": "99999999"})
    results.append({"cycle": 121, "name": "Keyboard Set Language Unknown ID", "category": "Environment", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 122. WebRTC offer с пустым телом -> 400 или 500
    r = make_req("/webrtc/offer", method="POST", data={})
    results.append({"cycle": 122, "name": "WebRTC Offer Empty Payload", "category": "Environment", "passed": r["status"] in (400, 500), "detail": f"status={r['status']}"})

    # 123. WebRTC close без активного соединения -> 200
    r = make_req("/webrtc/close", method="POST", data={"source": "mic"})
    results.append({"cycle": 123, "name": "WebRTC Close Idle Source", "category": "Environment", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 124. Safe Mode запрос GET статуса
    r = make_req("/api/safe_mode")
    results.append({"cycle": 124, "name": "Safe Mode Status Query", "category": "Environment", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 125. CORS Preflight OPTIONS на /shutdown_timer
    req_opt = urllib.request.Request(BASE_URL + "/shutdown_timer", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 125, "name": "Shutdown Timer CORS OPTIONS Preflight", "category": "HTTP Contract", "passed": r_opt.getcode() == 204, "detail": f"status={r_opt.getcode()}"})

    return results

if __name__ == "__main__":
    b5 = run_batch_5()
    passed = sum(1 for x in b5 if x["passed"])
    print(f"Batch 5 Results: {passed}/{len(b5)} passed")
    for r in b5:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
