#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path
import runpy
import struct
import subprocess
import tempfile

BASE_SHA = 'add0ee44a386db86a9860ae6bfe846d3b9424695d05271e93e574fff21c806bd'
parser = argparse.ArgumentParser()
parser.add_argument('baseline', type=Path)
parser.add_argument('candidate', type=Path)
parser.add_argument('script', type=Path)
parser.add_argument('sha256sum', type=Path)
args = parser.parse_args()
entries = runpy.run_path(str(Path(__file__).with_name('inspect-init-boot.py')))['entries']


def archive(path):
    image = path.read_bytes()
    size = struct.unpack_from('<I', image, 12)[0]
    return image, subprocess.run(['lz4', '-dc'], input=image[4096:4096 + size],
                                 stdout=subprocess.PIPE, check=True).stdout


original, old_archive = archive(args.baseline)
candidate, new_archive = archive(args.candidate)
assert hashlib.sha256(original).hexdigest() == BASE_SHA
old = {name: (inode, mode, data) for name, inode, mode, data in entries(old_archive)}
new = {name: (inode, mode, data) for name, inode, mode, data in entries(new_archive)}
assert len(old) + 2 == len(new)
assert set(new) - set(old) == {'gts9u-suspend-preflight', 'usr/bin/sha256sum'}
for data in (old_archive, new_archive):
    listed = subprocess.run(['cpio', '-it', '--quiet'], input=data, check=True,
                            stdout=subprocess.PIPE).stdout.decode().splitlines()
    expected = set(old if data is old_archive else new) - {'TRAILER!!!'}
    assert set(listed) == expected, (sorted(expected - set(listed))[:12], sorted(set(listed) - expected)[:12])
assert all(old[name] == new[name] for name in old if name != 'init')
assert new['init'][2].replace(b'if /gts9u-suspend-preflight; then :; fi\n', b'') == old['init'][2]
assert new['gts9u-suspend-preflight'][2] == args.script.read_bytes()
assert new['usr/bin/sha256sum'][2] == args.sha256sum.read_bytes()
assert candidate[:12] == original[:12] and candidate[16:4096] == original[16:4096]
assert len(candidate) == len(original) == 8388608
assert b'add0ee44a386db86a9860ae6bfe846d3b9424695d05271e93e574fff21c806bd' in args.script.read_bytes()
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / 'lib').symlink_to('usr/lib')
    for name in ('usr/bin/sha256sum', 'usr/lib/ld-linux-aarch64.so.1',
                 'usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1',
                 'usr/lib/aarch64-linux-gnu/libc.so.6',
                 'usr/lib/aarch64-linux-gnu/libcrypto.so.3'):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        inode, mode, data = new[name]
        if mode & 0o170000 == 0o120000:
            target.symlink_to(data.decode())
        else:
            target.write_bytes(data)
            target.chmod(mode & 0o777)
    result = subprocess.run(['qemu-aarch64-static', '-L', temp,
                             str(root / 'usr/bin/sha256sum'), '/dev/null'],
                            check=True, text=True, stdout=subprocess.PIPE)
    assert result.stdout.startswith('e3b0c44298fc1c149afbf4c8996fb924')
print('PASS: installed baseline, AVB-sized candidate, unchanged entries, ARM64 SHA-256 and original init path')
