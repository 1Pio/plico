#!/usr/bin/env python3
"""Protect preserved files and SDK paths during checkpoint restoration."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile
from scratch import scratch_directory

spec = importlib.util.spec_from_file_location('restore', Path(__file__).with_name('restore-upstream-checkpoint.py'))
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestorationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = scratch_directory(prefix='plico-checkpoint-test-')
        self.root = self.temporary.__enter__()
        self.destination = self.root / 'restored'

    def tearDown(self):
        self.temporary.__exit__(None, None, None)

    def archive(self, name='src/example.txt', target=None):
        tar = io.BytesIO()
        with tarfile.open(fileobj=tar, mode='w') as tree:
            item = tarfile.TarInfo(name)
            if target is None:
                item.size = 4
                tree.addfile(item, io.BytesIO(b'test'))
            else:
                item.type = tarfile.SYMTYPE
                item.linkname = target
                tree.addfile(item)
        path = self.root / 'input.zip'
        compressed = subprocess.check_output(['zstd', '-q', '-c'], input=tar.getvalue())
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('build_src.tar.zst', compressed)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_verified_file_and_completed_destination_refusal(self):
        archive, digest = self.archive()
        restore.restore(archive, self.destination, digest)
        self.assertEqual((self.destination / 'src/example.txt').read_text(), 'test')
        with self.assertRaisesRegex(RuntimeError, 'overwrite'):
            restore.restore(archive, self.destination, digest, resume=True)

    def test_path_escape_is_rejected(self):
        archive, digest = self.archive('src/../../outside.txt')
        with self.assertRaises(tarfile.OutsideDestinationError):
            restore.restore(archive, self.destination, digest)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_external_sdk_link_is_recorded_without_creation(self):
        archive, digest = self.archive('src/sdk', '/Applications/Xcode_26.app/SDK')
        report = restore.restore(archive, self.destination, digest)
        self.assertEqual(report['external_links_not_restored'][0]['path'], 'src/sdk')
        self.assertFalse((self.destination / 'src/sdk').is_symlink())

    def test_partial_resume_requires_matching_archive_identity(self):
        archive, digest = self.archive()
        self.destination.mkdir()
        marker = self.destination / 'restoration-in-progress.json'
        marker.write_text(json.dumps({'zip_sha256': 'different'}))
        with self.assertRaisesRegex(RuntimeError, 'different archive'):
            restore.restore(archive, self.destination, digest, resume=True)
        marker.write_text(json.dumps({'zip_sha256': digest}))
        restore.restore(archive, self.destination, digest, resume=True)
        self.assertEqual((self.destination / 'src/example.txt').read_text(), 'test')

    def test_probe_omits_only_link_cache_and_debug_symbols(self):
        for i, (name, omitted) in enumerate([
            ('src/out/Default/thinlto-cache/value', True),
            ('src/out/Default/Helium Framework.dSYM/Contents/data', True),
            ('src/out/Default/obj/base/example.o', False),
            ('src/out/Default/gen/example.h', False),
            ('src/base/example.cc', False),
            ('src/third_party/example.dSYM/required.cc', False),
        ]):
            with self.subTest(name=name):
                archive, digest = self.archive(name)
                destination = self.root / f'case-{i}'
                report = restore.restore(archive, destination, digest, object_probe=True)
                self.assertEqual((destination / name).exists(), not omitted)
                self.assertEqual(report['probe_outputs_omitted']['files'], int(omitted))
                self.assertEqual(report['restored_file_bytes'], 0 if omitted else 4)
                self.assertTrue(report['object_probe'])

    def test_probe_mode_cannot_resume_full_restoration(self):
        archive, digest = self.archive()
        self.destination.mkdir()
        (self.destination / 'restoration-in-progress.json').write_text(
            json.dumps({'zip_sha256': digest}))
        with self.assertRaisesRegex(RuntimeError, 'different restoration mode'):
            restore.restore(archive, self.destination, digest, resume=True, object_probe=True)

    def test_disk_gate_retains_reserve_for_probe(self):
        archive, digest = self.archive()
        with patch.object(restore.shutil, 'disk_usage', return_value=SimpleNamespace(free=30 * 1024**3)):
            with self.assertRaisesRegex(RuntimeError, '35 GiB'):
                restore.restore(archive, self.destination, digest)
            self.assertFalse(self.destination.exists())
            restore.restore(archive, self.destination, digest, object_probe=True)
        with patch.object(restore.shutil, 'disk_usage', return_value=SimpleNamespace(free=30 * 1024**3 - 1)):
            with self.assertRaisesRegex(RuntimeError, '30 GiB'):
                restore.restore(archive, self.root / 'too-small', digest, object_probe=True)

    def test_digest_failure_creates_no_destination(self):
        archive, _ = self.archive()
        with self.assertRaisesRegex(RuntimeError, 'digest mismatch'):
            restore.restore(archive, self.destination, 'wrong')
        self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
