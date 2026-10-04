#!/usr/bin/env python3
"""Exercise the packaged early Plymouth hook without using a display or disk."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

HOOK = Path(__file__).resolve().parents[1] / (
    'packaging/ubuntu-gts9u-device/usr/share/initramfs-tools/hooks/zz-gts9u-plymouth')


class PlymouthHookTests(unittest.TestCase):
    def test_normal_and_previously_patched_launchers(self):
        for existing in ('', ' --graphical-boot',
                         ' --graphical-boot --ignore-serial-consoles'):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'scripts/init-premount/plymouth'
                target.parent.mkdir(parents=True)
                original = '/usr/sbin/plymouthd --mode=boot --pid-file=/run/plymouth/pid'
                target.write_text('#!/bin/sh\n\t' + original + existing + '\n'
                                  '/usr/bin/plymouth --show-splash\n')
                env = dict(os.environ, DESTDIR=tmp)
                for _ in range(2):
                    subprocess.run(['sh', str(HOOK)], env=env, check=True)
                lines = target.read_text().splitlines()
                command = shlex.split(lines[1])
                self.assertEqual(command[:3], shlex.split(original))
                for flag in ('--graphical-boot', '--ignore-serial-consoles'):
                    self.assertEqual(command.count(flag), 1)
                self.assertEqual(lines[2], '/usr/bin/plymouth --show-splash')

    def test_missing_launcher_rejects_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'scripts/init-premount/plymouth'
            target.parent.mkdir(parents=True)
            target.write_text('#!/bin/sh\nexit 0\n')
            result = subprocess.run(['sh', str(HOOK)], env=dict(os.environ, DESTDIR=tmp),
                                    capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_prerequisites_do_not_require_destination(self):
        env = dict(os.environ)
        env.pop('DESTDIR', None)
        subprocess.run(['sh', str(HOOK), 'prereqs'], env=env, check=True,
                       stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    unittest.main()
