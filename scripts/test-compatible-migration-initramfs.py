#!/usr/bin/env python3
"""Execute initramfs-tools hook dispatch in an isolated temporary chroot."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap', REPO / 'scripts/build-compatible-migration-initramfs.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('busybox'), 'requires root and busybox on Linux')
class DispatchTests(unittest.TestCase):
    def test_missing_order_reproduces_fatal_dispatch_and_fixed_hook_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bin').mkdir()
            shutil.copyfile(shutil.which('busybox'), root / 'bin/busybox')
            (root / 'bin/busybox').chmod(0o755)
            libraries = subprocess.run(['ldd', shutil.which('busybox')], capture_output=True, text=True)
            for name in re.findall(r'(/[^\s()]+)', libraries.stdout):
                library = root / name.lstrip('/')
                library.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(name, library)
            (root / 'bin/sh').symlink_to('busybox')
            (root / 'scripts/local-bottom').mkdir(parents=True)
            (root / 'conf').mkdir()
            # The real initramfs-tools dispatch implementation, taken from the
            # trusted bootstrap: sourcing a missing ORDER is fatal to its shell.
            functions = 'run_scripts() { initdir=${1}; [ ! -d "${initdir}" ] && return; shift; . "${initdir}/ORDER"; }\n'
            (root / 'scripts/functions').write_text(functions)
            command = ['chroot', str(root), '/bin/sh', '-c',
                       'export rootmnt=/root; . /scripts/functions; run_scripts /scripts/local-bottom; echo DISPATCH_OK']
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('ORDER', failed.stderr)
            bootstrap.install_root_slot_hook(root)
            fixed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(fixed.returncode, 0, fixed.stderr)
            self.assertEqual(fixed.stdout.strip(), 'DISPATCH_OK')
            # Exercise an existing ORDER too: keep earlier hooks and avoid
            # executing the selector twice on rebuild (which triggers rollback).
            order = root / 'scripts/local-bottom/ORDER'
            order.write_text('echo EXISTING_HOOK\n' + order.read_text())
            bootstrap.install_root_slot_hook(root)
            bootstrap.install_root_slot_hook(root)
            self.assertEqual(order.read_text().count('/scripts/local-bottom/gts9u-root-slot "$@"'), 1)
            kept = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(kept.returncode, 0, kept.stderr)
            self.assertEqual(kept.stdout.splitlines(), ['EXISTING_HOOK', 'DISPATCH_OK'])


if __name__ == '__main__':
    unittest.main()
