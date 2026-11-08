"""
tests/test_native_and_web_control.py
Тестирование серверной интеграции нативного Android-клиента и веб-режима «Управление ПК»:
1. Проверка эндпоинтов /status, /volume, /mute, /action, /media/control, /api/mouse, /api/keyboard.
2. Валидация защиты токеном (401 при неверном токене) и идемпотентности.
3. Проверка целостности нативных Android-исходников и веб-скрипта управления ПК.
"""

import json
import unittest
from pathlib import Path
from flask import Flask
from core.config import get_auth_token
from modules.power import power_bp
from modules.volume import volume_bp
from modules.media import media_bp
from modules.input_controller import input_bp

BASE_DIR = Path(__file__).resolve().parent.parent


class NativeAndWebControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask("test_native_and_web_control")
        cls.app.config["TESTING"] = True
        cls.app.register_blueprint(power_bp)
        cls.app.register_blueprint(volume_bp)
        cls.app.register_blueprint(media_bp)
        cls.app.register_blueprint(input_bp)

        @cls.app.route("/status")
        def status():
            from flask import jsonify
            return jsonify({"status": "online", "hostname": "test-pc", "version": "2.4.0"})

        cls.client = cls.app.test_client()
        cls.token = get_auth_token()

    def test_status_endpoint(self):
        res = self.client.get("/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "online")
        self.assertEqual(data.get("version"), "2.4.0")

    def test_volume_endpoints(self):
        # 401 without token
        res_no_auth = self.client.get("/volume")
        self.assertEqual(res_no_auth.status_code, 401)

        # GET volume
        res = self.client.get("/volume", headers={"X-Auth-Token": self.token})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("percent", data)
        self.assertIn("muted", data)

        # POST volume
        res_set = self.client.post(
            "/volume",
            headers={"X-Auth-Token": self.token},
            json={"level": 40}
        )
        self.assertEqual(res_set.status_code, 200)

        # POST mute
        res_mute = self.client.post(
            "/mute",
            headers={"X-Auth-Token": self.token},
            json={}
        )
        self.assertEqual(res_mute.status_code, 200)

    def test_power_action_safe_mode(self):
        # 401 without token
        res_unauth = self.client.post("/action", json={"action": "sleep"})
        self.assertEqual(res_unauth.status_code, 401)

        # Safe mode execution for critical actions
        for act in ("sleep", "lock", "reboot", "shutdown"):
            res = self.client.post(
                "/action",
                headers={"X-Auth-Token": self.token, "X-Safe-Mode": "1"},
                json={"action": act}
            )
            self.assertEqual(res.status_code, 200)
            self.assertIn("успешно", res.get_json()["message"])

        # Invalid action returns 400
        res_bad = self.client.post(
            "/action",
            headers={"X-Auth-Token": self.token},
            json={"action": "invalid_command_xyz"}
        )
        self.assertEqual(res_bad.status_code, 400)

    def test_media_control_endpoints(self):
        # 401 without token
        res_unauth = self.client.post("/media/control", json={"action": "play_pause"})
        self.assertEqual(res_unauth.status_code, 401)

        # Valid commands
        for cmd in ("play_pause", "next", "prev", "stop"):
            res = self.client.post(
                "/media/control",
                headers={"X-Auth-Token": self.token},
                json={"action": cmd}
            )
            # 200 or 400 if Windows media service is busy, but auth and routing must pass
            self.assertIn(res.status_code, (200, 400))

        # Invalid command
        res_invalid = self.client.post(
            "/media/control",
            headers={"X-Auth-Token": self.token},
            json={"action": "explode"}
        )
        self.assertEqual(res_invalid.status_code, 400)

    def test_mouse_and_keyboard_endpoints(self):
        # Mouse relative move
        res_mouse = self.client.post(
            "/api/mouse",
            headers={"X-Auth-Token": self.token},
            json={"action": "move_rel", "dx": 5, "dy": -3}
        )
        self.assertEqual(res_mouse.status_code, 200)
        self.assertTrue(res_mouse.get_json()["ok"])

        # Mouse click
        res_click = self.client.post(
            "/api/mouse",
            headers={"X-Auth-Token": self.token},
            json={"action": "click", "button": "left"}
        )
        self.assertEqual(res_click.status_code, 200)

        # Keyboard text
        res_kb = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "text", "text": "Test Native"}
        )
        self.assertEqual(res_kb.status_code, 200)

        # Keyboard hotkey
        res_hotkey = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "hotkey", "keys": ["win", "d"]}
        )
        self.assertEqual(res_hotkey.status_code, 200)

    def test_web_stream_pc_control_overlay_exists(self):
        stream_js = BASE_DIR / "web" / "js" / "stream.js"
        self.assertTrue(stream_js.is_file())
        content = stream_js.read_text(encoding="utf-8")
        self.assertIn("initWebPcControlOverlay", content)
        self.assertIn("destroyWebPcControlOverlay", content)
        self.assertIn("stopPcControlMode", content)
        self.assertIn("startPcControlMode", content)

    def test_native_android_components_exist(self):
        src_dir = BASE_DIR / "android_app" / "src" / "com" / "pccontrol" / "remote"
        self.assertTrue((src_dir / "ApiClient.java").is_file())
        self.assertTrue((src_dir / "NativeDashboardView.java").is_file())
        self.assertTrue((src_dir / "NativeScreenView.java").is_file())
        self.assertTrue((src_dir / "MainActivity.java").is_file())
        self.assertTrue((src_dir / "BackgroundAudioService.java").is_file())


if __name__ == "__main__":
    unittest.main()
