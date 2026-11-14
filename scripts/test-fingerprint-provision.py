#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The two ways a tablet ends up running on another unit's calibration.

The packaged firmware directory carries the development unit's `calib.dat`,
and the driver uses it whenever this tablet has none of its own.  A reader
calibrated for a different sensor enrols and then never recognises a finger,
which is exactly what the two open reports describe, and nothing in the system
said so.  Both holes that lead there are covered here:

  * the calibration was looked for at one hard-coded path inside EFS, so a
    unit that keeps it anywhere else was never read; and
  * a failure to read the Android runtime out of `super` threw away the
    firmware that had already been collected -- including that calibration --
    leaving the packaged set in charge.

No root, no device, no partitions: the collectors are replaced and only the
decisions are exercised.
"""
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-fingerprint-provision'
MODULE = runpy.run_path(str(HELPER))
# run_path hands back a copy of the globals; the functions keep the original,
# so a replacement has to go into the dictionary they actually read.
GLOBALS = MODULE['provision'].__globals__


class CalibrationSearch(unittest.TestCase):
    def efs(self, *relative_paths, size=16):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for relative in relative_paths:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x' * size)
        return root

    def find(self, root, limit=1024):
        return MODULE['efs_candidate'](root, MODULE['EFS_CALIBRATION_PATTERNS'], limit)

    def test_the_canonical_path_is_taken_first(self):
        root = self.efs('biometrics/meta/egis_calibration_data.bin',
                        'biometrics/backup/egis_calibration_data.bin')
        self.assertEqual(self.find(root).relative_to(root).as_posix(),
                         'biometrics/meta/egis_calibration_data.bin')

    def test_a_unit_that_keeps_it_elsewhere_is_still_read(self):
        for relative in ('biometrics/meta/egis_calibration_data_0.bin',
                         'biometrics/egis_calibration.bin',
                         'biometrics/sensor/meta/egis_calibration_data.bin',
                         'biometrics/meta/fp_calibration_data.bin'):
            with self.subTest(relative=relative):
                root = self.efs(relative)
                found = self.find(root)
                self.assertIsNotNone(found, relative)
                self.assertEqual(found.relative_to(root).as_posix(), relative)

    def test_nothing_plausible_is_not_a_calibration(self):
        root = self.efs('biometrics/meta/notes.txt', 'wifi/.mac.info')
        self.assertIsNone(self.find(root))

    def test_an_oversized_file_is_refused(self):
        root = self.efs('biometrics/meta/egis_calibration_data.bin', size=4096)
        self.assertIsNone(self.find(root, limit=1024))

    def test_a_directory_with_the_right_name_is_not_taken(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'biometrics/meta/egis_calibration_data.bin').mkdir(parents=True)
        self.assertIsNone(self.find(root))

    def test_a_symlink_out_of_the_mount_is_not_taken(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'biometrics/meta').mkdir(parents=True)
        outside = root / 'outside.bin'
        outside.write_bytes(b'x' * 16)
        (root / 'biometrics/meta/egis_calibration_data.bin').symlink_to(outside)
        self.assertIsNone(self.find(root))

    def test_the_optical_blob_uses_its_own_patterns(self):
        root = self.efs('biometrics/meta/egoptbds_0.dat')
        found = MODULE['efs_candidate'](root, MODULE['EFS_OPTICAL_PATTERNS'], 1024)
        self.assertIsNotNone(found)


class RuntimeFailureKeepsTheFirmware(unittest.TestCase):
    def provision(self, runtime_error):
        """Run provision() with both collectors replaced; return the report."""
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        root = Path(state.name)
        saved = {name: GLOBALS[name] for name in
                 ('STATE', 'PROVENANCE', 'MANIFEST', 'collect_firmware',
                  'collect_runtime', 'current_state', 'ensure_nvm_dirs', 'log',
                  'DEVICE_NODE')}
        self.addCleanup(lambda: GLOBALS.update(saved))

        def collect_firmware(stage, report):
            firmware = stage / 'firmware'
            firmware.mkdir(mode=0o700)
            (firmware / 'calib.dat').write_bytes(b'this unit')
            report['sources']['calib.dat'] = {'from': 'sec_efs:biometrics/meta/x.bin'}

        def collect_runtime(stage, report):
            runtime = stage / 'runtime'
            runtime.mkdir(mode=0o700)
            (runtime / 'bin').mkdir()
            if runtime_error is not None:
                raise runtime_error

        GLOBALS['DEVICE_NODE'] = root
        GLOBALS['STATE'] = root
        GLOBALS['PROVENANCE'] = root / 'provenance.json'
        GLOBALS['MANIFEST'] = root / 'runtime.sha256'
        GLOBALS['collect_firmware'] = collect_firmware
        GLOBALS['collect_runtime'] = collect_runtime
        GLOBALS['current_state'] = lambda: {'firmware': False, 'runtime': False,
                                           'runtime_complete': False, 'provenance': None}
        GLOBALS['ensure_nvm_dirs'] = lambda: None
        GLOBALS['log'] = lambda *_args: None

        error = None
        try:
            MODULE['provision'](force=True)
        except MODULE['ProvisionError'] as raised:
            error = raised
        report = json.loads((root / 'provenance.json').read_text())
        return root, report, error

    def setUp(self):
        if os.geteuid() != 0:
            self.skipTest('provision() refuses to run as anyone but root')

    def test_a_readable_tablet_provisions_both_halves(self):
        root, report, error = self.provision(None)
        self.assertIsNone(error)
        self.assertTrue((root / 'firmware/calib.dat').is_file())
        self.assertTrue((root / 'runtime').is_dir())
        self.assertTrue(report['runtime_complete'])
        self.assertEqual(report['warnings'], [])

    def test_an_unreadable_super_still_leaves_this_unit_calibrated(self):
        # A tablet with no Android any more, or a `super` layout this parser
        # does not know: before, the staged firmware went with it.
        root, report, error = self.provision(
            MODULE['ProvisionError']('super has no vendor partition'))
        self.assertTrue((root / 'firmware/calib.dat').is_file(),
                        'this unit lost its own calibration to a runtime failure')
        self.assertFalse((root / 'runtime').exists())
        self.assertFalse(report['runtime_complete'])
        self.assertTrue(any('Android runtime could not be read' in w
                            for w in report['warnings']), report['warnings'])

    def test_the_owner_is_still_told_it_failed(self):
        root, report, error = self.provision(
            MODULE['ProvisionError']('super has no vendor partition'))
        self.assertIsNotNone(error, 'a half-provisioned tablet reported success')
        self.assertIn('Android runtime', str(error))

    def test_an_operating_system_error_is_caught_too(self):
        root, report, error = self.provision(OSError('loop device unavailable'))
        self.assertTrue((root / 'firmware/calib.dat').is_file())
        self.assertIsNotNone(error)


if __name__ == '__main__':
    unittest.main(verbosity=1)
