#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[1]


class UpgradeBuildInputsTests(unittest.TestCase):
    def test_locked_package_inputs_reject_wrong_suite_and_changed_bytes(self):
        spec = importlib.util.spec_from_file_location('locked_inputs', REPO / 'scripts/stage-rootfs-package-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'source'
            source.mkdir()
            file = source / 'example_1_all.deb'
            file.write_bytes(b'synthetic package')
            manifest = base / 'lock.json'
            destination = base / 'selected'
            manifest.write_text(json.dumps({'suite': 'noble', 'files': {file.name: module.digest(file)}}))
            with self.assertRaisesRegex(ValueError, 'suite'):
                module.stage(source, manifest, destination, 'resolute', True)
            manifest.write_text(json.dumps({'suite': 'resolute', 'files': {file.name: '0' * 64}}))
            with self.assertRaisesRegex(ValueError, 'checksum'):
                module.stage(source, manifest, destination, 'resolute', True)
            self.assertFalse(destination.exists())

    def test_fprintd_source_hashes_are_complete(self):
        source = (REPO / "scripts/build-fprintd-matched.sh").read_text()
        digests = re.findall(r"^\s+([0-9a-f]{40,})\s*$", source, re.M)
        self.assertEqual(len(digests), 6)
        for digest in digests:
            with self.subTest(digest=digest):
                self.assertEqual(len(digest), 64)

    def test_resolute_device_is_newer_than_the_bridge(self):
        control = REPO / "packaging/ubuntu-gts9u-device/DEBIAN"
        version = lambda name: re.search(r"^Version: (.+)$", (control / name).read_text(), re.M)[1]
        result = subprocess.run(["dpkg", "--compare-versions", version("control-resolute"),
                                 "gt", version("control")], capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_resolute_fingerprint_pair_and_boot_dependencies(self):
        control = (REPO / "packaging/ubuntu-gts9u-device/DEBIAN/control-resolute").read_text()
        version = (REPO / "packaging/fprintd/version-resolute").read_text().strip()
        for package in ("fprintd", "libpam-fprintd"):
            self.assertIn(f"{package} (>= {version})", control)
        self.assertIn("gir1.2-mutter-18", control)
        self.assertNotIn("gir1.2-mutter-14", control)
        for package in ("plymouth", "plymouth-theme-spinner", "gnome-shell-ubuntu-extensions"):
            self.assertIn(package, control)

    def test_rootfs_rejects_reusing_a_noble_buildroot_for_resolute(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            release = base / "buildroot/etc/os-release"
            release.parent.mkdir(parents=True)
            release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            result = subprocess.run(["bash", str(REPO / "scripts/build-ubuntu-rootfs.sh")],
                env={**os.environ, "UBUNTU_SUITE": "resolute", "UBUNTU_WORKDIR": str(base),
                     "BUILDROOT_DIR": str(base / "buildroot")}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("buildroot does not match resolute", result.stderr)
            self.assertFalse((base / "hooks").exists())
            self.assertEqual(release.read_text(), 'ID=ubuntu\nVERSION_ID="24.04"\n')

    def test_rootfs_dispatches_resolute_packages(self):
        source = (REPO / "scripts/build-ubuntu-rootfs.sh").read_text()
        self.assertIn('export UBUNTU_SUITE="$suite"', source)
        self.assertIn('camera_package=libcamera0.7', source)
        self.assertIn('fingerprint_tod_package=libfprint-2-tod1', source)
        self.assertIn('camera_builder=$repo/scripts/build-resolute-camera-packages.sh', source)
        self.assertIn('fprintd_version=$(cat "$repo/packaging/fprintd/version-resolute")', source)
        self.assertIn('resolute) power_version=50.0-1ubuntu1+gts9u1', source)
        self.assertIn('power_patch=ambient-target-hysteresis.patch', source)
        self.assertIn('if [ "$suite" = noble ]; then\nmutter_version=46.', source)
        self.assertIn('$gnome_local_packages', source)

    def test_all_project_extensions_retain_gnome50_support(self):
        extensions = list(REPO.glob("packaging/ubuntu-gts9u-*/usr/share/gnome-shell/extensions/*"))
        companion = list((REPO / 'external/galaxy-companion').glob(
            'packaging/galaxy-companion/usr/share/gnome-shell/extensions/*'))
        self.assertTrue(extensions)
        self.assertTrue(companion, 'Initialize the pinned Companion submodule')
        extensions += companion
        for extension in extensions:
            with self.subTest(extension=extension.name):
                metadata = json.loads((extension / "metadata.json").read_text())
                self.assertEqual(metadata["uuid"], extension.name)
                self.assertIn("50", metadata["shell-version"])


class MigrationFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.archive = self.base / "baseline.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("rootfs.img", b"simulated ext4 image")
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location("migration_fixture",
            REPO / "scripts/prepare-release-migration-fixture.py")
        self.fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fixture)
        self.manifest = {"suite": "noble", "version": "1.3.0"}
        self.output = self.base / "fixture"

    def tearDown(self):
        self.temporary.cleanup()

    def test_bad_digest_never_creates_a_fixture_or_executes_debugfs(self):
        with patch.object(self.fixture.subprocess, "run") as execute:
            with self.assertRaisesRegex(ValueError, "published digest"):
                self.fixture.prepare(self.archive, "0" * 64, self.output)
            execute.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_fixture_is_not_replaced(self):
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_text("existing work")
        with self.assertRaisesRegex(ValueError, "new absolute Linux"):
            self.fixture.prepare(self.archive, self.digest, self.output)
        self.assertEqual(marker.read_text(), "existing work")

    def test_wrong_release_is_rejected_before_extraction(self):
        with patch.object(self.fixture.bundle, "inspect",
                return_value={"suite": "noble", "version": "1.2.0"}):
            with self.assertRaisesRegex(ValueError, "port 1.3.0"):
                self.fixture.prepare(self.archive, self.digest, self.output)
        self.assertFalse(self.output.exists())

    def test_fixture_contract_with_simulated_debugfs(self):
        def extract(argv, **kwargs):
            self.assertEqual(argv[0], "debugfs")
            root = self.output / "root"
            for directory in ("etc", "usr/lib", "var/lib/dpkg"):
                (root / directory).mkdir(parents=True)
            (root / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            (root / "usr/lib/gts9u-release.json").write_text(json.dumps({
                "version": "1.3.0", "device": "gts9uwifi"}))
            (root / "var/lib/dpkg/status").write_text("simulated package database")
        with patch.object(self.fixture.bundle, "inspect", return_value=self.manifest), \
                patch.object(self.fixture.subprocess, "run", side_effect=extract):
            root = self.fixture.prepare(self.archive, self.digest, self.output)
        self.assertEqual(root, self.output / "root")
        self.assertEqual((self.output / "rootfs.img").read_bytes(), b"simulated ext4 image")
        self.assertEqual(json.loads((self.output / "provenance.json").read_text())["zip_sha256"],
                         self.digest)


if __name__ == "__main__":
    unittest.main()
