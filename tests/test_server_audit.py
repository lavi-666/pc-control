"""Server regressions; run in an isolated project copy (config is modified)."""
import unittest
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import server


class ServerAudit(unittest.TestCase):
    def setUp(self):
        (Path(__file__).resolve().parent.parent / 'scratch').mkdir(exist_ok=True)
        from core import config, auth, logger
        temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent / 'scratch')
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name)
        (folder / 'config.json').write_text(json.dumps({'token': 'audit-server-secret', 'language': 'ru'}), encoding='utf-8')
        for target, name, value in ((config, 'BASE_DIR', folder), (config, '_cached_config', None),
                                     (config, '_cached_config_mtime', -1), (auth, 'LOCKOUT_FILE', folder / 'lockouts.json'),
                                     (logger, 'LOG_FILE', folder / 'actions.jsonl'), (logger, 'ERROR_LOG_FILE', folder / 'errors.log')):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('PC_REMOTE_TOKEN', None)
        os.environ.pop('PC_CONTROL_TEST_MODE', None)
        os.environ.pop('SAFE_TEST_MODE', None)
        self.client = server.app.test_client()

    def test_json_non_objects_rejected(self):
        for path in ('/api/auth/login', '/api/auth/rotate', '/api/cors', '/volume', '/shutdown_after'):
            for payload in ([1], 'text', 42):
                with self.subTest(path=path, payload=payload):
                    self.assertEqual(self.client.post(path, json=payload).status_code, 400)

    def test_unicode_invalid_password_is_not_internal_error(self):
        response = self.client.post('/api/auth/login', json={'password': 'пароль-测试'})
        self.assertEqual(response.status_code, 401)

    def test_unicode_invalid_header_is_not_internal_error(self):
        response = self.client.get('/api/auth/verify', headers={'X-Auth-Token': 'пароль'})
        self.assertEqual(response.status_code, 401)

    def test_numeric_wildcard_cannot_match_domain(self):
        with patch.object(server, 'get_cors_allowed_origins', return_value=['http://192.168.*', 'http://10.*']):
            for origin in ('http://192.168.evil.example', 'http://10.attacker.example'):
                response = self.client.options('/status', headers={'Origin': origin})
                self.assertEqual(response.status_code, 403)
            self.assertEqual(self.client.options('/status', headers={'Origin': 'http://192.168.1.2:3000'}).status_code, 204)

    def test_empty_cors_list_is_respected(self):
        with patch.object(server, 'get_cors_allowed_origins', return_value=[]):
            self.assertEqual(self.client.options('/status', headers={'Origin': 'http://192.168.1.2:3000'}).status_code, 403)
            self.assertEqual(self.client.options('/status', headers={'Origin': 'http://localhost'}).status_code, 204)

    def test_domain_wildcard_still_supported(self):
        with patch.object(server, 'get_cors_allowed_origins', return_value=['https://*.tailscale.net']):
            self.assertEqual(self.client.options('/status', headers={'Origin': 'https://pc.tailscale.net'}).status_code, 204)

    def test_oversized_json_rejected(self):
        response = self.client.post('/api/auth/login', json={'password': 'x' * (1024 * 1024)})
        self.assertEqual(response.status_code, 413)

    def test_safe_mode_toggle_without_system_actions(self):
        from core.config import get_auth_token
        with patch.dict(os.environ, {}, clear=False):
            for enabled in (True, False, True):
                response = self.client.post('/api/safe_mode', json={'enabled': enabled},
                                            headers={'X-Auth-Token': get_auth_token()})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.client.get('/api/safe_mode', headers={'X-Auth-Token': get_auth_token()}).json['safe_mode'], enabled)

    def test_stream_settings_persist_and_restore(self):
        from core.config import get_auth_token, load_app_config
        from modules import streaming
        headers = {'X-Auth-Token': get_auth_token()}
        self.assertEqual(self.client.post('/screen/config', json={'monitor': 1, 'height': 720, 'fps': 30}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/screen/volume', json={'percent': 37, 'muted': True}, headers=headers).status_code, 200)
        self.assertEqual(load_app_config()['screen']['height'], 720)
        streaming._screen_cfg.update(height=1080, fps=60)
        streaming._stream_vol_cfg.update(percent=50, muted=False)
        streaming._restore_stream_settings()
        self.assertEqual(streaming._screen_cfg['height'], 720)
        self.assertEqual(streaming._stream_vol_cfg, {'percent': 37, 'muted': True})

    def test_stream_write_failure_rolls_back(self):
        from core.config import get_auth_token
        from modules import streaming
        old = dict(streaming._screen_cfg)
        with patch.object(streaming, 'update_config_section', return_value=False):
            response = self.client.post('/screen/config', json={'height': 720}, headers={'X-Auth-Token': get_auth_token()})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(streaming._screen_cfg, old)

    def test_unicode_and_special_password_round_trip(self):
        from core.config import get_auth_token, update_auth_token
        from urllib.parse import quote
        original = get_auth_token()
        self.addCleanup(update_auth_token, original)
        for token in ('пароль-测试', "'quoted'", '%41password'):
            self.assertTrue(update_auth_token(token))
            client = server.app.test_client()
            self.assertEqual(client.post('/api/auth/login', json={'password': token}).status_code, 200)
            client = server.app.test_client()
            self.assertEqual(client.get('/api/auth/verify', headers={'X-Auth-Token': quote(token, safe='')}).status_code, 200)

    def test_downloaded_relay_uses_saved_settings(self):
        import ast
        with patch.object(server, 'load_app_config', return_value={'mac_address': '12-34-56-78-9A-BC', 'relay_port': 6123}):
            response = self.client.get('/download/wol_relay.py')
        self.assertEqual(response.status_code, 200)
        source = response.data.decode()
        ast.parse(source)
        self.assertIn('DEFAULT_MAC = "12-34-56-78-9A-BC"', source)
        self.assertIn('PORT = 6123', source)

    def test_relay_environment_port_and_mac_validation(self):
        import runpy
        with patch.dict(os.environ, {'RELAY_PORT': '6124'}):
            relay = runpy.run_path(str(Path(__file__).resolve().parent.parent / 'scripts' / 'wol_relay.py'), run_name='audit_relay')
        self.assertEqual(relay['PORT'], 6124)
        with self.assertRaises(ValueError):
            relay['send_magic_packet']('AA-BB')


if __name__ == '__main__':
    unittest.main()
