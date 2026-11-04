#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise APT candidate selection without installing host packages."""
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

SELECTOR = Path(__file__).with_name("select-qemu-user-package.sh")


class QemuPackages(unittest.TestCase):
    def select(self, candidates):
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / "apt-cache"
            command.write_text("#!/usr/bin/env python3\nimport os,json,sys\n"
                               "candidate=json.loads(os.environ['TEST_CANDIDATES']).get(sys.argv[2])\n"
                               "if candidate: print('  Candidate: '+candidate)\n")
            command.chmod(0o755)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ["PATH"],
                       TEST_CANDIDATES=json.dumps(candidates))
            return subprocess.run(["bash", str(SELECTOR)], env=env, text=True,
                                  capture_output=True)

    def test_noble_keeps_the_static_package(self):
        result = self.select({"qemu-user-static": "1:8.2", "qemu-user-binfmt": "1:8.2"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "qemu-user-static")

    def test_virtual_static_package_selects_concrete_binfmt(self):
        result = self.select({"qemu-user-static": "(none)", "qemu-user-binfmt": "1:10.2"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "qemu-user-binfmt")

    def test_hwe_only_archive(self):
        result = self.select({"qemu-user-binfmt-hwe": "1:10.2"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "qemu-user-binfmt-hwe")

    def test_no_candidate_fails_before_installation(self):
        result = self.select({"qemu-user-static": "(none)"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class LibfprintVersion(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dpkg"), "Debian version comparison requires dpkg")
    def test_noble_derivative_outweighs_the_archive_and_stays_paired(self):
        repo = SELECTOR.resolve().parents[1]
        builder = (repo / "scripts/build-libfprint-el721.sh").read_text()
        version = re.search(r"noble\) default_version=([^ ;]+)", builder)[1]
        archive = "1:1.94.7+tod1-0ubuntu5~24.04.9"
        subprocess.run(["dpkg", "--compare-versions", version, "gt", archive], check=True)
        control = (repo / "packaging/ubuntu-gts9u-device/DEBIAN/control").read_text()
        self.assertIn("libfprint-2-2 (>= " + version + ")", control)
        noble = re.search(r"^Version: (.+)$", control, re.M)[1]
        resolute = (repo / "packaging/ubuntu-gts9u-device/DEBIAN/control-resolute").read_text()
        newer = re.search(r"^Version: (.+)$", resolute, re.M)[1]
        subprocess.run(["dpkg", "--compare-versions", noble, "gt", "2.90"], check=True)
        subprocess.run(["dpkg", "--compare-versions", newer, "gt", noble], check=True)


if __name__ == "__main__":
    unittest.main()
