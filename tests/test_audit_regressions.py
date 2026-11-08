"""
tests/test_audit_regressions.py
Регрессии, найденные при аудите (отчёт 14):
1. /processes/kill падал с 500 (в modules/system.py не было `import psutil`).
2. /api/pair/ticket выдавал билет без пароля любому адресу локальной сети, а билет меняется
   на сам пароль — полный доступ к ПК без пароля.
3. Пароль из ?token=… попадал открытым текстом в журнал запросов werkzeug.
4. Общий экземпляр PortAudio: /audio больше не создаёт и не уничтожает PortAudio на запрос.
"""

import logging
import os
import unittest
from unittest import mock

from core.config import get_auth_token


class AuditRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_env = {k: os.environ.pop(k) for k in ("PC_CONTROL_TEST_MODE", "SAFE_TEST_MODE") if k in os.environ}
        import server
        cls.server = server
        cls.client = server.app.test_client()
        cls.token = get_auth_token()

    @classmethod
    def tearDownClass(cls):
        os.environ.update(cls._saved_env)

    def test_kill_nonexistent_pid_is_not_500(self):
        r = self.client.post("/processes/kill", json={"pid": 999991},
                             headers={"X-Auth-Token": self.token, "X-Safe-Mode": "1"})
        self.assertNotEqual(r.status_code, 500, r.get_data(as_text=True))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

    def test_processes_list_uses_psutil(self):
        r = self.client.get("/processes", headers={"X-Auth-Token": self.token})
        self.assertEqual(r.status_code, 200)
        procs = r.get_json()
        self.assertTrue(procs)
        # create_time есть только в пути psutil (резервный tasklist даёт 0.0)
        self.assertTrue(any(p.get("create_time", 0) > 0 for p in procs))

    def test_pair_ticket_requires_password_even_from_lan(self):
        r = self.client.get("/api/pair/ticket", environ_base={"REMOTE_ADDR": "192.168.0.50"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/pair/ticket", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/pair/ticket", headers={"X-Auth-Token": self.token},
                            environ_base={"REMOTE_ADDR": "192.168.0.50"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ticket"])

    def test_access_log_redacts_token(self):
        flt = self.server._RedactSecretsFilter()
        rec = logging.LogRecord("werkzeug", logging.INFO, __file__, 1,
                                '%s - - [x] "%s" %s -', ("1.2.3.4", "GET /audio?token=SECRET123&t=5 HTTP/1.1", "200"), None)
        self.assertTrue(flt.filter(rec))
        msg = rec.getMessage()
        self.assertNotIn("SECRET123", msg)
        self.assertIn("token=***&t=5", msg)
        rec2 = logging.LogRecord("werkzeug", logging.INFO, __file__, 1, "GET /?ticket=abc-DEF_1 HTTP/1.1", (), None)
        flt.filter(rec2)
        self.assertNotIn("abc-DEF_1", rec2.getMessage())

    def test_action_log_is_rotated(self):
        import tempfile
        from pathlib import Path
        import core.logger as lg
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "actions.jsonl"
            with mock.patch.object(lg, "LOG_FILE", p), mock.patch.object(lg, "_ACTIONS_MAX_BYTES", 20_000):
                for i in range(3000):
                    lg.log_action("audit_rotation_test", {"i": i, "pad": "x" * 40})
                self.assertLessEqual(p.stat().st_size, 20_000 + 100 * 120)
                hist = lg.get_history(50)
                self.assertEqual(hist[0]["i"] if hist[0].get("i", -1) > hist[-1].get("i", -1) else hist[-1]["i"], 2999)
                # файл обрезан по границе строки: каждая строка — валидный JSON
                import json
                for line in p.read_text(encoding="utf-8").splitlines():
                    json.loads(line)

    def _run_guard_once(self, threads, remote_conns):
        import psutil

        class FakeConn:
            def __init__(self, ip):
                self.status = psutil.CONN_ESTABLISHED
                self.laddr = mock.Mock(port=5000)
                self.raddr = mock.Mock(ip=ip)

        class FakeProc:
            def num_threads(self): return threads
            def num_handles(self): return 10
            def memory_info(self): return mock.Mock(rss=2**20)
            def net_connections(self, kind="tcp"): return [FakeConn(ip) for ip in remote_conns]

        exits, actions = [], []
        sleeps = iter([None])

        def fake_sleep(_):
            try:
                next(sleeps)
            except StopIteration:
                raise KeyboardInterrupt  # остановить бесконечный цикл после одной проверки

        with mock.patch("psutil.Process", return_value=FakeProc()), \
                mock.patch.object(self.server.time, "sleep", side_effect=fake_sleep), \
                mock.patch.object(self.server.os, "_exit", side_effect=lambda c: exits.append(c)), \
                mock.patch.object(self.server, "log_action", side_effect=lambda n, e=None: actions.append(n)):
            with self.assertRaises(KeyboardInterrupt):
                self.server._resource_guard(5000)
        return exits, actions

    def test_resource_guard(self):
        exits, actions = self._run_guard_once(100, [])
        self.assertEqual((exits, actions), ([], []), "normal load: nothing happens")
        exits, actions = self._run_guard_once(500, [])
        self.assertEqual(exits, [])
        self.assertIn("resource_guard_warning", actions)
        exits, actions = self._run_guard_once(2000, ["192.168.0.100"])
        self.assertEqual(exits, [], "never restart while a phone is connected")
        exits, actions = self._run_guard_once(2000, [])
        self.assertEqual(exits, [3], "idle + runaway threads -> restart via watchdog")

    def test_uia_dom_not_found_backs_off(self):
        import modules.media_uia as mu
        calls = []
        with mock.patch.object(mu, "_find_ytm_chrome_hwnds", side_effect=lambda: calls.append(1) or [123]), \
                mock.patch.object(mu, "_get_uia", side_effect=RuntimeError("no uia")), \
                mock.patch.object(mu, "_dom_backoff_until", 0.0), \
                mock.patch.object(mu, "_cached_dom_state", {}), mock.patch.object(mu, "_cached_dom_time", 0.0):
            mu._read_ytm_live_dom(force=False)  # ошибка UIA -> состояние не найдено
            # имитация успешного «не найдено» с отсрочкой
            mu._cached_dom_state = {"found": False}
            mu._cached_dom_time = 0.0
            import time as _t
            mu._dom_backoff_until = _t.time() + 5.0
            n0 = len(calls)
            for _ in range(5):
                mu._read_ytm_live_dom(force=False)
            self.assertEqual(len(calls), n0, "no Chrome UIA traversal during back-off")
            mu._read_ytm_live_dom(force=True)
            self.assertEqual(len(calls), n0 + 1, "force bypasses the back-off")

    def test_audio_reuses_one_portaudio_instance(self):
        import modules.streaming as st
        created = []
        real = st._shared_pyaudio
        import pyaudiowpatch

        orig_init = pyaudiowpatch.PyAudio.__init__

        def counting_init(self, *a, **k):
            created.append(1)
            orig_init(self, *a, **k)

        with mock.patch.object(pyaudiowpatch.PyAudio, "__init__", counting_init):
            for _ in range(3):
                with self.server.app.test_request_context(f"/audio?token={self.token}"):
                    resp = st.audio()
                    it = iter(resp.response)
                    next(it)  # WAV-заголовок
                    next(it)  # первые PCM-данные
                    resp.response.close()
        self.assertLessEqual(len(created), 1, "PortAudio must be created at most once for repeated /audio")
        self.assertEqual(st._PA_ACTIVE_STREAMS, 0, "stream counter must return to zero")
        self.assertIs(real, st._shared_pyaudio)


if __name__ == "__main__":
    unittest.main()
