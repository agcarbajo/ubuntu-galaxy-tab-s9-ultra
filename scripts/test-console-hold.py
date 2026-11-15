#!/usr/bin/env python3
"""The unit that keeps /dev/console open, and the enablement list it is on.

What the unit is for cannot be tested off the tablet: it takes the serial
port whose last close costs 134 ms.  What can be tested is everything that
would quietly turn it back into nothing -- starting too late, being stopped
before the stop jobs print, holding a terminal it then has to manage, or
never being enabled -- and, for every unit the package enables, that the
target the postinst checks is the one the unit asks for.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packaging/ubuntu-gts9u-device'
UNITS = PACKAGE / 'usr/lib/systemd/system'
HOLD = UNITS / 'ubuntu-gts9u-console-hold.service'


def directives(path):
    """{section: [(key, value), ...]} of a unit file, comments dropped."""
    out, section = {}, None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            out.setdefault(section, [])
            continue
        key, _, value = line.partition('=')
        out[section].append((key.strip(), value.strip()))
    return out


def values(unit, section, key):
    return [word for k, v in unit.get(section, []) if k == key for word in v.split()]


def enabled_pairs():
    text = (PACKAGE / 'DEBIAN/postinst').read_text()
    block = re.search(r"^UNITS='\n(.*?)^'", text, re.S | re.M).group(1)
    return [tuple(line.split(':')) for line in block.split()]


class ConsoleHoldTests(unittest.TestCase):
    def setUp(self):
        self.unit = directives(HOLD)

    def test_it_is_there_before_plymouth_asks_for_status(self):
        self.assertEqual(values(self.unit, 'Unit', 'DefaultDependencies'), ['no'])
        before = values(self.unit, 'Unit', 'Before')
        self.assertIn('plymouth-start.service', before)
        self.assertIn('sysinit.target', before)
        # Nothing it would have to wait for: it must not be ordered after
        # anything that starts later than the first moments of userspace.
        self.assertEqual(values(self.unit, 'Unit', 'After'), [])
        self.assertEqual(values(self.unit, 'Unit', 'Requires') + values(self.unit, 'Unit', 'Wants'), [])
        self.assertEqual(values(self.unit, 'Install', 'WantedBy'), ['sysinit.target'])

    def test_it_outlives_the_serial_getty_at_shutdown(self):
        # The stop jobs print too, after the getty has released the port.
        self.assertEqual(values(self.unit, 'Unit', 'Conflicts'), [])
        self.assertNotIn('shutdown.target', values(self.unit, 'Unit', 'Before'))
        service = dict(self.unit['Service'])
        self.assertNotIn('RuntimeMaxSec', service)
        self.assertNotIn('TimeoutStopSec', service)

    def test_it_holds_the_device_and_does_nothing_with_it(self):
        service = dict(self.unit['Service'])
        self.assertEqual(service['StandardInput'], 'file:/dev/console')
        # Not a terminal as far as systemd is concerned: tty, tty-force and
        # the +console outputs make PID 1 reset and reopen the device itself.
        self.assertEqual(service['StandardOutput'], 'null')
        self.assertEqual(service['StandardError'], 'null')
        for key in ('TTYPath', 'TTYReset', 'TTYVHangup', 'TTYVTDisallocate'):
            self.assertNotIn(key, service)
        self.assertEqual(service['ExecStart'], '/usr/bin/sleep infinity')
        self.assertEqual(service['Type'], 'exec')
        self.assertEqual(values(self.unit, 'Unit', 'ConditionPathExists'), ['/dev/console'])

    def test_systemd_accepts_the_unit(self):
        analyze = shutil.which('systemd-analyze')
        if not analyze:
            self.skipTest('no systemd-analyze on this host')
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / HOLD.name
            # The checkout's own mode bits are not the package's.
            copy.write_text(HOLD.read_text())
            copy.chmod(0o644)
            result = subprocess.run([analyze, 'verify', '--recursive-errors=no', str(copy)],
                                    capture_output=True, text=True)
        complaints = [line for line in (result.stdout + result.stderr).splitlines()
                      if HOLD.name in line]
        self.assertEqual(complaints, [])


class EnablementTests(unittest.TestCase):
    def test_the_console_hold_is_enabled_where_it_installs(self):
        self.assertIn(('ubuntu-gts9u-console-hold.service', 'sysinit.target'), enabled_pairs())

    def test_every_enabled_unit_is_packaged_and_wanted_by_the_target_checked(self):
        pairs = enabled_pairs()
        self.assertGreater(len(pairs), 20)
        self.assertEqual(len(pairs), len(set(pairs)))
        for name, target in pairs:
            with self.subTest(unit=name):
                path = UNITS / name
                self.assertTrue(path.is_file(), f'{name} is enabled by the postinst but not packaged')
                self.assertIn(target, values(directives(path), 'Install', 'WantedBy'))


if __name__ == '__main__':
    unittest.main()
