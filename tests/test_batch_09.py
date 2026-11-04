"""
Batch 9: WebRTC сигналинг, SDP оферы, закрытие сессий, переключение экранов
Циклы 201-225.
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

def run_batch_09():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 201. /webrtc/offer OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/webrtc/offer", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 201, "name": "WebRTC Offer CORS OPTIONS", "category": "WebRTC", "passed": r_opt.getcode() == 204, "detail": f"status={r_opt.getcode()}"})

    # 202. /webrtc/offer без токена -> 401
    r = make_req("/webrtc/offer", method="POST", data={"source": "mic"}, token=None)
    results.append({"cycle": 202, "name": "WebRTC Offer Missing Auth 401", "category": "WebRTC", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 203. /webrtc/offer без указания source -> 400 или 500
    r = make_req("/webrtc/offer", method="POST", data={"sdp": "v=0..."})
    results.append({"cycle": 203, "name": "WebRTC Offer Missing Source", "category": "WebRTC", "passed": r["status"] in (400, 500), "detail": f"status={r['status']}"})

    # 204. /webrtc/offer с неизвестным source -> 400 или 500
    r = make_req("/webrtc/offer", method="POST", data={"source": "invalid_source_123", "sdp": "v=0..."})
    results.append({"cycle": 204, "name": "WebRTC Offer Unknown Source", "category": "WebRTC", "passed": r["status"] in (400, 500), "detail": f"status={r['status']}"})

    # 205. /webrtc/offer с пустым SDP -> 400 или 500
    r = make_req("/webrtc/offer", method="POST", data={"source": "mic", "sdp": ""})
    results.append({"cycle": 205, "name": "WebRTC Offer Empty SDP", "category": "WebRTC", "passed": r["status"] in (400, 500), "detail": f"status={r['status']}"})

    # 206. /webrtc/offer с поврежденным SDP -> 500 или 400
    r = make_req("/webrtc/offer", method="POST", data={"source": "mic", "sdp": "corrupted_raw_sdp_payload"})
    results.append({"cycle": 206, "name": "WebRTC Offer Malformed SDP Ingestion", "category": "WebRTC", "passed": r["status"] in (400, 500), "detail": f"status={r['status']}"})

    # 207. /webrtc/close OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/webrtc/close", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 207, "name": "WebRTC Close CORS OPTIONS", "category": "WebRTC", "passed": r_opt.getcode() == 204, "detail": f"status={r_opt.getcode()}"})

    # 208. /webrtc/close без токена -> 401
    r = make_req("/webrtc/close", method="POST", data={"source": "mic"}, token=None)
    results.append({"cycle": 208, "name": "WebRTC Close Missing Auth 401", "category": "WebRTC", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 209. /webrtc/close source="loopback"
    r = make_req("/webrtc/close", method="POST", data={"source": "loopback"})
    results.append({"cycle": 209, "name": "WebRTC Close Loopback Source", "category": "WebRTC", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 210. /webrtc/close source="mic"
    r = make_req("/webrtc/close", method="POST", data={"source": "mic"})
    results.append({"cycle": 210, "name": "WebRTC Close Mic Source", "category": "WebRTC", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 211. /webrtc/close source="screen"
    r = make_req("/webrtc/close", method="POST", data={"source": "screen"})
    results.append({"cycle": 211, "name": "WebRTC Close Screen Source", "category": "WebRTC", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 212. /webrtc/close empty body {} (закрыть всё)
    r = make_req("/webrtc/close", method="POST", data={})
    results.append({"cycle": 212, "name": "WebRTC Close All Sources", "category": "WebRTC", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 213. /screen/monitors список мониторов
    r = make_req("/screen/monitors")
    md = json.loads(r["data"]) if r["status"] == 200 else {}
    results.append({"cycle": 213, "name": "Screen Monitors Discovery", "category": "Screen", "passed": r["status"] == 200 and "monitors" in md and len(md["monitors"]) >= 1, "detail": f"monitors={len(md.get('monitors', []))}"})

    # 214. /screen/monitors конфигурация по умолчанию
    cfg = md.get("config", {})
    results.append({"cycle": 214, "name": "Screen Config Invariant Fields", "category": "Screen", "passed": "monitor" in cfg and "height" in cfg and "fps" in cfg, "detail": f"cfg={cfg}"})

    # 215. /screen/config POST monitor=0
    r = make_req("/screen/config", method="POST", data={"monitor": 0})
    results.append({"cycle": 215, "name": "Screen Config Switch Monitor 0", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 216. /screen/config POST monitor=1
    r = make_req("/screen/config", method="POST", data={"monitor": 1})
    results.append({"cycle": 216, "name": "Screen Config Switch Monitor 1", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 217. /screen/config POST height=720
    r = make_req("/screen/config", method="POST", data={"height": 720})
    results.append({"cycle": 217, "name": "Screen Config Resolution 720p", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 218. /screen/config POST height=1080
    r = make_req("/screen/config", method="POST", data={"height": 1080})
    results.append({"cycle": 218, "name": "Screen Config Resolution 1080p", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 219. /screen/config POST fps=30
    r = make_req("/screen/config", method="POST", data={"fps": 30})
    results.append({"cycle": 219, "name": "Screen Config Frame Rate 30 FPS", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 220. /screen/config POST fps=60
    r = make_req("/screen/config", method="POST", data={"fps": 60})
    results.append({"cycle": 220, "name": "Screen Config Frame Rate 60 FPS", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 221. /screen/config POST комбо {monitor: 0, height: 720, fps: 30}
    r = make_req("/screen/config", method="POST", data={"monitor": 0, "height": 720, "fps": 30})
    results.append({"cycle": 221, "name": "Screen Config Preset 720p 30FPS Mon0", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 222. /screen/config POST комбо {monitor: 1, height: 1080, fps: 60}
    r = make_req("/screen/config", method="POST", data={"monitor": 1, "height": 1080, "fps": 60})
    results.append({"cycle": 222, "name": "Screen Config Preset 1080p 60FPS Mon1", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 223. /screen/config POST с лишними полями -> 200 (игнорируются)
    r = make_req("/screen/config", method="POST", data={"monitor": 0, "unknown_field": "test_extra", "magic": 999})
    results.append({"cycle": 223, "name": "Screen Config Extra Keys Ignored", "category": "Screen", "passed": r["status"] == 200, "detail": f"status={r['status']}"})

    # 224. /screen/stream GET без токена -> 401
    r = make_req("/screen/stream", token=None)
    results.append({"cycle": 224, "name": "Screen Stream Missing Auth 401", "category": "Screen", "passed": r["status"] == 401, "detail": f"status={r['status']}"})

    # 225. /screen/stream HEAD контракт
    r_head = make_req("/screen/stream", method="HEAD")
    results.append({"cycle": 225, "name": "Screen Stream HEAD Request", "category": "Screen", "passed": r_head["status"] in (200, 400), "detail": f"status={r_head['status']}"})

    return results

if __name__ == "__main__":
    b = run_batch_09()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 9 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
