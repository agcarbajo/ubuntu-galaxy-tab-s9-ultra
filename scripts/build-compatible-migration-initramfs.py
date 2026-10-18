#!/usr/bin/env python3
"""Retain the proven early-boot runtime while selecting the new Resolute root."""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]


def install_root_slot_hook(root):
    hook = root / 'scripts/local-bottom/gts9u-root-slot'
    hook.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / 'packaging/ubuntu-gts9u-device/usr/share/initramfs-tools/scripts/local-bottom/gts9u-root-slot', hook)
    hook.chmod(0o755)
    # initramfs-tools sources ORDER; it does not enumerate executable hooks.
    # The trusted bootstrap may have no local-bottom stage at all. Preserve
    # its existing ordering and register the new hook exactly once.
    order = hook.parent / 'ORDER'
    text = order.read_text() if order.exists() else ''
    command = '/scripts/local-bottom/gts9u-root-slot "$@"'
    if command not in text.splitlines():
        if text and not text.endswith('\n'):
            text += '\n'
        text += command + '\n[ -e /conf/param.conf ] && . /conf/param.conf\n'
    order.write_text(text)
    order.chmod(0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init-boot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--kernel-config', type=Path, required=True)
    parser.add_argument('--baseline-root', type=Path, required=True)
    args = parser.parse_args()
    config = args.kernel_config.read_text().splitlines()
    for name in ('SCSI', 'BLK_DEV_SD', 'SCSI_UFSHCD', 'SCSI_UFS_QCOM', 'PHY_QCOM_QMP_UFS', 'EXT4_FS'):
        if 'CONFIG_' + name + '=y' not in config:
            raise ValueError('The migration bootstrap requires built-in root providers')
    with args.init_boot.open('rb') as source:
        header = source.read(4096)
        if header[:8] != b'ANDROID!' or struct.unpack_from('<I', header, 8)[0] != 0:
            raise ValueError('Expected the trusted header-v4 init_boot image')
        size = struct.unpack_from('<I', header, 12)[0]
        ramdisk = source.read(size)
    if ramdisk[:4] != bytes.fromhex('02214c18'):
        raise ValueError('Expected the physically validated legacy-LZ4 bootstrap')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / 'root'
        root.mkdir()
        data = subprocess.check_output(['lz4', '-dc'], input=ramdisk)
        subprocess.run(['cpio', '-id', '--quiet'], input=data, cwd=root, check=True)
        modules = root / 'usr/lib/modules'
        if modules.exists():
            shutil.rmtree(modules)
        for file in root.rglob('*'):
            if '.ko' in file.suffixes:
                raise ValueError('No previous-build module may enter the migration bootstrap')
        install_root_slot_hook(root)
        blockdev = root / 'usr/sbin/blockdev'
        if not blockdev.is_file():
            blockdev.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.baseline_root / 'usr/sbin/blockdev', blockdev)
            blockdev.chmod(0o755)
        names = sorted(['.'] + [file.relative_to(root).as_posix() for file in root.rglob('*')])
        archive = subprocess.check_output(['cpio', '--null', '-o', '--format=newc', '--reproducible', '--quiet'],
            cwd=root, input=('\0'.join(names) + '\0').encode())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['lz4', '-l', '-12', '-', str(args.output)], input=archive, check=True)
    if args.output.stat().st_size > 8314880:
        raise ValueError('The compatible bootstrap exceeds the Android v4 init_boot budget')
    print('Compatible migration initramfs:', args.output.stat().st_size, 'bytes;',
          hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
