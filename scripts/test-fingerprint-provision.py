#!/usr/bin/python3
"""Offline tests for the fingerprint provisioning helper.

No partition is opened, no mount is attempted and nothing under /var or /mnt
is touched: the LP metadata parser runs on a synthetic super image, the file
validators on fabricated ELF segments, and the installer in a temporary root.
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / 'packaging/ubuntu-gts9u-device'
SCRIPT = PACKAGE / 'usr/libexec/ubuntu-gts9u-fingerprint-provision'
loader = importlib.machinery.SourceFileLoader('provision', str(SCRIPT))
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader(loader.name, loader)
prov = importlib.util.module_from_spec(spec)
loader.exec_module(prov)


def lp_image(partitions, metadata_max_size=65536, slot_count=2):
    """Build the first bytes of a super image the way liblp lays them out:
    reserved sector, geometry twice, then metadata slot 0."""
    extents = []
    parts = []
    for name, ranges in partitions.items():
        first = len(extents)
        for offset, length, target_type in ranges:
            extents.append(struct.pack('<QIQI', length // 512, target_type, offset // 512, 0))
        parts.append(struct.pack('<36sIIII', name.encode(), 0, first, len(ranges), 0))
    tables = b''.join(parts) + b''.join(extents)
    header_size = 256
    descriptors = struct.pack('<III', 0, len(parts), 52) + \
        struct.pack('<III', len(parts) * 52, len(extents), 24) + \
        struct.pack('<III', len(tables), 0, 16) + struct.pack('<III', len(tables), 0, 64)
    header = struct.pack('<IHHI', prov.LP_METADATA_MAGIC, 10, 2, header_size)
    header += b'\0' * 32 + struct.pack('<I', len(tables)) + hashlib.sha256(tables).digest()
    header += descriptors
    header += b'\0' * (header_size - len(header))
    header_checksum = hashlib.sha256(header).digest()
    header = header[:12] + header_checksum + header[44:]
    geometry = struct.pack('<II', prov.LP_GEOMETRY_MAGIC, 52) + b'\0' * 32 + \
        struct.pack('<III', metadata_max_size, slot_count, 4096)
    geometry = geometry[:8] + hashlib.sha256(geometry).digest() + geometry[40:]
    geometry = geometry.ljust(prov.LP_GEOMETRY_SIZE, b'\0')
    metadata = (header + tables).ljust(metadata_max_size, b'\0')
    return b'\0' * prov.LP_RESERVED + geometry + geometry + metadata


def fake_elf(size=4096, phnum=prov.TA_SEGMENTS, machine=prov.EM_AARCH64, cls=2):
    header = bytearray(64)
    header[:4] = prov.ELF_MAGIC
    header[4] = cls
    struct.pack_into('<H', header, 18, machine)
    struct.pack_into('<H', header, 56, phnum)
    return bytes(header).ljust(size, b'\x5a')


class LpMetadata(unittest.TestCase):
    def test_parses_linear_extents(self):
        image = lp_image({'system': [(1 << 20, 8 << 20, 0)], 'vendor': [(16 << 20, 4 << 20, 0)]})
        parts = prov.parse_lp_metadata(image)
        self.assertEqual(parts['vendor'], [(16 << 20, 4 << 20)])
        self.assertEqual(parts['system'], [(1 << 20, 8 << 20)])

    def test_zero_fill_extents_are_not_offered(self):
        image = lp_image({'vendor': [(16 << 20, 4 << 20, 1)], 'odm': [(32 << 20, 1 << 20, 0)]})
        parts = prov.parse_lp_metadata(image)
        self.assertNotIn('vendor', parts)
        self.assertIn('odm', parts)

    def test_corrupted_tables_are_rejected(self):
        image = bytearray(lp_image({'vendor': [(16 << 20, 4 << 20, 0)]}))
        start = prov.LP_RESERVED + 2 * prov.LP_GEOMETRY_SIZE + 256
        image[start] ^= 0xff
        with self.assertRaisesRegex(prov.ProvisionError, 'tables checksum'):
            prov.parse_lp_metadata(bytes(image))

    def test_wrong_magic_and_short_image(self):
        with self.assertRaisesRegex(prov.ProvisionError, 'too short'):
            prov.parse_lp_metadata(b'\0' * 100)
        with self.assertRaisesRegex(prov.ProvisionError, 'no LP geometry'):
            prov.parse_lp_metadata(b'\0' * (prov.LP_RESERVED + 3 * prov.LP_GEOMETRY_SIZE))

    def test_slotted_name_is_accepted_only_when_unique(self):
        self.assertEqual(prov.select_logical({'vendor': [(1, 2)]}, 'vendor'), ('vendor', [(1, 2)]))
        self.assertEqual(prov.select_logical({'vendor_a': [(1, 2)]}, 'vendor'), ('vendor_a', [(1, 2)]))
        with self.assertRaisesRegex(prov.ProvisionError, 'no vendor'):
            prov.select_logical({'vendor_a': [(1, 2)], 'vendor_b': [(3, 4)]}, 'vendor')
        with self.assertRaisesRegex(prov.ProvisionError, 'no vendor'):
            prov.select_logical({'vendor_dlkm': [(1, 2)]}, 'vendor')


class Filesystems(unittest.TestCase):
    def test_detects_erofs_and_ext4(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'image'
            data = bytearray(4096)
            data[1024:1028] = b'\xe2\xe1\xf5\xe0'
            image.write_bytes(data)
            self.assertEqual(prov.detect_filesystem(image), 'erofs')
            data = bytearray(4096)
            data[1024 + 0x38:1024 + 0x3a] = b'\x53\xef'
            image.write_bytes(data)
            self.assertEqual(prov.detect_filesystem(image), 'ext4')
            image.write_bytes(bytes(4096))
            with self.assertRaisesRegex(prov.ProvisionError, 'unrecognised'):
                prov.detect_filesystem(image)


class Validation(unittest.TestCase):
    def test_ta_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(prov.TA_SEGMENTS):
                (root / ('dualfp.b%02d' % i)).write_bytes(fake_elf() if i == 0 else b'x' * 10)
            prov.check_ta(root, 'dualfp')
            (root / 'dualfp.b05').write_bytes(b'')
            with self.assertRaisesRegex(prov.ProvisionError, 'b05 is missing or empty'):
                prov.check_ta(root, 'dualfp')
            (root / 'dualfp.b05').write_bytes(b'x')
            (root / 'dualfp.b00').write_bytes(fake_elf(phnum=3))
            with self.assertRaisesRegex(prov.ProvisionError, 'declares 3 segments'):
                prov.check_ta(root, 'dualfp')
            with self.assertRaisesRegex(prov.ProvisionError, 'missing'):
                prov.check_ta(root, 'hwvault')

    def test_elf_must_be_aarch64(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lib.so'
            path.write_bytes(fake_elf())
            prov.check_elf(path, 'lib')
            path.write_bytes(fake_elf(machine=62))
            with self.assertRaisesRegex(prov.ProvisionError, 'AArch64'):
                prov.check_elf(path, 'lib')
            path.write_bytes(b'not elf')
            with self.assertRaisesRegex(prov.ProvisionError, 'not an ELF'):
                prov.check_elf(path, 'lib')

    def test_sizes_match_the_driver_limits(self):
        self.assertEqual(prov.CALIBRATION_MAX, 0x80000)
        self.assertEqual(prov.OPTICAL_MAX, 4 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calib.dat'
            path.write_bytes(b'c' * 500000)
            prov.check_size(path, prov.CALIBRATION_MAX, 'calib.dat')
            path.write_bytes(b'')
            with self.assertRaisesRegex(prov.ProvisionError, 'invalid size 0'):
                prov.check_size(path, prov.CALIBRATION_MAX, 'calib.dat')


class Installation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / 'state'
        self.patches = [
            patch.object(prov, 'STATE', self.state),
            patch.object(prov, 'FIRMWARE', self.state / 'firmware'),
            patch.object(prov, 'RUNTIME', self.state / 'runtime'),
            patch.object(prov, 'MANIFEST', self.state / 'runtime.sha256'),
            patch.object(prov, 'PROVENANCE', self.state / 'provenance.json'),
            patch.object(prov, 'NVM_DIRS', (root / 'persist', root / 'spunvm')),
            patch.object(prov.os, 'sync'),
        ]
        for p in self.patches:
            p.start()
        self.stage = root / 'stage'
        self.stage.mkdir()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def fill_runtime(self, stage):
        for name in prov.RUNTIME_FILES:
            path = stage / 'runtime' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(fake_elf(256) if not name.endswith('firmware_name') else b'spss1p.mdt\n')

    def test_install_is_atomic_and_writes_manifest(self):
        (self.stage / 'firmware').mkdir()
        for name in prov.TA_NAMES:
            (self.stage / 'firmware' / (name + '.b00')).write_bytes(fake_elf())
        (self.stage / 'firmware' / 'calib.dat').write_bytes(b'c')
        (self.stage / 'firmware' / 'egoptbds.dat').write_bytes(b'o')
        self.fill_runtime(self.stage)
        report = {'sources': {}, 'warnings': [], 'runtime_complete': True}
        prov.install(self.stage, report)
        self.assertFalse((self.stage / 'firmware').exists())
        state = prov.current_state()
        self.assertTrue(state['firmware'])
        self.assertTrue(state['runtime'])
        self.assertTrue(state['runtime_complete'])
        self.assertEqual(report['runtime_files'], len(prov.RUNTIME_FILES))
        manifest = (self.state / 'runtime.sha256').read_text().splitlines()
        self.assertEqual(len(manifest), len(prov.RUNTIME_FILES))
        for line in manifest:
            digest, name = line.split(None, 1)
            self.assertEqual(digest, hashlib.sha256((self.state / 'runtime' / name).read_bytes()).hexdigest())
        self.assertEqual((self.state / 'provenance.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((self.state / 'provenance.json').read_text())['runtime_complete'], True)

    def test_reinstall_replaces_previous_set(self):
        self.fill_runtime(self.stage)
        prov.install(self.stage, {'sources': {}, 'warnings': []})
        stage2 = self.state / 'stage2'
        stage2.mkdir()
        self.fill_runtime(stage2)
        (stage2 / 'runtime' / 'bin/sec_nvm').write_bytes(fake_elf(512))
        prov.install(stage2, {'sources': {}, 'warnings': []})
        self.assertEqual((self.state / 'runtime/bin/sec_nvm').stat().st_size, 512)
        self.assertFalse((self.state / 'runtime.previous').exists())

    def test_incomplete_runtime_is_reported(self):
        self.fill_runtime(self.stage)
        (self.stage / 'runtime' / prov.SHIM).unlink()
        prov.install(self.stage, {'sources': {}, 'warnings': []})
        state = prov.current_state()
        self.assertTrue(state['runtime'])
        self.assertFalse(state['runtime_complete'])

    def test_nvm_dirs_are_private_and_never_symlinks(self):
        prov.ensure_nvm_dirs()
        for path in prov.NVM_DIRS:
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        link = prov.NVM_DIRS[0]
        os.rmdir(link)
        link.symlink_to(self.tmp.name)
        with self.assertRaisesRegex(prov.ProvisionError, 'symlink'):
            prov.ensure_nvm_dirs()

    def test_check_writes_nothing(self):
        with patch.object(prov, 'PACKAGED_FIRMWARE', self.state / 'none'), \
             patch.object(prov, 'LEGACY_RUNTIME', self.state / 'none'), \
             patch.object(prov, 'BY_LABEL', self.state / 'none'), \
             patch('builtins.print') as printed:
            self.assertEqual(prov.main(['--check']), 0)
        self.assertFalse(self.state.exists())
        text = printed.call_args[0][0]
        self.assertIn('partition apnhlos  MISSING', text)
        self.assertIn('provisioned firmware: no', text)

    def test_boot_without_sensor_is_a_no_op(self):
        with patch.object(prov.os, 'geteuid', return_value=0), \
             patch.object(prov.Path, 'exists', return_value=False), \
             patch.object(prov, 'collect_firmware') as firmware, \
             patch.object(prov, 'collect_runtime') as runtime:
            self.assertEqual(prov.main(['--boot']), 0)
        firmware.assert_not_called()
        runtime.assert_not_called()

    def test_boot_requires_root(self):
        with patch.object(prov.os, 'geteuid', return_value=1000):
            self.assertEqual(prov.main(['--boot']), 1)


class Packaging(unittest.TestCase):
    def test_unit_runs_before_secure_startup(self):
        unit = (PACKAGE / 'usr/lib/systemd/system/ubuntu-gts9u-fingerprint-provision.service').read_text()
        self.assertIn('Before=ubuntu-gts9u-fingerprint-secure.service', unit)
        self.assertIn('ConditionPathExists=/sys/bus/platform/devices/egis-el721', unit)
        self.assertIn('Type=oneshot', unit)
        secure = (PACKAGE / 'usr/lib/systemd/system/ubuntu-gts9u-fingerprint-secure.service').read_text()
        self.assertIn('After=ubuntu-gts9u-fingerprint-provision.service', secure)
        self.assertIn('Wants=ubuntu-gts9u-fingerprint-provision.service', secure)

    def test_unit_is_enabled_by_postinst(self):
        postinst = (PACKAGE / 'DEBIAN/postinst').read_text()
        self.assertIn('ubuntu-gts9u-fingerprint-provision.service:multi-user.target', postinst)

    def test_secure_supervisor_prefers_provisioned_runtime(self):
        source = (PACKAGE / 'usr/libexec/ubuntu-gts9u-fingerprint-secure').read_text()
        self.assertIn("PROVISIONED = Path('/var/lib/ubuntu-gts9u/fingerprint')", source)
        self.assertIn('def select_runtime()', source)
        self.assertLess(source.index('def select_runtime()'), source.index('RUNTIME, MANIFEST = select_runtime()'))

    def test_libfprint_prefers_provisioned_firmware(self):
        qtee = (REPO / 'packaging/libfprint/el721-qtee.c').read_text()
        self.assertIn('/var/lib/ubuntu-gts9u/fingerprint/firmware', qtee)
        self.assertIn('el721_qtee_firmware_directory (void)', qtee)
        for name in ('el721.c', 'el721-secure-owner.c'):
            self.assertIn('el721_qtee_firmware_directory ()', (REPO / 'packaging/libfprint' / name).read_text())

    def test_runtime_file_list_matches_packaged_manifest(self):
        manifest = (PACKAGE / 'usr/share/ubuntu-gts9u/fingerprint-runtime.sha256').read_text()
        names = {line.split()[1] for line in manifest.splitlines() if line.strip()}
        self.assertEqual(names, set(prov.RUNTIME_FILES))

    def test_log_shim_is_built_from_source_and_packaged(self):
        source = REPO / 'packaging/fingerprint-shim/android-log-capture.c'
        self.assertTrue(source.is_file())
        text = source.read_text()
        for symbol in ('__android_log_print', '__android_log_buf_print'):
            self.assertIn(symbol, text)
        builder = (REPO / 'scripts/build-fingerprint-log-shim.sh').read_text()
        self.assertIn('-nostdlib', builder)
        self.assertIn('android-log-capture.c', builder)
        device = (REPO / 'scripts/build-device-package.sh').read_text()
        self.assertIn('usr/lib/ubuntu-gts9u/fingerprint', device)
        self.assertIn('build-fingerprint-log-shim.sh', device)
        for lib in ('liblog_capture.so', 'libvmmem.so'):
            self.assertIn(lib, device)
            self.assertIn(lib, builder)
        vmmem = (REPO / 'packaging/fingerprint-shim/vmmem-compat.c').read_text()
        for symbol in ('CreateVmMem', 'FreeVmMem', 'FindVmByName', 'ShareDmabuf',
                       'qcom,cp_spss_hlos_shared', 'qcom,hlos'):
            self.assertIn(symbol, vmmem)

    def test_runtime_sources_follow_the_validated_set(self):
        self.assertEqual(prov.SYSTEM_FILES['bin/linker64'][0], ('runtime-apex', 'bin/linker64'))
        self.assertEqual(prov.SYSTEM_FILES['lib64/ld-android.so'][0], ('runtime-apex', 'bin/linker64'))
        for name in ('libcrypto.so', 'libdmabufheap.so', 'libion.so', 'libhardware_legacy.so'):
            self.assertEqual(prov.SYSTEM_FILES['lib64/' + name][0][0], 'vndk-apex')
        self.assertNotIn('lib64/libvmmem.so', prov.VENDOR_FILES)
        self.assertIn('lib64/libvmmem.so', prov.PORT_LIBS)

    def test_erofs_module_is_device_owned(self):
        payload = (REPO / 'scripts/build-update-payload.py').read_text()
        self.assertIn('"erofs.ko"', payload)
        builder = (REPO / 'scripts/build-device-package.sh').read_text()
        self.assertIn('erofs.ko', builder)


if __name__ == '__main__':
    unittest.main()
