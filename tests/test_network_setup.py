import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch
import psutil
from scripts import network_setup as network, control_panel as panel


class NetworkSetupTests(unittest.TestCase):
    def test_mac_belongs_to_selected_ip(self):
        adapters = {'Ethernet': [N(family=socket.AF_INET, address='192.168.2.3'), N(family=psutil.AF_LINK, address='01:02:03:04:05:06')],
                    'Wi-Fi': [N(family=socket.AF_INET, address='192.168.1.9'), N(family=psutil.AF_LINK, address='11:12:13:14:15:16')]}
        with patch.object(psutil, 'net_if_addrs', return_value=adapters), patch.object(psutil, 'net_if_stats', return_value={k:N(isup=True) for k in adapters}), patch.object(socket, 'socket') as sock:
            sock.return_value.__enter__.return_value.getsockname.return_value = ('192.168.1.9', 0)
            self.assertEqual(network.detect_network(), {'lan_ip':'192.168.1.9', 'mac_address':'11-12-13-14-15-16'})

    def test_no_fake_addresses(self):
        with patch.object(psutil, 'net_if_addrs', return_value={}):
            self.assertEqual(network.detect_network(), {'lan_ip':'', 'mac_address':''})

    def test_tailscale_stopped_with_ip_is_not_connected(self):
        with tempfile.TemporaryDirectory() as d:
            cli = Path(d)/'tailscale.exe'; cli.touch()
            with patch.object(panel, '_cached_ts', None), patch.object(panel, 'find_tailscale_binaries', return_value={'cli':cli}), patch.object(panel.subprocess, 'run', return_value=N(returncode=0, stdout=json.dumps({'BackendState':'Stopped','TailscaleIPs':['100.64.1.2']}))):
                self.assertFalse(panel.get_tailscale_info()['running'])

    def test_tailscale_chooses_ipv4(self):
        with tempfile.TemporaryDirectory() as d:
            cli = Path(d)/'tailscale.exe'; cli.touch()
            with patch.object(panel, '_cached_ts', None), patch.object(panel, 'find_tailscale_binaries', return_value={'cli':cli}), patch.object(panel.subprocess, 'run', return_value=N(returncode=0, stdout=json.dumps({'BackendState':'Running','TailscaleIPs':['fd7a::1','100.64.1.2']}))):
                result = panel.get_tailscale_info()
                self.assertTrue(result['running']); self.assertEqual(result['ip'], '100.64.1.2')

    def check_sync(self, cfg, force=False):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'config.json'; file.write_text(json.dumps(cfg))
            with patch.object(panel, 'CONFIG_FILE', file), patch.object(panel, '_network_sync_time', 0), patch.object(network, 'detect_network', return_value={'lan_ip':'192.168.1.9','mac_address':'11-12-13-14-15-16'}):
                result=panel.sync_network_settings(cfg, {'running':True,'ip':'100.64.1.2'}, force=force)
                self.assertEqual(json.loads(file.read_text()), result)
                return result

    def test_auto_sync_after_login_preserves_other_settings(self):
        result=self.check_sync({'auto_network':True,'vpn_ip':'','port':8123,'token':'secret','language':'en'})
        self.assertEqual(result['vpn_ip'],'100.64.1.2'); self.assertEqual(result['port'],8123); self.assertEqual(result['token'],'secret')

    def test_manual_network_is_preserved(self):
        cfg={'auto_network':False,'lan_ip':'192.168.3.9','vpn_ip':'100.65.1.9','language':'en'}
        self.assertEqual(self.check_sync(cfg),cfg)

    def test_explicit_detection_enables_auto_mode(self):
        result=self.check_sync({'auto_network':False,'lan_ip':'192.168.3.9','language':'en'}, force=True)
        self.assertTrue(result['auto_network']); self.assertEqual(result['lan_ip'],'192.168.1.9')

    def test_invalid_installer_filename_rejected(self):
        import io
        with patch.object(network.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"Exes":["../bad.exe"]}')):
            with self.assertRaises(ValueError): network.download_tailscale('unused')


if __name__ == '__main__': unittest.main()
