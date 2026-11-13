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
    """The local derivative has to outrank every SRU of the revision it names.

    Asserting it against one archive version is how the pin went stale 47
    times: the archive moved, the comparison in the test moved with it, and
    the next build was the one that found out.  These compare against the
    whole family instead, so they hold for any SRU the archive ever ships.
    """

    SUITES = (
        ("noble", "control", "1:1.94.7+tod1-0ubuntu5"),
        ("resolute", "control-resolute", "1:1.95.1+tod1-0ubuntu2"),
    )

    def ordered(self, higher, lower):
        self.assertEqual(0, subprocess.run(
            ["dpkg", "--compare-versions", higher, "gt", lower]).returncode,
            f"{higher} must outrank {lower}")

    @unittest.skipUnless(shutil.which("dpkg"), "Debian version comparison requires dpkg")
    def test_each_derivative_outranks_every_archive_sru_and_stays_pinned(self):
        repo = SELECTOR.resolve().parents[1]
        builder = (repo / "scripts/build-libfprint-el721.sh").read_text()
        for suite, control_name, archive in self.SUITES:
            version = re.search(suite + r"\) default_version=([^ ;]+)", builder)[1]
            for sru in (archive, archive + ".1", archive + ".9", archive + "+x",
                        archive + "~24.04.9", archive + "~24.04.10",
                        archive + "~24.04.99", archive + "~26.04.1"):
                self.ordered(version, sru)
            # ...and still lose to a genuine new upstream revision, which is
            # the one case that has to stop the build for a human rebase.
            self.assertIn("~gts9u", version)
            self.ordered(version.split("~gts9u")[0], version)
            control = (repo / "packaging/ubuntu-gts9u-device/DEBIAN" / control_name).read_text()
            self.assertIn("libfprint-2-2 (>= " + version + ")", control,
                          f"the {suite} device package must require what it builds")

    @unittest.skipUnless(shutil.which("dpkg"), "Debian version comparison requires dpkg")
    def test_the_resolute_device_package_replaces_the_noble_one(self):
        repo = SELECTOR.resolve().parents[1]
        noble = re.search(r"^Version: (.+)$", (
            repo / "packaging/ubuntu-gts9u-device/DEBIAN/control").read_text(), re.M)[1]
        resolute = re.search(r"^Version: (.+)$", (
            repo / "packaging/ubuntu-gts9u-device/DEBIAN/control-resolute").read_text(), re.M)[1]
        self.ordered(noble, "2.90")
        self.ordered(resolute, noble)


if __name__ == "__main__":
    unittest.main()
