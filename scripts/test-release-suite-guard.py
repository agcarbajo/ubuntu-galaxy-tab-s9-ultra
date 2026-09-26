#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject a mislabeled cross-release payload before touching staged files."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
BUILDER = REPO / "scripts/build-update-payload.py"


class ReleaseSuiteGuardTests(unittest.TestCase):
    def test_rejects_resolute_without_replacing_existing_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            release = base / "rootfs/etc/os-release"
            release.parent.mkdir(parents=True)
            release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
            marker = base / "out/update-payload/existing"
            marker.parent.mkdir(parents=True)
            marker.write_text("keep")
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--base", str(base),
                 "--version", "1.3.0", "--bootstrap", str(base / "updater.pyz")],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("only supports Ubuntu 24.04/Noble", result.stderr)
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
                [sys.executable, str(BUILDER), "--base", str(base),
                 "--version", "1.3.0", "--bootstrap", str(base / "updater.pyz")],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("APT sources", result.stderr)
            self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
