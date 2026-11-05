"""Distribution tests using disposable SDK/project fixtures."""
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from scripts import build_apk, package_windows


class DistributionAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_standard_android_platforms_layout(self):
        platform = self.root / 'platforms' / 'android-35' / 'android.jar'
        platform.parent.mkdir(parents=True)
        platform.touch()
        with patch.object(build_apk, 'SDK_DIR', self.root / 'absent'), patch.dict(os.environ, {'ANDROID_HOME': str(self.root)}):
            self.assertEqual(build_apk._find_first('platform/**/android.jar'), platform)

    def test_java_home_lookup(self):
        executable = self.root / 'bin' / 'javac.exe'
        executable.parent.mkdir()
        executable.touch()
        with patch.object(build_apk, 'SDK_DIR', self.root / 'absent'), patch.dict(os.environ, {'JAVA_HOME': str(self.root)}):
            self.assertEqual(build_apk._find_first('jdk/**/bin/javac.exe'), executable)

    def test_missing_sdk_does_not_claim_old_apk_was_built(self):
        old = self.root / 'PC_Control.apk'
        old.write_bytes(b'old-apk')
        with patch.object(build_apk, 'OUT_APK', old), patch.object(build_apk, '_find_first', side_effect=FileNotFoundError('missing SDK')):
            with self.assertRaisesRegex(FileNotFoundError, 'was not rebuilt'):
                build_apk.build()
        self.assertEqual(old.read_bytes(), b'old-apk')

    def test_package_contains_runtime_but_no_user_secrets(self):
        for name in package_windows.ROOT_FILES:
            (self.root / name).write_text('fixture', encoding='utf-8')
        for name in ('tools/streamer.exe', 'scripts/control_panel.py', 'core/config.py', 'web/index.html', 'modules/power.py'):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('fixture', encoding='utf-8')
        (self.root / 'config.json').write_text('PRIVATE TOKEN')
        (self.root / 'launch_presets.json').write_text('PRIVATE PATH')
        (self.root / '.android_sdk').mkdir()
        (self.root / '.android_sdk' / 'secret.jks').write_text('PRIVATE KEY')
        archive = package_windows.package(self.root)
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            self.assertIn('PC_Control/scripts/control_panel.py', names)
            self.assertIn('PC_Control/tools/streamer.exe', names)
            self.assertNotIn('PC_Control/config.json', names)
            self.assertFalse(any('.jks' in name for name in names))
            self.assertEqual(zf.read('PC_Control/launch_presets.json'), b'[]\n')
            self.assertIsNone(zf.testzip())

    def test_missing_required_binary_fails_packaging(self):
        with self.assertRaises(FileNotFoundError):
            package_windows.package(self.root)


if __name__ == '__main__':
    unittest.main()
