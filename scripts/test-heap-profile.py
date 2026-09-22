#!/usr/bin/env python3
"""Protect heap diagnosis from misattributing sampled allocations."""
import gzip
import io
import json
from contextlib import redirect_stdout
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from scratch import scratch_directory

spec = importlib.util.spec_from_file_location('heap', Path(__file__).with_name('summarize-heap-profile.py'))
heap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heap)


def integer(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out) + bytes([value])


def field(number, value):
    if isinstance(value, int):
        return integer(number << 3) + integer(value)
    return integer(number << 3 | 2) + integer(len(value)) + value


def profile(packed=True, bad_location=False, value_count=2):
    # alloc_space comes first, proving the reader selects by type rather than index.
    strings = ['', 'alloc_space', 'bytes', 'inuse_space', 'leaf', 'parent']
    data = b''.join(field(6, s.encode()) for s in strings)
    data += field(1, field(1, 1) + field(2, 2)) + field(1, field(1, 3) + field(2, 2))
    for identity, name in [(10, 4), (20, 5)]:
        data += field(5, field(1, identity) + field(2, name))
    # Inline parent and repeated parent frame must not inflate cumulative bytes.
    data += field(4, field(1, 100) + field(4, field(1, 10)) + field(4, field(1, 20)))
    data += field(4, field(1, 200) + field(4, field(1, 20)))
    for ids, size in [([999 if bad_location else 100, 200], 1000), ([200], 500)]:
        values = [999999, size][:value_count]
        if packed:
            sample = field(1, b''.join(map(integer, ids))) + field(2, b''.join(map(integer, values)))
        else:
            sample = b''.join(field(1, i) for i in ids) + b''.join(field(2, v) for v in values)
        data += field(2, sample)
    return data


class HeapProfileTest(unittest.TestCase):
    def test_packed_and_unpacked_values_inline_and_recursion(self):
        for packed in (False, True):
            with self.subTest(packed=packed):
                report = heap.summarize(profile(packed=packed))
                self.assertEqual(report['sampled_total_bytes'], 1500)
                self.assertEqual({r['function']: r['bytes'] for r in report['flat']}, {'leaf': 1000, 'parent': 500})
                self.assertEqual({r['function']: r['bytes'] for r in report['cumulative']}, {'leaf': 1000, 'parent': 1500})

    def test_rejects_malformed_or_unsupported_profiles(self):
        cases = [profile()[:-1], profile(bad_location=True), profile(value_count=1),
                 profile() + field(7, 1), b'\x80' * 10, b'\x00',
                 profile().replace(b'inuse_space', b'alloc_space'),
                 profile() + field(1, 1), profile() + field(6, 1)]
        for data in cases:
            with self.subTest(data=data[-12:]), self.assertRaises(ValueError):
                heap.summarize(data)

    def test_cli_retains_two_complete_samples_after_interrupted_tail(self):
        with scratch_directory('plico-heap-cli-') as directory:
            for n in (1, 2, 3):
                (directory / f'siso-memory.{n:04d}.pprof').write_bytes(gzip.compress(profile()))
            tail = directory / 'siso-memory.0004.pprof'
            tail.write_bytes(gzip.compress(profile())[:-4])
            (directory / 'siso-memory.0005.pprof').write_bytes(
                b'\x1f\x8b\x08\x00' + bytes(6) + b'\x07' + bytes(8))
            output = io.StringIO()
            with patch('sys.argv', ['heap-reader', str(directory)]), redirect_stdout(output):
                heap.main()
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertIn('error', rows[0])
            self.assertIn('error', rows[1])
            self.assertEqual([r['profile'] for r in rows[2:]],
                             ['siso-memory.0002.pprof', 'siso-memory.0003.pprof'])
            self.assertTrue(all(r['sampled_total_bytes'] == 1500 for r in rows[2:]))

    def test_gzip_integrity_and_size_bound(self):
        with scratch_directory('plico-heap-test-') as directory:
            p = directory / 'heap.pprof'
            p.write_bytes(gzip.compress(profile()))
            self.assertEqual(heap.read_profile(p)['sampled_total_bytes'], 1500)
            with patch.object(heap, 'MAX_PROFILE_BYTES', 16), self.assertRaises(ValueError):
                heap.read_profile(p)
            p.write_bytes(p.read_bytes()[:-4])
            with self.assertRaises(EOFError):
                heap.read_profile(p)


if __name__ == '__main__':
    unittest.main()
