#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Synthetic rootfs assembly checks. No tablet or existing image is accessed."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

LIBRARY = Path(__file__).with_name("rootfs-build-lib.sh").resolve()


def shell(code, *args, check=True):
    return subprocess.run(["bash", "-c", 'set -euo pipefail; source "$1"; ' + code,
                           "test", str(LIBRARY), *map(str, args)], text=True,
                          capture_output=True, check=check)


class MountCleanup(unittest.TestCase):
    def test_transient_busy_mount_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            result = shell(r'''
                root=$(cd "$2" && pwd -P); touch "$root/busy"; calls=0
                mountpoint() { [ "$2" = "$root/proc" ] && [ -e "$root/busy" ]; }
                umount() { calls=$((calls+1)); [ "$calls" -ge 3 ] && rm "$root/busy"; }
                sleep() { :; }
                unmount_rootfs "$root"
                [ "$calls" -eq 3 ]
            ''', directory)
            self.assertEqual(result.returncode, 0)

    def test_persistent_mount_fails_after_three_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            result = shell(r'''
                root=$(cd "$2" && pwd -P); calls=0
                mountpoint() { [ "$2" = "$root/proc" ]; }
                umount() { calls=$((calls+1)); return 1; }
                sleep() { :; }
                if unmount_rootfs "$root"; then exit 99; fi
                [ "$calls" -eq 3 ]
            ''', directory)
            self.assertEqual(result.returncode, 0)
            self.assertIn("still has a live mount", result.stderr)

    def test_clean_root_never_calls_umount(self):
        with tempfile.TemporaryDirectory() as directory:
            shell('mountpoint() { return 1; }; umount() { exit 99; }; unmount_rootfs "$2"',
                  directory)

    def test_host_root_and_symlink_are_rejected(self):
        self.assertNotEqual(shell('unmount_rootfs /', check=False).returncode, 0)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "proc").symlink_to("/proc")
            self.assertNotEqual(shell('mountpoint() { return 1; }; unmount_rootfs "$2"',
                                      directory, check=False).returncode, 0)


class ImageRoot(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0,
                         "temporary loop-mounted ext4 fixture requires Linux root")
    def test_tar_root_metadata_is_normalized_and_verified_on_disk(self):
        for tool in ("mkfs.ext4", "debugfs", "mount", "umount", "tar"):
            self.assertIsNotNone(shutil.which(tool), tool)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            stage.mkdir()
            (stage / "synthetic").write_text("fixture\n")
            os.chown(stage, 1000, 1000)
            stage.chmod(0o700)
            archive = root / "stage.tar"
            subprocess.run(["tar", "-C", str(stage), "--numeric-owner", "-cf", str(archive), "."], check=True)
            image = root / "fixture.img"
            with image.open("wb") as stream:
                stream.truncate(32 * 1024**2)
            subprocess.run(["mkfs.ext4", "-F", "-q", str(image)], check=True)
            mount = root / "mount"
            mount.mkdir()
            subprocess.run(["mount", "-o", "loop", str(image), str(mount)], check=True)
            try:
                subprocess.run(["tar", "-C", str(mount), "--numeric-owner", "-xf", str(archive)], check=True)
                self.assertEqual(mount.stat().st_uid, 1000)
                self.assertEqual(mount.stat().st_mode & 0o7777, 0o700)
                shell('normalize_image_root "$2"', mount)
                self.assertEqual(mount.stat().st_uid, 0)
                self.assertEqual(mount.stat().st_mode & 0o7777, 0o755)
            finally:
                subprocess.run(["umount", str(mount)], check=True)
            shell('verify_image_root "$2"', image)
            for field, value in (("uid", "1000"), ("gid", "1000"), ("mode", "040700")):
                subprocess.run(["debugfs", "-w", "-R", f"set_inode_field <2> {field} {value}", str(image)], check=True, capture_output=True)
                self.assertNotEqual(shell('verify_image_root "$2"', image, check=False).returncode, 0)
                subprocess.run(["debugfs", "-w", "-R", f"set_inode_field <2> {field} " + ("040755" if field == "mode" else "0"), str(image)], check=True, capture_output=True)
            shell('verify_image_root "$2"', image)


if __name__ == "__main__":
    unittest.main()
