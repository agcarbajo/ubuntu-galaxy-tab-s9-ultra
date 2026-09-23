#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess


def entries(archive):
    offset = 0
    while offset + 110 <= len(archive):
        header = archive[offset:offset + 110]
        if header[:6] not in (b'070701', b'070702'):
            raise ValueError(f'Invalid cpio header at {offset}')
        fields = [int(header[n:n + 8], 16) for n in range(6, 110, 8)]
        size, namesize = fields[6], fields[11]
        start = offset + 110
        name = archive[start:start + namesize]
        if len(name) != namesize or not name.endswith(b'\0'):
            raise ValueError('Invalid cpio name')
        data_start = (start + namesize + 3) & ~3
        data_end = data_start + size
        if data_end > len(archive):
            raise ValueError('Invalid cpio size')
        yield name[:-1].decode(), fields[0], fields[1], archive[data_start:data_end]
        offset = (data_end + 3) & ~3
        if name == b'TRAILER!!!\0':
            if archive[offset:].strip(b'\0'):
                raise ValueError('Unexpected data after cpio trailer')
            return
    raise ValueError('Missing cpio trailer')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('image', type=Path)
    args = parser.parse_args()
    image = args.image.read_bytes()
    if len(image) != 8388608 or image[:8] != b'ANDROID!' or struct.unpack_from('<I', image, 40)[0] != 4:
        raise ValueError('Not the expected init_boot v4 image')
    size = struct.unpack_from('<I', image, 12)[0]
    ramdisk = image[4096:4096 + size]
    if not ramdisk.startswith(b'\x02\x21\x4c\x18'):
        raise ValueError('Not legacy LZ4')
    archive = subprocess.run(['lz4', '-dc'], input=ramdisk, stdout=subprocess.PIPE, check=True).stdout
    print('SHA256', hashlib.sha256(image).hexdigest(), 'ramdisk size', size, 'lz4 start', ramdisk[:24].hex())
    records = list(entries(archive))
    busybox = next((inode for name, inode, mode, data in records if name == 'usr/bin/busybox'), None)
    for name, inode, mode, data in records:
        if name in ('init', 'run', 'scripts/functions', 'scripts/init-premount', 'scripts/init-premount/ORDER', 'TRAILER!!!') or name.startswith('scripts/init-premount/') or (inode == busybox and data) or 'libcrypto' in name or name.split('/')[-1] in ('ld-linux-aarch64.so.1', 'libc.so.6', 'sha256sum', 'dd', 'timeout', 'mount', 'umount', 'blockdev', 'udevadm', 'sleep', 'logger'):
            print(name, inode, oct(mode), len(data), data.decode(errors='replace') if mode & 0o170000 == 0o120000 else '')
            if name == 'init':
                print(data[:2400].decode(errors='replace'))
                point = data.find(b'init-premount')
                print(data[max(0, point - 300):point + 500].decode(errors='replace'))
            if name == 'scripts/functions':
                point = data.find(b'run_scripts()')
                print(data[point:point + 1700].decode(errors='replace'))


if __name__ == '__main__':
    main()
