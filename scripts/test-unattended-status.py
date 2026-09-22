#!/usr/bin/env python3
"""Prevent historical guard status from being presented as live supervision."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('controller', Path(__file__).with_name('unattended-build.py'))
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class UnattendedStatusTest(unittest.TestCase):
    def test_exited_launchd_job_cannot_report_running(self):
        record = {'time': 100, 'pid': 42, 'state': 'running'}
        result = controller.supervision_health({'loaded': True, 'pid': None}, record, now=101)
        self.assertEqual(result['health'], 'supervision_lost')

    def test_live_job_needs_fresh_telemetry_for_running_or_waiting(self):
        for state in ('running', 'waiting'):
            record = {'time': 100, 'pid': 42, 'state': state}
            service = {'loaded': True, 'pid': 42}
            self.assertEqual(controller.supervision_health(service, record, now=105)['health'], state)
            self.assertEqual(controller.supervision_health(service, record, now=111)['health'], 'stale')

    def test_previous_run_record_cannot_describe_new_supervisor(self):
        service = {'loaded': True, 'pid': 43}
        for state in ('running', 'waiting', 'cleanup_error'):
            record = {'time': 100, 'pid': 42, 'state': state}
            self.assertEqual(controller.supervision_health(service, record, now=101)['health'], 'starting')

    def test_terminal_failure_is_retained(self):
        self.assertEqual(controller.supervision_health({'pid': None},
            {'time': 100, 'state': 'cleanup_error'}, now=200)['health'], 'cleanup_error')
        self.assertEqual(controller.supervision_health({'pid': None}, None)['health'], 'unavailable')


if __name__ == '__main__':
    unittest.main(verbosity=2)
