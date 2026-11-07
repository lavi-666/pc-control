"""Full-project update regressions, with disposable files and no network access."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from scripts import full_update as update


def manifest(files, revision='same-version'):
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    material = json.dumps({'files': hashes, 'revision': revision}, sort_keys=True, separators=(',', ':')).encode()
    return {'schema': 1, 'files': hashes, 'revision': revision, 'build_id': hashlib.sha256(material).hexdigest()}


class TestUpdateSystem(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'application'
        self.base.mkdir()
        self.files = {name: b'original' for name in ('Launcher.exe', 'server.py', 'scripts/control_panel.py', 'runtime/python.exe', 'runtime/pythonw.exe', 'web/index.html')}
        self.data = manifest(self.files)
        for name, content in self.files.items():
            target = self.base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (self.base / update.MANIFEST).write_text(json.dumps(self.data))
        self.remote = {'manifest': self.data, 'manifest_raw': json.dumps(self.data).encode(), 'tag': 'same', 'title': 'release', 'date': ''}

    def archive(self, files=None, extra=None):
        files = self.files if files is None else files
        raw = json.dumps(self.data).encode()
        archive = self.root / 'package.zip'
        with zipfile.ZipFile(archive, 'w') as zf:
            for name, content in files.items():
                zf.writestr('PC_Control/' + name, content)
            zf.writestr('PC_Control/' + update.MANIFEST, raw)
            zf.writestr('PC_Control/launch_presets.json', b'[]')
            if extra:
                zf.writestr(*extra)
        return archive, raw

    def test_identical_files_no_update(self):
        with patch.object(update, 'remote_release', return_value=self.remote):
            self.assertFalse(update.check(self.base)['has_update'])

    def test_one_code_change_same_version_detected(self):
        (self.base / 'server.py').write_bytes(b'changed')
        with patch.object(update, 'remote_release', return_value=self.remote):
            result = update.check(self.base)
        self.assertTrue(result['has_update'])
        self.assertEqual(result['changed_files'], ['server.py'])

    def test_missing_file_detected(self):
        (self.base / 'web/index.html').unlink()
        self.assertEqual(update.compare(self.base, self.data)[0], ['web/index.html'])

    def test_new_commit_same_contents_detected(self):
        self.remote['manifest'] = manifest(self.files, 'another-commit')
        with patch.object(update, 'remote_release', return_value=self.remote):
            self.assertTrue(update.check(self.base)['has_update'])

    def test_settings_do_not_trigger_update(self):
        (self.base / 'config.json').write_text('{"token":"user-password"}')
        (self.base / 'launch_presets.json').write_text('["user-script"]')
        self.assertEqual(update.compare(self.base, self.data)[:2], ([], []))

    def test_removed_managed_file_detected(self):
        future = dict(self.files)
        del future['web/index.html']
        self.assertEqual(update.compare(self.base, manifest(future))[1], ['web/index.html'])

    def test_no_local_manifest_requires_initial_sync(self):
        (self.base / update.MANIFEST).unlink()
        with patch.object(update, 'remote_release', return_value=self.remote):
            self.assertTrue(update.check(self.base)['has_update'])

    def test_bad_manifest_identifier_rejected(self):
        self.data['build_id'] = 'a' * 64
        with self.assertRaises(ValueError):
            update.validate_manifest(self.data)

    def test_manifest_cannot_target_user_config(self):
        self.files['config.json'] = b'bad'
        with self.assertRaises(ValueError):
            update.validate_manifest(manifest(self.files))

    def test_paths_and_device_names_rejected(self):
        for name in ('../server.py', '/server.py', 'scripts/../../config.json', 'scripts/CON.py', 'scripts/a.py:stream', 'scripts/a.py.', 'scripts\\a.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                update.managed_name(name)

    def test_case_collisions_rejected(self):
        self.files['web/INDEX.html'] = b'conflict'
        with self.assertRaises(ValueError):
            update.validate_manifest(manifest(self.files))

    def test_foreign_release_url_rejected(self):
        for url in ('https://evil.example/PC_Control_Windows.zip', 'http://github.com/lavi-666/pc-control/releases/download/v1/PC_Control_Windows.zip', 'https://github.com/other/repo/releases/download/v1/PC_Control_Windows.zip'):
            with self.assertRaises(ValueError):
                update.release_url(url, update.PACKAGE)

    def test_missing_full_release_reports_error(self):
        with patch.object(update, 'fetch', return_value=b'{"assets":[]}'):
            result = update.check(self.base)
        self.assertFalse(result['ok'])
        self.assertIn('полного', result['message'])

    def test_valid_archive_extracts_without_user_presets(self):
        archive, raw = self.archive()
        stage = self.root / 'stage'
        update.extract_package(archive, stage, self.data, raw)
        self.assertFalse((stage / 'launch_presets.json').exists())
        self.assertEqual((stage / 'server.py').read_bytes(), b'original')

    def test_archive_traversal_rejected(self):
        archive, raw = self.archive(extra=('PC_Control/../outside', b'bad'))
        with self.assertRaises(ValueError):
            update.extract_package(archive, self.root / 'stage', self.data, raw)
        self.assertFalse((self.root / 'outside').exists())

    def test_modified_archive_file_rejected(self):
        files = dict(self.files, **{'server.py': b'corrupt'})
        archive, raw = self.archive(files)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            update.extract_package(archive, self.root / 'stage', self.data, raw)

    def test_manifest_from_different_release_rejected(self):
        archive, raw = self.archive()
        with self.assertRaisesRegex(ValueError, 'manifest'):
            update.extract_package(archive, self.root / 'stage', self.data, raw + b' ')

    def test_full_replacement_removal_preserves_settings_and_rolls_back(self):
        stage, backup = self.root / 'stage', self.root / 'backup'
        stage.mkdir()
        (stage / 'server.py').write_bytes(b'new')
        (stage / 'modules').mkdir()
        (stage / 'modules/new.py').write_bytes(b'added')
        (self.base / 'config.json').write_bytes(b'private config')
        plan = {'files': ['server.py', 'web/index.html', 'modules/new.py'], 'new_files': ['server.py', 'modules/new.py'], 'had_old': ['server.py', 'web/index.html']}
        update.apply_files(self.base, stage, backup, plan)
        self.assertEqual((self.base / 'server.py').read_bytes(), b'new')
        self.assertFalse((self.base / 'web/index.html').exists())
        self.assertEqual((self.base / 'config.json').read_bytes(), b'private config')
        update.rollback(self.base, backup, plan)
        self.assertEqual((self.base / 'server.py').read_bytes(), b'original')
        self.assertTrue((self.base / 'web/index.html').exists())
        self.assertFalse((self.base / 'modules/new.py').exists())

    def test_partial_write_failure_restores_previous_files(self):
        stage, backup = self.root / 'stage', self.root / 'backup'
        stage.mkdir()
        (stage / 'server.py').write_bytes(b'new')
        plan = {'files': ['server.py', 'Launcher.exe'], 'new_files': ['server.py', 'Launcher.exe'], 'had_old': ['server.py', 'Launcher.exe']}
        with self.assertRaises(FileNotFoundError):
            update.apply_files(self.base, stage, backup, plan)
        update.rollback(self.base, backup, plan)
        self.assertEqual((self.base / 'server.py').read_bytes(), b'original')
        self.assertEqual((self.base / 'Launcher.exe').read_bytes(), b'original')

    def test_metadata_checksum_mismatch_blocks_download(self):
        urls = {name: 'https://github.com/lavi-666/pc-control/releases/download/v1/' + name for name in (update.MANIFEST, update.PACKAGE, 'SHA256SUMS.txt')}
        release = json.dumps({'assets': [{'name': name, 'browser_download_url': url} for name, url in urls.items()]}).encode()
        with patch.object(update, 'fetch', side_effect=[release, b'0' * 64 + b'  release-manifest.json', json.dumps(self.data).encode()]):
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                update.remote_release()

    def test_corrupt_download_leaves_application_untouched(self):
        self.remote.update(url='https://github.com/lavi-666/pc-control/releases/download/v1/' + update.PACKAGE, sha256='a' * 64)
        (self.base / 'server.py').write_bytes(b'local change')
        with patch.object(update, 'remote_release', return_value=self.remote), patch.object(update.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt')), patch.object(update.shutil, 'disk_usage') as disk:
            disk.return_value.free = 10 * 1024**3
            result = update.prepare(self.base, 12345)
        self.assertFalse(result['ok'])
        self.assertEqual((self.base / 'server.py').read_bytes(), b'local change')
        self.assertFalse((self.base / update.PENDING).exists())


if __name__ == '__main__':
    unittest.main()
