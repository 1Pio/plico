#!/usr/bin/env python3
"""Exercise patch refresh and preservation using tiny throwaway source trees."""
import difflib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from scratch import scratch_directory
import unittest

SCRIPT = Path(__file__).with_name('apply-downstream.py')

class DownstreamTest(unittest.TestCase):
    def setUp(self):
        self.temporary = scratch_directory(prefix='plico-overlay-test-')
        self.root = self.temporary.__enter__()
        for name in ('scripts', 'build/src', 'plico/patches'):
            (self.root / name).mkdir(parents=True)
        shutil.copy2(SCRIPT, self.root / 'scripts/apply-downstream.py')
        shutil.copy2(SCRIPT.with_name('scratch.py'), self.root / 'scripts/scratch.py')
        subprocess.run(['git', 'init', '-q', str(self.root / 'build/src')], check=True)
        (self.root / 'build/src/a.cc').write_text('upstream a\n')
        (self.root / 'build/src/b.cc').write_text('upstream b\n')
        (self.root / 'plico/core.cc').write_text('version 1\n')
        self.patch({'a.cc': 'plico a\n', 'b.cc': 'plico b\n'})

    def tearDown(self):
        self.temporary.__exit__(None, None, None)

    def patch(self, changes):
        text = []
        for name, new in changes.items():
            old = f'upstream {name[0]}\n'
            text.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                           fromfile='a/' + name, tofile='b/' + name))
        (self.root / 'plico/patches/0001-native-navigation.patch').write_text(''.join(text))
        (self.root / 'plico/patches/manifest.json').write_text(json.dumps({'touched_upstream_files': list(changes)}))

    def run_apply(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'scripts/apply-downstream.py'), *args],
                              capture_output=True, text=True)

    def test_check_is_read_only_and_apply_is_repeatable(self):
        result = self.run_apply('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'build/src/a.cc').read_text(), 'upstream a\n')
        self.assertFalse((self.root / 'build/src/plico').exists())
        self.assertEqual(self.run_apply().returncode, 0)
        stamp = (self.root / 'build/src/a.cc').stat().st_mtime_ns
        self.assertEqual(self.run_apply().returncode, 0)
        self.assertEqual((self.root / 'build/src/a.cc').stat().st_mtime_ns, stamp)
        (self.root / 'plico/core.cc').write_text('version 2\n')
        self.assertEqual(self.run_apply().returncode, 0)
        self.assertEqual((self.root / 'build/src/plico/core.cc').read_text(), 'version 2\n')

    def test_refresh_removes_obsolete_patch_hunks(self):
        self.assertEqual(self.run_apply().returncode, 0)
        self.patch({'a.cc': 'plico next\n'})
        result = self.run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'build/src/a.cc').read_text(), 'plico next\n')
        self.assertEqual((self.root / 'build/src/b.cc').read_text(), 'upstream b\n')

    def test_local_edits_are_preserved(self):
        self.assertEqual(self.run_apply().returncode, 0)
        target = self.root / 'build/src/plico/core.cc'
        target.write_text('local investigation\n')
        self.assertNotEqual(self.run_apply().returncode, 0)
        self.assertEqual(target.read_text(), 'local investigation\n')
        target.write_text('version 1\n')
        target = self.root / 'build/src/a.cc'
        target.write_text('local upstream investigation\n')
        self.assertNotEqual(self.run_apply().returncode, 0)
        self.assertEqual(target.read_text(), 'local upstream investigation\n')

if __name__ == '__main__':
    unittest.main(verbosity=2)
