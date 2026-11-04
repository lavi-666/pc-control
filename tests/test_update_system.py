import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.control_panel import (
    check_github_updates,
    apply_github_update,
    get_local_launcher_hash
)


def make_mock_resp(status_code: int, data: bytes):
    mock = MagicMock()
    mock.status = status_code
    mock.read.return_value = data
    cm = MagicMock()
    cm.__enter__.return_value = mock
    cm.__exit__.return_value = None
    return cm


class TestUpdateSystem(unittest.TestCase):
    """
    Validation suite for the PC Control Updater subsystem covering:
    1. Update is available.
    2. No update is available (latest version).
    3. GitHub is unavailable / network offline.
    4. Download is interrupted / corrupt file.
    5. Update completes successfully (PE validation and updater handover).
    6. Live GitHub connectivity test.
    """

    def test_01_no_update_available(self):
        """Scenario: Local hash matches remote hash -> returns has_update: False and up to date message."""
        local_hash = get_local_launcher_hash() or "f42deaa07d14297ec7bd3f3909fbb3942de5d0bb"
        
        cm_commits = make_mock_resp(200, b'{"sha": "7f16c8112345", "commit": {"message": "Test commit\\nDetails", "committer": {"date": "2026-10-24T12:00:00Z"}}}')
        cm_contents = make_mock_resp(200, f'{{"sha": "{local_hash}", "size": 60416, "download_url": "https://raw.githubusercontent.com/lavi-666/pc-control/main/Launcher.exe"}}'.encode('utf-8'))

        with patch("urllib.request.urlopen", side_effect=[cm_commits, cm_contents]):
            with patch("subprocess.check_output", return_value="7f16c81"):
                res = check_github_updates()

        self.assertTrue(res.get("ok"))
        self.assertFalse(res.get("has_update"))
        self.assertEqual(res.get("message"), "You are currently using the latest version.")

    def test_02_update_is_available(self):
        """Scenario: Remote hash differs from local hash -> returns has_update: True."""
        cm_commits = make_mock_resp(200, b'{"sha": "9999999abcdef", "commit": {"message": "New major release\\nDetails", "committer": {"date": "2026-10-24T13:00:00Z"}}}')
        cm_contents = make_mock_resp(200, b'{"sha": "diff_remote_hash_abcdef0123", "size": 62000, "download_url": "https://raw.githubusercontent.com/lavi-666/pc-control/main/Launcher.exe"}')

        with patch("urllib.request.urlopen", side_effect=[cm_commits, cm_contents]):
            with patch("subprocess.check_output", return_value="7f16c81"):
                res = check_github_updates()

        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("has_update"))
        self.assertEqual(res.get("message"), "A new version of PC Control is available")

    def test_03_github_unavailable_offline(self):
        """Scenario: Network offline / GitHub down -> returns ok: False and never reports 'up to date'."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network is unreachable")):
            res = check_github_updates()

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "ERR_GITHUB_UNREACHABLE")
        self.assertIn("Не удалось связаться с сервером обновлений", res.get("message", ""))
        self.assertNotIn("последнюю версию", res.get("message", ""))

    def test_04_download_corrupt_rejected(self):
        """Scenario: Downloaded file is corrupt or HTML 404 -> rejected before replacing Launcher.exe."""
        cm = make_mock_resp(200, b"<html>404 Not Found</html>")

        with patch("urllib.request.urlopen", return_value=cm):
            res = apply_github_update()

        self.assertFalse(res.get("ok"))
        self.assertIn(res.get("error_code"), ["ERR_INVALID_SIZE", "ERR_CORRUPT_PE"])

    def test_05_download_interrupted_rejected(self):
        """Scenario: Download drops connection mid-stream -> handled safely without touching existing exe."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
            res = apply_github_update()

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "ERR_DOWNLOAD_FAILED")

    def test_06_update_success_valid_pe(self):
        """Scenario: Valid PE executable downloaded -> safely verified and handed off to updater."""
        valid_pe = bytearray(30000)
        valid_pe[0:2] = b"MZ"
        valid_pe[0x3C:0x40] = (0x80).to_bytes(4, byteorder="little")
        valid_pe[0x80:0x84] = b"PE\0\0"

        cm = make_mock_resp(200, bytes(valid_pe))

        with patch("urllib.request.urlopen", return_value=cm):
            with patch("subprocess.Popen") as mock_popen:
                with patch("subprocess.check_output", return_value="Already up to date."):
                    res = apply_github_update()

        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("restarting"))
        mock_popen.assert_called_once()

        test_new = BASE_DIR / "Launcher.exe.new"
        if test_new.exists():
            test_new.unlink(missing_ok=True)

    def test_07_live_github_connectivity(self):
        """Scenario: Live connection to official GitHub repository succeeds with valid status."""
        res = check_github_updates()
        if not res.get("ok") and res.get("error_code") == "ERR_GITHUB_UNREACHABLE":
            self.skipTest(f"Live GitHub repository not reachable: {res.get('details')}")
        self.assertTrue(res.get("ok"))
        self.assertIn("current_version", res)
        self.assertIn("has_update", res)


if __name__ == "__main__":
    unittest.main()
