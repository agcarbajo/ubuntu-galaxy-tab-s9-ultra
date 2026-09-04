#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Safety tests run entirely on temporary files; never flash a tablet."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import shutil
import subprocess
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"))
from tab_companion import update_bundle as b
from tab_companion import update_core as c


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sizes = patch.dict(b.PARTITIONS, {p: 32 for p in b.PARTITIONS})
        self.sizes.start()

    def tearDown(self):
        self.sizes.stop()
        self.tmp.cleanup()

    def archive(self, change=lambda m: None, extra=None):
        data = {p + ".img": p.encode().ljust(32, b"\0") for p in b.PARTITIONS}
        data["UPDATE/debs/test_1_arm64.deb"] = b"package"
        manifest = {"format": 1, "device": "gts9uwifi", "suite": "noble", "architecture": "arm64",
                    "version": "1.1.0", "tag": "v1.1.0", "kernel_release": "7.2.0-rc3",
                    "apt_packages": ["python3"], "files": {n: {"size": len(v),
                    "sha256": hashlib.sha256(v).hexdigest()} for n, v in data.items()}}
        change(manifest)
        path = self.root / "build.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(b.MANIFEST, json.dumps(manifest))
            for n, value in data.items():
                z.writestr(n, value)
            if extra:
                extra(z)
        return path

    def test_roundtrip_only_payload_extracted(self):
        archive = self.archive(extra=lambda z: z.writestr("rootfs.img", b"never install this"))
        out = self.root / "out"
        manifest = b.extract(archive, out)
        self.assertEqual(manifest["tag"], "v1.1.0")
        self.assertFalse((out / "rootfs.img").exists())
        self.assertTrue((out / "boot.img").exists())

    def test_old_installer_rejected(self):
        path = self.root / "old.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("rootfs.img", b"destructive")
        with self.assertRaisesRegex(ValueError, "predates"):
            b.inspect(path)

    def test_wrong_device_suite_arch_format(self):
        for field, value in (("device", "gts9"), ("suite", "jammy"), ("architecture", "amd64"), ("format", 2)):
            with self.subTest(field=field):
                path = self.archive(lambda m: m.update({field: value}))
                with self.assertRaises(ValueError):
                    b.inspect(path)

    def test_path_traversal_and_unexpected_writes(self):
        for path in ("../etc/shadow", "/etc/passwd", "UPDATE/debs/../../etc/passwd", "vbmeta.img", "recovery.img"):
            archive = self.archive(lambda m: m["files"].update({path: {"size": 1, "sha256": "a" * 64}}))
            with self.assertRaises(ValueError):
                b.inspect(archive)

    def test_missing_or_short_boot(self):
        archive = self.archive(lambda m: m["files"].pop("boot.img"))
        with self.assertRaises(ValueError):
            b.inspect(archive)
        archive = self.archive(lambda m: m["files"]["boot.img"].update(size=10))
        with self.assertRaises(ValueError):
            b.inspect(archive)

    def test_corruption_rejected(self):
        path = self.archive(lambda m: m["files"]["boot.img"].update(sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "checksum"):
            b.extract(path, self.root / "out")

    def test_duplicate_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            path = self.archive(extra=lambda z: z.writestr("boot.img", b"x" * 32))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            b.inspect(path)

    def test_apt_arguments_cannot_be_injected(self):
        for item in ("--allow-unauthenticated", "x;reboot", "../../tmp/x.deb", "foo=1"):
            path = self.archive(lambda m: m.update(apt_packages=[item]))
            with self.assertRaisesRegex(ValueError, "requirements"):
                b.inspect(path)

    def test_versions_are_not_paths(self):
        path = self.archive(lambda m: m.update(kernel_release="../../etc"))
        with self.assertRaises(ValueError):
            b.inspect(path)

    def test_oversized_payload_rejected(self):
        path = self.archive()
        with patch.object(b, "MAX_PAYLOAD", 1), self.assertRaises(ValueError):
            b.inspect(path)

    def test_foreign_update_marker_untouched(self):
        marker = self.root / "system-update"
        marker.symlink_to("/some-other-updater")
        with patch.object(c, "MARKER", marker):
            c.unmark()
        self.assertTrue(marker.is_symlink())

    def test_partition_copy_readback(self):
        source = self.root / "boot.img"
        dest = self.root / "device"
        source.write_bytes(b"new boot")
        dest.write_bytes(b"old boot")
        c.copy_partition(source, dest, 8)
        self.assertEqual(source.read_bytes(), dest.read_bytes())

    def test_partition_copy_rejects_short_input(self):
        source = self.root / "boot.img"
        dest = self.root / "device"
        source.write_bytes(b"new")
        dest.write_bytes(b"old boot")
        with self.assertRaisesRegex(ValueError, "Truncated"):
            c.copy_partition(source, dest, 8)

    def test_apt_never_removes_or_ignores_authentication(self):
        (self.root / "plan.json").write_text(json.dumps({"files": {"UPDATE/debs/test.deb": {}}, "apt_packages": ["python3"]}))
        args = c.apt_args(self.root)
        self.assertIn("--no-remove", args)
        self.assertIn("--no-download", args)
        self.assertIn("Dpkg::Options::=--force-confold", args)
        self.assertNotIn("--allow-unauthenticated", args)
        self.assertNotIn("--allow-downgrades", args)

    def test_unknown_current_build(self):
        with patch.object(b, "IDENTITY", self.root / "absent"):
            self.assertEqual(b.current(), {})

    def test_pen_battery_does_not_gate_system_update(self):
        for name, values in {"pen": {"scope": "Device", "capacity": "", "type": "Battery", "online": "1"},
                             "main": {"capacity": "63", "type": "Battery"},
                             "usb": {"online": "1", "type": "USB"}}.items():
            (self.root / name).mkdir()
            for key, value in values.items():
                (self.root / name / key).write_text(value)
        with patch.object(c, "Path", return_value=self.root):
            c.power_check()
            for level, online, allowed in [(20, 0, True), (63, 0, True),
                                            (19, 0, False), (19, 1, True), (5, 1, True)]:
                with self.subTest(level=level, online=online):
                    (self.root / "main/capacity").write_text(str(level))
                    (self.root / "usb/online").write_text(str(online))
                    if allowed:
                        c.power_check()
                    else:
                        with self.assertRaisesRegex(ValueError, "below 20%"):
                            c.power_check()

    def test_symlink_lock_cannot_overwrite_a_file(self):
        target = self.root / "private"
        target.write_text("keep me")
        lock = self.root / "lock"
        lock.symlink_to(target)
        with patch.object(c, "LOCK", str(lock)), self.assertRaises(OSError):
            c.boot_lock()
        self.assertEqual(target.read_text(), "keep me")


class ReleaseTests(unittest.TestCase):
    def test_legacy_release_is_not_an_update(self):
        with patch.object(b, "request", return_value=self.response(self.release_data())):
            info = b.release()
        self.assertFalse(info["supports_updates"])
        self.assertEqual(b.release_state(info), "unsupported")

    def test_known_versions_do_not_offer_downgrades(self):
        with patch.object(b, "current", return_value={"tag": "v1.2.0", "version": "1.2.0"}):
            for tag, state in (("v1.0.0", "older"), ("v1.2.0", "current"), ("v1.3.0", "newer")):
                self.assertEqual(b.release_state({"tag": tag, "supports_updates": True}), state)

    def test_unknown_installed_version_is_not_claimed_newer(self):
        with patch.object(b, "current", return_value={}):
            self.assertEqual(b.release_state({"tag": "v1.1.0", "supports_updates": True}), "unknown")

    def test_machine_progress_contains_measured_bytes(self):
        with patch.object(c, "PROGRESS_JSON", True), patch.object(c, "emit") as emit:
            c.progress("download", 50, 100)
        self.assertEqual(json.loads(emit.call_args.args[0]), {
            "event": "progress", "stage": "download", "completed": 50, "total": 100})
        with patch.object(c, "PROGRESS_JSON", False), patch.object(c, "emit") as emit:
            c.progress("verify")
            emit.assert_not_called()

    def response(self, data):
        import io
        return io.BytesIO(json.dumps(data).encode())

    def release_data(self):
        return {"tag_name": "v1.0.0", "assets": [{"name": "ubuntu-24.04-sm-x910-v1.0.0.zip",
            "browser_download_url": "https://github.com/" + b.REPOSITORY + "/releases/download/v1.0.0/build.zip",
            "digest": "sha256:" + "a" * 64, "size": 100}]}

    def test_release_selection_ignores_other_assets(self):
        data = self.release_data()
        data["assets"].append({"name": "gts9u-split.zip"})
        with patch.object(b, "request", return_value=self.response(data)):
            self.assertEqual(b.release()["tag"], "v1.0.0")

    def test_missing_digest_and_foreign_url_rejected(self):
        for field, value in (("digest", None), ("browser_download_url", "https://example.com/foo")):
            data = self.release_data()
            data["assets"][0][field] = value
            with patch.object(b, "request", return_value=self.response(data)), self.assertRaises(ValueError):
                b.release()

    def test_repair_queries_exact_tag(self):
        with patch.object(b, "request", return_value=self.response(self.release_data())) as request:
            b.release("v1.0.0")
            self.assertEqual(request.call_args.args[0], b.API + "/tags/v1.0.0")


class OfflineTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.transaction = self.root / "transaction"
        self.transaction.mkdir()
        self.marker = self.root / "system-update"
        self.marker.symlink_to(self.transaction)
        self.identity = self.root / "identity.json"
        self.old = b"old boot".ljust(32, b"\0")
        self.new = b"new boot".ljust(32, b"\0")
        self.devices = {}
        for part in b.PARTITIONS:
            device = self.root / ("device-" + part)
            device.write_bytes(self.old)
            self.devices[part] = device
            (self.transaction / (part + ".img")).write_bytes(self.new)
        self.plan = {"files": {p + ".img": {"sha256": hashlib.sha256(self.new).hexdigest()}
                                for p in b.PARTITIONS}, "apt_packages": [],
                     "device": "gts9uwifi", "version": "1.1.0", "tag": "v1.1.0", "kernel_release": "test"}
        (self.transaction / "plan.json").write_text(json.dumps(self.plan))
        (self.transaction / "archives.json").write_text("{}")
        (self.root / "dpkg-status").write_text("installed packages")
        (self.transaction / "dpkg.sha256").write_text(b.sha256(self.root / "dpkg-status"))
        self.patches = [patch.object(c, "STATE", self.root), patch.object(c, "TRANSACTION", self.transaction),
            patch.object(c, "MARKER", self.marker), patch.object(b, "IDENTITY", self.identity),
            patch.dict(b.PARTITIONS, {p: 32 for p in b.PARTITIONS}),
            patch.object(c, "device_check"), patch.object(c, "power_check"),
            patch.object(c, "partitions", return_value=self.devices),
            patch.object(c.subprocess, "run", return_value=subprocess.CompletedProcess([], 3)),
            patch.object(c, "Path", side_effect=lambda p: self.root / "saved-ubuntu" if
                         p == "/var/lib/gts9u-boot-sets/ubuntu" else Path(p))]
        real_sha = b.sha256
        self.patches.append(patch.object(b, "sha256", side_effect=lambda p: real_sha(
            self.root / "dpkg-status" if str(p) == "/var/lib/dpkg/status" else p)))
        for p in self.patches:
            p.start()
        c.set_status("ready", tag="v1.1.0")
        self.commands = []

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def execute(self, argv, capture=False, offline=False):
        self.commands.append(argv)
        if argv[:2] == ["cp", "-a"]:
            source, dest = argv[2:]
            if source in ("/etc", "/usr/lib/modules"):
                Path(dest).mkdir()
                (Path(dest) / "preserved").write_text("user settings / old modules")
        return ""

    def test_complete_updates_boot_and_saved_set_only(self):
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "complete")
        self.assertFalse(self.marker.is_symlink())
        self.assertEqual(json.loads(self.identity.read_text())["tag"], "v1.1.0")
        for part, device in self.devices.items():
            self.assertEqual(device.read_bytes(), self.new)
            self.assertEqual((self.transaction / "backup" / (part + ".img")).read_bytes(), self.old)
            self.assertEqual((self.root / "saved-ubuntu" / (part + ".img")).read_bytes(), self.new)
        self.assertIn(["systemctl", "--no-block", "reboot"], self.commands)

    def test_package_changes_abort_before_writes(self):
        (self.root / "dpkg-status").write_text("changed since preparation")
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertFalse(any(a[0] == "apt-get" for a in self.commands))
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))

    def test_completed_transaction_is_not_rolled_back_after_power_loss(self):
        c.set_status("complete", tag="v1.1.0")
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "complete")
        self.assertFalse(self.marker.is_symlink())
        self.assertEqual(self.commands, [["systemctl", "--no-block", "reboot"]])

    def test_failed_second_boot_write_restores_all_partitions(self):
        real_copy = c.copy_partition
        count = 0
        def failing_copy(src, dst, size):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated I/O error")
            return real_copy(src, dst, size)
        with patch.object(c, "run", side_effect=self.execute), patch.object(c, "copy_partition", side_effect=failing_copy):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))
        self.assertFalse(self.identity.exists())
        self.assertFalse(self.marker.is_symlink())

    def test_corrupted_staging_aborts_before_apt(self):
        (self.transaction / "boot.img").write_bytes(b"corrupt")
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertFalse(any(a[0] == "apt-get" for a in self.commands))
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))

    def test_apt_failure_keeps_old_boot_and_backup(self):
        def fail_apt(argv, *args, **kwargs):
            if argv[0] == "apt-get":
                raise OSError("simulated package failure")
            return self.execute(argv, *args, **kwargs)
        with patch.object(c, "run", side_effect=fail_apt):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertTrue((self.transaction / "backup/complete").exists())
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))


class ConffileTests(unittest.TestCase):
    def test_real_apt_installs_cached_local_deb_offline(self):
        if not shutil.which("apt-get") or os.geteuid() != 0:
            self.skipTest("Needs APT and root in an isolated Linux test environment")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "root"
            (root / "var/lib/dpkg").mkdir(parents=True)
            database = root / "var/lib/dpkg/status"
            database.touch()
            stage = base / "package"
            (stage / "DEBIAN").mkdir(parents=True)
            (stage / "DEBIAN/control").write_text(
                "Package: test-offline-port\nVersion: 1:2.0\nArchitecture: all\n"
                "Maintainer: Test <test@example.invalid>\nDescription: Offline cache regression\n")
            (stage / "etc").mkdir()
            (stage / "etc/offline-test").write_text("installed")
            deb = base / "UPDATE/debs/arbitrary-name.deb"
            deb.parent.mkdir(parents=True)
            subprocess.run(["dpkg-deb", "-b", str(stage), str(deb)], check=True, capture_output=True)
            plan = {"files": {"UPDATE/debs/arbitrary-name.deb": {}}, "apt_packages": []}
            c.write_json(base / "plan.json", plan)
            (base / "archives/partial").mkdir(parents=True)
            c.cache_local_packages(base, plan)
            options = ["-o", "Dir::State::status=" + str(database),
                       "-o", "Dir::Etc::sourcelist=/dev/null", "-o", "Dir::Etc::sourceparts=-",
                       "-o", "Dir::State::lists=" + str(base / "lists"),
                       "-o", "DPkg::Options::=--root=" + str(root),
                       "-o", "APT::Get::AutomaticRemove=false"]
            result = subprocess.run(c.apt_args(base) + options, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((root / "etc/offline-test").read_text(), "installed")

    def test_real_dpkg_keeps_modified_configuration(self):
        if not shutil.which("dpkg-deb") or os.geteuid() != 0:
            self.skipTest("Needs dpkg-deb and root in the Linux test environment")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "root"
            (root / "var/lib/dpkg").mkdir(parents=True)
            (root / "var/lib/dpkg/status").touch()
            for version in ("1", "2"):
                stage = base / version
                (stage / "DEBIAN").mkdir(parents=True)
                (stage / "etc").mkdir()
                (stage / "etc/port.conf").write_text("default " + version)
                (stage / "DEBIAN/control").write_text(
                    "Package: test-port\nVersion: " + version + "\nArchitecture: all\n"
                    "Maintainer: Test <test@example.invalid>\nDescription: Test conffiles\n")
                (stage / "DEBIAN/conffiles").write_text("/etc/port.conf\n")
                deb = base / (version + ".deb")
                subprocess.run(["dpkg-deb", "-b", str(stage), str(deb)], check=True, capture_output=True)
                subprocess.run(["dpkg", "--root=" + str(root), "--force-confold", "--force-confdef",
                                "-i", str(deb)], check=True, capture_output=True)
                if version == "1":
                    (root / "etc/port.conf").write_text("user's custom settings")
            self.assertEqual((root / "etc/port.conf").read_text(), "user's custom settings")

    def test_adopting_preexisting_config_keeps_it(self):
        if not shutil.which("dpkg-deb") or os.geteuid() != 0:
            self.skipTest("Needs dpkg and root")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "root"
            (root / "var/lib/dpkg").mkdir(parents=True)
            (root / "var/lib/dpkg/status").touch()
            (root / "etc").mkdir()
            (root / "etc/port.conf").write_text("existing custom config")
            stage = base / "package"
            (stage / "DEBIAN").mkdir(parents=True)
            (stage / "etc").mkdir()
            (stage / "etc/port.conf").write_text("new default")
            (stage / "DEBIAN/control").write_text("Package: test-port\nVersion: 1\nArchitecture: all\nMaintainer: Test <test@example.invalid>\nDescription: Test\n")
            (stage / "DEBIAN/conffiles").write_text("/etc/port.conf\n")
            deb = base / "test.deb"
            subprocess.run(["dpkg-deb", "-b", str(stage), str(deb)], check=True, capture_output=True)
            subprocess.run(["dpkg", "--root=" + str(root), "--force-confold", "--force-confdef", "-i", str(deb)], check=True, capture_output=True)
            self.assertEqual((root / "etc/port.conf").read_text(), "existing custom config")


class PackagingTests(unittest.TestCase):
    def test_payload_builder_and_legacy_bootstrap(self):
        if not shutil.which("dpkg-deb"):
            self.skipTest("Needs dpkg-deb")
        spec = importlib.util.spec_from_file_location("build_update", REPO / "scripts/build-update-payload.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for path in ("rootfs/boot", "rootfs/usr/lib", "out/local-debs",
                         "out/kernel-gts9uwifi", "out/rootfs-overlay/usr/lib/modules/test",
                         "out/rootfs-overlay/etc/modules-load.d"):
                (base / path).mkdir(parents=True)
            (base / "rootfs/usr/lib/gts9u-required-packages.txt").write_text("python3\n")
            (base / "rootfs/boot/config-test").write_text("CONFIG_TEST=y\n")
            (base / "out/kernel-gts9uwifi/kernel.release").write_text("test\n")
            (base / "out/kernel-gts9uwifi/sm8550-samsung-gts9uwifi.dtb").write_bytes(b"test dtb")
            (base / "out/rootfs-overlay/usr/lib/modules/test/ath12k.ko").write_bytes(b"matching module")
            (base / "out/rootfs-overlay/etc/modules-load.d/ath12k.conf").write_text("ath12k\n")
            for name in ("ubuntu-gts9u-companion", "ubuntu-gts9u-device"):
                stage = base / name / "DEBIAN"
                stage.mkdir(parents=True)
                (stage / "control").write_text("Package: " + name + "\nVersion: 1\nArchitecture: arm64\nMaintainer: Test <test@example.invalid>\nDescription: Test\n")
                subprocess.run(["dpkg-deb", "-b", str(stage.parent), str(base / "out/local-debs" / (name + "_1_arm64.deb"))], check=True, capture_output=True)
            original = subprocess.check_output
            def output(argv, **kwargs):
                return "1" if argv[0] == "chroot" else original(argv, **kwargs)
            bootstrap = base / "gts9u-update.pyz"
            with patch.object(sys, "argv", ["build-update", "--base", str(base), "--version", "1.1", "--bootstrap", str(bootstrap)]), patch.object(module.subprocess, "check_output", side_effect=output):
                module.main()
            self.assertEqual(json.loads((base / "out/update-payload/metadata.json").read_text())["tag"], "v1.1")
            hardware = base / "out/update-payload/debs/ubuntu-gts9u-hardware_1.1_arm64.deb"
            listing = subprocess.check_output(["dpkg-deb", "-c", str(hardware)], text=True)
            self.assertIn("ath12k.ko", listing)
            self.assertNotIn("/home/", listing)
            output = subprocess.check_output([sys.executable, str(bootstrap), "--status"], text=True)
            self.assertIn("state", json.loads(output))
            # The offline runner is frozen from source, including inside zipapp.
            command = "import sys;sys.path.insert(0,sys.argv[1]);from tab_companion import update_core,update_bundle;assert 'def prepare' in update_core.__loader__.get_source(update_core.__name__);assert 'def inspect' in update_bundle.__loader__.get_source(update_bundle.__name__)"
            subprocess.run([sys.executable, "-c", command, str(bootstrap)], check=True)

    def test_zip_builder_and_reader_agree(self):
        spec = importlib.util.spec_from_file_location("make_twrp_zip", REPO / "scripts/make-twrp-zip.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            images = base / "images"
            images.mkdir()
            for name in module.IMAGES:
                (images / name).write_bytes(b"x" * 32)
            payload = base / "payload"
            (payload / "debs").mkdir(parents=True)
            (payload / "debs/test_1_arm64.deb").write_bytes(b"a test payload")
            (payload / "metadata.json").write_text(json.dumps({"format": 1, "device": "gts9uwifi",
                "suite": "noble", "architecture": "arm64", "version": "1.1", "tag": "v1.1",
                "kernel_release": "test", "apt_packages": ["python3"]}))
            archive = base / "build.zip"
            with patch.dict(module.IMAGES, {n: 32 for n in module.IMAGES}), patch.dict(b.PARTITIONS, {n: 32 for n in b.PARTITIONS}), patch.object(sys, "argv", ["make-twrp-zip", str(images), str(archive), "--update-payload", str(payload)]):
                module.main()
                result = b.extract(archive, base / "extracted")
            self.assertEqual(result["tag"], "v1.1")
            self.assertFalse((base / "extracted/vbmeta.img").exists())
            self.assertFalse((base / "extracted/META-INF").exists())


if __name__ == "__main__":
    unittest.main()
