#!/usr/bin/env python3
"""Exercise the shipped backup transaction against files, never block devices."""
import importlib.util
from unittest.mock import patch
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "android/bootswitcher/app/src/main/assets/refresh-android.sh"
PARTS = ("boot", "init_boot", "vendor_boot", "dtbo")

class TransactionTest(unittest.TestCase):
    def run_case(self, failure="", changed="1", interrupted=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mount = root / "linux"
            old = mount / "var/lib/gts9u-boot-sets/android"
            previous = mount / "var/lib/gts9u-boot-backups/android.previous"
            initial = previous if interrupted else old
            old.parent.mkdir(parents=True)
            initial.mkdir(parents=True)
            dev = root / "dev"
            dev.mkdir()
            for part in PARTS:
                (initial / (part + ".img")).write_bytes(b"o" * 64)
                (dev / part).write_bytes(b"n" * 64)
            bindir = root / "bin"
            bindir.mkdir()
            def executable(name, body):
                path = bindir / name
                path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
                path.chmod(0o755)
                return path
            executable("getprop", "echo gts9uwifi\n")
            executable("mount", 'echo "$*" >> "$TEST_MOUNTS"\n')
            executable("sync", "exit 0\n")
            executable("blockdev", 'stat -c %s "$2"\n')
            kernel = "wrong" if failure == "kernel" else os.uname().release
            magisk = executable("magiskboot", f"printf 'Linux version {kernel} test' > kernel\n")
            if failure == "rename":
                executable("mv", 'case "$1" in *.pending) exit 1;; esac\nexec /bin/mv "$@"\n')
            text = SCRIPT.read_text(encoding="utf-8")
            text = text.replace("/mnt/gts9u-linuxroot", str(mount))
            text = text.replace("/dev/block/by-name", str(dev))
            text = text.replace("/data/adb/magisk/magiskboot", str(magisk))
            text = text.replace("/data/local/tmp/gts9u-boot-check", str(root / "scratch"))
            for size in ("100663296", "8388608", "16777216"):
                text = text.replace(size, "64")
            expected = "\n".join(f"{hashlib.sha256((dev / p).read_bytes()).hexdigest()}  {p}.img" for p in PARTS)
            if failure == "hash":
                expected = expected.replace(expected[:64], "0" * 64, 1)
            env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                       SET_ID="android", SYSTEM_NAME="One UI 8", CHANGED=changed,
                       EXPECTED=expected, TEST_MOUNTS=str(root / "mounts"))
            result = subprocess.run(["sh"], input=text, text=True, capture_output=True, env=env)
            if failure:
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual((old / "boot.img").read_bytes(), b"o" * 64)
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((old / "boot.img").read_bytes(), (b"n" if changed == "1" else b"o") * 64)
                self.assertEqual((old / "name.txt").read_text().strip(), "One UI 8")
                if changed == "1":
                    self.assertEqual((previous / "boot.img").read_bytes(), b"o" * 64)
            for part in PARTS:
                self.assertEqual((dev / part).read_bytes(), b"n" * 64)
            if (root / "mounts").exists():
                self.assertIn("remount,ro", (root / "mounts").read_text().splitlines()[-1])

    def test_verified_update(self): self.run_case()
    def test_bad_hash_preserves_previous(self): self.run_case("hash")
    def test_foreign_kernel_preserves_previous(self): self.run_case("kernel")
    def test_commit_failure_rolls_back(self): self.run_case("rename")
    def test_label_only_does_not_copy(self): self.run_case(changed="0")
    def test_recovery_after_interrupted_commit(self): self.run_case(interrupted=True)

class LinuxLabelTest(unittest.TestCase):
    def test_android_is_not_named_after_running_linux(self):
        source = SCRIPT.parents[6] / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion/boot_core.py"
        spec = importlib.util.spec_from_file_location("boot_core", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            module.SETS_DIR = temp
            for set_id in ("android", "ubuntu"):
                target = Path(temp) / set_id
                target.mkdir()
                (target / "name.txt").write_text("original")
            with patch.object(module, "running_system_name", return_value="Ubuntu 24.04.5 LTS"):
                module.stamp_running_name("android")
                module.stamp_running_name("ubuntu")
            self.assertEqual((Path(temp) / "android/name.txt").read_text(), "original")
            self.assertEqual((Path(temp) / "ubuntu/name.txt").read_text().strip(), "Ubuntu 24.04.5 LTS")

if __name__ == "__main__":
    unittest.main()
