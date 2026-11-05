import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import hashlib
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
    1. Update is available (release SHA-256 differs).
    2. No update is available (release SHA-256 matches local).
    3. GitHub is unavailable / network offline.
    4. Download is interrupted / corrupt file.
    5. Update completes successfully (SHA-256 and PE validation and updater handover).
    6. Live GitHub connectivity test.
    7. Checksum mismatch rejection (no installation, Popen not called, no temp file).
    8. Missing checksum or SHA256SUMS.txt unavailable rejection.
    9. SHA256SUMS format variations (BOM, asterisks, backslashes).
    """

    def test_01_no_update_available(self):
        """Scenario: Local SHA-256 matches release SHA256SUMS -> returns has_update: False and up to date message."""
        local_hash = get_local_launcher_hash() or "f42deaa07d14297ec7bd3f3909fbb3942de5d0bb"
        
        cm_rel = make_mock_resp(200, b'{"tag_name": "v2.0.1", "name": "PC Control v2.0.1", "published_at": "2026-10-24T12:00:00Z", "assets": [{"name": "Launcher.exe", "size": 60416, "browser_download_url": "https://github.com/lavi-666/pc-control/releases/latest/download/Launcher.exe"}]}')
        cm_sums = make_mock_resp(200, f"{local_hash}  Launcher.exe\n".encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=[cm_rel, cm_sums]):
            res = check_github_updates()

        self.assertTrue(res.get("ok"))
        self.assertFalse(res.get("has_update"))
        self.assertEqual(res.get("message"), "You are currently using the latest version.")

    def test_02_update_is_available(self):
        """Scenario: Release SHA-256 differs from local SHA-256 -> returns has_update: True."""
        cm_rel = make_mock_resp(200, b'{"tag_name": "v2.1.0", "name": "PC Control v2.1.0", "published_at": "2026-10-24T13:00:00Z", "assets": [{"name": "Launcher.exe", "size": 62000, "browser_download_url": "https://github.com/lavi-666/pc-control/releases/latest/download/Launcher.exe"}]}')
        cm_sums = make_mock_resp(200, b"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef  Launcher.exe\n")

        with patch("urllib.request.urlopen", side_effect=[cm_rel, cm_sums]):
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

    def test_03b_github_rate_limited_403(self):
        """Scenario: GitHub API returns 403 rate limit -> returns ok: False and never reports 'up to date'."""
        err_403 = urllib.error.HTTPError(
            url="https://api.github.com/repos/lavi-666/pc-control/releases/latest",
            code=403,
            msg="rate limit exceeded",
            hdrs={},
            fp=None
        )
        with patch("urllib.request.urlopen", side_effect=err_403):
            res = check_github_updates()

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "ERR_RATE_LIMITED")
        self.assertIn("Превышен лимит запросов", res.get("message", ""))
        self.assertNotIn("последнюю версию", res.get("message", ""))

    def test_03c_checksums_fetch_error_not_up_to_date(self):
        """Scenario: Release exists but SHA256SUMS.txt fails network -> returns ok: False and never claims up to date."""
        cm_rel = make_mock_resp(200, b'{"tag_name": "v2.0.1", "name": "PC Control v2.0.1", "published_at": "2026-10-24T12:00:00Z", "assets": [{"name": "Launcher.exe", "size": 60416, "browser_download_url": "https://github.com/lavi-666/pc-control/releases/latest/download/Launcher.exe"}]}')
        err_network = urllib.error.URLError("Connection reset by peer")

        with patch("urllib.request.urlopen", side_effect=[cm_rel, err_network]):
            res = check_github_updates()

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "ERR_NO_CHECKSUM")
        self.assertNotIn("последнюю версию", res.get("message", ""))

    def test_04_download_corrupt_rejected(self):
        """Scenario: Downloaded file is corrupt or HTML 404 -> rejected before replacing Launcher.exe."""
        corrupt_data = b"<html>404 Not Found</html>"
        corrupt_hash = hashlib.sha256(corrupt_data).hexdigest()
        cm_exe = make_mock_resp(200, corrupt_data)
        cm_sums = make_mock_resp(200, f"{corrupt_hash}  Launcher.exe\n".encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=[cm_exe, cm_sums]):
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
        """Scenario: Valid PE executable and matching SHA-256 downloaded -> safely verified and handed off to updater."""
        valid_pe = bytearray(30000)
        valid_pe[0:2] = b"MZ"
        valid_pe[0x3C:0x40] = (0x80).to_bytes(4, byteorder="little")
        valid_pe[0x80:0x84] = b"PE\0\0"
        pe_bytes = bytes(valid_pe)
        expected_hash = hashlib.sha256(pe_bytes).hexdigest()

        cm_exe = make_mock_resp(200, pe_bytes)
        cm_sums = make_mock_resp(200, f"{expected_hash}  Launcher.exe\n".encode("utf-8"))

        new_exe = BASE_DIR / "Launcher.exe.new"
        if new_exe.exists():
            new_exe.unlink()

        try:
            with patch("urllib.request.urlopen", side_effect=[cm_exe, cm_sums]):
                with patch("subprocess.Popen") as mock_popen:
                    res = apply_github_update()

            self.assertTrue(res.get("ok"))
            self.assertTrue(res.get("restarting"))
            mock_popen.assert_called_once()
            self.assertTrue(new_exe.exists())
        finally:
            if new_exe.exists():
                new_exe.unlink(missing_ok=True)

    def test_07_live_github_connectivity(self):
        """Scenario: Live connection to official GitHub repository succeeds with valid status."""
        res = check_github_updates()
        if not res.get("ok") and res.get("error_code") == "ERR_GITHUB_UNREACHABLE":
            self.skipTest(f"Live GitHub repository not reachable: {res.get('details')}")
        self.assertTrue(res.get("ok"))
        self.assertIn("current_version", res)
        self.assertIn("has_update", res)

    def test_08_checksum_mismatch_rejected(self):
        """Scenario: Checksum mismatch -> rejected with ERR_CHECKSUM_MISMATCH, no file written, Popen not called."""
        valid_pe = bytearray(30000)
        valid_pe[0:2] = b"MZ"
        valid_pe[0x3C:0x40] = (0x80).to_bytes(4, byteorder="little")
        valid_pe[0x80:0x84] = b"PE\0\0"
        pe_bytes = bytes(valid_pe)

        cm_exe = make_mock_resp(200, pe_bytes)
        cm_sums = make_mock_resp(200, b"0000000000000000000000000000000000000000000000000000000000000000  Launcher.exe\n")

        new_exe = BASE_DIR / "Launcher.exe.new"
        if new_exe.exists():
            new_exe.unlink()

        with patch("urllib.request.urlopen", side_effect=[cm_exe, cm_sums]):
            with patch("subprocess.Popen") as mock_popen:
                res = apply_github_update()

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "ERR_CHECKSUM_MISMATCH")
        self.assertIn("Контрольная сумма", res.get("message", ""))
        self.assertFalse(new_exe.exists(), "Launcher.exe.new must NOT be created when checksum mismatches")
        mock_popen.assert_not_called()

    def test_09_no_checksum_or_missing_entry_rejected(self):
        """Scenario: SHA256SUMS.txt unavailable or missing Launcher.exe entry -> rejected with ERR_NO_CHECKSUM."""
        valid_pe = bytearray(30000)
        valid_pe[0:2] = b"MZ"
        valid_pe[0x3C:0x40] = (0x80).to_bytes(4, byteorder="little")
        valid_pe[0x80:0x84] = b"PE\0\0"
        cm_exe = make_mock_resp(200, bytes(valid_pe))
        cm_sums_other = make_mock_resp(200, b"1111111111111111111111111111111111111111111111111111111111111111  OtherFile.exe\n")

        new_exe = BASE_DIR / "Launcher.exe.new"
        if new_exe.exists():
            new_exe.unlink()

        with patch("urllib.request.urlopen", side_effect=[cm_exe, cm_sums_other]):
            with patch("subprocess.Popen") as mock_popen:
                res = apply_github_update()

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "ERR_NO_CHECKSUM")
        self.assertFalse(new_exe.exists())
        mock_popen.assert_not_called()

        with patch("urllib.request.urlopen", side_effect=[cm_exe, urllib.error.URLError("Not Found")]):
            with patch("subprocess.Popen") as mock_popen:
                res_err = apply_github_update()

        self.assertFalse(res_err.get("ok"))
        self.assertEqual(res_err.get("error_code"), "ERR_NO_CHECKSUM")
        self.assertFalse(new_exe.exists())
        mock_popen.assert_not_called()

    def test_10_checksum_format_variations(self):
        """Scenario: Handles BOM, asterisks prefix (*Launcher.exe), and backslashes in paths."""
        valid_pe = bytearray(30000)
        valid_pe[0:2] = b"MZ"
        valid_pe[0x3C:0x40] = (0x80).to_bytes(4, byteorder="little")
        valid_pe[0x80:0x84] = b"PE\0\0"
        pe_bytes = bytes(valid_pe)
        expected_hash = hashlib.sha256(pe_bytes).hexdigest()

        variations = [
            b"\xef\xbb\xbf" + f"{expected_hash}  Launcher.exe\n".encode("utf-8"),
            f"{expected_hash} *Launcher.exe\n".encode("utf-8"),
            f"{expected_hash}  tools\\release\\Launcher.exe\n".encode("utf-8"),
            f"{expected_hash}  ./build/Launcher.exe\n".encode("utf-8"),
        ]

        new_exe = BASE_DIR / "Launcher.exe.new"
        for sums_content in variations:
            if new_exe.exists():
                new_exe.unlink()
            cm_exe = make_mock_resp(200, pe_bytes)
            cm_sums = make_mock_resp(200, sums_content)

            try:
                with patch("urllib.request.urlopen", side_effect=[cm_exe, cm_sums]):
                    with patch("subprocess.Popen") as mock_popen:
                        res = apply_github_update()

                self.assertTrue(res.get("ok"), f"Failed for variation: {sums_content}")
                self.assertTrue(res.get("restarting"))
                mock_popen.assert_called_once()
            finally:
                if new_exe.exists():
                    new_exe.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
