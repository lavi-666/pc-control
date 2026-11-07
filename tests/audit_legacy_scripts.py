"""Exercise legacy BAT entry points only against a disposable extracted ZIP."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request


def main():
    project = Path(sys.argv[1]).resolve()
    workspace = Path(__file__).resolve().parent.parent
    if not project.is_relative_to(workspace / 'scratch') or project.name != 'PC_Control':
        raise ValueError('Only a disposable acceptance-test installation is allowed')
    env = os.environ.copy()
    env.update(PATH=os.environ['SystemRoot'] + r'\System32;' + os.environ['SystemRoot'],
               PYTHONHOME='nonexistent-python', PYTHONPATH='nonexistent-packages', PC_CONTROL_TEST_MODE='1')
    env.pop('PC_REMOTE_TOKEN', None)
    cmd = str(Path(os.environ['SystemRoot']) / 'System32/cmd.exe')
    def run(name, arguments=(), input_text=None):
        result = subprocess.run([cmd, '/d', '/c', name, *arguments], cwd=project, env=env,
                                input=input_text, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
        print(name, 'exit', result.returncode, result.stdout, result.stderr, flush=True)
        assert result.returncode == 0
    try:
        run('start_server.bat', ('--silent',))
        run('change_password.bat', ('legacy-audit-password',))
        config = json.loads((project / 'config.json').read_text(encoding='utf-8'))
        assert config['token'] == 'legacy-audit-password'
        with urllib.request.urlopen(f"http://127.0.0.1:{config['port']}/status", timeout=5) as response:
            assert json.load(response)['status'] == 'online'
        run(r'scripts\configure.bat', input_text='\n' * 5)
        assert json.loads((project / 'config.json').read_text(encoding='utf-8'))['port'] == config['port']
    finally:
        run('stop_server.bat', ('--silent',))
    print('Legacy BAT start/password/configure/stop passed without system Python')


if __name__ == '__main__':
    main()
