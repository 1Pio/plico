#!/usr/bin/env python3
"""Validate the Plico patch in a scratch tree, then apply it under the build lock."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from scratch import scratch_directory

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true', help='Only validate; do not modify build/src')
args = parser.parse_args()
source = root / 'build/src'
patch = root / 'plico/patches/0001-native-navigation.patch'
manifest = json.loads((root / 'plico/patches/manifest.json').read_text())
logs = root / 'build/logs'
logs.mkdir(parents=True, exist_ok=True)
lock = (logs / 'memory-guard.lock').open('a')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('A guarded build/check is active. Source updates must wait until it stops.')

def run_patch(directory, patch_path, *options, check=True):
    return subprocess.run(['git', 'apply', *options, str(patch_path)],
                          cwd=directory, check=check, capture_output=True, text=True)

applied = root / 'build/plico-applied.patch'
paths = set(manifest['touched_upstream_files'])
if applied.exists():
    paths.update(line[6:] for line in applied.read_text().splitlines()
                 if line.startswith('--- a/'))
paths = sorted(paths)
for name in paths:
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise SystemExit('Unsafe downstream manifest path')
before = {name: hashlib.sha256((source / name).read_bytes()).digest() for name in paths}
overlay_state = root / 'build/plico-overlay.json'
previous_overlay = json.loads(overlay_state.read_text()) if overlay_state.exists() else {}
overlay = {}
for path in (root / 'plico').rglob('*'):
    if not path.is_file() or 'patches' in path.relative_to(root / 'plico').parts:
        continue
    if path.is_symlink():
        raise SystemExit(f'Refusing a symlinked source file: {path}')
    name = str(path.relative_to(root / 'plico'))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    destination = source / 'plico' / name
    if destination.exists():
        current = hashlib.sha256(destination.read_bytes()).hexdigest()
        if current != digest and current != previous_overlay.get(name):
            raise SystemExit(f'Generated source was edited locally; preserving plico/{name}')
    overlay[name] = digest

# Prove the whole transition before changing the working source, including when
# replacing an earlier downstream patch. The snapshot is bounded to touched files.
with scratch_directory(prefix='plico-patch-check-') as temporary:
    scratch = Path(temporary)
    subprocess.run(['git', 'init', '-q', str(scratch)], check=True)
    for name in paths:
        target = scratch / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    if applied.exists():
        result = run_patch(scratch, applied, '--reverse', check=False)
        if result.returncode:
            raise SystemExit('Existing downstream source has diverged; preserving it.\n' + result.stderr)
    result = run_patch(scratch, patch, check=False)
    if result.returncode:
        raise SystemExit('Downstream patch does not apply to this source.\n' + result.stderr)
    run_patch(scratch, patch, '--reverse', '--check')
    if args.check:
        print(f'Validated apply and reverse for {len(paths)} touched files; source unchanged.')
        raise SystemExit(0)

    # Compare again before mutation to preserve concurrent manual source edits.
    if applied.exists():
        run_patch(source, applied, '--reverse', '--check')
    if before != {name: hashlib.sha256((source / name).read_bytes()).digest() for name in paths}:
        raise SystemExit('Source changed during patch validation; preserving it.')
    unchanged = applied.exists() and applied.read_bytes() == patch.read_bytes()
    if not unchanged:
        if applied.exists():
            run_patch(source, applied, '--reverse')
        try:
            run_patch(source, patch)
        except subprocess.CalledProcessError:
            if applied.exists():
                run_patch(source, applied)
            raise
        shutil.copy2(patch, applied)

for path in (root / 'plico').rglob('*'):
    if not path.is_file() or 'patches' in path.relative_to(root / 'plico').parts:
        continue
    destination = source / 'plico' / path.relative_to(root / 'plico')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_bytes() != path.read_bytes():
        shutil.copy2(path, destination)
overlay_state.write_text(json.dumps(overlay, sort_keys=True, indent=2) + '\n')
print('Applied downstream patch and synchronized native source. Regenerate GN before building.')
