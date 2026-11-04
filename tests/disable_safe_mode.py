import json
import urllib.request

req = urllib.request.Request(
    'http://127.0.0.1:5000/api/safe_mode',
    data=json.dumps({"enabled": False}).encode("utf-8"),
    headers={"X-Auth-Token": os.environ.get("PC_REMOTE_TOKEN") or "token", "Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req) as resp:
    print("Safe mode disabled:", resp.read().decode())
