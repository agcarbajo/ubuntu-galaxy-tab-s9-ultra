#!/usr/bin/env python3
"""Shipping-image privacy checks, without touching a running installation."""
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'sanitize', pathlib.Path(__file__).with_name('sanitize-release-rootfs.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ShippingRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        for name, text in {
            'etc/os-release': 'ID=ubuntu\n',
            'etc/passwd': 'root:x:0:0:root:/root:/bin/bash\n',
            'etc/shadow': 'root:!:0:0:99999:7:::\n',
            'usr/lib/systemd/system/ubuntu-gts9u-ssh-host-keys.service': '[Unit]\n',
            'etc/ssh/ssh_host_ed25519_key': 'build-only fixture',
            'etc/ssh/ssh_host_ed25519_key.pub': 'build-only public fixture',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')

    def test_removes_build_identity(self):
        module.sanitize(self.root)
        self.assertFalse(list((self.root / 'etc/ssh').glob('ssh_host_*')))

    def test_rejects_personal_account_before_modifying_image(self):
        with (self.root / 'etc/passwd').open('a', encoding='utf-8') as file:
            file.write('owner:x:1000:1000:Owner:/home/owner:/bin/bash\n')
        with self.assertRaisesRegex(ValueError, 'personal user'):
            module.sanitize(self.root)
        self.assertTrue((self.root / 'etc/ssh/ssh_host_ed25519_key').exists())

    def test_missing_generation_unit_is_rejected(self):
        (self.root / 'usr/lib/systemd/system/ubuntu-gts9u-ssh-host-keys.service').unlink()
        with self.assertRaisesRegex(ValueError, 'generation unit'):
            module.sanitize(self.root)

    def test_rejects_personal_vm_in_home_before_modifying_image(self):
        path = self.root / 'home/owner/macos-vm-lab/guest.qcow2'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'private disk fixture')
        with self.assertRaisesRegex(ValueError, 'personal data in home'):
            module.sanitize(self.root)
        self.assertTrue((self.root / 'etc/ssh/ssh_host_ed25519_key').exists())

    def test_rejects_reserved_personal_namespaces(self):
        for name in ('var/lib/gts9u-project-archive', 'opt/ubuntu-gts9u-macos',
                     'var/lib/ubuntu-gts9u-macos'):
            with self.subTest(name=name):
                path = self.root / name
                path.mkdir(parents=True)
                with self.assertRaisesRegex(ValueError, 'personal deployment or archive'):
                    module.sanitize(self.root)
                self.assertTrue((self.root / 'etc/ssh/ssh_host_ed25519_key').exists())
                path.rmdir()

    def test_rejects_dangling_personal_namespace_link(self):
        path = self.root / 'opt/ubuntu-gts9u-macos'
        path.parent.mkdir()
        path.symlink_to('/nonexistent-private-macos-installation')
        with self.assertRaisesRegex(ValueError, 'personal deployment or archive'):
            module.sanitize(self.root)

    def test_allows_generic_virtualization_packages(self):
        for name in ('usr/bin/qemu-system-aarch64',
                     'usr/share/doc/gunyah/README',
                     'usr/share/vulkan/icd.d/freedreno_icd.aarch64.json'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('generic package fixture', encoding='utf-8')
        module.sanitize(self.root)

    def test_allows_uninitialized_machine_id(self):
        path = self.root / 'etc/machine-id'
        path.write_text('uninitialized\n', encoding='ascii')
        module.sanitize(self.root)

    def test_rejects_real_machine_id(self):
        path = self.root / 'etc/machine-id'
        path.write_text('0123456789abcdef0123456789abcdef\n', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'machine identity'):
            module.sanitize(self.root)

    def test_first_start_generates_unique_keys_and_preserves_existing(self):
        module.sanitize(self.root)
        command = ['ssh-keygen', '-A', '-f', str(self.root)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        keys = {p.name: p.read_bytes() for p in (self.root / 'etc/ssh').glob('ssh_host_*')}
        self.assertIn('ssh_host_ed25519_key', keys)
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        self.assertEqual(keys, {p.name: p.read_bytes() for p in (self.root / 'etc/ssh').glob('ssh_host_*')})


if __name__ == '__main__':
    unittest.main()
