"""Isolated real-HTTP launcher regressions; never starts/stops the user's server."""
import concurrent.futures
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import control_panel as panel


class LauncherAudit(unittest.TestCase):
    def setUp(self):
        (Path(__file__).resolve().parent.parent / 'scratch').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent / 'scratch')
        self.addCleanup(self.temp.cleanup)
        self.cfg_file = Path(self.temp.name) / 'config.json'
        self.initial = dict(token='audit-secret', language='ru', port=5000, relay_port=5050,
                            lan_ip='192.168.1.2', vpn_ip='', wol_relay_ip='',
                            mac_address='AA-BB-CC-DD-EE-FF', custom_option=42)
        self.cfg_file.write_text(json.dumps(self.initial), encoding='utf-8')
        self.patch = patch.object(panel, 'CONFIG_FILE', self.cfg_file)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.httpd = panel.http.server.ThreadingHTTPServer(('127.0.0.1', 0), panel.ControlPanelHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def request(self, data=None, headers=None, method='POST', path='/api/action', raw=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        try:
            conn.request(method, path, raw if raw is not None else json.dumps(data or {}),
                         headers or {'Content-Type': 'application/json'})
            response = conn.getresponse()
            body = response.read()
            return response.status, json.loads(body), dict(response.headers)
        finally:
            conn.close()

    def test_foreign_origin_cannot_read_secret(self):
        status, _, headers = self.request(method='GET', path='/api/status', headers={'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_dns_rebinding_rejected(self):
        self.assertEqual(self.request({'action': 'clear_logs'}, headers={'Host': 'evil.example'})[0], 403)

    def test_same_origin_allowed(self):
        origin = f'http://127.0.0.1:{self.httpd.server_port}'
        self.assertEqual(self.request({'action': 'get_settings'}, headers={'Origin': origin})[0], 200)

    def test_invalid_json_shapes(self):
        for body in ('[]', 'null', '42', '"text"', '{bad', '[1]'):
            with self.subTest(body=body):
                self.assertEqual(self.request(raw=body)[0], 400)

    def test_oversized_request(self):
        self.assertEqual(self.request(raw=' ' * 65537)[0], 400)

    def test_bad_content_length(self):
        self.assertEqual(self.request(raw='', headers={'Content-Length': '-1'})[0], 400)

    def test_settings_round_trip_and_reload(self):
        settings = {k: self.initial[k] for k in ('port', 'relay_port', 'lan_ip', 'vpn_ip', 'wol_relay_ip', 'mac_address')}
        settings.update(port=6000, vpn_ip='100.64.0.2', wol_relay_ip='192.168.1.3')
        with patch.object(panel, 'is_server_running', return_value=False):
            self.assertEqual(self.request({'action': 'save_settings', 'settings': settings})[0], 200)
        self.assertEqual(self.request({'action': 'get_settings'})[1]['settings'], settings)
        disk = json.loads(self.cfg_file.read_text())
        self.assertEqual(disk['custom_option'], 42)
        self.assertEqual(disk['token'], 'audit-secret')
        self.assertEqual(panel.load_config_data()['port'], 6000)

    def test_invalid_ports_and_addresses(self):
        for key, value in [('port', 0), ('port', 65536), ('port', True), ('port', 5051),
                           ('port', 5055), ('port', 5050), ('lan_ip', '192.168.999.1'), ('mac_address', 'x')]:
            with self.subTest(key=key, value=value):
                settings = dict(self.initial, **{key: value})
                self.assertEqual(self.request({'action': 'save_settings', 'settings': settings})[0], 400)

    def test_running_server_port_change_rejected(self):
        with patch.object(panel, 'is_server_running', return_value=True):
            self.assertEqual(self.request({'action': 'save_settings', 'settings': dict(self.initial, port=6000)})[0], 409)
        self.assertEqual(panel.load_config_data()['port'], 5000)

    def test_write_failure_reported(self):
        with patch.object(panel, 'save_config_data', side_effect=PermissionError('read only')):
            self.assertEqual(self.request({'action': 'save_settings', 'settings': self.initial})[0], 500)
        self.assertEqual(json.loads(self.cfg_file.read_text()), self.initial)

    def test_password_saved_without_log_leak(self):
        secret = 'new-audit-password'
        self.assertTrue(self.request({'action': 'set_password', 'password': secret})[1]['ok'])
        self.assertEqual(panel.load_config_data()['token'], secret)
        self.assertFalse(any(secret in line for line in panel.get_logs()))

    def test_password_bad_type(self):
        self.assertEqual(self.request({'action': 'set_password', 'password': []})[0], 400)

    def test_password_write_failure(self):
        with patch.object(panel, 'save_token_everywhere', return_value=False):
            self.assertEqual(self.request({'action': 'set_password', 'password': 'valid'})[0], 500)
            self.assertEqual(self.request({'action': 'rotate_token'})[0], 500)

    def test_language_saved(self):
        for language in ('en', 'ru', 'uk'):
            self.assertEqual(self.request({'action': 'set_language', 'language': language})[0], 200)
            self.assertEqual(panel.load_config_data()['language'], language)
        self.assertEqual(self.request({'action': 'set_language', 'language': []})[0], 400)

    def test_hello_requires_boolean(self):
        with patch.object(panel, 'set_windows_hello_state') as setter:
            self.assertEqual(self.request({'action': 'set_windows_hello', 'enabled': 'false'})[0], 400)
            setter.assert_not_called()

    def test_stop_failure_propagates(self):
        with patch.object(panel, 'stop_server_process', return_value=(False, 'ERR_STOP', 'Failed', 'still running')):
            status, data, _ = self.request({'action': 'stop_server'})
        self.assertEqual(status, 500)
        self.assertFalse(data['ok'])

    def test_concurrent_password_and_language(self):
        actions = [{'action': 'set_password', 'password': 'concurrent-secret'}, {'action': 'set_language', 'language': 'uk'}]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(self.request, actions))
        self.assertTrue(all(result[0] == 200 for result in results))
        config = panel.load_config_data()
        self.assertEqual(config['token'], 'concurrent-secret')
        self.assertEqual(config['language'], 'uk')

    def test_unknown_action(self):
        self.assertEqual(self.request({'action': 'not_an_action'})[0], 400)


if __name__ == '__main__':
    unittest.main()
