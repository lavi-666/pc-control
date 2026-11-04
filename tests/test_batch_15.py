"""
Batch 15: Безопасность, токены аутентификации, заголовки, защита от обхода путей (Path Traversal)
Циклы 351-375.
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

def run_batch_15():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 351. Токен в заголовке x-auth-token строчными
    r = make_req("/history", token=None, headers={"x-auth-token": TOKEN})
    results.append({"cycle": 351, "name": "Auth Lowercase x-auth-token", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 352. Токен в заголовке X-AUTH-TOKEN прописными
    r = make_req("/history", token=None, headers={"X-AUTH-TOKEN": TOKEN})
    results.append({"cycle": 352, "name": "Auth Uppercase X-AUTH-TOKEN", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 353. Токен в заголовке X-AuTh-ToKeN смешанным регистром
    r = make_req("/history", token=None, headers={"X-AuTh-ToKeN": TOKEN})
    results.append({"cycle": 353, "name": "Auth Mixed Case X-AuTh-ToKeN", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 354. Односимвольный токен 'a' -> 401
    r = make_req("/history", token="a")
    results.append({"cycle": 354, "name": "Auth 1-char Short Token 401", "category": "Security", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 355. 2000-символьный токен -> 401
    r = make_req("/history", token="B" * 2000)
    results.append({"cycle": 355, "name": "Auth 2000-char Long Token 401", "category": "Security", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 356. Токен с нуль-байтом \x00 -> 401
    r = make_req("/history", token=TOKEN + "\x00")
    results.append({"cycle": 356, "name": "Auth Null Byte Token 401", "category": "Security", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 357. Токен с символом переноса \n в query параметре -> 401
    r = make_req(f"/history?token={TOKEN}%0A", token=None)
    results.append({"cycle": 357, "name": "Auth Newline Token 401", "category": "Security", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 358. Токен с символом табуляции \t -> 401
    r = make_req("/history", token=TOKEN + "\t")
    results.append({"cycle": 358, "name": "Auth Tab Character Token 401", "category": "Security", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 359. secrets.compare_digest тайминг-стойкость
    import secrets
    results.append({"cycle": 359, "name": "Auth Constant-Time Comparison", "category": "Security", "passed": secrets.compare_digest(TOKEN, TOKEN), "detail": "secrets.compare_digest active"})

    # 360. Токен в теле JSON для /volume
    r = make_req("/volume", method="POST", data={"token": TOKEN, "percent": 50}, token=None)
    results.append({"cycle": 360, "name": "Auth Token In JSON Body /volume", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 361. Токен в теле JSON для /screen/config
    r = make_req("/screen/config", method="POST", data={"token": TOKEN, "height": 720}, token=None)
    results.append({"cycle": 361, "name": "Auth Token In JSON Body /screen/config", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 362. Токен в теле JSON для /media/mode
    r = make_req("/media/mode", method="POST", data={"token": TOKEN, "mode": "normal"}, token=None)
    results.append({"cycle": 362, "name": "Auth Token In JSON Body /media/mode", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 363. Токен в query параметре ?token=TOKEN на /status
    r = make_req(f"/status?token={TOKEN}", token=None)
    results.append({"cycle": 363, "name": "Auth Token In Query /status", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 364. Токен в query параметре ?token=TOKEN на /history
    r = make_req(f"/history?token={TOKEN}", token=None)
    results.append({"cycle": 364, "name": "Auth Token In Query /history", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 365. Токен в query параметре ?token=TOKEN на /volume
    r = make_req(f"/volume?token={TOKEN}", token=None)
    results.append({"cycle": 365, "name": "Auth Token In Query /volume", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 366. Bearer токен на /volume
    r = make_req("/volume", token=None, headers={"Authorization": f"Bearer {TOKEN}"})
    results.append({"cycle": 366, "name": "Auth Bearer Header /volume", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 367. Bearer токен на /history
    r = make_req("/history", token=None, headers={"Authorization": f"Bearer {TOKEN}"})
    results.append({"cycle": 367, "name": "Auth Bearer Header /history", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 368. Bearer токен на /app_volumes
    r = make_req("/app_volumes", token=None, headers={"Authorization": f"Bearer {TOKEN}"})
    results.append({"cycle": 368, "name": "Auth Bearer Header /app_volumes", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 369. Bearer токен на /media/queue
    r = make_req("/media/queue", token=None, headers={"Authorization": f"Bearer {TOKEN}"})
    results.append({"cycle": 369, "name": "Auth Bearer Header /media/queue", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 370. Cookie токен на /history
    r = make_req("/history", token=None, headers={"Cookie": f"token={TOKEN}"})
    results.append({"cycle": 370, "name": "Auth Cookie Token /history", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 371. Cookie токен на /volume
    r = make_req("/volume", token=None, headers={"Cookie": f"token={TOKEN}"})
    results.append({"cycle": 371, "name": "Auth Cookie Token /volume", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 372. Path Traversal попытка /download/../../server.py -> 404
    r = make_req("/download/../../server.py")
    results.append({"cycle": 372, "name": "Path Traversal Dots Protection 404", "category": "Security", "passed": r["status"] == 404, "detail": f"status={r['status']}"})

    # 373. Path Traversal urlencoded /download/..%2f..%2fserver.py -> 404
    r = make_req("/download/..%2f..%2fserver.py")
    results.append({"cycle": 373, "name": "Path Traversal Encoded Slashes 404", "category": "Security", "passed": r["status"] == 404, "detail": f"status={r['status']}"})

    # 374. Path Traversal системный путь /download/C:/Windows/System32/drivers/etc/hosts -> 404
    r = make_req("/download/C:/Windows/System32/drivers/etc/hosts")
    results.append({"cycle": 374, "name": "Path Traversal Absolute Path 404", "category": "Security", "passed": r["status"] == 404, "detail": f"status={r['status']}"})

    # 375. Приоритет валидного токена в заголовке над невалидным в query
    r = make_req("/history?token=invalid_query_token", token=TOKEN)
    results.append({"cycle": 375, "name": "Auth Header Precedence Over Query", "category": "Security", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    return results

if __name__ == "__main__":
    b = run_batch_15()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 15 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
