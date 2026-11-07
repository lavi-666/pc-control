"""Shared CLI entry point for legacy start/stop shortcuts."""
import argparse
from pathlib import Path
from control_panel import BASE_DIR, start_server_process, stop_server_process, restart_server_process, clean_browser_profiles


def stop_owned_helpers():
    """Terminate only helpers whose executable/script belongs to this copy."""
    import psutil
    failures = []
    owned_executables = {(BASE_DIR / 'Launcher.exe').resolve(), (BASE_DIR / 'tools/streamer.exe').resolve()}
    panel_script = (BASE_DIR / 'scripts/control_panel.py').resolve()
    for process in psutil.process_iter(['pid', 'exe', 'cmdline']):
        try:
            executable = process.info.get('exe')
            command = process.info.get('cmdline') or []
            owned = bool(executable and Path(executable).resolve() in owned_executables)
            if not owned and executable and Path(executable).name.lower().startswith('python'):
                cwd = Path(process.cwd())
                owned = any((cwd / argument).resolve() == panel_script for argument in command[1:] if not argument.startswith('-'))
            if owned:
                process.terminate()
                process.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        except (psutil.AccessDenied, psutil.TimeoutExpired) as error:
            failures.append(str(error))
    return not failures, '', 'Helpers', '\n'.join(failures) or 'Stopped helpers belonging to this installation'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "restart", "stop-all", "clean-profiles"))
    args = parser.parse_args()
    if args.action == 'clean-profiles':
        result = clean_browser_profiles()
        print(result['message'])
        return 0 if result['ok'] else 1
    if args.action == 'stop-all':
        result = stop_server_process()
        if not result[0]:
            print(result[3])
            return 1
        operation = stop_owned_helpers
    else:
        operation = {"start": start_server_process, "stop": stop_server_process,
                     "restart": restart_server_process}[args.action]
    ok, code, title, details = operation()
    print(f"{title}: {details}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
