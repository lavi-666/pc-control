"""
tests/test_input_controller.py
Комплексное приёмочное тестирование и валидация модуля управления ПК (Input Controller):
1. Относительное и абсолютное перемещение мыши, сглаживание и акселерация.
2. Все типы кликов: левый, правый, средний, двойной, зажатие (down), отпускание (up), скролл.
3. Клавиатура: аппаратные VK коды, расширенные клавиши (EXTENDEDKEY: стрелки, Del, Win), Unicode UTF-16, горячие клавиши.
4. Сброс залипаний клавиш (release_all_inputs) со снятием флагов модификаторов.
5. Авторизация (401 без токена) и валидация некорректных данных (400 Bad Request).
6. Проверка статуса микрофона и безопасное отклонение при отсутствии VB-CABLE.
7. Мультимониторные координаты и виртуальное пространство Windows.
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
    EXTENDED_VKS,
)


class InputControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask("test_input_controller")
        cls.app.register_blueprint(input_bp)
        cls.token = get_auth_token()
        cls.client = cls.app.test_client()

    def test_direct_mouse_functions(self):
        # Относительное перемещение (малые и большие дистанции)
        self.assertTrue(mouse_move_relative(1, 1, sensitivity=1.0, accel=False))
        self.assertTrue(mouse_move_relative(35, -25, sensitivity=1.5, accel=True))
        # Абсолютное перемещение
        self.assertTrue(mouse_move_normalized(0.1, 0.9, monitor_idx=1))
        self.assertTrue(mouse_move_normalized(0.5, 0.5, monitor_idx=0))  # Все экраны
        # Клики и удержание
        self.assertTrue(mouse_button_event("left", is_down=True))
        self.assertTrue(mouse_button_event("left", is_down=False))
        self.assertTrue(mouse_button_event("right", is_down=True))
        self.assertTrue(mouse_button_event("right", is_down=False))
        self.assertTrue(mouse_click("left", double=False))
        self.assertTrue(mouse_click("left", double=True))
        self.assertTrue(mouse_click("right", double=False))
        self.assertTrue(mouse_click("middle", double=False))
        # Прокрутка колесом
        self.assertTrue(mouse_scroll(1))
        self.assertTrue(mouse_scroll(-3))

    def test_direct_keyboard_functions(self):
        # Обычная клавиша
        self.assertTrue(keyboard_key_event(0x20, is_down=True))
        self.assertTrue(keyboard_key_event(0x20, is_down=False))
        # Расширенная навигационная клавиша (Стрелка влево VK_LEFT = 0x25)
        self.assertIn(0x25, EXTENDED_VKS)
        self.assertTrue(keyboard_key_event(0x25, is_down=True))
        self.assertTrue(keyboard_key_event(0x25, is_down=False))
        # Клавиша Win (VK_LWIN = 0x5B)
        self.assertIn(0x5B, EXTENDED_VKS)
        self.assertTrue(keyboard_key_event(0x5B, is_down=True))
        self.assertTrue(keyboard_key_event(0x5B, is_down=False))
        # Unicode ввод (RU, UK, EN, спецсимволы и эмодзи)
        self.assertTrue(keyboard_text_unicode("Привет мир! Добрий день, Київ! Hello 123 🚀"))
        # Горячие комбинации
        self.assertTrue(keyboard_hotkey(["ctrl", "shift", "esc"]))
        self.assertTrue(keyboard_hotkey(["alt", "tab"]))
        # Сброс всех залипаний
        release_all_inputs()

    def test_api_auth_required(self):
        # Все эндпоинты ввода должны возвращать 401 при отсутствии токена
        res1 = self.client.post("/api/mouse", json={"action": "move_rel", "dx": 5, "dy": 5})
        self.assertEqual(res1.status_code, 401)

        res2 = self.client.post("/api/keyboard", json={"action": "text", "text": "test"})
        self.assertEqual(res2.status_code, 401)

        res3 = self.client.get("/api/mic/status")
        self.assertEqual(res3.status_code, 401)

        res4 = self.client.post("/api/mic/stream")
        self.assertEqual(res4.status_code, 401)

    def test_api_invalid_payloads(self):
        # Невалидный JSON / неизвестные действия должны возвращать ошибку
        res1 = self.client.post("/api/mouse", headers={"X-Auth-Token": self.token}, data="invalid_not_json")
        self.assertEqual(res1.status_code, 400)

        res2 = self.client.post("/api/keyboard", headers={"X-Auth-Token": self.token}, json={"action": "unknown_action_xyz"})
        self.assertEqual(res2.status_code, 400)

        res3 = self.client.post("/api/keyboard", headers={"X-Auth-Token": self.token}, json={"action": "hotkey", "keys": "not_a_list"})
        self.assertEqual(res3.status_code, 400)

    def test_api_mouse_endpoint(self):
        # Одиночное относительное перемещение
        res = self.client.post(
            "/api/mouse",
            headers={"X-Auth-Token": self.token},
            json={"action": "move_rel", "dx": 10, "dy": -8, "sensitivity": 1.2, "accel": True}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # Абсолютное перемещение
        res_abs = self.client.post(
            "/api/mouse",
            headers={"X-Auth-Token": self.token},
            json={"action": "move_norm", "x": 0.45, "y": 0.55, "monitor": 1}
        )
        self.assertEqual(res_abs.status_code, 200)
        self.assertTrue(res_abs.get_json()["ok"])

        # Пакетная отправка событий
        res_batch = self.client.post(
            "/api/mouse",
            headers={"X-Auth-Token": self.token},
            json={
                "events": [
                    {"action": "move_rel", "dx": 2, "dy": 3},
                    {"action": "down", "button": "left"},
                    {"action": "up", "button": "left"},
                    {"action": "scroll", "dy": 2},
                    {"action": "release_all"}
                ]
            }
        )
        self.assertEqual(res_batch.status_code, 200)
        self.assertEqual(res_batch.get_json()["processed"], 5)

    def test_api_keyboard_endpoint(self):
        # Ввод Unicode-текста
        res_text = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "text", "text": "PC Control Клавиатура"}
        )
        self.assertEqual(res_text.status_code, 200)
        self.assertTrue(res_text.get_json()["ok"])

        # Key down / Key up
        res_down = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "key_down", "key": "shift"}
        )
        self.assertEqual(res_down.status_code, 200)

        res_up = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "key_up", "key": "shift"}
        )
        self.assertEqual(res_up.status_code, 200)

        # Release all
        res_rel = self.client.post(
            "/api/keyboard",
            headers={"X-Auth-Token": self.token},
            json={"action": "release_all"}
        )
        self.assertEqual(res_rel.status_code, 200)

    def test_api_mic_status_and_safety(self):
        res = self.client.get(
            "/api/mic/status",
            headers={"X-Auth-Token": self.token}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("active", data)
        self.assertIn("virtual_cable_detected", data)
        self.assertIn("target_device", data)
        self.assertIn("instructions", data)

        # Проверка безопасности: при отсутствии VB-CABLE на ПК, стриминг отклоняется с кодом 400 и понятной ошибкой
        if not data.get("virtual_cable_detected"):
            res_stream = self.client.post(
                "/api/mic/stream",
                headers={"X-Auth-Token": self.token, "Content-Type": "application/octet-stream"},
                data=b"\x00" * 1024
            )
            self.assertEqual(res_stream.status_code, 400)
            self.assertIn("VB-CABLE", res_stream.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
