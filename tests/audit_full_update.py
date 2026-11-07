"""Real Windows updater acceptance: browser -> HTTP -> independent worker -> health.

Only release transport is replaced by a local fixture; all process/file operations
run against a disposable application with its own bundled Python and ports.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import full_update as update


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def identify(data):
    content = json.dumps({'files': data['files'], 'revision': data.get('revision', '')}, sort_keys=True, separators=(',', ':')).encode()
    data['build_id'] = hashlib.sha256(content).hexdigest()
    return data


def main():
    directory = ROOT / 'scratch' / ('full-update-' + time.strftime('%Y%m%d-%H%M%S'))
    directory.mkdir()
    package = directory / 'release-fixture.zip'
    shutil.copy2(ROOT / 'dist/PC_Control_Windows.zip', package)
    with zipfile.ZipFile(package) as archive:
        archive.extractall(directory)
        release_raw = archive.read('PC_Control/' + update.MANIFEST)
    base = directory / 'PC_Control'
    panel_port, server_port = free_port(), free_port()
    config = {'port': server_port, 'relay_port': 5050, 'token': 'update-audit-password', 'language': 'en', 'lan_ip': '127.0.0.1', 'vpn_ip': '', 'wol_relay_ip': '', 'mac_address': 'AA-BB-CC-DD-EE-FF'}
    (base / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    (base / 'launch_presets.json').write_text('[]\n', encoding='utf-8')
    (base / 'my-notes.txt').write_text('user file must survive', encoding='utf-8')
    old = json.loads(release_raw)
    obsolete = 'modules/update_obsolete_test.py'
    (base / obsolete).write_text('# obsolete\n', encoding='utf-8')
    old['files'][obsolete] = update.digest(base / obsolete)
    (base / 'web/control_panel.html').write_bytes((base / 'web/control_panel.html').read_bytes() + b'\n<!-- previous build -->')
    old['files']['web/control_panel.html'] = update.digest(base / 'web/control_panel.html')
    old['revision'] = 'previous-build'
    (base / update.MANIFEST).write_text(json.dumps(identify(old)), encoding='utf-8')
    env = os.environ.copy()
    env['PC_CONTROL_PANEL_PORT'] = str(panel_port)
    env['PC_CONTROL_TEST_MODE'] = '1'
    env.pop('PC_REMOTE_TOKEN', None)
    url = f'http://127.0.0.1:{panel_port}'
    helper = directory / 'fixture_host.py'
    helper.write_text('''import json, sys, zipfile, hashlib
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts import control_panel as panel, full_update as update
archive = Path(sys.argv[2])
with zipfile.ZipFile(archive) as z:
    raw = z.read('PC_Control/release-manifest.json')
update.remote_release = lambda: {'manifest': json.loads(raw), 'manifest_raw': raw, 'url': 'https://github.com/lavi-666/pc-control/releases/download/audit/PC_Control_Windows.zip', 'sha256': update.digest(archive), 'title': 'Audit release', 'date': '', 'tag': 'same-version'}
original_open = update.urllib.request.urlopen
def urlopen(request, *args, **kwargs):
    url = request.full_url if hasattr(request, 'full_url') else str(request)
    if url.endswith('/audit/PC_Control_Windows.zip'):
        return archive.open('rb')
    return original_open(request, *args, **kwargs)
update.urllib.request.urlopen = urlopen
original_prepare = update.prepare
def prepare(*args, **kwargs):
    kwargs['open_browser'] = False
    return original_prepare(*args, **kwargs)
update.prepare = prepare
sys.argv = ['control_panel.py', '--no-browser']
panel.main()
''', encoding='utf-8')
    results = []

    def start_host(archive):
        subprocess.Popen([str(base / 'runtime/python.exe'), '-E', '-s', str(helper), str(base), str(archive)], cwd=base, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=update.NO_WINDOW)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url + '/api/identity', timeout=1):
                    return
            except OSError:
                time.sleep(.2)
        raise AssertionError('Fixture panel did not start')

    def wait_result(expected):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            try:
                state = json.loads((base / 'logs/update_status.json').read_text(encoding='utf-8'))
                if state['phase'] in ('recovery_required', 'failed'):
                    raise AssertionError(state)
                if state['phase'] == expected and not (base / update.PENDING).exists():
                    with urllib.request.urlopen(f'http://127.0.0.1:{server_port}/status', timeout=2) as response:
                        assert json.load(response)['status'] == 'online'
                    return state
            except (OSError, ValueError):
                pass
            time.sleep(.5)
        raise AssertionError('Update completion timed out: ' + (base / 'logs/update_status.json').read_text())

    def assert_preserved(saved):
        for name, content in saved.items():
            assert (base / name).read_bytes() == content, name

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            start_host(package)
            page.goto(url)
            page.wait_for_function('currentStatus && currentStatus.port')
            page.locator('#btnToggleServer').click()
            page.wait_for_function('currentStatus.server_running && !lifecyclePending', timeout=60000)
            saved = {name: (base / name).read_bytes() for name in ('config.json', 'launch_presets.json', 'my-notes.txt')}
            with page.expect_response(lambda response: response.url.endswith('/api/action') and response.request.post_data_json.get('action') == 'check_updates', timeout=180000) as check_response:
                page.locator('[onclick="handleCheckUpdates(this)"]').click()
            check_result = check_response.value.json()
            assert check_result.get('has_update'), check_result
            page.locator('#updateBanner').wait_for(state='visible', timeout=180000)
            page.locator('#btnUpdateNow').click()
            result = wait_result('complete')
            assert_preserved(saved)
            assert not (base / obsolete).exists()
            assert (base / update.MANIFEST).read_bytes() == release_raw
            for name, checksum in json.loads(release_raw)['files'].items():
                assert update.digest(base / name) == checksum, name
            page.reload()
            page.wait_for_function('currentStatus && currentStatus.full_update_status && currentStatus.full_update_status.phase === "complete"')
            page.screenshot(path=str(directory / 'update-complete.png'), full_page=True)
            results.append({'case': 'complete update via launcher button; all hashes, removal, settings and running server preserved', 'state': result})
            update.stop_owned(base, os.getpid())

            # A correctly checksummed release that crashes must still roll back.
            bad = directory / 'bad-release.zip'
            invalid = b'raise RuntimeError("intentional acceptance-test startup failure")\n'
            bad_manifest = json.loads(release_raw)
            bad_manifest['files']['scripts/control_panel.py'] = hashlib.sha256(invalid).hexdigest()
            bad_manifest['revision'] = 'bad-startup-build'
            identify(bad_manifest)
            with zipfile.ZipFile(package) as original, zipfile.ZipFile(bad, 'w', compression=zipfile.ZIP_STORED) as archive:
                for name in original.namelist():
                    content = original.read(name)
                    if name == 'PC_Control/scripts/control_panel.py':
                        content = invalid
                    elif name == 'PC_Control/' + update.MANIFEST:
                        content = json.dumps(bad_manifest).encode()
                    archive.writestr(name, content)
            start_host(bad)
            page.reload()
            page.wait_for_function('currentStatus && currentStatus.port')
            page.locator('#btnToggleServer').click()
            page.wait_for_function('currentStatus.server_running && !lifecyclePending', timeout=60000)
            page.locator('[onclick="handleCheckUpdates(this)"]').click()
            page.locator('#updateBanner').wait_for(state='visible', timeout=180000)
            page.locator('#btnUpdateNow').click()
            result = wait_result('rolled_back')
            assert_preserved(saved)
            assert (base / update.MANIFEST).read_bytes() == release_raw
            results.append({'case': 'valid package with broken startup automatically rolled back', 'state': result})
            update.stop_owned(base, os.getpid())

            # Simulate interruption after a file replacement, then use real Launcher recovery.
            job = directory / ('.pccontrol-update-' + uuid.uuid4().hex)
            job.mkdir()
            shutil.copytree(base / 'runtime', job / 'runner', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copy2(ROOT / 'scripts/full_update.py', job / 'worker.py')
            (job / 'stage').mkdir()
            (job / 'stage/server.py').write_bytes(invalid)
            plan = {'base': str(base), 'port': panel_port, 'restart_server': True, 'open_browser': False,
                    'parent_pid': 999999999, 'parent_created': 0, 'files': ['server.py'], 'new_files': ['server.py'], 'had_old': ['server.py']}
            update.atomic_json(job / 'plan.json', plan)
            update.apply_files(base, job / 'stage', job / 'backup', plan)
            (job / 'applying').write_text('1')
            (base / update.PENDING).write_text(str(job), encoding='utf-8')
            update.status(base, 'applying', 'Simulated interrupted update')
            subprocess.Popen([str(base / 'Launcher.exe'), '--no-browser'], cwd=base, env=env)
            result = wait_result('rolled_back')
            assert update.digest(base / 'server.py') == json.loads(release_raw)['files']['server.py']
            assert_preserved(saved)
            results.append({'case': 'real Launcher.exe recovered interrupted file transaction', 'state': result})
            browser.close()
        (directory / 'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'directory': str(directory), 'results': results}, ensure_ascii=False, indent=2))
    finally:
        update.stop_owned(base, os.getpid())


if __name__ == '__main__':
    main()
