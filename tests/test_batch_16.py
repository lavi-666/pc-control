"""
Batch 16: Матрица CORS (Cross-Origin Resource Sharing) для всех эндпоинтов сервера
Циклы 376-400.
"""
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:5000"

def check_cors(path):
    req = urllib.request.Request(BASE_URL + path, method="OPTIONS")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            hdrs = dict(resp.headers)
            status = resp.getcode()
            origin = hdrs.get("Access-Control-Allow-Origin", "")
            return status == 204 and (origin == "*" or origin != "")
    except Exception as e:
        return False

def run_batch_16():
    results = []

    endpoints = [
        (376, "/action", "CORS /action"),
        (377, "/webrtc/offer", "CORS /webrtc/offer"),
        (378, "/webrtc/close", "CORS /webrtc/close"),
        (379, "/status", "CORS /status"),
        (380, "/volume", "CORS /volume"),
        (381, "/history", "CORS /history"),
        (382, "/screen/config", "CORS /screen/config"),
        (383, "/screen/monitors", "CORS /screen/monitors"),
        (384, "/screen/volume", "CORS /screen/volume"),
        (385, "/app_volumes", "CORS /app_volumes"),
        (386, "/app_volume", "CORS /app_volume"),
        (387, "/app_volume/mute", "CORS /app_volume/mute"),
        (388, "/media/now", "CORS /media/now"),
        (389, "/media/control", "CORS /media/control"),
        (390, "/media/volume", "CORS /media/volume"),
        (391, "/media/mode", "CORS /media/mode"),
        (392, "/media/queue", "CORS /media/queue"),
        (393, "/media/queue/play", "CORS /media/queue/play"),
        (394, "/keyboard/languages", "CORS /keyboard/languages"),
        (395, "/keyboard/switch_language", "CORS /keyboard/switch_language"),
        (396, "/keyboard/set_language", "CORS /keyboard/set_language"),
        (397, "/processes", "CORS /processes"),
        (398, "/processes/kill", "CORS /processes/kill"),
        (399, "/shutdown_timer", "CORS /shutdown_timer"),
        (400, "/api/wol", "CORS /api/wol"),
    ]

    for cycle, ep, name in endpoints:
        ok = check_cors(ep)
        results.append({
            "cycle": cycle,
            "name": name,
            "category": "CORS",
            "passed": ok,
            "detail": f"cors_ok={ok}"
        })

    return results

if __name__ == "__main__":
    b = run_batch_16()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 16 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
