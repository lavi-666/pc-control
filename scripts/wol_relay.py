"""
PC Control - Wake-on-LAN relay for Android devices.
Runs in Termux on a phone connected to local Wi-Fi and Tailscale.
"""
import http.server
import json
import os
import socket
import sys

PORT = 5050
DEFAULT_MAC = "AA-BB-CC-DD-EE-FF"
try:
    _cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    if not os.path.exists(_cfg_path):
        _cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(_cfg_path):
        with open(_cfg_path, "r", encoding="utf-8") as _f:
            _cfg = json.load(_f) or {}
            DEFAULT_MAC = _cfg.get("mac_address", DEFAULT_MAC)
            if not os.environ.get("RELAY_PORT"):
                PORT = int(_cfg.get("relay_port", PORT))
except Exception:
    pass

TARGET_MAC = os.environ.get("TARGET_MAC", DEFAULT_MAC)
PORT = int(os.environ.get("RELAY_PORT", PORT))
if not 1 <= PORT <= 65535:
    raise ValueError("RELAY_PORT must be between 1 and 65535")
BROADCASTS = ["255.255.255.255", "192.168.0.255", "192.168.1.255"]

def send_magic_packet(mac=TARGET_MAC):
    clean = mac.replace(":", "").replace("-", "").replace(".", "").replace(" ", "").strip()
    hw_addr = bytes.fromhex(clean)
    if len(hw_addr) != 6:
        raise ValueError("MAC address must contain exactly six bytes")
    packet = b"\xff" * 6 + hw_addr * 16
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            for ip in BROADCASTS:
                for port in (9, 7):
                    try:
                        s.sendto(packet, (ip, port))
                        sent += 1
                    except Exception:
                        pass
    return sent

class WolHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        try:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
        except Exception:
            pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        try:
            clean_path = self.path.split("?")[0].rstrip("/")
            if clean_path in ("/wake", "", "/api/wol") or clean_path.endswith("/wake"):
                count = send_magic_packet()
                print(f"[WOL Relay] >>> WAKE SIGNAL RECEIVED from {self.address_string()}!", flush=True)
                print(f"[WOL Relay] >>> Sent {count} Magic Packets to MAC {TARGET_MAC} via Wi-Fi.", flush=True)
                data = json.dumps({"ok": True, "message": f"Magic Packet sent to PC ({count} packets)"}).encode("utf-8")
            else:
                data = json.dumps({"ok": True, "status": "relay_running", "mac": TARGET_MAC}).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            try:
                err_data = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_data)))
                self.end_headers()
                self.wfile.write(err_data)
            except Exception:
                pass

    def log_message(self, format, *args):
        try:
            print(f"[WOL Relay] {self.address_string()} - {args[0]}", flush=True)
        except Exception:
            pass

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    http.server.ThreadingHTTPServer.allow_reuse_address = True
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), WolHandler)
    server.daemon_threads = True

    print("==================================================", flush=True)
    print(f" WOL Relay started on port {PORT}!", flush=True)
    print(f" Ready to wake PC (MAC: {TARGET_MAC})", flush=True)
    print(" To keep running in background run: termux-wake-lock", flush=True)
    print("==================================================", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...", flush=True)
