"""
Batch 7: Медиа-контроллер, плееры Windows (SMTC), очереди треков, громкость плеера, режимы
Циклы 151-175.
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

def run_batch_07():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 151. /media/now контракт
    r = make_req("/media/now")
    d = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 151, "name": "Media Now Contract Check", "category": "Media", "passed": r["status"] == 200 and "available" in d, "detail": f"status={r['status']}"})

    # 152. /media/control POST action="play"
    r = make_req("/media/control", method="POST", data={"action": "play"})
    results.append({"cycle": 152, "name": "Media Control Play", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 153. /media/control POST action="pause"
    r = make_req("/media/control", method="POST", data={"action": "pause"})
    results.append({"cycle": 153, "name": "Media Control Pause", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 154. /media/control POST action="play_pause"
    r = make_req("/media/control", method="POST", data={"action": "play_pause"})
    results.append({"cycle": 154, "name": "Media Control Play/Pause Toggle", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 155. /media/control POST action="next"
    r = make_req("/media/control", method="POST", data={"action": "next"})
    results.append({"cycle": 155, "name": "Media Control Next Track", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 156. /media/control POST action="prev"
    r = make_req("/media/control", method="POST", data={"action": "prev"})
    results.append({"cycle": 156, "name": "Media Control Prev Track", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 157. /media/control POST action="stop"
    r = make_req("/media/control", method="POST", data={"action": "stop"})
    results.append({"cycle": 157, "name": "Media Control Stop", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 158. /media/control POST action="seek" position=0
    r = make_req("/media/control", method="POST", data={"action": "seek", "position": 0})
    results.append({"cycle": 158, "name": "Media Control Seek Zero", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 159. /media/control POST action="seek" position=60
    r = make_req("/media/control", method="POST", data={"action": "seek", "position": 60})
    results.append({"cycle": 159, "name": "Media Control Seek 60s", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 160. /media/control POST action="seek" position=-10
    r = make_req("/media/control", method="POST", data={"action": "seek", "position": -10})
    results.append({"cycle": 160, "name": "Media Control Seek Negative", "category": "Media", "passed": r["status"] in (200, 400), "detail": f"status={r['status']}"})

    # 161. /media/control POST action="unknown_action" -> 400
    r = make_req("/media/control", method="POST", data={"action": "unknown_action_foo"})
    results.append({"cycle": 161, "name": "Media Control Invalid Action 400", "category": "Media", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 162. /media/control POST empty body {} -> 400
    r = make_req("/media/control", method="POST", data={})
    results.append({"cycle": 162, "name": "Media Control Empty Body 400", "category": "Media", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 163. /media/volume POST percent=0
    r = make_req("/media/volume", method="POST", data={"percent": 0})
    results.append({"cycle": 163, "name": "Media Volume Zero", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 164. /media/volume POST percent=100
    r = make_req("/media/volume", method="POST", data={"percent": 100})
    results.append({"cycle": 164, "name": "Media Volume 100%", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 165. /media/volume POST percent=-20 (clamping)
    r = make_req("/media/volume", method="POST", data={"percent": -20})
    results.append({"cycle": 165, "name": "Media Volume Clamping Min", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 166. /media/volume POST percent=150 (clamping)
    r = make_req("/media/volume", method="POST", data={"percent": 150})
    results.append({"cycle": 166, "name": "Media Volume Clamping Max", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 167. /media/volume POST percent="fifty" -> 400
    r = make_req("/media/volume", method="POST", data={"percent": "fifty"})
    results.append({"cycle": 167, "name": "Media Volume String 400", "category": "Media", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 168. /media/volume POST mute=True
    r = make_req("/media/volume", method="POST", data={"mute": True})
    results.append({"cycle": 168, "name": "Media Volume Mute True", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 169. /media/volume POST mute=False
    r = make_req("/media/volume", method="POST", data={"mute": False})
    results.append({"cycle": 169, "name": "Media Volume Mute False", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 170. /media/mode POST mode="normal"
    r = make_req("/media/mode", method="POST", data={"mode": "normal"})
    results.append({"cycle": 170, "name": "Media Mode Normal", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 171. /media/mode POST mode="repeat"
    r = make_req("/media/mode", method="POST", data={"mode": "repeat"})
    results.append({"cycle": 171, "name": "Media Mode Repeat", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 172. /media/mode POST mode="shuffle"
    r = make_req("/media/mode", method="POST", data={"mode": "shuffle"})
    results.append({"cycle": 172, "name": "Media Mode Shuffle", "category": "Media", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 173. /media/mode POST mode="invalid_mode" -> 400
    r = make_req("/media/mode", method="POST", data={"mode": "invalid_mode"})
    results.append({"cycle": 173, "name": "Media Mode Invalid 400", "category": "Media", "passed": r["status"] == 400, "detail": f"status={r['status']}"})

    # 174. /media/queue GET структура
    r = make_req("/media/queue")
    q_data = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 174, "name": "Media Queue Data Structure", "category": "Media", "passed": r["status"] == 200 and "tracks" in q_data, "detail": f"status={r['status']}"})

    # 175. /media/queue/play POST index=-1 -> 400
    r = make_req("/media/queue/play", method="POST", data={"index": -1})
    results.append({"cycle": 175, "name": "Media Queue Play Negative Index", "category": "Media", "passed": r["status"] in (400, 404), "detail": f"status={r['status']}"})

    return results

if __name__ == "__main__":
    b = run_batch_07()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 7 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
