#!/usr/bin/env python3
"""Small real-process regressions; no compiler or large allocation is started."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

GUARD = Path(__file__).with_name("memory-guard.py")
spec = importlib.util.spec_from_file_location("memory_guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError("Timed out waiting for process state")


class MemoryGuardTest(unittest.TestCase):
    def run_guard(self, payload, *, interrupt=None, threshold=None):
        with tempfile.TemporaryDirectory(prefix="plico-guard-test-") as temp:
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
            command = [sys.executable, str(GUARD), "--log", str(root / "memory.jsonl")]
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
        with tempfile.TemporaryDirectory(prefix='plico-host-limit-') as temp:
            root = Path(temp)
            child_code = f"from pathlib import Path; Path({str(root / 'started')!r}).touch()"
            result = subprocess.run([sys.executable, str(GUARD), '--max-host-mib', '1',
                '--log', str(root / 'memory.jsonl'), '--', sys.executable, '-c', child_code],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('host app already uses', result.stderr)
            self.assertFalse((root / 'started').exists())

    def test_shared_directory_rejects_concurrent_guard(self):
        with tempfile.TemporaryDirectory(prefix='plico-build-lock-') as temp:
            root = Path(temp)
            marker = root / 'started'
            prefix = [sys.executable, str(GUARD), '--log', str(root / 'memory.jsonl'), '--']
            child_code = f"from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(2)"
            first = subprocess.Popen(prefix + [sys.executable, '-c', child_code],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait_until(marker.exists)
                second = subprocess.run(prefix + [sys.executable, '-c', 'pass'],
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(second.returncode, 0)
                self.assertIn('already using this build directory', second.stderr)
            finally:
                first.wait(timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
