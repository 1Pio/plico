#!/usr/bin/env python3
"""Run one guarded Plico build under the user's launchd, without auto-restarts."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'dev.plico.guarded-build'
DOMAIN = f'gui/{os.getuid()}'
SERVICE = f'{DOMAIN}/{LABEL}'
LOGS = ROOT / 'build/logs'
PLIST = ROOT / 'build/launchd' / (LABEL + '.plist')


def service_state():
    result = subprocess.run(['/bin/launchctl', 'print', SERVICE],
                            capture_output=True, text=True)
    if result.returncode:
        return {'loaded': False, 'pid': None}
    match = re.search(r'^\s*pid = (\d+)\s*$', result.stdout, re.MULTILINE)
    return {'loaded': True, 'pid': int(match[1]) if match else None}


def supervision_health(service, record, now=None):
    """A historical running record is not proof of a live monitor."""
    now = time.time() if now is None else now
    if record is None:
        return {'health': 'starting' if service.get('pid') else 'unavailable'}
    age = max(0, now - record.get('time', 0))
    state = record.get('state')
    if service.get('pid') and service['pid'] != record.get('pid'):
        health = 'starting'
    elif state in ('running', 'waiting'):
        if not service.get('pid'):
            health = 'supervision_lost'
        elif age > 10:
            health = 'stale'
        else:
            health = state
    else:
        health = state or 'unavailable'
    return {'health': health, 'status_age_seconds': round(age, 1)}


def job_definition(jobs, wait_seconds, runtime_seconds, log):
    return {
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/caffeinate', '-s', '/bin/bash', str(ROOT / 'scripts/build.sh')],
        'WorkingDirectory': str(ROOT),
        'EnvironmentVariables': {
            'PATH': f'{ROOT}/build/venv/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
            'PLICO_GUARD_MODE': 'independent',
            'PLICO_BUILD_JOBS': str(jobs),
            'PLICO_WAIT_FOR_HEADROOM_SECONDS': str(wait_seconds),
            'PLICO_MAX_RUNTIME_SECONDS': str(runtime_seconds),
        },
        'RunAtLoad': True,
        'KeepAlive': False,
        'ExitTimeOut': 30,
        'StandardOutPath': str(log),
        'StandardErrorPath': str(log),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--jobs', type=int, choices=(1, 2, 3), default=2)
    parser.add_argument('--wait-seconds', type=int, default=43200)
    parser.add_argument('--runtime-seconds', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 43200 or args.runtime_seconds < 0:
        parser.error('Invalid wait or runtime limit')
    if args.jobs == 3 and not 0 < args.runtime_seconds <= 600:
        parser.error('Three jobs require a bounded calibration runtime of 1 to 600 seconds')
    if args.action == 'status':
        execute(args)
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / 'unattended-controller.lock').open('a') as controller_lock:
        try:
            fcntl.flock(controller_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another Plico controller operation is in progress.')
        execute(args)


def execute(args):
    state = service_state()
    if args.action == 'status':
        path = LOGS / 'unattended-status.json'
        record = json.loads(path.read_text()) if path.exists() else None
        print(json.dumps({**state, **supervision_health(state, record), 'guard': record}, indent=2))
        return
    if args.action == 'stop':
        if state['loaded']:
            subprocess.run(['/bin/launchctl', 'bootout', SERVICE], check=True)
        print('Owned launchd job unloaded. Inspect telemetry to confirm worker cleanup.')
        return
    if state['pid']:
        raise SystemExit(f'Plico supervision is already running as PID {state["pid"]}.')
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / 'memory-guard.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another guarded Plico operation is active; no job started.')
    if state['loaded']:
        subprocess.run(['/bin/launchctl', 'bootout', SERVICE], check=True)
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    log = LOGS / f'plico-unattended-{run_id}.log'
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    temporary = PLIST.with_suffix('.plist.tmp')
    with temporary.open('wb') as stream:
        plistlib.dump(job_definition(args.jobs, args.wait_seconds, args.runtime_seconds, log), stream)
    temporary.chmod(0o600)
    temporary.replace(PLIST)
    subprocess.run(['/bin/launchctl', 'bootstrap', DOMAIN, str(PLIST)], check=True)
    print(json.dumps({'service': SERVICE, 'plist': str(PLIST), 'log': str(log),
                      'jobs': args.jobs, 'automatic_restart': False}, indent=2))


if __name__ == '__main__':
    main()
