from ipaddress import ip_address, ip_network
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import urllib.request
import psutil

TAILSCALE_NET = ip_network('100.64.0.0/10')
RFC1918_NETS = (
    ip_network('192.168.0.0/16'),
    ip_network('10.0.0.0/8'),
    ip_network('172.16.0.0/12'),
)
VIRTUAL_ADAPTERS = (
    'tailscale', 'loopback', 'vethernet', 'virtual', 'wsl', 'wslg',
    'vmware', 'vmnet', 'vbox', 'virtualbox', 'radmin', 'hamachi',
    'zerotier', 'zt', 'docker', 'hyper-v', 'bluetooth', 'teredo', 'isatap',
    '6to4', 'wireguard', 'openvpn', 'tap-windows', 'wintun',
    'protonvpn', 'nordlynx', 'nord', 'mullvad', 'expressvpn', 'surfshark',
    'warp', 'cloudflare', 'amnezia', 'adguard', 'sing-box', 'v2ray', 'xray',
    'hiddify', 'clash', 'outline', 'anyconnect', 'fortinet', 'pangp', 'npcap',
    'miniport', 'multipass', 'qemu', 'kvm',
)
VIRTUAL_SUBNETS = (
    ip_network('192.168.56.0/24'),  # VirtualBox host-only
    ip_network('172.17.0.0/16'),     # Docker default bridge
)
SAFE_INSTALLER = re.compile(r'^tailscale-setup-[\w.-]+\.exe$', re.ASCII)


def _format_mac(raw: str) -> str:
    value = (raw or '').strip().upper().replace(':', '-')
    if re.fullmatch(r'([0-9A-F]{2}-){5}[0-9A-F]{2}', value) and value != '00-00-00-00-00-00':
        return value
    return ''


def _valid_lan_ip(raw: str) -> bool:
    try:
        addr = ip_address(raw)
    except ValueError:
        return False
    return (
        addr.version == 4
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_unspecified
        and not addr.is_multicast
        and addr not in TAILSCALE_NET
    )


def _is_rfc1918(raw: str) -> bool:
    try:
        addr = ip_address(raw)
        return any(addr in net for net in RFC1918_NETS)
    except ValueError:
        return False


def _is_virtual_adapter(name: str, ip: str, mac: str) -> bool:
    lname = (name or '').lower()
    if any(tag in lname for tag in VIRTUAL_ADAPTERS):
        return True
    # Layer-3 VPN/TUN interfaces lack a hardware Ethernet MAC address
    if not mac:
        return True
    # Subnet-based virtual checks
    try:
        addr = ip_address(ip)
        if any(addr in net for net in VIRTUAL_SUBNETS):
            return True
    except ValueError:
        pass
    # VirtualBox Host-Only default IP (192.168.56.1)
    if ip == '192.168.56.1':
        return True
    # Radmin VPN (26.x.x.x) and LogMeIn Hamachi (25.x.x.x)
    if ip.startswith('26.') or ip.startswith('25.'):
        return True
    return False


def _probe_route_ips() -> list[str]:
    found: list[str] = []
    for target in ('10.255.255.255', '192.168.1.1', '192.168.0.1', '172.16.0.1', '1.1.1.1', '8.8.8.8'):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 1))
                ip = sock.getsockname()[0]
                if ip and ip not in found:
                    found.append(ip)
        except OSError:
            pass
    return found


def list_network_interfaces() -> list[dict]:
    """
    Возвращает список доступных IPv4 сетевых интерфейсов ПК с оценкой приоритета
    для подключения телефона по локальной сети Wi-Fi / LAN.
    """
    route_ips = _probe_route_ips()
    primary_route = route_ips[0] if route_ips else ''

    try:
        stats = psutil.net_if_stats()
        addrs_map = psutil.net_if_addrs()
    except Exception:
        return []

    raw_list: list[dict] = []
    for name, addrs in addrs_map.items():
        if name in stats and not stats[name].isup:
            continue
        ips = [a.address for a in addrs if getattr(a, 'family', None) == socket.AF_INET and _valid_lan_ip(a.address)]
        macs = [_format_mac(a.address) for a in addrs if getattr(a, 'family', None) == getattr(psutil, 'AF_LINK', -1)]
        mac = next((m for m in macs if m), '')
        for ip in ips:
            is_virt = _is_virtual_adapter(name, ip, mac)
            lname = name.lower()
            is_wifi = any(w in lname for w in ('wi-fi', 'wifi', 'wlan', 'беспровод', 'wireless'))
            is_eth = any(e in lname for e in ('ethernet', 'eth', 'локальн'))
            # Приоритет выбора (меньше = лучше)
            if not is_virt and ip == primary_route:
                rank = (0, 0 if is_wifi else (1 if is_eth else 2), name, ip)
            elif not is_virt and ip in route_ips:
                rank = (1, 0 if is_wifi else (1 if is_eth else 2), name, ip)
            elif not is_virt and _is_rfc1918(ip):
                rank = (2, 0 if is_wifi else (1 if is_eth else 2), name, ip)
            elif not is_virt:
                rank = (3, 0 if is_wifi else (1 if is_eth else 2), name, ip)
            else:
                rank = (9, 0 if ip == primary_route else 1, name, ip)

            raw_list.append({
                'name': name,
                'ip': ip,
                'mac': mac,
                'is_virtual': is_virt,
                'is_route': ip in route_ips,
                'is_wifi': is_wifi,
                '_rank': rank,
            })

    raw_list.sort(key=lambda item: item['_rank'])
    non_virtual = [item for item in raw_list if not item['is_virtual']]
    effective = non_virtual if non_virtual else raw_list

    result: list[dict] = []
    for idx, item in enumerate(effective):
        entry = {
            'name': item['name'],
            'ip': item['ip'],
            'mac': item['mac'],
            'is_virtual': item['is_virtual'],
            'is_route': item['is_route'],
            'is_wifi': item['is_wifi'],
            'is_preferred': (idx == 0),
            'label': f"{item['name']} — {item['ip']}" + (f" ({item['mac']})" if item['mac'] else ""),
        }
        result.append(entry)
    return result


def detect_network() -> dict[str, str]:
    interfaces = list_network_interfaces()
    for item in interfaces:
        if not item.get('is_virtual'):
            return {'lan_ip': item['ip'], 'mac_address': item['mac']}
    return {'lan_ip': '', 'mac_address': ''}


def get_best_lan_ip() -> str:
    """Возвращает лучший физический IPv4 адрес для локального подключения телефона или '' если сеть недоступна."""
    return detect_network().get('lan_ip', '')


def get_network_diagnostics() -> dict:
    interfaces = list_network_interfaces()
    physical = [item for item in interfaces if not item.get('is_virtual')]
    virtual = [item for item in interfaces if item.get('is_virtual')]
    primary = physical[0]['ip'] if physical else ''
    alternatives = [p['ip'] for p in physical[1:]]
    return {
        'ok': bool(primary),
        'has_lan': bool(primary),
        'primary_ip': primary,
        'alternative_ips': alternatives,
        'physical_interfaces': physical,
        'virtual_interfaces': [{'name': v['name'], 'ip': v['ip']} for v in virtual],
    }


def powershell_env() -> dict[str, str]:
    root = os.environ.get('SystemRoot', r'C:\Windows')
    env = os.environ.copy()
    env['PATH'] = root + r'\System32;' + root + r'\System32\WindowsPowerShell\v1.0;' + root
    env['PSModulePath'] = root + r'\System32\WindowsPowerShell\v1.0\Modules'
    return env


def verify_tailscale_signature(path: Path) -> None:
    if sys.platform != 'win32':
        return
    ps = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    cmd = (
        "$sig = Get-AuthenticodeSignature -LiteralPath $env:TS_INSTALLER; "
        "if ($sig.Status -ne 'Valid' -or -not $sig.SignerCertificate -or "
        "$sig.SignerCertificate.Subject -notmatch 'Tailscale') { exit 1 }"
    )
    env = powershell_env()
    env['TS_INSTALLER'] = str(path)
    res = subprocess.run([str(ps if ps.is_file() else 'powershell.exe'), '-NoProfile', '-Command', cmd],
                         capture_output=True, text=True, timeout=30, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    if res.returncode != 0:
        raise ValueError('Tailscale installer signature verification failed')


def download_tailscale(arch: str) -> Path:
    req = urllib.request.Request('https://pkgs.tailscale.com/stable/?mode=json',
                                 headers={'User-Agent': 'PCControl-Launcher/2.4'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        meta = json.load(resp)
    exes = meta.get('Exes') or []
    installer = next((x for x in exes if str(x).endswith(f'-{arch}.exe')), '')
    if not SAFE_INSTALLER.fullmatch(installer):
        raise ValueError('Unexpected Tailscale installer filename')
    target = Path(tempfile.mkdtemp(prefix='pccontrol-tailscale-')) / installer
    url = 'https://pkgs.tailscale.com/stable/' + installer
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'PCControl-Launcher/2.4'}), timeout=120) as resp:
        with open(target, 'wb') as out:
            while chunk := resp.read(262144):
                out.write(chunk)
    if target.stat().st_size < 1024 * 1024:
        raise ValueError('Downloaded Tailscale installer is incomplete')
    verify_tailscale_signature(target)
    return target
