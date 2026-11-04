import urllib.request
import urllib.error

req = urllib.request.Request(
    'http://127.0.0.1:5000/status',
    headers={"Cookie": "token=token"}
)
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode())
