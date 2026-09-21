#!/usr/bin/env python3
"""Recover lost archive timestamp precision only for hash-verified object files.

Schema: Chromium build bc45e8f67ae0f37d337190ad64aa8bb440c791eb,
siso/hashfs/proto/state.proto. This does not edit dependency logs or object bytes.
The command applies only to an identified, disposable object-probe restoration.
"""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SHA256 = 'd777ec2fafb4be162babbdf7c7b1b01210fb559940e763cca00fca7fba999ce2'
ORIGINAL_ROOT = '/Users/runner/work/helium-macos/helium-macos/build/src/'
NANOSECONDS = 1_000_000_000


def varint(stream):
    value = 0
    for offset in range(10):
        byte = stream.read(1)
        if not byte:
            if offset == 0:
                return None
            raise ValueError('Truncated protobuf varint')
        number = byte[0]
        if offset == 9 and number > 1:
            raise ValueError('Protobuf integer exceeds 64 bits')
        value |= (number & 127) << (offset * 7)
        if not number & 128:
            return value
    raise ValueError('Oversized protobuf varint')


def exact(stream, size):
    if size is None or size > 16 * 1024**2:
        raise ValueError('Invalid or oversized protobuf field')
    value = stream.read(size)
    if len(value) != size:
        raise ValueError('Truncated protobuf field')
    return value


def fields(stream):
    while (tag := varint(stream)) is not None:
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError('Invalid protobuf field number')
        if wire == 0:
            value = varint(stream)
            if value is None:
                raise ValueError('Missing protobuf integer')
        elif wire == 2:
            value = exact(stream, varint(stream))
        elif wire in (1, 5):
            value = exact(stream, 8 if wire == 1 else 4)
        else:
            raise ValueError('Unsupported protobuf wire type')
        yield number, value


def object_records(stream):
    records = {}
    digest_function = 0
    for number, value in fields(stream):
        if number == 6:
            digest_function = value
        if number != 1:
            continue
        entry = dict(fields(io.BytesIO(value)))
        name = entry.get(2, b'').decode()
        if not name.startswith(ORIGINAL_ROOT) or not name.endswith('.o'):
            continue
        if entry.get(5) or not entry.get(6):
            continue  # Never infer timestamps for symlinks or source inputs.
        relative = PurePosixPath(name[len(ORIGINAL_ROOT):])
        if '..' in relative.parts:
            raise ValueError('Unexpected archived object path')
        if relative.parts[:2] != ('out', 'Default'):
            continue  # Other build directories are outside this restoration.
        identity = dict(fields(io.BytesIO(entry.get(1, b''))))
        digest = dict(fields(io.BytesIO(entry.get(3, b''))))
        timestamp = identity.get(1)
        checksum = digest.get(1, b'').decode()
        size = digest.get(2)
        if not isinstance(timestamp, int) or timestamp <= 0 or size is None:
            raise ValueError('Missing object identity')
        if not re.fullmatch('[0-9a-f]{64}', checksum):
            raise ValueError('Missing SHA256 object digest')
        key = relative.as_posix()
        record = {'path': key, 'mtime_ns': timestamp, 'sha256': checksum, 'bytes': size}
        if key in records and records[key] != record:
            raise ValueError('Conflicting object identities')
        records[key] = record
    if digest_function not in (0, 1):  # REAPI UNKNOWN historical default / SHA256.
        raise ValueError('Checkpoint digest function is not SHA256')
    if not records:
        raise ValueError('No archived object identities found')
    return records.values()


def verify_objects(source, records):
    source = source.resolve(strict=True)
    plan = []
    already_precise = 0
    for record in records:
        path = source / record['path']
        if path.is_symlink() or path.resolve(strict=True) != path:
            raise ValueError('Object path crosses a symlink')
        if not path.is_relative_to(source):
            raise ValueError('Object path escapes the restored tree')
        before = path.stat()
        expected = record['mtime_ns']
        rounded = expected // NANOSECONDS * NANOSECONDS
        # Long PAX paths retain decimal fractional timestamps, but tarfile's
        # float-based os.utime introduces a reproducible sub-microsecond error.
        seconds, nanos = divmod(expected, NANOSECONDS)
        as_float = float(f'{seconds}.{nanos:09d}')
        float_restored = int(as_float) * NANOSECONDS + int((as_float - int(as_float)) * NANOSECONDS)
        if before.st_mtime_ns not in (rounded, expected, float_restored):
            raise ValueError('Object timestamp differs beyond archive precision loss: ' + record['path'])
        if before.st_size != record['bytes']:
            raise ValueError('Object size mismatch: ' + record['path'])
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Object changed during verification')
        if checksum != record['sha256']:
            raise ValueError('Object SHA256 mismatch: ' + record['path'])
        if before.st_mtime_ns == expected:
            already_precise += 1
        else:
            plan.append((path, before, expected))
    return plan, already_precise


def recover(source, records, apply=False):
    # Verify every candidate before changing any timestamp.
    plan, already_precise = verify_objects(source, records)
    if apply:
        for path, before, timestamp in plan:
            current = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (current.st_ino, current.st_size, current.st_mtime_ns):
                raise ValueError('Object changed before timestamp restoration')
            os.utime(path, ns=(before.st_atime_ns, timestamp), follow_symlinks=False)
            if path.stat().st_mtime_ns != timestamp:
                raise ValueError('Filesystem did not retain exact timestamp')
    return {'hash_verified_objects': len(plan) + already_precise,
            'already_precise': already_precise,
            'timestamps_restored' if apply else 'timestamps_recoverable': len(plan),
            'scope': 'Timestamp metadata only; object bytes and dependency logs unchanged. Reuse still requires a dry run.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    destination = ROOT / 'build/reuse-qualification/restored'
    receipt = json.loads((destination / 'restoration.json').read_text())
    if receipt.get('zip_sha256') != ARCHIVE_SHA256 or receipt.get('object_probe') is not True:
        raise SystemExit('Requires the exact disposable object-probe restoration; complete/local builds are protected.')
    with (ROOT / 'build/logs/memory-guard.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A guarded operation is active; no timestamp metadata changed.')
        source = destination / 'src'
        state = source / 'out/Default/.siso_fs_state'
        decoder = subprocess.Popen(['zstd', '-dq', '-c', '-M128MB', str(state)], stdout=subprocess.PIPE)
        try:
            records = list(object_records(decoder.stdout))
            if decoder.wait(timeout=30):
                raise RuntimeError('State decompression failed')
        finally:
            decoder.stdout.close()
            if decoder.poll() is None:
                decoder.terminate()
                decoder.wait(timeout=10)
        report = recover(source, records, apply=args.apply)
        (ROOT / 'build/reuse-qualification/object-timestamp-recovery.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
