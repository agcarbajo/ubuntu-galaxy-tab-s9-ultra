#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise APT candidate selection without installing host packages."""
import json
import os
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


if __name__ == "__main__":
    unittest.main()
