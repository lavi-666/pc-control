"""
tests/test_input_controller.py
Тестирование модуля ввода и контроллера мыши, клавиатуры и микрофона PC Control:
1. Относительное и абсолютное перемещение мыши.
2. Клики, двойные клики, правые клики и прокрутка колеса.
3. Отправка клавиш, Unicode текста (RU/UK/EN) и комбинаций hotkey.
4. Сброс залипших клавиш (release_all).
5. HTTP эндпоинты /api/mouse, /api/keyboard, /api/mic/status.
"""

import unittest
from flask import Flask
from core.config import get_auth_token
from modules.input_controller import (
    input_bp,
    mouse_move_relative,
    mouse_move_normalized,
    mouse_click,
    mouse_button_event,
    mouse_scroll,
    keyboard_key_event,
    keyboard_text_unicode,
    keyboard_hotkey,
    release_all_inputs,
)


class InputControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask("test_input_controller")
        cls.app.register_blueprint(input_bp)
        cls.token = get_auth_token()
        cls.client = cls.app.test_client()

    def test_direct_mouse_functions(self):
        # Относительное перемещение
        self.assertTrue(mouse_move_relative(5, -5, sensitivity=1.2, accel=True))
        # Абсолютное перемещение
        self.assertTrue(mouse_move_normalized(0.5, 0.5, monitor_idx=1))
        # Клики и удержание
        self.assertTrue(mouse_button_event("left", is_down=True))
        self.assertTrue(mouse_button_event("left", is_down=False))
        self.assertTrue(mouse_click("left", double=False))
        self.assertTrue(mouse_click("left", double=True))
        self.assertTrue(mouse_click("right", double=False))
        # Прокрутка
        self.assertTrue(mouse_scroll(2))
        self.assertTrue(mouse_scroll(-2))

    def test_direct_keyboard_functions(self):
        # Нажатие и отпускание клавиши (например, VK_SPACE = 0x20)
        self.assertTrue(keyboard_key_event(0x20, is_down=True))
        self.assertTrue(keyboard_key_event(0x20, is_down=False))
        # Unicode ввод (русский, украинский, английский, спецсимволы)
        self.assertTrue(keyboard_text_unicode("Привет, Світ! PC Control 2026 @#$"))
        # Горячие клавиши
        self.assertTrue(keyboard_hotkey(["ctrl", "c"]))
        # Сброс залипаний
        release_all_inputs()

    def test_api_mouse_endpoint(self):
        # Одиночное перемещение
        res = self.client.post(
            "/api/mouse",
            headers={"X-Auth-Token": self.token},
            json={"action": "move_rel", "dx": 10, "dy": -8, "sensitivity": 1.0}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # Пакетная обработка событий для низкой задержки
        res_batch = self.client.post(
            "/api/mouse",
            headers={"X-Auth-Token": self.token},
            json={
                "events": [
                    {"action": "move_rel", "dx": 2, "dy": 3},
                    {"action": "click", "button": "left"},
                    {"action": "scroll", "dy": 1}
                ]
            }
        )
        self.assertEqual(res_batch.status_code, 200)
        self.assertEqual(res_batch.get_json()["processed"], 3)

    def test_api_keyboard_endpoint(self):
        # Ввод текста
        res = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "text", "text": "Тестовый ввод"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # Нажатие клавиши
        res_key = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "key_press", "key": "enter"}
        )
        self.assertEqual(res_key.status_code, 200)
        self.assertTrue(res_key.get_json()["ok"])

        # Hotkey
        res_hotkey = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "hotkey", "keys": ["ctrl", "a"]}
        )
        self.assertEqual(res_hotkey.status_code, 200)
        self.assertTrue(res_hotkey.get_json()["ok"])

    def test_api_mic_status(self):
        res = self.client.get(
            "/api/mic/status",
            headers={"X-Auth-Token": self.token}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("active", data)
        self.assertIn("target_device", data)


if __name__ == "__main__":
    unittest.main()
