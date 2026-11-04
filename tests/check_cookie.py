import urllib.request
import urllib.error

req = urllib.request.Request(
    'http://127.0.0.1:5000/history',
    headers={"Cookie": "token=token", "X-Safe-Mode": "1"}
)
try:
    with urllib.request.urlopen(req) as resp:
        print("Status:", resp.getcode())
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read().decode())
