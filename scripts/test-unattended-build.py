#!/usr/bin/env python3
"""Qualify launchd independence and cleanup with a harmless, bounded payload."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guard', ROOT / 'scripts/memory-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
OUT = ROOT / 'build/qualification/supervision'
OUT.mkdir(parents=True, exist_ok=True)
label = f'dev.plico.supervision-probe-{os.getpid()}'
service = f'gui/{os.getuid()}/{label}'
status = OUT / f'{label}.json'
probe = OUT / f'{label}.py'
log = OUT / f'{label}.log'
plist = OUT / f'{label}.plist'
# Deterministic system samples apply only to this no-allocation test process.
# Actual ancestry, native footprint accounting, ownership and launchd are real.
probe.write_text(f'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location('guard', {str(ROOT / 'scripts/memory-guard.py')!r})
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
assert guard.host_app() is None, 'Probe is still owned by the desktop app'
guard.system_memory = lambda: (80, 0)
guard.kernel_pressure = lambda: 1
sys.exit(guard.main())
''')
arguments = ['/usr/bin/caffeinate', '-s', sys.executable, str(probe),
             '--independent', '--max-build-mib', '64', '--max-runtime-seconds', '20',
             '--log', str(OUT / (label + '.jsonl')), '--status', str(status),
             '--', sys.executable, '-c', 'import time; time.sleep(60)']
with plist.open('wb') as stream:
    plistlib.dump({'Label': label, 'ProgramArguments': arguments,
                  'RunAtLoad': True, 'KeepAlive': False, 'ExitTimeOut': 30,
                  'StandardOutPath': str(log), 'StandardErrorPath': str(log)}, stream)
plist.chmod(0o600)
identities = {}
loaded = False
try:
    subprocess.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)], check=True)
    loaded = True
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if status.exists():
            state = json.loads(status.read_text())
            if state.get('state') == 'running':
                break
        time.sleep(.1)
    else:
        raise RuntimeError('Probe did not run: ' + (log.read_text() if log.exists() else 'no log'))
    assert state['independent']
    for pid in (state['pid'], state['child_pid']):
        identities[pid] = guard.process_identity(pid)
        assert identities[pid] is not None
    # The bootstrap caller has returned, but the launchd-owned job remains live.
    time.sleep(1)
    assert all(guard.process_identity(pid) == identity for pid, identity in identities.items())
    subprocess.run(['/bin/launchctl', 'bootout', service], check=True)
    loaded = False
    deadline = time.monotonic() + 12
    while any(guard.process_identity(pid) == identity for pid, identity in identities.items()):
        if time.monotonic() >= deadline:
            raise RuntimeError('Owned probe process survived launchd stop')
        time.sleep(.1)
    report = {'launchd_independent_ancestry': True, 'survived_bootstrap_caller': True,
              'guard_and_payload_cleaned_up': True, 'large_allocation': False,
              'pressure_samples': 'simulated only for this harmless probe',
              'status': json.loads(status.read_text())}
    (OUT / 'launchd-qualification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
finally:
    if loaded:
        subprocess.run(['/bin/launchctl', 'bootout', service], capture_output=True)
