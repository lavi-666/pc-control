with open("server.py", "r", encoding="utf-8") as f:
    for idx, line in enumerate(f, 1):
        for ep in ["/volume", "/screen/volume", "/screen/config", "/app_volume", "/processes/kill", "/keyboard/set_language", "/api/wol", "/shutdown_timer"]:
            if ('@app.route("' + ep) in line:
                print(f"{idx}: {line.strip()}")
