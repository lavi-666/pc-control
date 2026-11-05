"""Acceptance test: real Launcher.exe and bundled Python in a fresh extracted ZIP.

Run with an audit interpreter containing Playwright; it is only the browser driver.
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
    with zipfile.ZipFile(ROOT / 'dist/PC_Control_Windows.zip') as archive:
        members = [name for name in archive.namelist() if not (args.source_zip and name.startswith('PC_Control/runtime/'))]
        archive.extractall(destination, members=members)
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
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            page.wait_for_function('currentStatus && currentStatus.port', timeout=60000)
            assert page.evaluate('currentStatus.python_deps.installed')
            assert str(app / 'runtime/python.exe').lower() == page.evaluate('currentStatus.python_deps.interpreter').lower()
            page.locator('[onclick="openNetworkSettings()"]').first.click()
            page.locator('[name="port"]').fill(str(server_port))
            page.locator('[name="wol_relay_ip"]').fill('192.168.1.70')
            page.locator('#networkModal button[type="submit"]').click()
            page.locator('#networkModal').wait_for(state='hidden')
            page.locator('#btnChangePwd').click()
            page.locator('#pwdInput').fill('clean-install-audit-password')
            page.locator('#btnModalSave').click()
            page.locator('#pwdModal').wait_for(state='hidden')
            page.locator('#btnToggleServer').click()
            page.wait_for_function('currentStatus && currentStatus.server_running === true', timeout=60000)
            reports.append('Real Launcher.exe: private runtime, network/password UI save, server start')
            page.locator('[onclick="runAction(\'restart_server\', {}, this)"]').click()
            page.wait_for_timeout(5000)
            with urllib.request.urlopen(f'http://127.0.0.1:{server_port}/status', timeout=10) as response:
                assert json.load(response)['status'] == 'online'
            page.locator('#btnToggleServer').click()
            page.wait_for_function('currentStatus.server_running === false', timeout=60000)
            reports.append('Server restart, health, stop via actual UI')
            for width, height in ((390, 844), (360, 740)):
                page.set_viewport_size({'width': width, 'height': height})
                page.reload()
                page.wait_for_function('currentStatus && currentStatus.port')
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
