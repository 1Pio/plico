#!/usr/bin/env python3
"""Restore the verified upstream checkpoint into a new, isolated directory."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import threading
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inventory', ROOT / 'scripts/inspect-upstream-checkpoint.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)
DESTINATION = ROOT / 'build/reuse-qualification/restored'


def probe_only_output(name):
    parts = Path(name).parts
    return (len(parts) >= 4 and parts[:3] == ('src', 'out', 'Default')
            and '..' not in parts
            and (parts[3] == 'thinlto-cache' or parts[3].endswith('.dSYM')))


def restore(archive_path, destination, expected_digest, resume=False, object_probe=False):
    marker = destination / 'restoration-in-progress.json'
    if destination.is_symlink():
        raise RuntimeError('Refusing a symlinked restoration directory')
    if destination.exists():
        if not resume or (destination / 'restoration.json').exists() or not marker.exists():
            raise RuntimeError('Refusing to overwrite an existing restoration directory')
        previous = json.loads(marker.read_text())
        if previous.get('object_probe', False) != object_probe:
            raise RuntimeError('Existing partial restoration has a different restoration mode')
        if previous.get('zip_sha256') != expected_digest:
            raise RuntimeError('Existing partial restoration has a different archive identity')
    digest = hashlib.sha256()
    with archive_path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise RuntimeError('Archive digest mismatch; refusing restoration')
    # This pinned archive contains 5,555,202,258 bytes of link cache/debug
    # symbols. Omitting only those leaves 23.895 GiB of file payload and over
    # 6 GiB for filesystem overhead and reserve.
    required_gib = 30 if object_probe else 35
    if shutil.disk_usage(destination.parent).free < required_gib * 1024**3:
        raise RuntimeError(f'At least {required_gib} GiB free disk space is required')
    destination.mkdir(exist_ok=resume)
    marker.write_text(json.dumps({'zip_sha256': expected_digest, 'object_probe': object_probe}) + '\n')
    files = size = entries = 0
    errors, external_links = [], []
    omitted_files = omitted_bytes = 0
    with zipfile.ZipFile(archive_path) as archive:
        inner = archive.open('build_src.tar.zst')
        decoder = subprocess.Popen(['zstd', '-dq', '-c', '-M128MB'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        def feed():
            try:
                with inner, decoder.stdin:
                    while chunk := inner.read(256 * 1024):
                        decoder.stdin.write(chunk)
            except Exception as error:
                errors.append(type(error).__name__)
        producer = threading.Thread(target=feed)
        producer.start()
        try:
            with tarfile.open(fileobj=decoder.stdout, mode='r|') as tree:
                for item in tree:
                    name = item.name.removeprefix('./')
                    if name != 'src' and not name.startswith('src/'):
                        raise RuntimeError('Unexpected archive root: ' + name)
                    entries += 1
                    if item.isfile():
                        files += 1
                        size += item.size
                    if entries > 1500000 or size > 40 * 1024**3:
                        raise RuntimeError('Archive exceeds the bounded restoration size')
                    if object_probe and probe_only_output(name):
                        if item.isfile():
                            omitted_files += 1
                            omitted_bytes += item.size
                        tree.members.clear()
                        continue
                    # Python's data filter rejects escaping paths/links and devices.
                    try:
                        tree.extract(item, destination, filter='data')
                    except (tarfile.AbsoluteLinkError, tarfile.LinkOutsideDestinationError):
                        # SDK/log symlinks belong to the upstream runner. Record,
                        # but never create or follow them on the developer's Mac.
                        external_links.append({'path': name, 'target': item.linkname})
                    tree.members.clear()
                    if entries % 50000 == 0:
                        print(json.dumps({'entries': entries, 'bytes': size}), flush=True)
            while decoder.stdout.read(256 * 1024):
                pass
            producer.join(timeout=60)
            if producer.is_alive() or decoder.wait(timeout=30) or errors:
                raise RuntimeError('Checkpoint decompression did not complete cleanly')
        finally:
            decoder.stdout.close()
            if decoder.poll() is None:
                decoder.terminate()
                try:
                    decoder.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    decoder.kill()
                    decoder.wait(timeout=10)
            producer.join(timeout=10)
    report = {'zip_sha256': expected_digest,
              'files': files - omitted_files, 'bytes': size - omitted_bytes,
              'archive_files': files, 'archive_bytes': size,
              'entries': entries, 'destination': str(destination),
              'external_links_not_restored': external_links,
              'object_probe': object_probe,
              'probe_outputs_omitted': {'files': omitted_files, 'bytes': omitted_bytes},
              'restored_file_bytes': size - omitted_bytes,
              'scope': ('Object probe only: link cache and debug symbols omitted; not a complete build checkpoint.'
                        if object_probe else 'Verified archive restored only; no source overlay, build or reuse claimed.')}
    (destination / 'restoration.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true', help="Resume only this archive's identified partial restoration")
    parser.add_argument('--object-probe', action='store_true',
                        help='Omit only link cache and debug symbols for object-level dry runs')
    args = parser.parse_args()
    with (ROOT / 'build/logs/memory-guard.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A guarded operation is active; no restoration started.')
        print(json.dumps(restore(ROOT / inventory.ZIP, DESTINATION, inventory.SHA256, resume=args.resume, object_probe=args.object_probe), indent=2))


if __name__ == '__main__':
    main()
