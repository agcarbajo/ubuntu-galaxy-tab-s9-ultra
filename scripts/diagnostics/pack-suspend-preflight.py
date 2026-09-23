#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

BASE_SHA = 'add0ee44a386db86a9860ae6bfe846d3b9424695d05271e93e574fff21c806bd'
AVB_SHA = '14dc8d6ec533f551ec05ffd9a986ced0fd1290a201f62c91dad329dd51dfe3ed'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def entry(name, data, mode, inode):
    name = name.encode() + b'\0'
    fields = (inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0)
    header = b'070701' + b''.join(f'{value:08x}'.encode() for value in fields)
    prefix = header + name
    prefix += bytes(-len(prefix) % 4)
    result = prefix + data
    return result + bytes(-len(result) % 4)


def modify(archive, script, sha_binary):
    offset = 0
    result = bytearray()
    names = set()
    old_init = None
    while offset + 110 <= len(archive):
        header = archive[offset:offset + 110]
        if header[:6] != b'070701':
            raise ValueError(f'Invalid cpio at offset {offset}')
        fields = [int(header[pos:pos + 8], 16) for pos in range(6, 110, 8)]
        namesize, size = fields[11], fields[6]
        start = offset + 110
        name = archive[start:start + namesize]
        if not name.endswith(b'\0'):
            raise ValueError('Invalid cpio name')
        path = name[:-1].decode()
        if path in names:
            raise ValueError('Duplicate cpio entry: ' + path)
        names.add(path)
        data_start = (start + namesize + 3) & ~3
        end = (data_start + size + 3) & ~3
        if end > len(archive):
            raise ValueError('Invalid cpio payload size')
        if path == 'init':
            old_init = archive[data_start:data_start + size]
            needle = b'run_scripts /scripts/init-premount\n'
            if old_init.count(needle) != 1:
                raise ValueError('Unexpected init mount sequence')
            amended = old_init.replace(needle, needle + b'if /gts9u-suspend-preflight; then :; fi\n')
            fields[6] = len(amended)
            updated = b'070701' + b''.join(f'{value:08x}'.encode() for value in fields)
            prefix = updated + archive[start:data_start]
            result.extend(prefix + amended + bytes(-(len(prefix) + len(amended)) % 4))
        elif path == 'TRAILER!!!':
            if archive[end:].strip(b'\0'):
                raise ValueError('Unexpected data after cpio trailer')
            if 'gts9u-suspend-preflight' in names or 'usr/bin/sha256sum' in names:
                raise ValueError('Diagnostic already present')
            result.extend(entry('gts9u-suspend-preflight', script, 0o100755, 0x711001))
            result.extend(entry('usr/bin/sha256sum', sha_binary, 0o100755, 0x711002))
            result.extend(archive[offset:])
            return bytes(result), old_init, amended
        else:
            result.extend(archive[offset:end])
        offset = end
    raise ValueError('Missing cpio trailer')


def verify(avbtool, image):
    with tempfile.TemporaryDirectory() as tmp:
        name = Path(tmp) / 'init_boot.img'
        name.symlink_to(image.resolve())
        subprocess.run([sys.executable, str(avbtool), 'verify_image', '--image', str(name)],
                       check=True, stdout=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser()
    for key in ('baseline', 'script', 'sha256sum', 'avbtool', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--build-unvalidated-diagnostic', action='store_true')
    args = parser.parse_args()
    if not args.build_unvalidated_diagnostic:
        parser.error('Previous diagnostic failed to boot; output requires new physical validation')
    image = args.baseline.read_bytes()
    if digest(image) != BASE_SHA or len(image) != 8388608 or image[:8] != b'ANDROID!':
        raise ValueError('Baseline is not the verified installed init_boot')
    if struct.unpack_from('<I', image, 8)[0] != 0 or struct.unpack_from('<I', image, 40)[0] != 4:
        raise ValueError('Unexpected init_boot header')
    if digest(args.avbtool.read_bytes()) != AVB_SHA:
        raise ValueError('Unexpected avbtool')
    verify(args.avbtool, args.baseline)
    size = struct.unpack_from('<I', image, 12)[0]
    ramdisk = image[4096:4096 + size]
    if not ramdisk.startswith(b'\x02\x21\x4c\x18'):
        raise ValueError('Expected legacy LZ4')
    archive = subprocess.run(['lz4', '-dc'], input=ramdisk, check=True,
                             stdout=subprocess.PIPE).stdout
    changed, old_init, amended = modify(archive, args.script.read_bytes(),
                                         args.sha256sum.read_bytes())
    if amended.count(b'if /gts9u-suspend-preflight; then :; fi\n') != 1:
        raise ValueError('Diagnostic entry missing from init')
    packed = subprocess.run(['lz4', '-l', '-9', '-z', '-c'], input=changed,
                            check=True, stdout=subprocess.PIPE).stdout
    if not packed.startswith(b'\x02\x21\x4c\x18'):
        raise ValueError('Legacy LZ4 compression failed')
    if subprocess.run(['lz4', '-dc'], input=packed, check=True,
                      stdout=subprocess.PIPE).stdout != changed:
        raise ValueError('Ramdisk roundtrip failed')
    header = bytearray(image[:4096])
    struct.pack_into('<I', header, 12, len(packed))
    payload = bytes(header) + packed
    payload += bytes(-len(payload) % 4096)
    if len(payload) + 65536 >= len(image) or args.output.exists():
        raise ValueError(f'init_boot size budget exceeded ({len(payload)} + 65536 > {len(image)}) or output already exists')
    with args.output.open('xb') as target:
        target.write(payload)
    subprocess.run([sys.executable, str(args.avbtool), 'add_hash_footer', '--image',
                    str(args.output), '--partition_name', 'init_boot', '--partition_size',
                    str(len(image)), '--hash_algorithm', 'sha256', '--salt',
                    digest(packed), '--algorithm', 'NONE'], check=True)
    verify(args.avbtool, args.output)
    result = args.output.read_bytes()
    if len(result) != len(image) or result[:12] != image[:12] or result[16:4096] != image[16:4096]:
        raise ValueError('Unexpected init_boot header or size change')
    print('original_init_sha256', digest(old_init))
    print('diagnostic_ramdisk_bytes', len(packed))
    print('diagnostic_image_sha256', digest(result))


if __name__ == '__main__':
    main()
