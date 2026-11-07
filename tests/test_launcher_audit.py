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

    def test_port_change_preserves_auto_network_but_manual_address_disables_it(self):
        cfg = dict(self.initial, auto_network=True)
        self.cfg_file.write_text(json.dumps(cfg), encoding='utf-8')
        settings = {k: cfg[k] for k in ('lan_ip', 'vpn_ip', 'mac_address', 'wol_relay_ip', 'port', 'relay_port')}
        settings['port'] = 8199
        with patch.object(panel, 'is_server_running', return_value=False):
            self.assertTrue(self.request({'action': 'save_settings', 'settings': settings})[1]['ok'])
        self.assertTrue(json.loads(self.cfg_file.read_text())['auto_network'])
        settings['lan_ip'] = '192.168.1.77'
        self.assertTrue(self.request({'action': 'save_settings', 'settings': settings})[1]['ok'])
        self.assertFalse(json.loads(self.cfg_file.read_text())['auto_network'])

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

    def test_identity_is_specific_to_installation(self):
        status, identity, _ = self.request(method='GET', path='/api/identity')
        self.assertEqual(status, 200)
        self.assertEqual(identity['instance'], panel.instance_id())
        with patch.object(panel, 'BASE_DIR', Path(self.temp.name)):
            self.assertNotEqual(identity['instance'], panel.instance_id())

    def test_foreign_online_server_is_not_our_server(self):
        import io
        response = io.BytesIO(json.dumps({'status': 'online', 'instance': 'another-copy'}).encode())
        response.status = 200
        with patch.object(panel.urllib.request, 'urlopen', return_value=response):
            self.assertFalse(panel.is_server_running(12345))

    def test_pythonw_cli_path_is_not_truncated(self):
        runtime = Path(self.temp.name)
        (runtime / 'python.exe').touch()
        with patch.object(panel, 'get_pythonw_path', return_value=str(runtime / 'pythonw.exe')):
            self.assertEqual(panel.get_python_cli_path(), str(runtime / 'python.exe'))

    def test_firewall_indicator_requires_active_rule_for_current_port(self):
        rule = 'v2.30|Name=PC Control Server|Active=TRUE|Action=Allow|Dir=In|Protocol=6|LPort=5000|'
        self.assertTrue(panel.firewall_rule_matches(rule, 5000))
        self.assertFalse(panel.firewall_rule_matches(rule, 5001))
        self.assertFalse(panel.firewall_rule_matches(rule.replace('TRUE', 'FALSE'), 5000))
        self.assertFalse(panel.firewall_rule_matches(rule.replace('Allow', 'Block'), 5000))

    def test_busy_installer_does_not_claim_task_started(self):
        panel._background_lock.acquire()
        try:
            status, result, _ = self.request({'action': 'install_deps'})
            self.assertEqual(status, 409)
            self.assertFalse(result['ok'])
        finally:
            panel._background_lock.release()

    def test_failed_profile_removal_is_reported(self):
        import os
        profile = Path(self.temp.name) / 'PCControl' / 'EdgeProfile'
        profile.mkdir(parents=True)
        with patch.dict(os.environ, {'LOCALAPPDATA': self.temp.name}), patch.object(panel.shutil, 'rmtree', side_effect=PermissionError('in use')):
            result = panel.clean_browser_profiles()
        self.assertFalse(result['ok'])
        self.assertEqual(result['removed_items'], [])
        self.assertEqual(result['freed_bytes'], 0)

    def test_status_uses_saved_lan_address(self):
        with patch.object(panel, 'get_local_ip', return_value='192.168.99.99'), patch.object(panel, 'get_tailscale_info', return_value={}), patch.object(panel, 'is_firewall_configured', return_value=False), patch.object(panel, 'check_python_deps', return_value={}), patch.object(panel, 'get_windows_hello_status', return_value={}):
            status, data, _ = self.request(method='GET', path='/api/status')
        self.assertEqual(status, 200)
        self.assertEqual(data['lan_ip'], self.initial['lan_ip'])
        self.assertIn(self.initial['lan_ip'], data['server_url'])

    def test_legacy_app_uses_saved_port_and_encodes_password(self):
        import runpy
        legacy = runpy.run_path(str(Path(__file__).resolve().parent.parent / 'open_app.pyw'))
        with patch.object(panel, 'load_config_data', return_value={'port': 6123, 'token': 'pass&?#'}):
            self.assertEqual(legacy['get_app_url'](), 'http://127.0.0.1:6123/?token=pass%26%3F%23')

    def test_cors_origins_round_trip_and_write_failure(self):
        status, data, _ = self.request({'action': 'set_cors_origins', 'origins': 'http://localhost:*, http://127.0.0.1:*'})
        self.assertEqual(status, 200)
        self.assertEqual(data['origins'], ['http://localhost:*', 'http://127.0.0.1:*'])
        status, got, _ = self.request({'action': 'get_cors_origins'})
        self.assertEqual(status, 200)
        self.assertEqual(got['origins'], ['http://localhost:*', 'http://127.0.0.1:*'])
        with patch.object(panel, 'save_config_data', side_effect=PermissionError('read only')):
            self.assertEqual(self.request({'action': 'set_cors_origins', 'origins': ['http://localhost:*']})[0], 500)

    def test_launch_tailscale_native_gui_fallback_when_web_unavailable(self):
        gui = Path(self.temp.name) / 'tailscale-ipn.exe'
        gui.touch()
        with patch.object(panel, 'find_tailscale_binaries', return_value={'installed': True, 'gui': gui, 'cli': None, 'shortcut': None}), \
             patch.object(panel, 'check_tailscale_web_accessible', return_value=False), \
             patch.object(panel.subprocess, 'Popen') as popen_mock:
            status, data, _ = self.request({'action': 'launch_tailscale', 'lang': 'ru'})
        self.assertEqual(status, 200)
        self.assertTrue(data['ok'])
        self.assertTrue(popen_mock.called)

    def test_apply_firewall_polls_and_passes_no_pause(self):
        with patch.object(panel, 'run_elevated_command', return_value=(True, '', 'OK')) as elev_mock, \
             patch.object(panel, 'is_firewall_configured', side_effect=[False, True, True]):
            status, data, _ = self.request({'action': 'apply_firewall'})
        self.assertEqual(status, 200)
        self.assertTrue(data['ok'])
        self.assertTrue(data['firewall_ok'])
        self.assertIn('PC_CONTROL_NO_PAUSE=1', elev_mock.call_args[0][1])


if __name__ == '__main__':
    unittest.main()
