#!/usr/bin/env python3
"""Verify the memory-guard boundary and explicit, bounded compiler concurrency."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from scratch import scratch_directory

SCRIPT = Path(__file__).with_name('build.sh')


class BuildWrapperTest(unittest.TestCase):
    def setUp(self):
        self.temporary = scratch_directory(prefix='plico-build-wrapper-test-')
        self.root = self.temporary.__enter__()
        for name in ('scripts', 'build/src/out/Default', 'build/venv/bin'):
            (self.root / name).mkdir(parents=True)
        shutil.copy2(SCRIPT, self.root / 'scripts/build.sh')
        (self.root / 'build/src/out/Default/build.ninja').write_text('# test fixture\n')
        fake_python = self.root / 'build/venv/bin/python3'
        fake_python.write_text(
            '#!' + sys.executable + '\nimport json, os, sys\n'
            'print(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}))\n')
        fake_python.chmod(0o700)

    def tearDown(self):
        self.temporary.__exit__(None, None, None)

    def run_wrapper(self, jobs=None, *targets):
        env = os.environ.copy()
        env.pop('PLICO_BUILD_JOBS', None)
        if jobs is not None:
            env['PLICO_BUILD_JOBS'] = jobs
        return subprocess.run(['bash', str(self.root / 'scripts/build.sh'), *targets],
                              env=env, capture_output=True, text=True)

    def test_each_supported_count_retains_guard_and_explicit_siso_limit(self):
        for jobs in (None, '1', '2', '3'):
            with self.subTest(jobs=jobs):
                result = self.run_wrapper(jobs)
                self.assertEqual(result.returncode, 0, result.stderr)
                capture = json.loads(result.stdout)
                self.assertEqual(Path(capture['cwd']).resolve(), (self.root / 'build/src').resolve())
                self.assertEqual(capture['argv'], [
                    str(self.root / 'scripts/memory-guard.py'), '--log',
                    str(self.root / 'build/logs/build-memory.jsonl'), '--',
                    'python3', 'third_party/depot_tools/autoninja.py', '-C',
                    'out/Default', '-local_jobs=' + (jobs or '2'),
                    '-fs_state_compression_threads=1', 'chrome', 'chromedriver'])

    def test_unsafe_counts_are_rejected_before_starting_guard(self):
        for jobs in ('0', '4', '15', '-1', '2.5', '02', '9999999999999999999999'):
            with self.subTest(jobs=jobs):
                result = self.run_wrapper(jobs)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')

    def test_targets_cannot_override_limits(self):
        for option in ('-j15', '-local_jobs=15', '--max-build-mib=999999'):
            with self.subTest(option=option):
                result = self.run_wrapper('2', option)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')

    def test_narrow_targets_keep_the_same_guard(self):
        result = self.run_wrapper('2', 'obj/plico/native.o')
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(result.stdout)['argv']
        self.assertEqual(argv[0], str(self.root / 'scripts/memory-guard.py'))
        self.assertEqual(argv[-1], 'obj/plico/native.o')
        self.assertIn('-local_jobs=2', argv)


if __name__ == '__main__':
    unittest.main(verbosity=2)
