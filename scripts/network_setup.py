"""Discover actual network adapters; bootstrap the signed official VPN installer."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import urllib.request


def detect_network():
    import psutil
    route_ip = ''
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('10.255.255.255', 1))
            route_ip = sock.getsockname()[0]
    except OSError:
        pass
    candidates = []
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        if not stats.get(name) or not stats[name].isup:
            continue
        if any(word in name.lower() for word in ('tailscale', 'loopback', 'vethernet', 'virtual', 'wsl')):
            continue
        mac = next((a.address.replace(':', '-').upper() for a in addresses
                    if a.family == psutil.AF_LINK and re.fullmatch(r'(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', a.address)), '')
        for addr in addresses:
            if addr.family == socket.AF_INET and not addr.address.startswith(('127.', '169.254.', '100.')):
                candidates.append((addr.address != route_ip, name, addr.address, mac))
    if not candidates:
        return {'lan_ip': '', 'mac_address': ''}
    _, _, ip, mac = sorted(candidates)[0]
    return {'lan_ip': ip, 'mac_address': mac}


def download_tailscale(directory):
    base = 'https://pkgs.tailscale.com/stable/'
    with urllib.request.urlopen(base + '?mode=json', timeout=30) as response:
        data = json.loads(response.read(1024 * 1024))
    name = next((n for n in data.get('Exes', []) if re.fullmatch(r'tailscale-setup-[0-9.]+\.exe', n)), None)
    if not name:
        raise ValueError('Official Tailscale installer not found')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    temporary = path.with_suffix('.download')
    try:
        with urllib.request.urlopen(base + name, timeout=60) as response, temporary.open('wb') as output:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 512 * 1024**2:
                    raise ValueError('Installer exceeds size limit')
                output.write(block)
        env = os.environ.copy()
        env.pop('PSModulePath', None)
        env.pop('PSMODULEPATH', None)
        env['PC_CONTROL_INSTALLER_CHECK'] = str(temporary.resolve())
        command = "$s = Get-AuthenticodeSignature -LiteralPath $env:PC_CONTROL_INSTALLER_CHECK; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Tailscale (Inc\\.|LLC)') { exit 1 }"
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', command], env=env, check=True, timeout=120,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        os.replace(temporary, path)
        return path
    finally:
        temporary.unlink(missing_ok=True)
