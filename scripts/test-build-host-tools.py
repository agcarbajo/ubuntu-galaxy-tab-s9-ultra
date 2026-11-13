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
    # A real `apt-cache policy` prints the candidate near the top and keeps
    # going: installed version, pin, then a version table with one or two
    # lines per pocket.  The fake prints a tail of its own for the same reason
    # -- a parser that stops reading at the candidate closes the pipe under
    # apt-cache, and the selector used to die of the resulting SIGPIPE with
    # the answer already in hand.  TEST_POLICY_TAIL makes that tail long
    # enough to fill the pipe buffer, which turns the race into a certainty.
    def select(self, candidates, tail=4):
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / "apt-cache"
            command.write_text(
                "#!/usr/bin/env python3\n"
                "import os,json,sys\n"
                "candidate=json.loads(os.environ['TEST_CANDIDATES']).get(sys.argv[2])\n"
                "if candidate is None: sys.exit(0)\n"
                "print(sys.argv[2]+':')\n"
                "print('  Installed: (none)')\n"
                "print('  Candidate: '+candidate)\n"
                "print('  Version table:')\n"
                "for line in range(int(os.environ['TEST_POLICY_TAIL'])):\n"
                "    print('     1:8.2.2+ds-0ubuntu1.%d 500' % line)\n"
                "    print('        500 http://ports.ubuntu.com/ubuntu-ports noble/universe arm64 Packages')\n")
            command.chmod(0o755)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ["PATH"],
                       TEST_CANDIDATES=json.dumps(candidates),
                       TEST_POLICY_TAIL=str(tail))
            return subprocess.run(["bash", str(SELECTOR)], env=env, text=True,
                                  capture_output=True)

    def test_a_long_policy_listing_does_not_sigpipe_the_selector(self):
        result = self.select({"qemu-user-static": "1:8.2"}, tail=20000)
        self.assertEqual(result.returncode, 0,
                         f"selector exited {result.returncode}: {result.stderr}")
        self.assertEqual(result.stdout.strip(), "qemu-user-static")

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
