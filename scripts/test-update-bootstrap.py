#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline regression for the actual update bootstrap writer; no tablet access."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

spec = importlib.util.spec_from_file_location(
    "build_update_payload", Path(__file__).with_name("build-update-payload.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BootstrapTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(time, "tzset"), "POSIX timezone switching required")
    def test_timezones_produce_the_same_executable_archive(self):
        original = os.environ.get("TZ")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "app"
                (source / "devices").mkdir(parents=True)
                (source / "devices/device.json").write_text('{"synthetic":true}\n')
                (source / "__main__.py").write_text('print("bootstrap-smoke")\n')
                for file in source.rglob("*"):
                    os.utime(file, (315532800, 315532800))
                archives = []
                for index, zone in enumerate(("UTC0", "PST8PDT", "HST10", "JST-9")):
                    os.environ["TZ"] = zone
                    time.tzset()
                    target = root / f"out/{index}.pyz"
                    builder.create_bootstrap(source, target)
                    archives.append(target.read_bytes())
                    self.assertEqual(os.environ["TZ"], zone)
                    self.assertEqual(target.stat().st_mode & 0o777, 0o755)
                    with zipfile.ZipFile(target) as archive:
                        self.assertIsNone(archive.testzip())
                        self.assertEqual(set(archive.namelist()),
                                         {"__main__.py", "devices/", "devices/device.json"})
                        for entry in archive.infolist():
                            self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(subprocess.check_output(
                        [sys.executable, str(target)], text=True), "bootstrap-smoke\n")
                self.assertTrue(all(item == archives[0] for item in archives))
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            time.tzset()


if __name__ == "__main__":
    unittest.main()
