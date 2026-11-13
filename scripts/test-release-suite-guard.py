#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject a mislabeled cross-release payload before touching staged files."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
BUILDER = REPO / "scripts/build-update-payload.py"


class ReleaseSuiteGuardTests(unittest.TestCase):
    def release(self, base, **environment):
        # RELEASE_VERSION is deliberately invalid: the version gate is the
        # first one after the suite is resolved, so reaching it proves the
        # suite gate let the build through without starting a kernel build.
        return subprocess.run(['bash', str(REPO / 'scripts/build-release.sh')],
            env={**os.environ, 'UBUNTU_WORKDIR': str(base),
                 'RELEASE_VERSION': 'not-a-version', **environment},
            text=True, capture_output=True)

    def test_a_build_with_no_provenance_stops_before_the_first_stage(self):
        # Built from a snapshot with no BUILD-SOURCE.json, the manifest used
        # to print an empty port_revision after a complete build: the one
        # field that says what the ZIP was made from, lost in silence.
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary) / 'snapshot'
            (tree / 'scripts').mkdir(parents=True)
            for name in ('build-release.sh',):
                (tree / 'scripts' / name).write_bytes((REPO / 'scripts' / name).read_bytes())
            (tree / 'VERSION').write_text('9.9.9' + chr(10))
            base = Path(temporary) / 'work'
            base.mkdir()
            result = subprocess.run(['bash', str(tree / 'scripts/build-release.sh')],
                env={**os.environ, 'UBUNTU_WORKDIR': str(base)},
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('no provenance for this build', result.stderr)
            self.assertIn('snapshot-build-source.py', result.stderr)
            self.assertEqual(list(base.iterdir()), [])

    def test_an_ordinary_resolute_release_needs_no_migration_backend(self):
        # Resolute required one unconditionally while the only Resolute
        # release in existence was the one that carried Noble installations
        # across.  Every release is Resolute now and most migrate nothing.
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            result = self.release(base, UBUNTU_SUITE='resolute', MIGRATION_BACKEND='')
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('migration backend', result.stderr)
            self.assertIn('invalid release version', result.stderr)
            self.assertIn('ordinary 26.04 port release', result.stdout)
            self.assertEqual(list(base.iterdir()), [])

    def test_resolute_is_the_default_suite(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            result = self.release(base)
            self.assertIn('26.04', result.stdout)
            self.assertNotIn('24.04', result.stdout)
            self.assertEqual(list(base.iterdir()), [])

    def test_a_named_migration_backend_has_to_exist_before_any_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            result = self.release(base, UBUNTU_SUITE='resolute',
                                  MIGRATION_BACKEND=str(base / 'absent.pyz'))
            self.assertEqual(result.returncode, 2)
            self.assertIn('is not a file', result.stderr)
            self.assertEqual(list(base.iterdir()), [])

    def test_rejects_a_rootfs_from_the_other_suite_without_replacing_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            release = base / "rootfs/etc/os-release"
            release.parent.mkdir(parents=True)
            release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
            marker = base / "out/update-payload/existing"
            marker.parent.mkdir(parents=True)
            marker.write_text("keep")
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--base", str(base), "--suite", "noble",
                 "--update-format", "1",
                 "--version", "1.3.0", "--bootstrap", str(base / "updater.pyz")],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("is not the Ubuntu 24.04", result.stderr)
            self.assertEqual(marker.read_text(), "keep")

    def test_rejects_mixed_sources_without_replacing_existing_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            release = base / "rootfs/etc/os-release"
            release.parent.mkdir(parents=True)
            release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            sources = base / "rootfs/etc/apt/sources.list.d/ubuntu.sources"
            sources.parent.mkdir(parents=True)
            sources.write_text("Suites: resolute resolute-updates resolute-backports\n"
                               "Suites: resolute-security\n")
            marker = base / "out/update-payload/existing"
            marker.parent.mkdir(parents=True)
            marker.write_text("keep")
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--base", str(base), "--suite", "noble",
                 "--update-format", "1",
                 "--version", "1.3.0", "--bootstrap", str(base / "updater.pyz")],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("APT sources", result.stderr)
            self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
