#!/usr/bin/env python3
"""Prepare, never flash, the experimental GPU/UFS kernel #10 candidate from boot #8.

Intentionally accepts only the two audited input hashes. Preserves the boot
header and appended DTB, regenerates the existing unsigned AVB hash footer,
and checks the result. Requires the build host's AOSP avbtool.py.
"""
import argparse
import gzip
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

BASE_SHA = 'a48a7d1b81e27641683fc930b5f9c712990e3748121b09b1cc82bd33e5d9ac8f'
IMAGE_SHA = '2105964b0e7b1cdb89da621793e298e8cc8a0d8651eb80839dfccaf767e58fcc'
AVBTOOL_SHA = '69783733ce5e198317b02a5567cc356e898c891de872f58a963e9d5c082973c6'
SALT = '2105964b0e7b1cdb89da621793e298e8cc8a0d8651eb80839dfccaf767e58fcc'
PAGE = 4096
PARTITION_SIZE = 100663296


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unpack_kernel(boot):
    size = struct.unpack_from('<I', boot, 8)[0]
    decoder = zlib.decompressobj(31)
    raw = decoder.decompress(boot[PAGE:PAGE + size]) + decoder.flush()
    require(decoder.eof, 'Incomplete kernel gzip stream')
    return raw, decoder.unused_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--avbtool', type=Path, required=True)
    args = parser.parse_args()
    base = args.baseline.read_bytes()
    raw = args.image.read_bytes()
    require(hashlib.sha256(base).hexdigest() == BASE_SHA, 'Unexpected baseline boot')
    require(hashlib.sha256(raw).hexdigest() == IMAGE_SHA, 'Unexpected or partial kernel Image')
    require(hashlib.sha256(args.avbtool.read_bytes()).hexdigest() == AVBTOOL_SHA,
            'Expected the audited build-host AOSP avbtool 1.2.0')
    require(not args.output.exists(), 'Output already exists; will not overwrite it')
    require(len(base) == PARTITION_SIZE and base[:8] == b'ANDROID!', 'Invalid boot container')
    require(struct.unpack_from('<I', base, 40)[0] == 4, 'Expected boot header v4')
    require(struct.unpack_from('<I', base, 20)[0] == 1584, 'Unexpected header size')
    require(struct.unpack_from('<I', base, 12)[0] == 0, 'Unexpected boot ramdisk')
    require(struct.unpack_from('<I', base, 1580)[0] == 0, 'Unexpected boot signature')
    require(raw[56:60] == b'ARM\x64', 'Not an arm64 Image')
    require(b'Linux version 7.2.0-rc3-dirty ' in raw, 'Wrong module release')
    _, dtb = unpack_kernel(base)
    require(dtb[:4] == b'\xd0\x0d\xfe\xed', 'Missing appended DTB')
    require(struct.unpack_from('>I', dtb, 4)[0] == len(dtb), 'Unexpected DTB trailer')

    def avb(*arguments):
        subprocess.run([sys.executable, str(args.avbtool), *arguments], check=True)

    def verify(path):
        # avbtool resolves the hash descriptor's partition name as boot.img.
        with tempfile.TemporaryDirectory(prefix='gts9u-avb-check-') as directory:
            link = Path(directory) / 'boot.img'
            link.symlink_to(path.resolve())
            avb('verify_image', '--image', str(link))

    verify(args.baseline)
    kernel = gzip.compress(raw, compresslevel=9, mtime=0) + dtb
    header = bytearray(base[:PAGE])
    struct.pack_into('<I', header, 8, len(kernel))
    payload = bytes(header) + kernel
    payload += bytes((-len(payload)) % PAGE)
    require(len(payload) + 65536 < PARTITION_SIZE, 'Candidate exceeds partition capacity')
    with args.output.open('xb') as target:
        target.write(payload)
    avb('add_hash_footer', '--image', str(args.output), '--partition_name', 'boot',
        '--partition_size', str(PARTITION_SIZE), '--hash_algorithm', 'sha256',
        '--salt', SALT, '--algorithm', 'NONE', '--rollback_index', '0', '--flags', '0')
    verify(args.output)
    candidate = args.output.read_bytes()
    require(len(candidate) == PARTITION_SIZE, 'Unexpected final partition size')
    require(candidate[:8] == base[:8] and candidate[12:PAGE] == base[12:PAGE],
            'Boot header changed beyond kernel size')
    new_raw, new_dtb = unpack_kernel(candidate)
    require(new_raw == raw and new_dtb == dtb, 'Kernel or original DTB changed')
    print('PASS: kernel, original DTB, header, partition size and AVB hash verified')
    print(hashlib.sha256(candidate).hexdigest(), args.output)


if __name__ == '__main__':
    main()
