"""
tests/test_launcher_setup.py
Регрессии лаунчера (первоначальная настройка на новом ПК, отчёт 15):
1. Кнопка «Обновить» не должна откатывать более новую установку на старый релиз GitHub.
2. Занятый другой программой (или зарезервированный Windows) порт сервера выбирается
   автоматически, без ручных действий пользователя.
3. Брандмауэр: успех засчитывается только если правило реально появилось.
4. build-info.json подставляется git archive / ZIP с GitHub (export-subst).
"""

import json
import socket
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent.parent


class UpdateDirectionTests(unittest.TestCase):
    def _remote(self, date, revision="a" * 40):
        return {"manifest": {"build_id": "b" * 64, "revision": revision, "files": {"server.py": "0" * 64}},
                "date": date, "title": "build-1", "tag": "build-1", "url": "", "sha256": "", "manifest_raw": b""}

    def test_newer_local_code_is_not_offered_an_update(self):
        import scripts.full_update as fu
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "build-info.json").write_text(json.dumps(
                {"commit": "c" * 40, "date": "2026-11-08T10:00:00+02:00"}), encoding="utf-8")
            (Path(d) / "server.py").write_text("print(1)", encoding="utf-8")
            with mock.patch.object(fu, "remote_release", return_value=self._remote("2026-11-07T02:37:52Z")):
                r = fu.check(d)
                self.assertTrue(r["ok"])
                self.assertFalse(r["has_update"], r)
                self.assertTrue(r.get("local_newer"))
                p = fu.prepare(d, 5000)
                self.assertFalse(p["ok"])
                self.assertEqual(p.get("error_code"), "ERR_LOCAL_NEWER")

    def test_older_local_code_is_offered_the_update(self):
        import scripts.full_update as fu
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "build-info.json").write_text(json.dumps(
                {"commit": "c" * 40, "date": "2026-11-01T10:00:00Z"}), encoding="utf-8")
            (Path(d) / "server.py").write_text("print(1)", encoding="utf-8")
            with mock.patch.object(fu, "remote_release", return_value=self._remote("2026-11-07T02:37:52Z")):
                r = fu.check(d)
                self.assertTrue(r["has_update"], r)
                self.assertFalse(r.get("local_newer", False))

    def test_git_archive_substitutes_build_info(self):
        with tempfile.TemporaryDirectory() as d:
            z = Path(d) / "a.zip"
            subprocess.run(["git", "archive", "--format=zip", "-o", str(z), "HEAD", "build-info.json"],
                           cwd=BASE, check=True, capture_output=True)
            info = json.loads(zipfile.ZipFile(z).read("build-info.json"))
            self.assertNotIn("$Format", info["commit"])
            self.assertEqual(len(info["commit"]), 40)
            self.assertIn("T", info["date"])


class PortAutoSelectionTests(unittest.TestCase):
    def test_busy_port_is_replaced_by_a_free_one(self):
        import scripts.control_panel as cp
        blocker = socket.socket()
        blocker.bind(("0.0.0.0", 0))
        blocker.listen(1)
        busy = blocker.getsockname()[1]
        try:
            self.assertFalse(cp._port_bindable(busy))
            free = cp._find_free_port(busy + 1)
            self.assertIsNotNone(free)
            self.assertNotEqual(free, busy)
            self.assertTrue(cp._port_bindable(free))
            self.assertNotIn(free, (5050, 5055))
        finally:
            blocker.close()


class FirewallVerificationTests(unittest.TestCase):
    def test_success_requires_the_rule_to_exist(self):
        """Права получены и сценарий отработал, но правила нет — это ошибка, а не «успех»."""
        import io
        import scripts.control_panel as cp

        class FakeHandler(cp.ControlPanelHandler):
            def __init__(self):
                self.sent = None

            def send_json(self, data, status=200):
                self.sent = (status, data)

        h = FakeHandler()
        body = json.dumps({"action": "apply_firewall"}).encode()
        h.headers = {"Content-Length": str(len(body))}
        h.rfile = io.BytesIO(body)
        h.connection = mock.Mock()
        h.path = "/api/action"
        with mock.patch.object(cp, "run_elevated_and_wait", return_value=(True, "OK", "exit code 0", 0)), \
                mock.patch.object(cp, "is_firewall_configured", return_value=False):
            h._handle_post()
        status, data = h.sent
        self.assertFalse(data["ok"], data)
        self.assertEqual(data["error_code"], "ERR_FIREWALL_NOT_APPLIED")
        with mock.patch.object(cp, "run_elevated_and_wait", return_value=(True, "OK", "exit code 0", 0)), \
                mock.patch.object(cp, "is_firewall_configured", return_value=True):
            h.rfile = io.BytesIO(body)
            h._handle_post()
        self.assertTrue(h.sent[1]["ok"])


class ConfigRobustnessTests(unittest.TestCase):
    """config.json, сохранённый Блокнотом/PowerShell с BOM, не должен «теряться»
    (раньше панель создавала новый файл с новым ключом доступа)."""

    def _patched(self, d):
        import scripts.control_panel as cp
        import scripts.network_setup as ns
        return cp, [
            mock.patch.object(cp, "CONFIG_FILE", Path(d) / "config.json"),
            mock.patch.object(cp, "get_tailscale_info", return_value={"running": False}),
            mock.patch.object(cp, "get_local_ip", return_value="192.168.1.10"),
            mock.patch.object(ns, "detect_network", return_value={"lan_ip": "192.168.1.10", "mac_address": "AA-BB-CC-DD-EE-FF"}),
        ]

    def test_bom_config_is_read_not_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            cp, patches = self._patched(d)
            (Path(d) / "config.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"token": "keep-me", "port": 5123}).encode())
            for p in patches:
                p.start()
            try:
                cfg = cp._load_config_data()
            finally:
                for p in patches:
                    p.stop()
            self.assertEqual(cfg["token"], "keep-me")
            self.assertEqual(cfg["port"], 5123)

    def test_damaged_config_is_backed_up_before_recreation(self):
        with tempfile.TemporaryDirectory() as d:
            cp, patches = self._patched(d)
            (Path(d) / "config.json").write_text('{"token": "old", ', encoding="utf-8")
            for p in patches:
                p.start()
            try:
                cfg = cp._load_config_data()
            finally:
                for p in patches:
                    p.stop()
            backups = list(Path(d).glob("config.broken-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertIn('"old"', backups[0].read_text(encoding="utf-8"))
            self.assertTrue(cfg.get("token"))

    def test_server_config_reader_accepts_bom(self):
        import core.config as cc
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "config.json"
            f.write_bytes(b"\xef\xbb\xbf" + json.dumps({"token": "srv", "port": 5000}).encode())
            with mock.patch.object(cc, "CONFIG_FILE", f), mock.patch.object(cc, "_cached_config", None):
                self.assertEqual(cc.load_app_config().get("token"), "srv")


class DiagnosticsTests(unittest.TestCase):
    def test_export_diagnostics_succeeds(self):
        """Кнопка «Диагностика системы» падала: load_journal() возвращает (журнал, статус)."""
        import io
        import scripts.control_panel as cp

        class FakeHandler(cp.ControlPanelHandler):
            def __init__(self):
                self.sent = None

            def send_json(self, data, status=200):
                self.sent = (status, data)

        with tempfile.TemporaryDirectory() as d:
            h = FakeHandler()
            body = json.dumps({"action": "export_diagnostics"}).encode()
            h.headers = {"Content-Length": str(len(body))}
            h.rfile = io.BytesIO(body)
            h.connection = mock.Mock()
            h.path = "/api/action"
            with mock.patch.object(cp, "LOGS_DIR", Path(d)), \
                    mock.patch.object(cp, "load_config_data", return_value={"port": 5000, "lan_ip": "192.168.1.10"}), \
                    mock.patch.object(cp, "is_server_running", return_value=True), \
                    mock.patch.object(cp, "is_firewall_configured", return_value=False), \
                    mock.patch.object(cp, "get_tailscale_info", return_value={"running": False}):
                h._handle_post()
            status, data = h.sent
            self.assertEqual(status, 200, data)
            self.assertTrue(data["ok"])
            self.assertEqual(data["checks"], {"server": True, "firewall": False,
                                              "deps": data["checks"]["deps"], "lan_ip": True})
            self.assertTrue((Path(d) / "diagnostic_report.json").is_file())


class BatchLineEndingTests(unittest.TestCase):
    def test_batch_files_use_crlf(self):
        """cmd.exe неверно разбирает .bat с переводами строк LF: строки «рвутся» на куски
        (так ломалась кнопка «Применить правило» брандмауэра)."""
        bad = []
        for p in list(BASE.glob("*.bat")) + list((BASE / "scripts").glob("*.bat")):
            data = p.read_bytes()
            if data.count(b"\n") != data.count(b"\r\n"):
                bad.append(p.name)
        self.assertEqual(bad, [])


class SetupWizardTests(unittest.TestCase):
    def test_mark_setup_complete_persists_flag(self):
        import io
        import scripts.control_panel as cp

        class FakeHandler(cp.ControlPanelHandler):
            def __init__(self):
                self.sent = None

            def send_json(self, data, status=200):
                self.sent = (status, data)

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "config.json"
            f.write_text(json.dumps({"token": "t", "port": 5000}), encoding="utf-8")
            h = FakeHandler()
            body = json.dumps({"action": "mark_setup_complete"}).encode()
            h.headers = {"Content-Length": str(len(body))}
            h.rfile = io.BytesIO(body)
            h.connection = mock.Mock()
            h.path = "/api/action"
            with mock.patch.object(cp, "CONFIG_FILE", f):
                h._handle_post()
            self.assertTrue(h.sent[1]["ok"], h.sent)
            saved = json.loads(f.read_text(encoding="utf-8"))
            self.assertTrue(saved["setup_completed"])
            self.assertEqual(saved["token"], "t")

    def test_wizard_ui_is_wired(self):
        html = (BASE / "web" / "control_panel.html").read_text(encoding="utf-8")
        for needle in ('id="setupWizard"', "function runSetupWizard", "maybeAutoOpenWizard(data)",
                       "mark_setup_complete", "wizAnswerFirewall"):
            self.assertIn(needle, html)
        for lang in ("en", "ru", "uk"):
            self.assertIn(f"Object.assign(I18N.{lang}, {{\n    wiz_open_btn", html)


if __name__ == "__main__":
    unittest.main()
