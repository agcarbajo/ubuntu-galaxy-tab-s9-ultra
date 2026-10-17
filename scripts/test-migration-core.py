#!/usr/bin/env python3
"""Isolated migration, data-retention and simulated boot-failure regressions."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
__import__("os").environ.setdefault("GALAXY_COMPANION_DEVICE", "gts9uwifi")
sys.path.insert(0, str(REPO / "external/galaxy-companion/packaging/galaxy-companion/usr/lib/galaxy-companion"))
sys.path.insert(0, str(REPO / "packaging/gts9u-migration"))
from galaxy_companion import update_core as core
from gts9u_migration import migration_core as migration, migration_plan as plans


class PackagePlanTests(unittest.TestCase):
    def test_epoch_versions_and_reviewed_replacements(self):
        plan = plans.parse_plan("Inst libfprint-2-2 [1:1.94.7] (1:1.95.1+tod1-0ubuntu2+gts9u2 Ubuntu [arm64])\n"
                                "Remv libcamera-gts9u [0.7.2]\n")
        self.assertEqual(plan["remove"], ["libcamera-gts9u"])
        self.assertIn("libfprint-2-2", plan["install"])

    def test_unreviewed_application_removal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            plans.parse_plan("Remv personal-application [1]\nInst gnome-shell (50.1 Ubuntu [arm64])")

    def test_downgrades_and_archive_kernels_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "downgrade"):
            plans.parse_plan("Inst example (1 Ubuntu [arm64])", {"example": "2"})
        with self.assertRaisesRegex(ValueError, "archive kernel"):
            plans.parse_plan("Inst linux-image-generic (7.0 Ubuntu [arm64])")

    def test_conflicting_and_empty_plans_are_rejected(self):
        for value in ("", "Inst example (1 Ubuntu)\nInst example (2 Ubuntu)",
                      "Inst libcamera-gts9u (2 Ubuntu)\nRemv libcamera-gts9u [1]"):
            with self.assertRaises(ValueError):
                plans.parse_plan(value)

    def test_dependency_selection_is_bounded_and_keeps_exact_epoch_versions(self):
        text = ('The following packages will be REMOVED:\n'
                '   libgjs0g (1.80.2)\n'
                'The following NEW packages will be installed:\n'
                '   libgjs0 (1.88.0-1)\n'
                'The following packages will be upgraded:\n'
                '   libfprint-2-2 (1:1.94.7 => 1:1.95.1+tod1-0ubuntu2+gts9u2)\n'
                '1 upgraded, 1 newly installed, 1 to remove and 0 not upgraded.\n')
        plan = plans.parse_selection(text, {'libgjs0g': '1.80.2', 'libfprint-2-2': '1:1.94.7'})
        self.assertEqual(plan['remove'], ['libgjs0g'])
        self.assertEqual(plan['install']['libfprint-2-2'], '1:1.95.1+tod1-0ubuntu2+gts9u2')
        for broken in (text.replace('libgjs0 (1.88.0-1)', 'unrelated (1)'),
                       text.replace('1 to remove', '2 to remove'),
                       text.replace('1.80.2)', 'bad version)'),
                       text.replace('libgjs0g (1.80.2)', 'personal-application (1)')):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                plans.parse_selection(broken)

    def test_obsolete_names_are_explicitly_removed_but_other_apps_requested(self):
        result = plans.requested_packages({"example": "1", "libcamera-gts9u": "1"}, ["gnome-shell"])
        self.assertIn("example", result)
        self.assertIn("libcamera-gts9u-", result)
        self.assertNotIn("libcamera-gts9u", result)
        with self.assertRaises(ValueError):
            plans.requested_packages({"--allow-unauthenticated": "1"}, [])


class AptRuntimeTests(unittest.TestCase):
    def test_generated_metapackage_is_in_the_canonical_offline_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'source'
            for name in ('var/lib/dpkg', 'etc/apt/preferences.d'):
                (source / name).mkdir(parents=True)
            (source / 'var/lib/dpkg/status').write_text('')
            (source / 'etc/apt/preferences.d/no-distro-kernel').write_text('Package: linux-image-*\nPin: release *\nPin-Priority: -1\n')
            transaction = base / 'transaction'
            (transaction / 'UPDATE/debs').mkdir(parents=True)
            runtime = migration.AptRuntime(transaction)
            runtime.configure(source)
            try:
                runtime.local_repository({'version': '1.4.0', 'apt_packages': ['python3']})
                cached = transaction / 'archives/ubuntu-gts9u-migration_1.4.0_all.deb'
                self.assertTrue(cached.is_file())
                self.assertEqual(migration.bundle.sha256(cached), migration.bundle.sha256(
                    transaction / 'UPDATE/debs/ubuntu-gts9u-migration_all.deb'))
                plan = {'install': {'ubuntu-gts9u-migration': '1.4.0'}, 'remove': []}
                self.assertIn(cached.name, migration.verify_archives(transaction, plan))
            finally:
                subprocess.run(['gpgconf', '--homedir', str(transaction / 'repository-signing'),
                                '--kill', 'gpg-agent'], check=True)


class RootSlotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.source = Path(self.temporary.name) / "source"
        self.source.mkdir()
        for name in ("etc", "home/example", "usr/bin", "var/lib/fprint", "etc/ssh",
                     "etc/NetworkManager/system-connections", "var/lib/gts9u-boot-sets/android"):
            (self.source / name).mkdir(parents=True, exist_ok=True)
        (self.source / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/bash\nexample:x:1000:1000::/home/example:/bin/bash\n")
        (self.source / "etc/shadow").write_text("root:!:1:0:99999:7:::\nexample:!synthetic:1:0:99999:7:::\n")
        (self.source / "home/example/dconf").write_text("synthetic user settings")
        (self.source / "var/lib/fprint/print").write_text("synthetic encrypted template")
        (self.source / "etc/ssh/ssh_host_test_key").write_text("not a real key; synthetic fixture")
        (self.source / "etc/NetworkManager/system-connections/example").write_text("synthetic network profile")
        (self.source / "usr/bin/example").write_text("user-installed application")
        self.slot = migration.create_slot(self.source, "a" * 32)

    def tearDown(self):
        self.temporary.cleanup()

    def test_real_rsync_retains_state_and_never_copies_home_or_recurses(self):
        if os.geteuid() != 0:
            self.skipTest("Linux root needed to preserve exact ownership")
        before = (self.source / "home/example/dconf").stat().st_ino
        root = migration.clone_system(self.source, self.slot)
        self.assertFalse((root / "home/example").exists())
        self.assertFalse((root / migration.STORE_NAME).exists())
        self.assertEqual((root / "usr/bin/example").read_text(), "user-installed application")
        plans.check_preservation(self.source, root)
        self.assertEqual((self.source / "home/example/dconf").stat().st_ino, before)
        self.assertEqual(stat.S_IMODE((root / ".gts9u-base").stat().st_mode), 0o700)

    def test_removed_timezone_compatibility_file_is_restored_without_masking_changes(self):
        timezone = self.source / 'etc/timezone'
        timezone.write_text('Europe/Madrid\n')
        (self.source / 'etc/localtime').symlink_to('/usr/share/zoneinfo/Europe/Madrid')
        root = migration.clone_system(self.source, self.slot)
        (root / 'etc/timezone').unlink()
        (root / 'etc/localtime').unlink()
        (root / 'etc/localtime').symlink_to('/usr/share/zoneinfo/Etc/UTC')
        with self.assertRaisesRegex(ValueError, 'protected'):
            plans.check_preservation(self.source, root)
        plans.restore_compatibility_files(self.source, root)
        self.assertEqual((root / 'etc/timezone').read_bytes(), timezone.read_bytes())
        plans.check_preservation(self.source, root)
        (root / 'etc/timezone').write_text('unexpected timezone\n')
        plans.restore_compatibility_files(self.source, root)
        with self.assertRaisesRegex(ValueError, 'protected'):
            plans.check_preservation(self.source, root)

    def test_changed_template_or_account_aborts_validation(self):
        root = migration.clone_system(self.source, self.slot)
        (root / "var/lib/fprint/print").write_text("changed synthetic template")
        with self.assertRaisesRegex(ValueError, "protected"):
            plans.check_preservation(self.source, root)
        (root / "var/lib/fprint/print").write_text("synthetic encrypted template")
        (root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/bash\nexample:x:1001:1000::/home/example:/bin/bash\n")
        with self.assertRaisesRegex(ValueError, "identity"):
            plans.check_preservation(self.source, root)

    def test_invalid_or_existing_slots_and_targets_are_rejected(self):
        for value in ("../home", "b" * 31, "x" * 32):
            with self.assertRaises(ValueError):
                migration.create_slot(self.source, value)
        with self.assertRaises(FileExistsError):
            migration.create_slot(self.source, "a" * 32)
        with self.assertRaises(ValueError):
            migration.clone_system(self.source, self.source / "home")

    def test_atomic_selector_is_regular_private_and_complete(self):
        file = self.source / migration.STORE_NAME / "selected"
        migration.atomic_text(file, "a" * 32 + "\n")
        self.assertEqual(file.read_text(), "a" * 32 + "\n")
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertFalse(file.with_suffix(".tmp").exists())

    def boot_fixture(self):
        transaction = Path(self.temporary.name) / "transaction"
        transaction.mkdir()
        devices = {}
        for part in migration.bundle.PARTITIONS:
            (transaction / (part + ".img")).write_bytes(b"new boot".ljust(32, b"\0"))
            devices[part] = Path(self.temporary.name) / ("device-" + part)
            devices[part].write_bytes(b"old boot".ljust(32, b"\0"))
        return transaction, devices

    def test_all_boot_readbacks_precede_root_selection(self):
        transaction, devices = self.boot_fixture()
        events = []
        original = core.copy_partition
        selector = self.source / migration.STORE_NAME / "selected"
        def copy(source, destination, size):
            self.assertFalse(selector.exists())
            events.append(source.stem)
            original(source, destination, size)
        with patch.dict(migration.bundle.PARTITIONS, {part: 32 for part in devices}), \
                patch.object(core, "copy_partition", side_effect=copy):
            migration.commit_slot(self.source, self.slot, transaction, {"kernel_release": "test"}, devices)
        self.assertEqual(events, list(migration.BOOT_ORDER))
        self.assertEqual(selector.read_text().strip(), self.slot.name)
        self.assertTrue((self.slot / "backup/SHA256SUMS").exists())
        for device in devices.values():
            self.assertEqual(device.read_bytes(), b"new boot".ljust(32, b"\0"))

    def test_detected_write_failure_restores_old_boot_and_does_not_select_new_root(self):
        transaction, devices = self.boot_fixture()
        original = core.copy_partition
        count = 0
        def fail(source, destination, size):
            nonlocal count
            count += 1
            if count == 2:
                destination.write_bytes(b"partial boot".ljust(32, b"\0"))
                raise OSError("simulated write failure")
            original(source, destination, size)
        with patch.dict(migration.bundle.PARTITIONS, {part: 32 for part in devices}), \
                patch.object(core, "copy_partition", side_effect=fail):
            with self.assertRaisesRegex(OSError, "simulated"):
                migration.commit_slot(self.source, self.slot, transaction, {"kernel_release": "test"}, devices)
        for device in devices.values():
            self.assertEqual(device.read_bytes(), b"old boot".ljust(32, b"\0"))
        self.assertFalse((self.source / migration.STORE_NAME / "selected").exists())
        self.assertFalse((self.source / migration.STORE_NAME / "pending").exists())


class HandoffTests(unittest.TestCase):
    def test_verified_bridge_transaction_is_retained_not_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transaction = root / "transaction"
            transaction.mkdir()
            (transaction / "release.zip").write_bytes(b"public fixture")
            handoff = root / "handoff"
            handoff.mkdir()
            archive = handoff / "release.zip"
            archive.write_bytes(b"public fixture")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(core, "TRANSACTION", transaction), \
                    patch.object(core, "status", return_value={"state": "preparing"}), \
                    patch.dict(os.environ, {core.HANDOFF_ENV: digest}):
                migration.adopt_handoff(archive)
            self.assertEqual((handoff / "bridge-staging/release.zip").read_bytes(), b"public fixture")
            self.assertEqual(list(transaction.iterdir()), [])

    def test_unknown_staging_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transaction = root / "transaction"
            transaction.mkdir()
            marker = transaction / "private-backup"
            marker.write_text("keep")
            archive = root / "release.zip"
            archive.write_bytes(b"fixture")
            with patch.object(core, "TRANSACTION", transaction), self.assertRaises(ValueError):
                migration.adopt_handoff(archive)
            self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
