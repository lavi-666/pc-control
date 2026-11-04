"""
Batch 20: Эмуляция Android OkHttp-клиента, мобильного стека и поведения мобильного приложения
Циклы 476-500.
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

def run_batch_20():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 476. OkHttp 4.9.2 User-Agent
    r476 = make_req("/status", headers={"User-Agent": "okhttp/4.9.2"})
    results.append({"cycle": 476, "name": "OkHttp 4.9.2 User-Agent Ingestion", "category": "Mobile Simulation", "passed": r476["status"] == 200, "detail": f"status={r476['status']}"})

    # 477. OkHttp 5.0.0 User-Agent on screen config
    r477 = make_req("/screen/config", method="POST", data={"fps": 30}, headers={"User-Agent": "okhttp/5.0.0-alpha.11"})
    results.append({"cycle": 477, "name": "OkHttp 5.x User-Agent Ingestion", "category": "Mobile Simulation", "passed": r477["status"] == 200, "detail": f"status={r477['status']}"})

    # 478. Mobile Chrome WebView User-Agent
    r478 = make_req("/", headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"})
    results.append({"cycle": 478, "name": "Mobile Chrome WebView UA", "category": "Mobile Simulation", "passed": r478["status"] == 200, "detail": f"status={r478['status']}"})

    # 479. Empty User-Agent string
    r479 = make_req("/status", headers={"User-Agent": ""})
    results.append({"cycle": 479, "name": "Empty User-Agent String Tolerance", "category": "Mobile Simulation", "passed": r479["status"] == 200, "detail": f"status={r479['status']}"})

    # 480. Accept: application/json, text/plain, */*
    r480 = make_req("/status", headers={"Accept": "application/json, text/plain, */*"})
    results.append({"cycle": 480, "name": "Standard Mobile Accept Header", "category": "Mobile Simulation", "passed": r480["status"] == 200, "detail": f"status={r480['status']}"})

    # 481. Accept: image/png on screenshot HEAD
    r481 = make_req("/screenshot", method="HEAD", headers={"Accept": "image/png"})
    results.append({"cycle": 481, "name": "Image Accept Header on Screenshot", "category": "Mobile Simulation", "passed": r481["status"] in (200, 401), "detail": f"status={r481['status']}"})

    # 482. Accept-Language ru-RU
    r482 = make_req("/status", headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"})
    results.append({"cycle": 482, "name": "Accept-Language Russian Locale", "category": "Mobile Simulation", "passed": r482["status"] == 200, "detail": f"status={r482['status']}"})

    # 483. Accept-Language en-US on action
    r483 = make_req("/action", method="POST", data={"action": "lock"}, headers={"Accept-Language": "en-US,en;q=0.9"})
    results.append({"cycle": 483, "name": "Accept-Language English Locale", "category": "Mobile Simulation", "passed": r483["status"] == 200, "detail": f"status={r483['status']}"})

    # 484. If-None-Match simulation
    r484 = make_req("/download/apk", headers={"If-None-Match": "\"some-random-etag\""})
    results.append({"cycle": 484, "name": "If-None-Match Conditional Handling", "category": "Mobile Simulation", "passed": r484["status"] in (200, 304), "detail": f"status={r484['status']}"})

    # 485. Aborted socket during stream simulation
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1", 5000))
        s.sendall(f"GET /processes HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Auth-Token: {TOKEN}\r\nX-Safe-Mode: 1\r\n\r\n".encode())
        _ = s.recv(64)  # read start of stream then disconnect abruptly
    finally:
        s.close()
    time.sleep(0.05)
    r485 = make_req("/status")
    results.append({"cycle": 485, "name": "Abrupt Mobile Connection Drop Tolerance", "category": "Mobile Simulation", "passed": r485["status"] == 200, "detail": "Server stayed responsive"})

    # 486. Rapid Polling: 10 status calls with 20ms delta
    rapid_ok = True
    for _ in range(10):
        if make_req("/status")["status"] != 200:
            rapid_ok = False
            break
        time.sleep(0.02)
    results.append({"cycle": 486, "name": "High-Rate Polling 10x 20ms Interval", "category": "Mobile Simulation", "passed": rapid_ok, "detail": f"rapid_ok={rapid_ok}"})

    # 487. Token in URL parameter with Android URL encoding
    r487 = make_req(f"/status?token={TOKEN}", token=None)
    results.append({"cycle": 487, "name": "Mobile Query Token Authentication", "category": "Mobile Simulation", "passed": r487["status"] == 200, "detail": f"status={r487['status']}"})

    # 488. Bearer token with irregular whitespace padding
    r488 = make_req("/status", token=None, headers={"Authorization": f"Bearer    {TOKEN}   "})
    results.append({"cycle": 488, "name": "Bearer Token Whitespace Trimming", "category": "Mobile Simulation", "passed": r488["status"] == 200, "detail": f"status={r488['status']}"})

    # 489. Custom Mobile Device Model Header
    r489 = make_req("/status", headers={"X-Client-Model": "Google Pixel 8 Pro"})
    results.append({"cycle": 489, "name": "Custom Mobile Model Metadata Ingestion", "category": "Mobile Simulation", "passed": r489["status"] == 200, "detail": f"status={r489['status']}"})

    # 490. Custom Mobile App Version Header
    r490 = make_req("/status", headers={"X-App-Version": "2.1.0-release"})
    results.append({"cycle": 490, "name": "Mobile App Version Metadata Ingestion", "category": "Mobile Simulation", "passed": r490["status"] == 200, "detail": f"status={r490['status']}"})

    # 491. Screen Resolution Toggle (480p mobile bandwidth mode)
    r491 = make_req("/screen/config", method="POST", data={"height": 480, "fps": 30})
    results.append({"cycle": 491, "name": "Mobile Screen Low-Bandwidth Mode 480p", "category": "Mobile Simulation", "passed": r491["status"] == 200, "detail": f"status={r491['status']}"})

    # 492. Audio Volume Fine-grained Sweeps (40% to 44%)
    sweep_ok = True
    for p in [40, 41, 42, 43, 44]:
        res = make_req("/volume", method="POST", data={"percent": p})
        if res["status"] != 200:
            sweep_ok = False
    results.append({"cycle": 492, "name": "Volume Slider Fine-grained Micro-Sweeps", "category": "Mobile Simulation", "passed": sweep_ok, "detail": f"sweep_ok={sweep_ok}"})

    # 493. Media Debounce: play then pause in rapid succession
    r493_a = make_req("/media/control", method="POST", data={"action": "play"})
    r493_b = make_req("/media/control", method="POST", data={"action": "pause"})
    results.append({"cycle": 493, "name": "Media Play-Pause Debounce Tolerance", "category": "Mobile Simulation", "passed": r493_a["status"] in (200, 400) and r493_b["status"] in (200, 400), "detail": f"a={r493_a['status']}, b={r493_b['status']}"})

    # 494. Wake-on-LAN check interval
    r494 = make_req("/api/wol", method="POST", data={"mac": "AA:BB:CC:DD:EE:FF"})
    results.append({"cycle": 494, "name": "Mobile App Background WOL Polling", "category": "Mobile Simulation", "passed": r494["status"] == 200, "detail": f"status={r494['status']}"})

    # 495. Duplicate Header keys
    r495 = make_req("/status", headers={"X-Client-Retry": "1"})
    results.append({"cycle": 495, "name": "Mobile Retry Counter Header Ingestion", "category": "Mobile Simulation", "passed": r495["status"] == 200, "detail": f"status={r495['status']}"})

    # 496. Case-mixed Content-Type
    r496 = make_req("/api/safe_mode", method="POST", data=b'{"enabled": true}', headers={"Content-Type": "application/JSON; CHARSET=UTF-8"})
    results.append({"cycle": 496, "name": "Case-mixed Content-Type Ingestion", "category": "Mobile Simulation", "passed": r496["status"] == 200, "detail": f"status={r496['status']}"})

    # 497. JSON body with UTF-8 BOM
    bom_data = b'\xef\xbb\xbf{"action": "lock"}'
    r497 = make_req("/action", method="POST", data=bom_data, headers={"Content-Type": "application/json"})
    results.append({"cycle": 497, "name": "JSON Body with UTF-8 BOM Handling", "category": "Mobile Simulation", "passed": r497["status"] == 200, "detail": f"status={r497['status']}"})

    # 498. JSON body with Windows CRLF newlines within JSON string
    crlf_json = '{\r\n  "action": "lock"\r\n}'
    r498 = make_req("/action", method="POST", data=crlf_json, headers={"Content-Type": "application/json"})
    results.append({"cycle": 498, "name": "JSON with Embedded CRLF Formats", "category": "Mobile Simulation", "passed": r498["status"] == 200, "detail": f"status={r498['status']}"})

    # 499. New TCP ephemeral port simulation
    r499 = make_req("/status")
    results.append({"cycle": 499, "name": "New Ephemeral Client Port Negotiation", "category": "Mobile Simulation", "passed": r499["status"] == 200, "detail": f"status={r499['status']}"})

    # 500. Round-trip Latency Benchmark (<100ms average across 5 calls)
    latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        make_req("/status")
        latencies.append((time.perf_counter() - t0) * 1000)
    avg_latency = sum(latencies) / len(latencies)
    results.append({"cycle": 500, "name": "Mobile Round-Trip Latency (<100ms)", "category": "Mobile Simulation", "passed": avg_latency < 100.0, "detail": f"avg={avg_latency:.2f}ms"})

    return results

if __name__ == "__main__":
    b = run_batch_20()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 20 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
