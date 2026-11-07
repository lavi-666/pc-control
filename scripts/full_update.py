"""Full application updates. The worker runs from an independent private runtime."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

MANIFEST = 'release-manifest.json'
PACKAGE = 'PC_Control_Windows.zip'
PENDING = '.pccontrol-update.pending'
REPOSITORY = 'https://github.com/lavi-666/pc-control'
API = 'https://api.github.com/repos/lavi-666/pc-control/releases/latest'
DIRECTORIES = {'core', 'modules', 'scripts', 'web', 'tools', 'runtime', 'docs'}
ROOT_FILES = {'Launcher.exe', 'PC_Control.apk', 'pc_control.ico', 'server.py', 'open_app.pyw',
              'requirements.txt', 'requirements-runtime.lock', 'runtime-source.json', 'config.example.json',
              'README.md', 'README.ru.md', 'LICENSE', 'launcher.bat', 'start_server.bat',
              'stop_server.bat', 'change_password.bat', 'uninstall.bat', 'START_HERE.txt'}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_lock = threading.Lock()
_check_lock = threading.Lock()
_hash_cache = {}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def replace_file(source, target):
    for attempt in range(20):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.25)


def managed_name(name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        raise ValueError('Invalid update path')
    parts = PurePosixPath(name).parts
    if not parts or '/'.join(parts) != name or any(p in ('.', '..') or p.endswith((' ', '.')) for p in parts):
        raise ValueError('Unsafe update path: ' + name)
    if not (len(parts) == 1 and name in ROOT_FILES or len(parts) > 1 and parts[0] in DIRECTORIES):
        raise ValueError('Update cannot replace user data: ' + name)
    for part in parts:
        if part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
            raise ValueError('Reserved Windows name')
    return name


def validate_manifest(data):
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('files'), dict):
        raise ValueError('Unsupported release manifest')
    seen = set()
    for name, checksum in data['files'].items():
        managed_name(name)
        if name.lower() in seen or not isinstance(checksum, str) or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
            raise ValueError('Invalid or duplicate manifest entry')
        seen.add(name.lower())
    if not {'Launcher.exe', 'server.py', 'scripts/control_panel.py', 'runtime/python.exe', 'runtime/pythonw.exe'} <= data['files'].keys():
        raise ValueError('Incomplete full application release')
    material = json.dumps({'files': data['files'], 'revision': data.get('revision', '')}, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(material).hexdigest() != data.get('build_id'):
        raise ValueError('Invalid release build identifier')
    return data


def fetch(url, limit=4 * 1024 * 1024):
    request = urllib.request.Request(url, headers={'User-Agent': 'PC-Control-Full-Updater', 'Accept': 'application/json, text/plain, */*'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Update metadata exceeds size limit')
    return data


def release_url(url, filename):
    parsed = urllib.parse.urlsplit(url)
    prefix = '/lavi-666/pc-control/releases/download/'
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.startswith(prefix) or parsed.query or parsed.fragment:
        raise ValueError('Untrusted release asset URL')
    if parsed.path.rsplit('/', 1)[-1] != filename or len(parsed.path[len(prefix):].split('/')) != 2:
        raise ValueError('Unexpected release asset')
    return url


def remote_release():
    release = json.loads(fetch(API))
    assets = {item['name']: item['browser_download_url'] for item in release.get('assets', [])}
    required = (MANIFEST, PACKAGE, 'SHA256SUMS.txt')
    if not all(name in assets for name in required):
        raise ValueError('В релизе ещё нет полного пакета обновления и манифеста. Нужна публикация нового полного релиза.')
    urls = {name: release_url(assets[name], name) for name in required}
    if len({url.rsplit('/', 1)[0] for url in urls.values()}) != 1:
        raise ValueError('Release assets belong to different versions')
    checksums = {}
    for line in fetch(urls['SHA256SUMS.txt']).decode('utf-8-sig').splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            checksums[parts[1].lstrip('*').replace('\\', '/')] = parts[0].lower()
    raw = fetch(urls[MANIFEST])
    if hashlib.sha256(raw).hexdigest() != checksums.get(MANIFEST):
        raise ValueError('Release manifest SHA-256 mismatch')
    expected = checksums.get(PACKAGE, '')
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('Full package checksum is missing')
    return {'manifest': validate_manifest(json.loads(raw)), 'manifest_raw': raw,
            'url': urls[PACKAGE], 'sha256': expected, 'tag': release.get('tag_name', ''),
            'title': release.get('name', ''), 'date': release.get('published_at', '')}


def compare(base, manifest, use_cache=True):
    base = Path(base)
    old = {}
    if (base / MANIFEST).is_file():
        old = validate_manifest(json.loads((base / MANIFEST).read_text(encoding='utf-8')))
    changed = []
    for name, checksum in manifest['files'].items():
        path = base / name
        if not path.is_file():
            changed.append(name)
            continue
        info = path.stat()
        key = (str(path.resolve()), info.st_mtime_ns, info.st_ctime_ns, info.st_size)
        actual = _hash_cache.get(key) if use_cache else None
        if actual is None:
            actual = digest(path)
            _hash_cache[key] = actual
        if actual != checksum:
            changed.append(name)
    removed = sorted(set(old.get('files', {})) - set(manifest['files']))
    return changed, removed, old


def check(base):
    with _check_lock:
        return _check(base)


def _check(base):
    try:
        remote = remote_release()
        changed, removed, old = compare(base, remote['manifest'])
        different = bool(changed or removed or old.get('build_id') != remote['manifest']['build_id'])
        return {'ok': True, 'has_update': different, 'changed_count': len(changed), 'removed_count': len(removed),
                'changed_files': changed[:100], 'removed_files': removed[:100],
                'current_version': old.get('revision', 'local')[:12], 'current_commit': old.get('build_id', 'local')[:12],
                'latest_commit': remote['manifest']['build_id'][:12], 'commit_message': remote['title'],
                'commit_date': remote['date'], 'release_url': REPOSITORY + '/releases/latest',
                'message': f'Изменено файлов: {len(changed)}, удалено: {len(removed)}. Настройки будут сохранены.' if different else 'Все файлы проекта соответствуют опубликованной сборке.'}
    except Exception as error:
        return {'ok': False, 'has_update': False, 'error_code': 'ERR_FULL_UPDATE_CHECK', 'message': str(error)}


def status(base, phase, message, **extra):
    atomic_json(Path(base) / 'logs/update_status.json', {'phase': phase, 'message': message, 'time': time.time(), **extra})


def extract_package(archive, stage, manifest, raw_manifest):
    stage = Path(stage)
    stage.mkdir()
    expected = set(manifest['files']) | {MANIFEST, 'launch_presets.json'}
    seen = set()
    with zipfile.ZipFile(archive) as zf:
        expanded_size = sum(info.file_size for info in zf.infolist())
        if expanded_size > 4 * 1024**3:
            raise ValueError('Extracted package is too large')
        if shutil.disk_usage(stage.parent).free < expanded_size * 3:
            raise ValueError('Недостаточно места для распаковки и резервной копии обновления')
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith('PC_Control/'):
                raise ValueError('Unexpected archive root')
            name = info.filename[len('PC_Control/'):]
            if name not in expected or name.lower() in seen or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unexpected, duplicate or linked archive entry: ' + name)
            seen.add(name.lower())
            if name == 'launch_presets.json':
                continue  # Existing user presets are never replaced by release defaults.
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
        if not (set(manifest['files']) | {MANIFEST}) <= {i.filename[len('PC_Control/'):] for i in zf.infolist()}:
            raise ValueError('Missing files in release ZIP')
    if (stage / MANIFEST).read_bytes() != raw_manifest:
        raise ValueError('ZIP manifest does not match the verified release')
    for name, checksum in manifest['files'].items():
        if digest(stage / name) != checksum:
            raise ValueError('File checksum mismatch: ' + name)


def prune_finished_jobs(base):
    """Retain one prior completed update; never touch another installation's jobs."""
    import psutil
    completed = []
    for candidate in base.parent.glob('.pccontrol-update-*'):
        if candidate.is_symlink() or candidate.resolve().parent != base.parent or not candidate.is_dir():
            continue
        try:
            finished = json.loads((candidate / 'finished.json').read_text(encoding='utf-8'))
            if Path(finished['base']).resolve() == base and not psutil.pid_exists(finished['pid']):
                completed.append((finished['time'], candidate))
        except (OSError, ValueError, KeyError):
            continue
    for _, candidate in sorted(completed, reverse=True)[1:]:
        if candidate.resolve().parent != base.parent or not candidate.name.startswith('.pccontrol-update-'):
            raise ValueError('Invalid completed update workspace')
        shutil.rmtree(candidate)


def prepare(base, port, restart_server=False, log=lambda message: None, open_browser=True):
    base = Path(base).resolve()
    if not _lock.acquire(False):
        return {'ok': False, 'message': 'Обновление уже выполняется.'}
    job = None
    try:
        if (base / PENDING).exists():
            raise RuntimeError('Предыдущее обновление не завершено. Запустите Launcher.exe для восстановления.')
        prune_finished_jobs(base)
        remote = remote_release()
        changed, removed, old = compare(base, remote['manifest'], use_cache=False)
        if not changed and not removed and old.get('build_id') == remote['manifest']['build_id']:
            return {'ok': True, 'restarting': False, 'message': 'Все файлы уже актуальны.'}
        if shutil.disk_usage(base.parent).free < 3 * 1024**3:
            raise RuntimeError('Для безопасного обновления нужно не менее 3 ГБ свободного места.')
        job = base.parent / ('.pccontrol-update-' + uuid.uuid4().hex)
        job.mkdir()
        status(base, 'downloading', 'Загрузка полного пакета проекта...')
        archive = job / PACKAGE
        request = urllib.request.Request(remote['url'], headers={'User-Agent': 'PC-Control-Full-Updater'})
        total = 0
        with urllib.request.urlopen(request, timeout=60) as response, archive.open('wb') as output:
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 1024**3:
                    raise ValueError('Package exceeds 1 GB')
                output.write(block)
                if total % (8 * 1024 * 1024) == 0:
                    status(base, 'downloading', f'Загружено {total // 1024**2} МБ')
        if digest(archive) != remote['sha256']:
            raise ValueError('Full package SHA-256 mismatch')
        status(base, 'verifying', 'Проверка файлов и подготовка резервной копии...')
        extract_package(archive, job / 'stage', remote['manifest'], remote['manifest_raw'])
        shutil.copytree(base / 'runtime', job / 'runner', ignore=shutil.ignore_patterns('__pycache__'))
        subprocess.run([str(job / 'runner/python.exe'), '-I', '-c', 'import psutil'], check=True, timeout=30, creationflags=NO_WINDOW)
        shutil.copy2(__file__, job / 'worker.py')
        plan = {'base': str(base), 'port': port, 'restart_server': restart_server, 'open_browser': open_browser,
                'parent_pid': os.getpid(), 'parent_created': __import__('psutil').Process().create_time(),
                'files': sorted(set(changed) | set(removed) | {MANIFEST}),
                'new_files': changed + [MANIFEST],
                'had_old': [name for name in set(changed) | set(removed) | {MANIFEST} if (base / name).exists()]}
        atomic_json(job / 'plan.json', plan)
        pointer = base / (PENDING + '.tmp')
        with pointer.open('w', encoding='utf-8') as stream:
            stream.write(str(job))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pointer, base / PENDING)
        command = [str(job / 'runner/python.exe'), '-I', str(job / 'worker.py'), '--job', str(job)]
        subprocess.Popen(command, cwd=job, creationflags=NO_WINDOW)
        log('Полный пакет проверен. Выполняется обновление проекта; пользовательские данные сохраняются.')
        return {'ok': True, 'restarting': True, 'message': 'Пакет проверен. Выполняется установка и проверка запуска; при ошибке будет откат.'}
    except Exception as error:
        status(base, 'failed', str(error))
        if job is not None and not (base / PENDING).exists() and job.parent == base.parent and job.name.startswith('.pccontrol-update-'):
            shutil.rmtree(job, ignore_errors=True)
        return {'ok': False, 'error_code': 'ERR_FULL_UPDATE', 'message': str(error)}
    finally:
        _lock.release()


def safe_target(base, name, checked_dirs=None):
    if name != MANIFEST:
        managed_name(name)
    path = base / name
    checked_dirs = set() if checked_dirs is None else checked_dirs
    for part in [path, *path.parents]:
        if part == base:
            break
        if part != path and part in checked_dirs:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Linked update target is not allowed: ' + name)
        if part != path:
            checked_dirs.add(part)
    return path


def apply_files(base, stage, backup, plan):
    """Journal is persisted before mutation; backups remain until health succeeds."""
    base = base.resolve()
    checked_dirs = set()
    for name in plan['files']:
        safe_target(base, name, checked_dirs)
    backup.mkdir(exist_ok=True)
    for name in plan['files']:
        target = safe_target(base, name, checked_dirs)
        saved = backup / name
        if target.exists():
            if not target.is_file():
                raise ValueError('Expected a file: ' + name)
            saved.parent.mkdir(parents=True, exist_ok=True)
            replace_file(target, saved)
        if name in plan['new_files']:
            target.parent.mkdir(parents=True, exist_ok=True)
            replace_file(stage / name, target)


def rollback(base, backup, plan):
    base = base.resolve()
    checked_dirs = set()
    for name in reversed(plan['files']):
        target = safe_target(base, name, checked_dirs)
        saved = backup / name
        if saved.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            replace_file(saved, target)
        elif name not in plan['had_old']:
            target.unlink(missing_ok=True)


def stop_owned(base, excluded_pid):
    import psutil
    for process in psutil.process_iter(['pid', 'exe', 'cmdline']):
        if process.pid == excluded_pid:
            continue
        owned = False
        try:
            exe = process.info['exe']
            command = process.info['cmdline'] or []
            owned = bool(exe and Path(exe).resolve().is_relative_to(base))
            if not owned and exe and Path(exe).name.lower().startswith('python'):
                cwd = Path(process.cwd())
                scripts = {base / 'server.py', base / 'scripts/watchdog.pyw', base / 'scripts/control_panel.py'}
                owned = any((cwd / arg).resolve() in scripts for arg in command[1:] if not arg.startswith('-'))
            if owned:
                process.terminate()
                process.wait(timeout=15)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            if owned:
                raise


def launch_and_verify(base, plan):
    env = os.environ.copy()
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    env['PC_CONTROL_PANEL_PORT'] = str(plan['port'])
    subprocess.run([str(base / 'Launcher.exe'), '--update-self-test'], cwd=base, env=env,
                   timeout=30, check=True, creationflags=NO_WINDOW)
    process = subprocess.Popen([str(base / 'runtime/pythonw.exe'), '-E', '-s', str(base / 'scripts/control_panel.py'), '--no-browser'], cwd=base, env=env, creationflags=NO_WINDOW)
    identity = hashlib.sha256(str(base).lower().rstrip('\\/').encode()).hexdigest()
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Updated control panel exited during startup')
        try:
            data = json.loads(fetch(f"http://127.0.0.1:{plan['port']}/api/identity"))
            if data.get('instance') == identity:
                break
        except Exception:
            time.sleep(.3)
    else:
        raise RuntimeError('Updated panel did not confirm health')
    subprocess.run([str(base / 'runtime/python.exe'), '-I', '-c', 'import flask, PIL, psutil, aiortc, winsdk.windows.media.control'], cwd=base, timeout=45, check=True, creationflags=NO_WINDOW)
    if plan['restart_server']:
        request = urllib.request.Request(f"http://127.0.0.1:{plan['port']}/api/action", data=b'{"action":"start_server"}', headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=90) as response:
            if not json.load(response).get('ok'):
                raise RuntimeError('Updated server failed to start')


def worker(job, recover=False):
    job = Path(job).resolve()
    plan = json.loads((job / 'plan.json').read_text(encoding='utf-8'))
    base = Path(plan['base']).resolve()
    if job.parent != base.parent or not job.name.startswith('.pccontrol-update-') or job == base:
        raise ValueError('Invalid update workspace')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, 'Local\\PCControlFullUpdate_' + hashlib.sha256(str(base).lower().encode()).hexdigest())
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
        return
    try:
        import psutil
        try:
            parent = psutil.Process(plan['parent_pid'])
            if parent.create_time() == plan['parent_created']:
                try:
                    parent.wait(timeout=20)
                except psutil.TimeoutExpired:
                    raise RuntimeError('Launcher did not release the update operation')
        except psutil.NoSuchProcess:
            pass
        (base / 'logs').mkdir(exist_ok=True)
        (base / 'logs/manual_stop.flag').write_text('update', encoding='ascii')
        stop_owned(base, os.getpid())
        backup = job / 'backup'
        if recover:
            if (job / 'applying').exists():
                rollback(base, backup, plan)
            status(base, 'rolled_back', 'Прерванное обновление отменено. Предыдущая версия восстановлена.')
        else:
            try:
                (job / 'applying').write_text('1', encoding='ascii')
                status(base, 'applying', 'Установка файлов проекта...')
                apply_files(base, job / 'stage', backup, plan)
                status(base, 'testing', 'Проверка обновлённого приложения...')
                launch_and_verify(base, plan)
                status(base, 'complete', 'Проект полностью обновлён. Запуск проверен; настройки сохранены.')
            except Exception as error:
                stop_owned(base, os.getpid())
                rollback(base, backup, plan)
                status(base, 'rolled_back', 'Обновление отменено, восстановлена предыдущая версия: ' + str(error))
        if recover or json.loads((base / 'logs/update_status.json').read_text(encoding='utf-8'))['phase'] == 'rolled_back':
            launch_and_verify(base, plan)
        (base / PENDING).unlink(missing_ok=True)
        env = os.environ.copy()
        env['PC_CONTROL_PANEL_PORT'] = str(plan['port'])
        subprocess.Popen([str(base / 'Launcher.exe')] + ([] if plan.get('open_browser', True) else ['--no-browser']), cwd=base, env=env, creationflags=NO_WINDOW)
        atomic_json(job / 'finished.json', {'base': str(base), 'time': time.time(), 'pid': os.getpid()})
    except Exception as error:
        status(base, 'recovery_required', 'Нужен повторный запуск Launcher.exe для восстановления: ' + str(error))
        raise
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    worker(args.job, args.recover)
