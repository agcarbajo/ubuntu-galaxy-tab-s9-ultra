#!/usr/bin/env python3
"""Protocol tests for the TCG harness; these do not execute a real guest."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HARNESS = Path(__file__).resolve().parents[1] / 'scripts/test-qemu-tcg-linux.py'
FIXTURE = '''#!/usr/bin/env python3
import os, sys, time
print("Enter 'help' for a list of built-in commands.", flush=True)
command = sys.stdin.readline()
mode = os.environ['TCG_FIXTURE_MODE']
if mode == 'timeout':
    time.sleep(10)
elif mode == 'echo':
    print(command, flush=True)
else:
    print('GUEST_SHELL_READY\\naarch64\\nGUEST_PROBE_COMPLETE', flush=True)
if mode != 'no_poweroff':
    print('[1.0] reboot: Power down', flush=True)
sys.exit(2 if mode == 'failed_exit' else 0)
'''


@unittest.skipUnless(os.name == 'posix', 'fixture uses a POSIX executable')
class HarnessTests(unittest.TestCase):
    def run_fixture(self, mode):
        with tempfile.TemporaryDirectory(prefix='tcg-harness-test-') as tmp:
            root = Path(tmp)
            executable = root / 'qemu-fixture'
            executable.write_text(FIXTURE)
            executable.chmod(0o700)
            kernel, initrd = root / 'Image', root / 'initrd'
            kernel.touch()
            initrd.touch()
            result = subprocess.run([
                sys.executable, str(HARNESS), '--qemu', str(executable),
                '--kernel', str(kernel), '--initrd', str(initrd),
                '--log', str(root / 'test.log'), '--timeout', '1',
            ], env={**os.environ, 'TCG_FIXTURE_MODE': mode},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
            return result.returncode, result.stdout.decode()

    def test_success(self):
        rc, output = self.run_fixture('success')
        self.assertEqual(rc, 0, output)
        self.assertIn('TCG_SHELL_PASS=True', output)

    def test_echo_does_not_count_as_guest_output(self):
        rc, output = self.run_fixture('echo')
        self.assertNotEqual(rc, 0, output)

    def test_requires_poweroff(self):
        rc, output = self.run_fixture('no_poweroff')
        self.assertNotEqual(rc, 0, output)

    def test_failed_exit(self):
        rc, output = self.run_fixture('failed_exit')
        self.assertNotEqual(rc, 0, output)

    def test_timeout(self):
        rc, output = self.run_fixture('timeout')
        self.assertNotEqual(rc, 0, output)
        self.assertIn('TIMEOUT=True', output)


if __name__ == '__main__':
    unittest.main()
