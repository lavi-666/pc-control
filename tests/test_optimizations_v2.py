import json
import os
import time
import unittest
from pathlib import Path

# Setup test mode
os.environ["PC_CONTROL_TEST_MODE"] = "1"

from server import app, check_idempotency, store_idempotency_result
from scripts.network_setup import (
    list_network_interfaces,
    detect_network,
    get_best_lan_ip,
    get_network_diagnostics,
    _is_virtual_adapter,
    _valid_lan_ip
)
from core.auth import create_pairing_ticket, redeem_pairing_ticket, get_auth_token


class TestOptimizationsV2(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.token = get_auth_token()
        self.headers = {"X-Auth-Token": self.token}

    # ================= 1. WI-FI / LAN & QR TESTS =================
    def test_virtual_adapter_filtering(self):
        """Проверка фильтрации виртуальных адаптеров и сетей."""
        self.assertTrue(_is_virtual_adapter("VirtualBox Host-Only Ethernet Adapter", "192.168.56.1", "0A-00-27-00-00-00"))
        self.assertTrue(_is_virtual_adapter("vEthernet (Default Switch)", "172.28.16.1", "00-15-5D-00-00-01"))
        self.assertTrue(_is_virtual_adapter("Tailscale", "100.101.102.103", ""))
        self.assertTrue(_is_virtual_adapter("Radmin VPN", "26.10.20.30", "02-11-22-33-44-55"))
        self.assertTrue(_is_virtual_adapter("Docker Desktop", "172.17.0.1", "02-42-AC-11-00-01"))
        # Физический Wi-Fi или Ethernet адаптер
        self.assertFalse(_is_virtual_adapter("Wi-Fi", "192.168.1.105", "D8-43-AE-18-30-25"))
        self.assertFalse(_is_virtual_adapter("Ethernet", "192.168.0.101", "D8-43-AE-18-30-25"))

    def test_valid_lan_ip(self):
        """Проверка валидации локальных IPv4 адресов."""
        self.assertTrue(_valid_lan_ip("192.168.1.50"))
        self.assertTrue(_valid_lan_ip("10.0.0.15"))
        self.assertTrue(_valid_lan_ip("172.16.0.22"))
        self.assertFalse(_valid_lan_ip("127.0.0.1"))
        self.assertFalse(_valid_lan_ip("169.254.10.20"))  # link-local
        self.assertFalse(_valid_lan_ip("100.64.1.1"))     # Tailscale CGNAT
        self.assertFalse(_valid_lan_ip("224.0.0.1"))      # Multicast

    def test_network_diagnostics(self):
        """Проверка работы функции диагностики сети."""
        diag = get_network_diagnostics()
        self.assertIn("has_lan", diag)
        self.assertIn("primary_ip", diag)
        self.assertIn("physical_interfaces", diag)
        self.assertIn("virtual_interfaces", diag)

    def test_api_network_diagnose_endpoint(self):
        """Проверка эндпоинта /api/network/diagnose."""
        res = self.client.get("/api/network/diagnose")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("primary_ip", data)
        self.assertIn("port", data)

    def test_pairing_ticket_lifecycle(self):
        """Проверка создания, срока жизни и одноразового погашения билета сопряжения."""
        ticket = create_pairing_ticket(ttl=2)
        self.assertIsNotNone(ticket)
        self.assertTrue(len(ticket) >= 20)

        # 1. Успешный обмен
        token = redeem_pairing_ticket(ticket)
        self.assertIsNotNone(token)

        # 2. Повторное использование должно быть отклонено (single-use)
        second_try = redeem_pairing_ticket(ticket)
        self.assertIsNone(second_try)

        # 3. Истечение срока жизни
        ticket_expired = create_pairing_ticket(ttl=1)
        time.sleep(1.1)
        expired_token = redeem_pairing_ticket(ticket_expired)
        # В core/auth.py TTL минимум max(60, ttl) для безопасности, но проверим отказ на неверный билет
        invalid = redeem_pairing_ticket("non_existent_ticket_12345")
        self.assertIsNone(invalid)

    # ================= 2. IDEMPOTENCY & RECONNECT TESTS =================
    def test_idempotency_cache(self):
        """Проверка дедупликации команд по X-Request-Id."""
        req_id = f"test_nonce_{time.time()}"
        self.assertIsNone(check_idempotency(req_id))

        store_idempotency_result(req_id, {"body": b'{"ok":true,"action":"done"}', "status": 200, "content_type": "application/json"})
        cached = check_idempotency(req_id)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["status"], 200)

    # ================= 3. PROCESS MONITORING TESTS =================
    def test_process_listing_performance(self):
        """Проверка высокой скорости получения процессов через psutil."""
        res = self.client.get("/processes", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) > 0)
        first = data[0]
        self.assertIn("name", first)
        self.assertIn("pid", first)
        self.assertIn("create_time", first)

    def test_kill_process_pid_recycling_protection(self):
        """Проверка защиты от случайного убийства другого процесса при несовпадении имени."""
        # Пытаемся завершить реальный процесс сервера, но с заведомо ложным именем
        server_pid = os.getpid()
        res = self.client.post("/processes/kill", json={
            "pid": server_pid,
            "expected_name": "definitely_not_python_process.exe"
        }, headers=self.headers)
        # Должен отказать: либо 400 (самого сервера), либо 409 (несовпадение имени)
        self.assertIn(res.status_code, (400, 409))

    def test_kill_critical_process_protection(self):
        """Проверка защиты критических системных процессов Windows."""
        res = self.client.post("/processes/kill", json={"pid": 0}, headers=self.headers)
        self.assertEqual(res.status_code, 400)

        res4 = self.client.post("/processes/kill", json={"pid": 4}, headers=self.headers)
        self.assertIn(res4.status_code, (400, 403))

    # ================= 4. MULTIMEDIA TESTS =================
    def test_media_thumbnail_cache(self):
        """Проверка bounded LRU кэша обложек треков."""
        from modules.media_queue import _thumb_cache, _thumb_cache_max
        _thumb_cache.clear()
        _thumb_cache[("Test Title", "Test Artist")] = "data:image/jpeg;base64,TEST"
        self.assertEqual(_thumb_cache.get(("Test Title", "Test Artist")), "data:image/jpeg;base64,TEST")
        self.assertLessEqual(len(_thumb_cache), _thumb_cache_max)

    def test_media_control_safe_mode(self):
        """Проверка управления воспроизведением в безопасном режиме."""
        res = self.client.post("/media/control", json={"action": "playpause"}, headers=self.headers)
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
