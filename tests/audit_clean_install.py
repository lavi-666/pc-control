"""Acceptance test: real Launcher.exe and bundled Python in a fresh extracted ZIP.

Run with an audit interpreter containing Playwright, Pillow and zxing-cpp;
these are external test tools, not application dependencies.
The application receives a Windows-only PATH, no developer Python or configuration.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import zipfile
import io
from PIL import Image
import zxingcpp
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-zip', action='store_true', help='Exclude runtime and exercise actual Launcher bootstrap')
    args = parser.parse_args()
    destination = ROOT / 'scratch' / ('Чистый ZIP ' + time.strftime('%Y%m%d-%H%M%S'))
    destination.mkdir()
    archive_path = ROOT / 'dist/PC_Control_Windows.zip'
    if args.source_zip:
        archive_path = destination / 'source-snapshot.zip'
        names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode('utf-8').split('\0')
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(set(names)):
                if name and (ROOT / name).is_file():
                    archive.write(ROOT / name, 'PC_Control/' + name)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(destination)
    app = destination / 'PC_Control'
    assert not (app / 'config.json').exists()
    assert not (app / 'venv').exists()
    port, server_port = free_port(), free_port()
    env = os.environ.copy()
    env.update(PATH=os.environ['SystemRoot'] + r'\System32;' + os.environ['SystemRoot'],
               PYTHONHOME=str(destination / 'nonexistent-python'),
               PYTHONPATH=str(destination / 'nonexistent-packages'),
               PYTHONNOUSERSITE='1', PC_CONTROL_PANEL_PORT=str(port), PC_CONTROL_TEST_MODE='1')
    env.pop('VIRTUAL_ENV', None)
    env.pop('PC_REMOTE_TOKEN', None)
    url = f'http://127.0.0.1:{port}'
    reports = []

    def launch():
        proc = subprocess.Popen([str(app / 'Launcher.exe'), '--no-browser'], cwd=app, env=env)
        deadline = time.monotonic() + (600 if args.source_zip else 45)
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url + '/api/identity', timeout=1) as response:
                    identity = json.load(response)
                expected = hashlib.sha256(str(app.resolve()).lower().encode()).hexdigest()
                assert identity['instance'] == expected
                proc.wait(timeout=20)
                return
            except OSError:
                time.sleep(.2)
        raise AssertionError('Real launcher did not start its panel')

    def terminate_owned():
        # psutil runs only in the external test driver; match exact extracted path.
        import psutil
        for process in psutil.process_iter(['pid', 'cmdline']):
            command = process.info['cmdline'] or []
            if any(str(app).lower() in arg.lower() for arg in command):
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

    try:
        launch()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            page.wait_for_function('currentStatus && currentStatus.port', timeout=60000)
            assert page.evaluate('currentStatus.python_deps.installed')
            import psutil
            detected_ip = page.evaluate('currentStatus.lan_ip')
            detected_mac = page.evaluate('currentStatus.mac_address')
            matching = [addresses for addresses in psutil.net_if_addrs().values() if any(a.address == detected_ip for a in addresses)]
            assert matching, 'Auto LAN IP does not belong to a local adapter'
            assert any(a.address.upper().replace(':', '-') == detected_mac for addresses in matching for a in addresses), 'MAC is not paired with LAN adapter'
            assert str(app / 'runtime/python.exe').lower() == page.evaluate('currentStatus.python_deps.interpreter').lower()
            for button, value in (('#btnCopyLan', 'currentStatus.lan_ip'), ('#btnCopyToken', 'currentStatus.token')):
                page.locator(button).click()
                page.wait_for_function(f'navigator.clipboard.readText().then(text => text === {value})')
            for language in ('uk', 'ru', 'en'):
                page.locator('#langTriggerBtn').click()
                page.locator(f'.lang-opt[data-lang="{language}"]').click()
                page.wait_for_function(f'currentLang === "{language}"')
            for field in ('Lan', 'Vpn', 'Token'):
                eye = page.locator('#btnEye' + field)
                if eye.is_visible():
                    eye.click()
                    eye.click()
            page.locator('#btnChangePwd').click()
            page.locator('#btnModalGen').click()
            assert len(page.locator('#pwdInput').input_value()) >= 12
            page.locator('#btnModalCancel').click()
            page.locator('[onclick="openCorsModal()"]').click()
            page.locator('#corsInput').fill('http://localhost:*, http://127.0.0.1:*')
            page.locator('#corsModal [data-i18n="btn_save"]').click()
            page.locator('#corsModal').wait_for(state='hidden')
            page.locator('#btnVpnDetails').click()
            page.locator('#tailscaleModal.open').wait_for()
            page.locator('#tailscaleModal [data-i18n="btn_close"]').click()
            with page.expect_download() as pending_download:
                page.locator('[onclick="location.href=\'/download/apk\'"]').click()
            download = pending_download.value
            assert hashlib.sha256(Path(download.path()).read_bytes()).digest() == hashlib.sha256((app / 'PC_Control.apk').read_bytes()).digest()
            if not args.source_zip:
                assert page.locator('#btnBuildApk').is_enabled()
            reports.append('Three languages, secret visibility, password generation/cancel, CORS save, VPN details, exact APK download')
            page.screenshot(path=str(destination / 'desktop-1440.png'), full_page=True)
            page.locator('[onclick="openNetworkSettings()"]').first.click()
            page.locator('#btnDetectNetwork').click()
            page.wait_for_function('!networkDetectionPending')
            page.wait_for_function("document.querySelector('[name=lan_ip]').value === currentStatus.lan_ip")
            assert json.loads((app / 'config.json').read_text())['auto_network'] is True
            page.locator('[name="port"]').fill(str(server_port))
            page.locator('[name="wol_relay_ip"]').fill('192.168.1.70')
            page.locator('#networkModal button[type="submit"]').click()
            page.locator('#networkModal').wait_for(state='hidden')
            page.locator('#btnChangePwd').click()
            page.locator('#pwdInput').fill('clean-install-audit-password')
            page.locator('#btnModalSave').click()
            page.locator('#pwdModal').wait_for(state='hidden')
            def lifecycle(action, selector):
                with page.expect_response(lambda response: response.url.endswith('/api/action') and response.request.post_data_json.get('action') == action, timeout=60000) as pending:
                    page.locator(selector).click()
                result = pending.value.json()
                assert result['ok'], result
                page.wait_for_function('!lifecyclePending', timeout=60000)

            page.locator('#btnConnectPhone').click()
            page.locator('#phoneModal').wait_for(state='visible', timeout=60000)
            page.wait_for_function('currentStatus && currentStatus.server_running === true', timeout=60000)
            qr_src = page.locator('#phoneQr').get_attribute('src')
            qr_bytes = page.request.get(qr_src).body()
            decoded = zxingcpp.read_barcode(Image.open(io.BytesIO(qr_bytes)))
            assert decoded, 'QR could not be decoded'
            target = decoded.text
            lan = page.evaluate('currentStatus.lan_ip')
            assert target.startswith(f'http://{lan}:{server_port}/?token=')
            phone = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
            phone_page = phone.new_page()
            phone_page.goto(target, timeout=30000)
            phone_page.wait_for_function("localStorage.getItem('pc_token') === 'clean-install-audit-password'")
            with phone_page.expect_download() as phone_download:
                phone_page.locator('#apkBanner a[download]').click()
            assert hashlib.sha256(Path(phone_download.value.path()).read_bytes()).digest() == hashlib.sha256((app / 'PC_Control.apk').read_bytes()).digest()
            page.screenshot(path=str(destination / 'phone-qr.png'), full_page=True)
            phone_page.screenshot(path=str(destination / 'phone-remote.png'), full_page=True)
            phone.close()
            page.locator('#phoneModal button').click()
            reports.append('Launcher QR decoded independently; actual LAN URL opened in fresh mobile browser; token imported; APK downloaded with identical hash')
            page.locator('#btnOpenRemote').click()
            page.locator('#remoteViewContainer').wait_for(state='visible')
            remote = page.frame_locator('#remoteIframe')
            remote.locator('.brand').click()
            remote.locator('#settingsModalBackdrop').wait_for(state='visible')
            remote.locator('#settingsModalBackdrop .settings-modal-close').click()
            page.locator('#btnRemoteBack').click()
            page.locator('#remoteViewContainer').wait_for(state='hidden')
            reports.append('Real Launcher.exe: private runtime, network/password UI save, server start')
            lifecycle('restart_server', '[onclick="runAction(\'restart_server\', {}, this)"]')
            with urllib.request.urlopen(f'http://127.0.0.1:{server_port}/status', timeout=10) as response:
                assert json.load(response)['status'] == 'online'
            lifecycle('stop_server', '#btnToggleServer')
            page.wait_for_function('currentStatus.server_running === false', timeout=60000)
            with socket.socket() as check:
                assert check.connect_ex(('127.0.0.1', server_port)) != 0, 'Stopped server still has a listening socket'
            lifecycle('start_server', '[onclick="runAction(\'start_server\', {}, this)"]')
            lifecycle('stop_server', '[onclick="runAction(\'stop_server\', {}, this)"]')
            with socket.socket() as check:
                assert check.connect_ex(('127.0.0.1', server_port)) != 0
            page.locator('#btnClearLogs').click()
            reports.append('Server restart, health, stop via actual UI')
            for width, height in ((390, 844), (360, 740)):
                page.set_viewport_size({'width': width, 'height': height})
                page.reload()
                page.wait_for_function('currentStatus && currentStatus.port')
                assert page.evaluate('currentStatus.server_running') is False
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.locator('[onclick="openNetworkSettings()"]').first.click()
                assert page.locator('[name="port"]').input_value() == str(server_port)
                page.screenshot(path=str(destination / f'mobile-{width}.png'), full_page=True)
                page.locator('#networkModal [data-i18n="btn_cancel"]').click()
            terminate_owned()
            launch()
            page.reload()
            page.wait_for_function('currentStatus && currentStatus.port')
            assert page.evaluate('currentStatus.port') == server_port
            assert page.evaluate('currentStatus.token') == 'clean-install-audit-password'
            assert page.evaluate('currentStatus.cors_allowed_origins') == ['http://localhost:*', 'http://127.0.0.1:*']
            reports.append('Full panel process restart: network/password persisted; mobile layouts 390/360')
            assert not errors, errors
            browser.close()
        clean_env = env.copy()
        clean_env.pop('PYTHONHOME', None)
        clean_env.pop('PYTHONPATH', None)
        subprocess.run([str(app / 'runtime/python.exe'), '-I', '-m', 'pip', 'check'], env=clean_env, check=True)
        result = json.dumps({'project': str(app), 'source_bootstrap': args.source_zip, 'passed': reports, 'page_errors': errors}, ensure_ascii=False, indent=2)
        (destination / 'acceptance.json').write_text(result, encoding='utf-8')
        print(result)
    finally:
        terminate_owned()


if __name__ == '__main__':
    main()
