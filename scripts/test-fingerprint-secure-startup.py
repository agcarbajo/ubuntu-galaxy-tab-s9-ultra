#!/usr/bin/python3
"""Offline tests. No modules, secure devices, services or tablet are touched."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch, Mock

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / 'packaging/ubuntu-gts9u-device'
SCRIPT = PACKAGE / 'usr/libexec/ubuntu-gts9u-fingerprint-secure'
loader = importlib.machinery.SourceFileLoader('secure_startup', str(SCRIPT))
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader(loader.name, loader)
startup = importlib.util.module_from_spec(spec)
loader.exec_module(startup)

class Startup(unittest.TestCase):
    def test_valid_lease(self):
        self.assertTrue(startup.ready_record(dict(state='ready', expires=105, owner_pid=20), 100))

    def test_invalid_leases(self):
        for record in (None, [], {}, dict(state='starting', expires=105, owner_pid=20),
                       dict(state='failed', expires=105, owner_pid=20),
                       dict(state='ready', expires=100, owner_pid=20),
                       dict(state='ready', expires=107, owner_pid=20),
                       dict(state='ready', expires=float('nan'), owner_pid=20),
                       dict(state='ready', expires=105, owner_pid=0),
                       dict(state='ready', expires=105, owner_pid=1),
                       dict(state='ready', expires=105, owner_pid='20')):
            with self.subTest(record=record):
                self.assertFalse(startup.ready_record(record, 100))

    def test_publish_and_invalidate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(startup, 'STATE', Path(directory)):
            startup.publish('ready', Mock(pid=20))
            path = Path(directory) / 'status.json'
            self.assertTrue(startup.ready_record(json.loads(path.read_text()), startup.time.monotonic()))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            startup.publish('failed', Mock(pid=20))
            self.assertFalse(startup.ready_record(json.loads(path.read_text()), startup.time.monotonic()))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.touch(mode=0o600)
            link = Path(directory) / 'link'
            link.symlink_to(target)
            with self.assertRaises(RuntimeError):
                startup.protected(link)

    def test_writable_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.touch()
            path.chmod(0o666)
            with self.assertRaises(RuntimeError):
                startup.protected(path)

    def test_no_second_attempt(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(startup, 'STATE', Path(directory)):
            (Path(directory) / 'attempt').touch()
            with self.assertRaisesRegex(RuntimeError, 'already attempted'):
                startup.fresh_preflight()

    def test_check_never_starts_hardware(self):
        with patch.object(startup.sys, 'argv', ['secure', '--check']), \
             patch.object(startup, 'runtime_preflight') as preflight, \
             patch.object(startup, 'boot') as boot:
            startup.main()
            preflight.assert_called_once()
            boot.assert_not_called()

    def test_wait_failed_is_immediate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(startup, 'STATE', Path(directory)), \
             patch.object(startup, 'protected'), patch.object(startup.time, 'sleep') as sleep:
            (Path(directory) / 'status.json').write_text('{"state":"failed"}')
            with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                startup.wait_ready()
            sleep.assert_not_called()

    def test_wait_checks_live_owner(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(startup, 'STATE', Path(directory)), \
             patch.object(startup, 'protected'), patch.object(startup.os, 'kill') as kill:
            startup.publish('ready', Mock(pid=1234))
            startup.wait_ready()
            kill.assert_called_once_with(1234, 0)

    def test_wait_times_out(self):
        with patch.object(startup.time, 'monotonic', side_effect=[100, 161]):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                startup.wait_ready()

    def test_service_lifetime_policy(self):
        unit = (PACKAGE / 'usr/lib/systemd/system/ubuntu-gts9u-fingerprint-secure.service').read_text()
        for line in ('Type=simple', 'Restart=no', 'RefuseManualStop=yes',
                     'RuntimeDirectoryPreserve=yes', 'LimitCORE=0'):
            self.assertIn(line, unit)
        self.assertNotIn('ExecStop=', unit)
        self.assertNotIn('SurviveFinalKillSignal', unit)

    def test_fprintd_dependency_bounded(self):
        unit = (PACKAGE / 'usr/lib/systemd/system/fprintd.service.d/10-gts9u-el721.conf').read_text()
        self.assertIn('ubuntu-gts9u-fingerprint-secure.service', unit)
        self.assertIn('fingerprint-secure --wait', unit)
        self.assertIn('TimeoutStartSec=75', unit)

    def test_no_upgrade_restart_of_secure_owner(self):
        postinst = (PACKAGE / 'DEBIAN/postinst').read_text()
        for line in postinst.splitlines():
            if 'fingerprint-secure' in line:
                self.assertNotIn('restart', line)
                self.assertNotIn('--now', line)

    def test_owner_order_and_uncertain_dma(self):
        source = (REPO / 'packaging/libfprint/el721-secure-owner.c').read_text()
        main = source.split('int main (', 1)[1]
        ordered = ['register_qis_listener', '0x200', '0x207', 'bind_spu_buffer',
                   '0x215', '0x3121', '0x2116', 'el721_qtee_restore_hwvault']
        positions = [main.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('if (!shared_with_ta) return', main)
        binding = source.split('bind_spu_buffer (', 1)[1].split('int main (', 1)[0]
        self.assertLess(binding.index('shared_with_ta = TRUE'), binding.index('qcomtee_object_invoke'))
        self.assertNotIn('SPCOM_IOCTL_DMABUF_UNLOCK', binding)

    def test_manifest_does_not_ship_old_probes(self):
        manifest = (PACKAGE / 'usr/share/ubuntu-gts9u/fingerprint-runtime.sha256').read_text()
        lines = manifest.splitlines()
        self.assertEqual(len(lines), 23)
        for line in lines:
            digest, name = line.split()
            self.assertEqual(len(digest), 64)
            self.assertNotIn('..', Path(name).parts)
            self.assertNotIn('event_proxy', name)
            self.assertNotIn('compat-udmabuf', name)

if __name__ == '__main__':
    unittest.main()
