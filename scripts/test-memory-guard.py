#!/usr/bin/env python3
"""Small real-process regressions; no compiler or large allocation is started."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from scratch import scratch_directory
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

GUARD = Path(__file__).with_name("memory-guard.py")
spec = importlib.util.spec_from_file_location("memory_guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

# Small process fixtures use deterministic system samples. Native footprint
# accounting, signals, and process ownership remain real. This does not grant a
# compiler permission to run under pressure; live preflight is checked separately.
ENTRY = f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location('guard', {str(GUARD)!r})
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
guard.system_memory = lambda: (80, 0)
guard.kernel_pressure = lambda: 1
"""


def prefix(overrides=''):
    return [sys.executable, '-c', ENTRY + overrides + '\nsys.exit(guard.main())']


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError("Timed out waiting for process state")


class MemoryGuardTest(unittest.TestCase):
    def run_guard(self, payload, *, interrupt=None, threshold=None, flags=(), overrides=""):
        with scratch_directory(prefix="plico-guard-test-") as temp:
            root = Path(temp)
            payload = f"""
import importlib.util
spec = importlib.util.spec_from_file_location('guard', {str(GUARD)!r})
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
def save_pid(root, name, pid):
    identity = guard.process_identity(pid)
    assert identity is not None
    (root / name).write_text(f'{{pid}}:{{identity}}')
""" + payload
            command = prefix(overrides) + ["--log", str(root / "memory.jsonl"), *flags]
            if threshold:
                command += ["--max-build-mib", str(threshold)]
            command += ["--", sys.executable, "-c", payload, str(root)]
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True)
            try:
                if interrupt:
                    wait_until(lambda: (root / "child").exists())
                    # Allow the monitor to observe the child before the signal.
                    time.sleep(1.1)
                    proc.send_signal(interrupt)
                _, stderr = proc.communicate(timeout=30)
                for pid_file in root.glob("pid-*"):
                    pid, identity = map(int, pid_file.read_text().split(":"))
                    wait_until(lambda: guard.process_identity(pid) != identity)
                if threshold and proc.returncode == 75:
                    records = [json.loads(line) for line in (root / "memory.jsonl").read_text().splitlines()]
                    stop = next(record for record in records if "stop_reason" in record)
                    self.assertTrue(stop["owned_processes"])
                    self.assertIn("executable", stop["owned_processes"][0])
                return proc.returncode, stderr
            finally:
                # Cleanup is independent of the tested guard if a regression fails.
                for pid_file in root.glob("pid-*"):
                    try:
                        pid, identity = map(int, pid_file.read_text().split(":"))
                        if guard.process_identity(pid) == identity:
                            os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_success_and_limits_propagate(self):
        payload = """
import os, multiprocessing
assert multiprocessing.cpu_count() == 1
assert os.environ['NODE_OPTIONS'] == '--max-old-space-size=2048'
assert os.environ['GRIT_DISABLE_MULTIPROCESSING'] == '1'
assert os.environ['GOMEMLIMIT'] == '1536MiB'
"""
        self.assertEqual(self.run_guard(payload)[0], 0)

    def test_low_threshold_stops_without_large_allocation(self):
        code, stderr = self.run_guard("import time; time.sleep(20)", threshold=1)
        self.assertEqual(code, 75, stderr)

    def test_signals_do_not_abandon_child(self):
        payload = """
import os, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
save_pid(root, 'pid-child', os.getpid())
(root / 'child').touch()
time.sleep(25)
"""
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig):
                code, stderr = self.run_guard(payload, interrupt=sig)
                self.assertEqual(code, 128 + sig, stderr)

    def test_normal_scheduler_exit_cleans_worker(self):
        payload = """
import pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(25)'])
save_pid(root, 'pid-worker', child.pid)
time.sleep(1.5)
"""
        code, stderr = self.run_guard(payload)
        self.assertEqual(code, 0, stderr)

    def test_escalation_reaches_detached_stubborn_worker(self):
        payload = """
import pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
child = subprocess.Popen([sys.executable, '-c', '''
import signal, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(25)
'''], start_new_session=True)
save_pid(root, 'pid-worker', child.pid)
time.sleep(1.5)
"""
        code, stderr = self.run_guard(payload)
        self.assertEqual(code, 0, stderr)

    def test_discovery_failure_still_stops_owned_child(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'],
                                 start_new_session=True, stderr=subprocess.DEVNULL)
        owned = guard.OwnedProcesses(child)
        owned.refresh()
        try:
            with patch.object(guard, 'process_tree', side_effect=OSError('injected ps failure')):
                guard.stop_group(owned, delays=(.2, .2, .2))
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

    def test_reused_root_does_not_capture_unrelated_descendants(self):
        class Exited:
            pid = 123
            returncode = 0
        owned = guard.OwnedProcesses(Exited())
        owned.identities = {123: 1, 100: 2}
        with patch.object(guard, 'process_identity', side_effect=lambda pid: {123: 3, 124: 4, 100: 2}.get(pid)), \
             patch.object(guard.subprocess, 'check_output', return_value='123 1 123\n124 123 123\n100 1 100\n'), \
             patch.object(guard.os, 'getpgid', return_value=100), \
             patch.object(guard.os, 'killpg') as group_signal, \
             patch.object(guard.os, 'kill') as pid_signal:
            self.assertEqual(owned.refresh(), {100})
            owned.signal(signal.SIGTERM)
            group_signal.assert_not_called()
            pid_signal.assert_called_once_with(100, signal.SIGTERM)

    def test_host_limit_refuses_child_launch(self):
        if guard.host_app() is None:
            self.skipTest("Not running within the desktop app")
        with scratch_directory(prefix='plico-host-limit-') as temp:
            root = Path(temp)
            child_code = f"from pathlib import Path; Path({str(root / 'started')!r}).touch()"
            result = subprocess.run(prefix() + ['--max-host-mib', '1',
                '--log', str(root / 'memory.jsonl'), '--', sys.executable, '-c', child_code],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('exceeding 1 MiB', result.stdout)
            self.assertFalse((root / 'started').exists())

    def test_shared_directory_rejects_concurrent_guard(self):
        with scratch_directory(prefix='plico-build-lock-') as temp:
            root = Path(temp)
            marker = root / 'started'
            guard_command = prefix() + ['--log', str(root / 'memory.jsonl'), '--']
            child_code = f"from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(2)"
            first = subprocess.Popen(guard_command + [sys.executable, '-c', child_code],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait_until(marker.exists)
                second = subprocess.run(guard_command + [sys.executable, '-c', 'pass'],
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(second.returncode, 0)
                self.assertIn('already using this build directory', second.stderr)
            finally:
                first.wait(timeout=10)


    def test_kernel_warning_stops_owned_process(self):
        code, stderr = self.run_guard('import time; time.sleep(20)',
            overrides="levels = iter([1, 2]); guard.kernel_pressure = lambda: next(levels)")
        self.assertEqual(code, 75, stderr)
        self.assertIn('kernel memory pressure is Warning', stderr)

    def test_independent_mode_rejects_desktop_app_ancestry(self):
        code, stderr = self.run_guard('raise AssertionError("must not run")',
            flags=('--independent',), overrides='guard.host_app = lambda: (123, 456)')
        self.assertNotEqual(code, 0)
        self.assertIn('requires launchd ancestry', stderr)

    def test_independent_mode_finishes_without_a_host_and_cleans_timed_work(self):
        code, stderr = self.run_guard('import time; time.sleep(20)',
            flags=('--independent', '--max-runtime-seconds', '1'),
            overrides='guard.host_app = lambda: None; guard.app_processes = lambda: set()')
        self.assertEqual(code, 124, stderr)

    def test_headroom_wait_expires_without_starting_payload(self):
        code, stderr = self.run_guard('raise AssertionError("must not run")',
            flags=('--independent', '--wait-for-headroom-seconds', '1'),
            overrides='guard.host_app = lambda: None; guard.app_processes = lambda: set(); guard.kernel_pressure = lambda: 2')
        self.assertEqual(code, 75, stderr)
        self.assertNotIn('must not run', stderr)

    def test_readiness_keeps_each_existing_limit_and_ac_gate(self):
        args = SimpleNamespace(min_free_percent=35, max_host_mib=14336,
            require_ac_power=True, max_build_mib=6144, max_swap_growth_mib=512)
        self.assertIsNone(guard.readiness_reason(45, 1, 14336, args))
        for free, pressure, mib, ac in ((44,1,1,True), (80,2,1,True),
                                      (80,4,1,True), (80,1,14337,True), (80,1,1,False)):
            self.assertIsNotNone(guard.readiness_reason(free, pressure, mib, args, ac))
        self.assertIsNotNone(guard.breach(80, 513, 0, 1, args, 1))
        self.assertIsNotNone(guard.breach(80, 0, 0, 6145, args, 1))
        self.assertIsNotNone(guard.breach(80, 0, 0, 1, args, 14337))

    def test_app_discovery_reconciles_new_instances_by_start_identity(self):
        with patch.object(guard.subprocess, 'check_output', return_value='10 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT\n11 /other/app\n'), \
             patch.object(guard, 'process_identity', return_value=100), \
             patch.object(guard, 'process_tree', return_value={10,12}) as tree:
            self.assertEqual(guard.app_processes(), {10,12})
            tree.assert_called_once_with(None, {10:100}, {10:100})
        with patch.object(guard.subprocess, 'check_output', return_value='20 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT\n'), \
             patch.object(guard, 'process_identity', return_value=200), \
             patch.object(guard, 'process_tree', return_value={20}) as tree:
            self.assertEqual(guard.app_processes(), {20})
            tree.assert_called_once_with(None, {20:200}, {20:200})

    def test_status_write_failure_after_spawn_still_cleans_child(self):
        overrides = r"""
from pathlib import Path
original_popen = guard.subprocess.Popen
def tracked_popen(*a, **kw):
    child = original_popen(*a, **kw)
    if kw.get('start_new_session'):
        (Path(sys.argv[-1]) / 'pid-spawned').write_text(f'{child.pid}:{guard.process_identity(child.pid)}')
    return child
guard.subprocess.Popen = tracked_popen
original_status = guard.write_status
def failing_status(path, **values):
    if values.get('state') == 'running': raise OSError('injected status failure')
    original_status(path, **values)
guard.write_status = failing_status
"""
        code, stderr = self.run_guard('import time; time.sleep(20)', overrides=overrides)
        self.assertNotEqual(code, 0)
        self.assertIn('injected status failure', stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
