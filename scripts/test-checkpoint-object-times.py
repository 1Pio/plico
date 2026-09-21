#!/usr/bin/env python3
"""Ensure metadata recovery cannot bless changed checkpoint object contents."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from scratch import scratch_directory

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).with_name('restore-checkpoint-object-times.py'))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def integer(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def field(number, value):
    if isinstance(value, int):
        return integer(number << 3) + integer(value)
    return integer((number << 3) | 2) + integer(len(value)) + value


def state(record, digest_function=1):
    identity = field(1, record['mtime_ns'])
    digest = field(1, record['sha256'].encode()) + field(2, record['bytes'])
    entry = field(1, identity) + field(2, (recovery.ORIGINAL_ROOT + record['path']).encode()) + field(3, digest) + field(6, b'command-hash')
    return field(1, entry) + field(6, digest_function)


class ObjectTimesTest(unittest.TestCase):
    def setUp(self):
        self.scratch = scratch_directory(prefix='plico-object-times-')
        self.source = self.scratch.__enter__().resolve()
        self.timestamp = 1789705018508492000

    def tearDown(self):
        self.scratch.__exit__(None, None, None)

    def object(self, name='example.o'):
        path = self.source / 'out/Default/obj' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'verified object')
        rounded = self.timestamp // 10**9 * 10**9
        os.utime(path, ns=(rounded, rounded))
        record = {'path': path.relative_to(self.source).as_posix(),
                  'mtime_ns': self.timestamp, 'bytes': path.stat().st_size,
                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        return path, record

    def test_hash_verified_precision_recovery_and_idempotence(self):
        path, original = self.object()
        records = list(recovery.object_records(io.BytesIO(state(original))))
        self.assertEqual(records, [original])
        report = recovery.recover(self.source, records)
        self.assertEqual(report['timestamps_recoverable'], 1)
        self.assertNotEqual(path.stat().st_mtime_ns, self.timestamp)
        report = recovery.recover(self.source, records, apply=True)
        self.assertEqual(report['timestamps_restored'], 1)
        self.assertEqual(path.stat().st_mtime_ns, self.timestamp)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original['sha256'])
        self.assertEqual(recovery.recover(self.source, records, apply=True)['already_precise'], 1)

    def test_nested_toolchain_objects_are_retained(self):
        _, record = self.object()
        record['path'] = 'out/Default/clang_arm64_for_rust_host_build_tools/obj/tool.o'
        self.assertEqual(list(recovery.object_records(io.BytesIO(state(record)))), [record])

    def test_exact_float_extraction_loss_is_recoverable(self):
        path, record = self.object()
        record['mtime_ns'] = 1789708092375665000
        value = float('1789708092.375665000')
        os.utime(path, times=(value, value))
        self.assertNotEqual(path.stat().st_mtime_ns, record['mtime_ns'])
        self.assertEqual(recovery.recover(self.source, [record], apply=True)['timestamps_restored'], 1)
        self.assertEqual(path.stat().st_mtime_ns, record['mtime_ns'])

    def test_same_size_tampering_prevents_all_changes(self):
        first, good = self.object('good.o')
        second, bad = self.object('bad.o')
        rounded = first.stat().st_mtime_ns
        second.write_bytes(b'corrupt! object')
        self.assertEqual(second.stat().st_size, bad['bytes'])
        os.utime(second, ns=(rounded, rounded))
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            recovery.recover(self.source, [good, bad], apply=True)
        self.assertEqual(first.stat().st_mtime_ns, rounded)
        self.assertEqual(second.stat().st_mtime_ns, rounded)

    def test_unrelated_timestamp_change_is_not_hidden(self):
        path, record = self.object()
        value = path.stat().st_mtime_ns - 10**9
        os.utime(path, ns=(value, value))
        with self.assertRaisesRegex(ValueError, 'beyond archive precision loss'):
            recovery.recover(self.source, [record], apply=True)
        self.assertEqual(path.stat().st_mtime_ns, value)

    def test_symlink_is_not_followed_for_hash_or_change(self):
        path, record = self.object()
        alias = path.parent / 'alias.o'
        alias.symlink_to(path.name)
        record['path'] = alias.relative_to(self.source).as_posix()
        with self.assertRaisesRegex(ValueError, 'symlink'):
            recovery.recover(self.source, [record], apply=True)
        self.assertNotEqual(path.stat().st_mtime_ns, self.timestamp)

    def test_cli_refuses_complete_checkpoint_before_spawning(self):
        destination = self.source / 'build/reuse-qualification/restored'
        destination.mkdir(parents=True)
        (destination / 'restoration.json').write_text(json.dumps({
            'zip_sha256': recovery.ARCHIVE_SHA256, 'object_probe': False}))
        with patch.object(recovery, 'ROOT', self.source), patch('sys.argv', ['recover', '--apply']):
            with patch.object(recovery.subprocess, 'Popen') as child:
                with self.assertRaisesRegex(SystemExit, 'complete/local builds are protected'):
                    recovery.main()
                child.assert_not_called()

    def test_malformed_or_unsupported_state_is_rejected(self):
        _, record = self.object()
        with self.assertRaisesRegex(ValueError, 'not SHA256'):
            list(recovery.object_records(io.BytesIO(state(record, 2))))
        with self.assertRaisesRegex(ValueError, 'Missing protobuf integer'):
            list(recovery.object_records(io.BytesIO(state(record)[:-1])))
        record['path'] = 'out/Default/obj/../../outside.o'
        with self.assertRaisesRegex(ValueError, 'Unexpected archived object path'):
            list(recovery.object_records(io.BytesIO(state(record))))


if __name__ == '__main__':
    unittest.main(verbosity=2)
