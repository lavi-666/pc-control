"""USB cable connection between the phone and this PC (works with no internet / airplane mode).

Two paths, both started from server.py (the server is the process that is always running —
autostart + watchdog — and the only one that knows its own port; the panel is optional):

A) ADB: every few seconds ask the adb server for authorized devices and make
   `adb reverse tcp:<port> tcp:<port>` for every port the app uses, so on the phone
   http://127.0.0.1:<port> reaches this server through the cable. The app's whole traffic
   (API, H.264 screen, PC sound, phone mic, input stream) goes through the one HTTP port —
   streamer.exe (5051) and the media bridge (5017) are reached by the server on 127.0.0.1 and
   the WOL relay (5050) runs on another device, so only the server port is reversed.

   We talk to the adb server with its own socket protocol (127.0.0.1:5037) instead of running
   adb.exe each time: an adb.exe of another version kills a running adb server of a different
   version ("adb server version doesn't match this client; killing..."), which would break
   Android Studio / scrcpy sessions of the user. The bundled tools/adb/adb.exe is only used to
   START a server when none is running.

   Rules we made are remembered in logs/usb_link_state.json and removed on shutdown or when the
   server port changes. A reverse rule for the same phone port that points somewhere else belongs
   to someone else and is left alone (norebind).

B) USB tethering ("USB modem"): the phone and the PC get a private network over the cable.
   The server sends a small UDP broadcast beacon on every private IPv4 interface; the app
   listens for it to learn the PC's address on the tethering interface (it then verifies the
   server with /status?nonce=… before sending the password). Sending broadcasts needs no
   inbound firewall rule; the phone's TCP connection to the server port is covered by the
   "PC Control Server" rule (profile=any, private remote ranges — the tethering network is
   classified as Public by Windows).

Status for the panel: logs/usb_link.json.
"""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from core.config import BASE_DIR, LOGS_DIR

ADB_HOST = "127.0.0.1"
BEACON_PORT = 5058
BEACON_INTERVAL = 3.0
POLL_INTERVAL = 3.0
VERIFY_INTERVAL = 15.0
START_SERVER_RETRY = 300.0
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

STATUS_FILE = LOGS_DIR / "usb_link.json"
STATE_FILE = LOGS_DIR / "usb_link_state.json"


def adb_port() -> int:
    try:
        return int(os.environ.get("PC_CONTROL_ADB_PORT") or 5037)
    except ValueError:
        return 5037


class AdbError(Exception):
    pass


# ---------------------------------------------------------------------------------- adb protocol
def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise AdbError("connection closed by adb server")
        buf += chunk
    return buf


def _send_request(sock: socket.socket, payload: str) -> None:
    data = payload.encode("utf-8")
    sock.sendall(b"%04x" % len(data) + data)


def _read_status(sock: socket.socket) -> None:
    status = _recv_exact(sock, 4)
    if status == b"OKAY":
        return
    if status == b"FAIL":
        n = int(_recv_exact(sock, 4), 16)
        raise AdbError(_recv_exact(sock, n).decode("utf-8", "replace"))
    raise AdbError(f"unexpected adb reply {status!r}")


def _read_string(sock: socket.socket) -> str:
    n = int(_recv_exact(sock, 4), 16)
    return _recv_exact(sock, n).decode("utf-8", "replace") if n else ""


class AdbClient:
    """Minimal client of the adb server's host protocol (what adb.exe itself does)."""

    def __init__(self, host: str = ADB_HOST, port: int | None = None, timeout: float = 3.0):
        self.host = host
        self.port = adb_port() if port is None else port
        self.timeout = timeout

    def _connect(self) -> socket.socket:
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        return s

    def server_running(self) -> bool:
        try:
            with self._connect():
                return True
        except OSError:
            return False

    def host_query(self, service: str) -> str:
        with self._connect() as s:
            _send_request(s, service)
            _read_status(s)
            return _read_string(s)

    def devices(self) -> list[dict]:
        """[{serial, state, model, product, device}] from host:devices-l."""
        out = []
        for line in self.host_query("host:devices-l").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            item = {"serial": parts[0], "state": parts[1], "model": "", "product": "", "device": ""}
            for p in parts[2:]:
                if ":" in p:
                    k, v = p.split(":", 1)
                    if k in ("model", "product", "device"):
                        item[k] = v
            out.append(item)
        return out

    def _device_command(self, serial: str, service: str, *, read_result: bool) -> str:
        with self._connect() as s:
            _send_request(s, "host:transport:" + serial)
            _read_status(s)
            _send_request(s, service)
            _read_status(s)
            if read_result:
                return _read_string(s)
            try:  # reverse:forward / killforward answer a second OKAY (adb_command)
                _read_status(s)
            except (AdbError, OSError):
                pass
            return ""

    def reverse_list(self, serial: str) -> list[tuple[str, str]]:
        """[(phone side, pc side)] e.g. [("tcp:5000", "tcp:5000")]."""
        res = []
        for line in self._device_command(serial, "reverse:list-forward", read_result=True).splitlines():
            parts = line.split()
            if len(parts) >= 3:
                res.append((parts[1], parts[2]))
        return res

    def reverse_add(self, serial: str, remote: str, local: str) -> None:
        self._device_command(serial, f"reverse:forward:norebind:{remote};{local}", read_result=False)

    def reverse_remove(self, serial: str, remote: str) -> None:
        self._device_command(serial, f"reverse:killforward:{remote}", read_result=False)


def find_adb_exe(base_dir: Path | None = None) -> str:
    root = base_dir or BASE_DIR
    for p in (root / "tools" / "adb" / "adb.exe", root / "tools" / "adb.exe"):
        if p.is_file():
            return str(p)
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk = os.environ.get(env)
        if sdk:
            p = Path(sdk) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
            if p.is_file():
                return str(p)
    return shutil.which("adb") or ""


def launchable_adb(adb_exe: str, base_dir: Path | None = None) -> str:
    """The adb server keeps running after `start-server` and holds its exe open. Started from
    tools/adb it would lock the installation folder (update / uninstall could not replace or
    delete it), so a bundled adb is started from a copy in %LOCALAPPDATA%\\PCControl\\adb\\<hash>."""
    root = (base_dir or BASE_DIR).resolve()
    src = Path(adb_exe)
    try:
        if not src.resolve().is_relative_to(root) or not os.environ.get("LOCALAPPDATA"):
            return adb_exe
        import hashlib
        digest = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
        dst_dir = Path(os.environ["LOCALAPPDATA"]) / "PCControl" / "adb" / digest
        dst = dst_dir / src.name
        if not dst.is_file():
            dst_dir.mkdir(parents=True, exist_ok=True)
            for name in ("AdbWinApi.dll", "AdbWinUsbApi.dll", src.name):  # exe last = complete copy
                f = src.parent / name
                if f.is_file():
                    tmp = dst_dir / (name + ".tmp")
                    shutil.copy2(f, tmp)
                    os.replace(tmp, dst_dir / name)
        return str(dst)
    except (OSError, ValueError):
        return adb_exe


# ---------------------------------------------------------------------------------- reverse manager
class AdbReverseManager:
    """Keeps `adb reverse` rules for the server port(s) on every authorized phone."""

    def __init__(self, ports: Iterable[int], client: AdbClient | None = None, adb_exe: str | None = None,
                 state_file: Path = STATE_FILE, start_server: bool = True,
                 clock: Callable[[], float] = time.monotonic):
        self.ports = sorted({int(p) for p in ports if 0 < int(p) < 65536})
        self.client = client or AdbClient()
        self.adb_exe = find_adb_exe() if adb_exe is None else adb_exe
        self.state_file = state_file
        self.allow_start_server = start_server
        self.clock = clock
        self.applied: dict[str, set[int]] = {}      # serial -> ports we reversed
        self.conflicts: dict[str, list[int]] = {}   # serial -> ports reversed by someone else
        self.last_verify: dict[str, float] = {}
        self.devices: list[dict] = []
        self.adb_state = "unknown"                  # running / started / absent / no_adb / error
        self._last_start_attempt = -1e9
        self._stale_ports = self._load_stale_ports()

    # --- persistence of what we created (to clean up after a port change / crash)
    def _load_stale_ports(self) -> set[int]:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return {int(p) for p in data.get("ports", [])} - set(self.ports)
        except (OSError, ValueError, TypeError):
            return set()

    def _save_state(self) -> None:
        ports = sorted({p for s in self.applied.values() for p in s})
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"ports": ports}), encoding="utf-8")
        except OSError:
            pass

    # --- adb server
    def _ensure_server(self) -> bool:
        if self.client.server_running():
            if self.adb_state not in ("running", "started"):
                self.adb_state = "running"
            return True
        if not self.adb_exe:
            self.adb_state = "no_adb"
            return False
        if not self.allow_start_server:
            self.adb_state = "absent"
            return False
        now = self.clock()
        if now - self._last_start_attempt < START_SERVER_RETRY:
            self.adb_state = "absent"
            return False
        self._last_start_attempt = now
        try:
            subprocess.run([launchable_adb(self.adb_exe), "-P", str(self.client.port), "start-server"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           timeout=20, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            self.adb_state = "error"
            return False
        if self.client.server_running():
            self.adb_state = "started"
            return True
        self.adb_state = "error"
        return False

    # --- one polling step
    def tick(self) -> None:
        if not self.ports or not self._ensure_server():
            self.devices = []
            self.applied.clear()
            return
        try:
            devices = self.client.devices()
        except (OSError, AdbError):
            self.devices = []
            return
        self.devices = devices
        ready = {d["serial"] for d in devices if d["state"] == "device"}
        for gone in [s for s in self.applied if s not in ready]:
            self.applied.pop(gone, None)
            self.last_verify.pop(gone, None)
            self.conflicts.pop(gone, None)
        now = self.clock()
        changed = False
        for serial in sorted(ready):
            if serial in self.applied and now - self.last_verify.get(serial, 0) < VERIFY_INTERVAL:
                continue
            changed |= self._sync_device(serial)
            self.last_verify[serial] = now
        if changed:
            self._save_state()

    def _sync_device(self, serial: str) -> bool:
        try:
            current = dict(self.client.reverse_list(serial))
        except (OSError, AdbError):
            return False
        before = set(self.applied.get(serial, set()))
        mine: set[int] = set()
        conflicts: list[int] = []
        for port in self._stale_ports:  # rule of a previous run on an old port
            key = f"tcp:{port}"
            if current.get(key) == key:
                try:
                    self.client.reverse_remove(serial, key)
                except (OSError, AdbError):
                    pass
        for port in self.ports:
            key = f"tcp:{port}"
            target = current.get(key)
            if target == key:
                mine.add(port)
                continue
            if target is not None:
                conflicts.append(port)  # someone else's rule (another tool/port) — keep it
                continue
            try:
                self.client.reverse_add(serial, key, key)
                mine.add(port)
            except (OSError, AdbError):
                pass
        self.applied[serial] = mine
        if conflicts:
            self.conflicts[serial] = conflicts
        else:
            self.conflicts.pop(serial, None)
        return mine != before

    def remove_all(self) -> None:
        """Shutdown: remove only the rules we made and that still point to us."""
        for serial, ports in list(self.applied.items()):
            try:
                current = dict(self.client.reverse_list(serial))
            except (OSError, AdbError):
                continue
            for port in ports:
                key = f"tcp:{port}"
                if current.get(key) == key:
                    try:
                        self.client.reverse_remove(serial, key)
                    except (OSError, AdbError):
                        pass
        self.applied.clear()
        try:
            self.state_file.write_text(json.dumps({"ports": []}), encoding="utf-8")
        except OSError:
            pass

    def snapshot(self) -> dict:
        devs = []
        for d in self.devices:
            serial = d["serial"]
            devs.append({
                "serial": serial,
                "state": d["state"],
                "model": (d.get("model") or "").replace("_", " "),
                "reverse": sorted(self.applied.get(serial, set())),
                "conflicts": self.conflicts.get(serial, []),
            })
        return {"adb": self.adb_state, "adb_path": bool(self.adb_exe), "ports": self.ports, "devices": devs}


# ---------------------------------------------------------------------------------- tethering beacon
def _private_v4(ip: str) -> bool:
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private and not a.is_loopback and not a.is_link_local and a not in ipaddress.IPv4Network("100.64.0.0/10")


def beacon_targets() -> list[tuple[str, str]]:
    """[(local ip, directed broadcast)] for every up interface with a private IPv4 address."""
    try:
        import psutil
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
    except Exception:
        return []
    out = []
    for name, items in addrs.items():
        st = stats.get(name)
        if st is not None and not st.isup:
            continue
        for a in items:
            if a.family != socket.AF_INET or not _private_v4(a.address) or not a.netmask:
                continue
            try:
                net = ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False)
            except ValueError:
                continue
            if net.prefixlen >= 31:
                continue
            out.append((a.address, str(net.broadcast_address)))
    return out


def beacon_payload(port: int, instance: str) -> bytes:
    # No hostname / secrets: only what the app needs to find the server and pick its instance.
    return json.dumps({"pcc": 1, "port": int(port), "inst": instance[:16]}, separators=(",", ":")).encode("utf-8")


def send_beacons(port: int, instance: str, targets: list[tuple[str, str]] | None = None,
                 beacon_port: int = BEACON_PORT) -> int:
    sent = 0
    payload = beacon_payload(port, instance)
    for local_ip, bcast in (beacon_targets() if targets is None else targets):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind((local_ip, 0))
                s.sendto(payload, (bcast, beacon_port))
                sent += 1
        except OSError:
            pass
    return sent


# ---------------------------------------------------------------------------------- service
class UsbLinkService:
    def __init__(self, port: int, instance: str, adb_enabled: bool = True, beacon_enabled: bool = True):
        self.port = int(port)
        self.instance = instance
        self.manager = AdbReverseManager([self.port]) if adb_enabled else None
        self.beacon_enabled = beacon_enabled
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_status = ""

    def start(self) -> None:
        if self.manager is not None:
            t = threading.Thread(target=self._adb_loop, name="usb-adb-reverse", daemon=True)
            t.start()
            self._threads.append(t)
        if self.beacon_enabled:
            t = threading.Thread(target=self._beacon_loop, name="usb-beacon", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        if self.manager is not None:
            try:
                self.manager.remove_all()
            except Exception:
                pass
        self._write_status()

    def _adb_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.manager.tick()
            except Exception:
                pass
            self._write_status()
            self._stop.wait(POLL_INTERVAL)

    def _beacon_loop(self) -> None:
        while not self._stop.is_set():
            try:
                send_beacons(self.port, self.instance)
            except Exception:
                pass
            self._stop.wait(BEACON_INTERVAL)

    def snapshot(self) -> dict:
        snap = self.manager.snapshot() if self.manager is not None else {"adb": "disabled", "devices": []}
        snap.update({"port": self.port, "beacon": self.beacon_enabled, "running": not self._stop.is_set()})
        return snap

    def _write_status(self) -> None:
        snap = self.snapshot()
        text = json.dumps(snap, ensure_ascii=False, sort_keys=True)
        if text == self._last_status:
            return
        self._last_status = text
        snap["updated"] = time.time()
        try:
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATUS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, STATUS_FILE)
        except OSError:
            pass


_service: UsbLinkService | None = None


def start_service(port: int, instance: str, cfg: dict | None = None) -> UsbLinkService | None:
    """Started once from server.py. config.json: "usb_adb": false / "usb_beacon": false to disable."""
    global _service
    if _service is not None:
        return _service
    cfg = cfg or {}
    adb_on = bool(cfg.get("usb_adb", True)) and os.environ.get("PC_CONTROL_USB_ADB", "1") != "0"
    beacon_on = bool(cfg.get("usb_beacon", True)) and os.environ.get("PC_CONTROL_USB_BEACON", "1") != "0"
    if not adb_on and not beacon_on:
        return None
    _service = UsbLinkService(port, instance, adb_enabled=adb_on, beacon_enabled=beacon_on)
    _service.start()
    import atexit
    atexit.register(_service.stop)
    return _service


def get_service() -> UsbLinkService | None:
    return _service


def read_status_file() -> dict:
    """For the panel (a separate process): last status written by the server, or {}."""
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
