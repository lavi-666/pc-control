with open("server.py", "r", encoding="utf-8") as f:
    for idx, line in enumerate(f, 1):
        for keyword in ["shutdown", "reboot", "sleep", "lock", "taskkill", "ExitWindowsEx", "rundll32"]:
            if keyword in line and not line.strip().startswith("#"):
                print(f"{idx}: {line.strip()[:100]}")
