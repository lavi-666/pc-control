"""Shared CLI entry point for legacy start/stop shortcuts."""
import argparse
from control_panel import start_server_process, stop_server_process, restart_server_process


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "restart"))
    args = parser.parse_args()
    operation = {"start": start_server_process, "stop": stop_server_process,
                 "restart": restart_server_process}[args.action]
    ok, code, title, details = operation()
    print(f"{title}: {details}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
