import argparse
import gzip
import hashlib
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile

helpers = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'prepare-lid-wake-kernel11-boot.py'))
require = helpers['require']
unpack_kernel = helpers['unpack_kernel']
PAGE = helpers['PAGE']
SIZE = helpers['PARTITION_SIZE']


def main():
    parser = argparse.ArgumentParser()
    for name in ('baseline', 'image', 'output', 'avbtool'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--baseline-sha256', required=True)
    parser.add_argument('--image-sha256', required=True)
    args = parser.parse_args()
    require(args.baseline.is_file() and args.image.is_file(), 'Inputs must be regular files')
    base, raw = args.baseline.read_bytes(), args.image.read_bytes()
    require(hashlib.sha256(base).hexdigest() == args.baseline_sha256, 'Baseline hash mismatch')
    require(hashlib.sha256(raw).hexdigest() == args.image_sha256, 'Kernel hash mismatch')
    require(hashlib.sha256(args.avbtool.read_bytes()).hexdigest() == helpers['AVBTOOL_SHA'], 'Unaudited avbtool')
    require(not args.output.exists(), 'Refusing to overwrite an existing output')
    require(len(base) == SIZE and base[:8] == b'ANDROID!', 'Wrong boot container')
    require(struct.unpack_from('<I', base, 40)[0] == 4, 'Expected header v4')
    require(struct.unpack_from('<I', base, 20)[0] == 1584, 'Wrong header size')
    require(struct.unpack_from('<I', base, 12)[0] == 0, 'Unexpected ramdisk')
    require(struct.unpack_from('<I', base, 1580)[0] == 0, 'Unexpected boot signature')
    require(raw[56:60] == b'ARM\x64' and b'Linux version 7.2.0-rc3-dirty ' in raw, 'Wrong kernel ABI')
    _, dtb = unpack_kernel(base)
    require(dtb[:4] == b'\xd0\x0d\xfe\xed' and struct.unpack_from('>I', dtb, 4)[0] == len(dtb), 'Invalid appended DTB')

    def avb(*arguments):
        subprocess.run([sys.executable, str(args.avbtool), *arguments], check=True)

    def verify(path):
        with tempfile.TemporaryDirectory(prefix='gts9u-boot-verify-') as directory:
            link = Path(directory) / 'boot.img'
            link.symlink_to(path.resolve())
            avb('verify_image', '--image', str(link))

    verify(args.baseline)
    payload_kernel = gzip.compress(raw, compresslevel=9, mtime=0) + dtb
    header = bytearray(base[:PAGE])
    struct.pack_into('<I', header, 8, len(payload_kernel))
    payload = bytes(header) + payload_kernel
    payload += bytes(-len(payload) % PAGE)
    require(len(payload) + 65536 < SIZE, 'Kernel exceeds boot capacity')
    with args.output.open('xb') as stream:
        stream.write(payload)
    avb('add_hash_footer', '--image', str(args.output), '--partition_name', 'boot',
        '--partition_size', str(SIZE), '--hash_algorithm', 'sha256',
        '--salt', args.image_sha256, '--algorithm', 'NONE', '--rollback_index', '0', '--flags', '0')
    verify(args.output)
    candidate = args.output.read_bytes()
    require(len(candidate) == SIZE, 'Wrong final boot size')
    require(candidate[12:PAGE] == base[12:PAGE], 'Header changed beyond kernel size')
    new_raw, new_dtb = unpack_kernel(candidate)
    require(new_raw == raw and new_dtb == dtb, 'Kernel or DTB changed while packing')
    print('PASS: original header/DTB, replacement kernel and AVB footer verified')
    print(hashlib.sha256(candidate).hexdigest(), args.output)


if __name__ == '__main__':
    main()
