"""Build a relocatable Windows runtime from a pinned, verified fresh distribution.

This runs on the release builder, never on the end user's first launch.
No installed Python packages or developer configuration are copied.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE = json.loads((BASE_DIR / 'runtime-source.json').read_text(encoding='utf-8'))
URL = SOURCE['url']
SHA256 = SOURCE['sha256']


def build():
    destination = BASE_DIR / 'runtime'
    if destination.exists():
        raise FileExistsError('runtime already exists; use a fresh build directory')
    scratch = BASE_DIR / 'scratch'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='runtime-build-', dir=scratch) as temp:
        staging = Path(temp)
        archive = staging / 'python.tar.gz'
        print('Downloading pinned Python 3.12.16 distribution...', flush=True)
        with urllib.request.urlopen(URL, timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise ValueError('Python distribution SHA-256 mismatch')
        with tarfile.open(archive) as tf:
            tf.extractall(staging, filter='data')
        python_dir = staging / 'python'
        executable = python_dir / 'python.exe'
        if not executable.is_file():
            raise FileNotFoundError('Python distribution has an unexpected layout')
        env = os.environ.copy()
        for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
            env.pop(key, None)
        env['PYTHONNOUSERSITE'] = '1'
        subprocess.run([str(executable), '-I', '-m', 'pip', 'install', '--no-cache-dir',
                        '--only-binary=:all:', '-r', str(BASE_DIR / 'requirements-runtime.lock')],
                       env=env, check=True)
        subprocess.run([str(executable), '-I', '-m', 'pip', 'check'], env=env, check=True)
        subprocess.run([str(executable), '-I', '-c',
                        'import flask, PIL, pycaw, comtypes, winsdk, aiortc, pyaudiowpatch, mss, qrcode, psutil, numpy; '
                        'from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager; '
                        'print("Runtime imports verified")'], env=env, check=True)
        manifest = {'python': '3.12.16', 'source': URL, 'source_sha256': SHA256,
                    'requirements_sha256': hashlib.sha256((BASE_DIR / 'requirements-runtime.lock').read_bytes()).hexdigest()}
        (python_dir / 'pccontrol-runtime.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        shutil.move(str(python_dir), destination)
    print(f'Portable runtime ready: {destination}', flush=True)


if __name__ == '__main__':
    build()
