"""
PC Control — Automated Security Audit Suite.
Tests:
  1. CORS Origin validation (allowed localhost, LAN wildcards, rejected evil origins, OPTIONS 403)
  2. CORS Configuration API (/api/cors GET and POST)
  3. Token Rotation (/api/auth/rotate authenticated vs unauthenticated, old token invalidation)
  4. Token leakage prevention (GET / HTML does not leak token, no unauth cookie)
  5. X-Safe-Mode client header bypass disabled
  6. Path traversal rejection ('..')
  7. Null byte injection rejection ('\x00')
  8. Error message localization (ru, uk, en)
"""

import unittest
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from server import app
from core.config import get_auth_token, update_auth_token, get_cors_allowed_origins, update_cors_origins


class TestSecurityAudit(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.original_token = get_auth_token()
        self.original_cors = get_cors_allowed_origins()

    def tearDown(self):
        # Restore original token and CORS origins if modified
        if get_auth_token() != self.original_token:
            update_auth_token(self.original_token)
        update_cors_origins(self.original_cors)

    def test_cors_allowed_localhost(self):
        """Проверка, что разрешённый Origin (localhost:3000) получает Access-Control-Allow-Origin."""
        resp = self.client.get("/status", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://localhost:3000")
        self.assertEqual(resp.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_cors_options_preflight_allowed(self):
        """Проверка preflight OPTIONS запроса для разрешённого Origin."""
        resp = self.client.options("/status", headers={"Origin": "http://127.0.0.1:8080"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:8080")

    def test_cors_options_preflight_rejected(self):
        """Проверка, что неразрешённый Origin (evil-hacker.com) блокируется на preflight с 403."""
        resp = self.client.options("/status", headers={"Origin": "http://evil-hacker.com"})
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", resp.headers)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("message", data)

    def test_cors_get_rejected_origin_no_leak(self):
        """Проверка, что GET запрос с неразрешённым Origin не получает заголовок Access-Control-Allow-Origin."""
        resp = self.client.get("/status", headers={"Origin": "http://evil-attacker.ru"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://evil-attacker.ru")

    def test_cors_wildcard_lan_pattern(self):
        """Проверка гибкого матчинга по wildcard (например, http://192.168.*)."""
        update_cors_origins(["http://localhost:*", "http://192.168.*"])
        resp = self.client.options("/status", headers={"Origin": "http://192.168.1.55:3000"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://192.168.1.55:3000")

    def test_cors_api_endpoints(self):
        """Проверка эндпоинтов /api/cors (GET и POST)."""
        # 1. Без авторизации -> 401
        resp = self.client.get("/api/cors")
        self.assertEqual(resp.status_code, 401)

        # 2. С авторизацией -> 200
        token = get_auth_token()
        resp = self.client.get("/api/cors", headers={"X-Auth-Token": token})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("origins"), list)

        # 3. Обновление origins через POST
        new_origins = ["http://localhost:*", "http://192.168.*", "https://*.tailscale.net"]
        resp = self.client.post(
            "/api/cors",
            headers={"X-Auth-Token": token},
            json={"origins": new_origins}
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data.get("origins"), new_origins)

    def test_token_rotation_workflow(self):
        """Проверка безопасной ротации токена через /api/auth/rotate."""
        # 1. Попытка ротации без авторизации -> 401
        resp = self.client.post("/api/auth/rotate")
        self.assertEqual(resp.status_code, 401)

        old_token = get_auth_token()

        # 2. Успешная ротация авторизованным запросом
        resp = self.client.post("/api/auth/rotate", headers={"X-Auth-Token": old_token})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertTrue(data.get("ok"))
        new_token = data.get("token")
        self.assertTrue(bool(new_token))
        self.assertNotEqual(new_token, old_token)

        # 3. Проверяем, что старый токен больше не валиден
        resp = self.client.get("/api/auth/verify", headers={"X-Auth-Token": old_token})
        self.assertEqual(resp.status_code, 401)

        # 4. Проверяем, что новый токен валиден
        resp = self.client.get("/api/auth/verify", headers={"X-Auth-Token": new_token})
        self.assertEqual(resp.status_code, 200)

        # 5. Ротация обратно на старый токен для чистоты состояния
        resp = self.client.post(
            "/api/auth/rotate",
            headers={"X-Auth-Token": new_token},
            json={"new_token": old_token}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_auth_token(), old_token)

    def test_token_not_leaked_in_get_slash(self):
        """Проверка, что GET / отдаёт чистый HTML без утечки токена и без cookie."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("const DEFAULT_APP_TOKEN = '';", html)
        self.assertNotIn(f"const DEFAULT_APP_TOKEN = '{self.original_token}';", html)
        # Убеждаемся, что в Set-Cookie нет токена
        set_cookie = resp.headers.get("Set-Cookie", "")
        self.assertNotIn("pc_token=", set_cookie)

    def test_safe_mode_header_bypass_prevented(self):
        """Проверка, что заголовок X-Safe-Mode не позволяет обойти защиту авторизации."""
        resp = self.client.get(
            "/api/auth/verify",
            headers={"X-Auth-Token": "wrong_password_123", "X-Safe-Mode": "1"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_null_byte_protection(self):
        """Проверка отклонения запросов с null-байтом."""
        resp = self.client.get("/status?test=%00injection")
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("message", data)

    def test_path_traversal_protection(self):
        """Проверка отклонения запросов с path traversal ('..')."""
        resp = self.client.get("/api/..")
        self.assertEqual(resp.status_code, 404)

    def test_localization_headers(self):
        """Проверка локализации сообщений об ошибках по заголовку Accept-Language."""
        # 1. Русский
        resp = self.client.get("/api/auth/verify", headers={"Accept-Language": "ru-RU,ru;q=0.9"})
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data.get("message"), "Требуется авторизация")

        # 2. Украинский
        resp = self.client.get("/api/auth/verify", headers={"Accept-Language": "uk-UA,uk;q=0.9"})
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data.get("message"), "Потрібна авторизація")

        # 3. Английский
        resp = self.client.get("/api/auth/verify", headers={"Accept-Language": "en-US,en;q=0.9"})
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data.get("message"), "Authentication required")

    def test_pairing_ticket_lifecycle_and_single_use(self):
        """Проверка безопасности: одноразовый билет сопряжения обменивается на сессионную cookie и сгорает."""
        # 1. Получение билета сопряжения
        resp = self.client.get("/api/pair/ticket", headers={"X-Auth-Token": self.original_token})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertTrue(data.get("ok"))
        ticket = data.get("ticket")
        self.assertTrue(ticket and len(ticket) > 16)
        self.assertEqual(data.get("expires_in"), 300)

        # 2. Первое погашение билета клиентом (успешно)
        exchange_resp = self.client.post("/api/pair/exchange", json={"ticket": ticket})
        self.assertEqual(exchange_resp.status_code, 200)
        ex_data = json.loads(exchange_resp.data.decode("utf-8"))
        self.assertTrue(ex_data.get("ok"))
        self.assertEqual(ex_data.get("token"), self.original_token)

        # Проверяем установку защищённых cookies
        cookies = exchange_resp.headers.getlist("Set-Cookie")
        self.assertTrue(any("pc_token=" in c for c in cookies), "pc_token cookie must be set")
        self.assertTrue(any("token=" in c for c in cookies), "token cookie must be set")

        # 3. Повторная попытка использовать тот же билет (ОБЯЗАНА отклоняться — single-use protection)
        second_resp = self.client.post("/api/pair/exchange", json={"ticket": ticket})
        self.assertEqual(second_resp.status_code, 401, "Reusing single-use pairing ticket MUST be rejected with 401")

        # 4. Попытка обмена фиктивного билета
        invalid_resp = self.client.post("/api/pair/exchange", json={"ticket": "non_existent_fake_ticket_123"})
        self.assertEqual(invalid_resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
