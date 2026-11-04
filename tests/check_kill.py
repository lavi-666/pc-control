import json
import urllib.request
import urllib.error

req = urllib.request.Request(
    'http://127.0.0.1:5000/processes/kill',
    data=json.dumps({"pid": -1}).encode("utf-8"),
    headers={"X-Auth-Token": os.environ.get("PC_REMOTE_TOKEN") or "token", "Content-Type": "application/json"},
    method="POST"
)
try:
    with urllib.request.urlopen(req) as resp:
        print("Status:", resp.getcode(), resp.read().decode())
except urllib.error.HTTPError as e:
    print("HTTPError Status:", e.code, e.read().decode())
except Exception as e:
    print("Exception:", e)
