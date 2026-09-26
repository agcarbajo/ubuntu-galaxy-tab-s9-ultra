#!/usr/bin/env python3
"""Compare known RM gate instructions across hash-pinned private hyp images.

This is an offline byte comparison, not a proof that either image can boot a VM.
Neither image bytes nor authentication material are included in the output.
"""
import argparse
import hashlib
import struct
from pathlib import Path

KNOWN = {
    '6249c495ff8c63f45450496c36dfba34e664b49cf5447a5168a600591ddb824c',
    'dc03857f02055531c221476fa68e6e76006797c20b8e884a1ebd01cee3043b52',
    '83673420c2d7dafe2abb960563b7b13ad6c863bdfef28f35d8f36a1d645c6644',
}
GATES = {
    'allocation': (0x39288, 0x3928c, 0x39860),
    'authentication': (0x46a24, 0x4703c, 0x47040, 0x47044, 0x470fc,
                       0x47100, 0x47104, 0x47118, 0x4711c, 0x47324),
    'firmware_rpc': (0x378d4, 0x378dc, 0x378e0, 0x378ec, 0x37a84,
                     0x37a88, 0x37a90, 0x37a94, 0x37fbc, 0x37fc8,
                     0x37fcc, 0x37fd8, 0x392f0, 0x392f8, 0x393b0,
                     0x393bc, 0x39508, 0x39518, 0x39528, 0x39534,
                     0x39c70, 0x39c74),
}


def instructions(path):
    image = path.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    if digest not in KNOWN:
        raise ValueError(f'Unrecognized firmware: {path}')
    rm = image[0x1145c0:]
    if rm[:6] != b'\x7fELF\x02\x01':
        raise ValueError(f'RM ELF64 LE missing: {path}')
    phoff = struct.unpack_from('<Q', rm, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', rm, 54)
    loads = []
    for i in range(phnum):
        typ, flags, off, va, _pa, fs, _ms, _align = struct.unpack_from(
            '<IIQQQQQQ', rm, phoff + i * phsize)
        if typ == 1 and flags & 1:
            if off + fs > len(rm):
                raise ValueError(f'RM ELF bounds exceeded: {path}')
            loads.append((off, va, fs))
    found = {}
    for group, addresses in GATES.items():
        for addr in addresses:
            off, va, fs = next((s for s in loads if s[1] <= addr
                                and addr + 4 <= s[1] + s[2]), (None, None, None))
            if off is None:
                raise ValueError(f'Gate {addr:#x} outside executable segment')
            found[addr] = rm[off + addr - va:off + addr - va + 4]
    return digest, found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    old_hash, old = instructions(args.baseline)
    new_hash, new = instructions(args.candidate)
    print(f'baseline_sha256={old_hash}')
    print(f'candidate_sha256={new_hash}')
    changes = 0
    for group, addresses in GATES.items():
        differing = [hex(addr) for addr in addresses if old[addr] != new[addr]]
        changes += len(differing)
        print(f'{group}: {len(addresses) - len(differing)}/{len(addresses)} '
              f'identical; differing addresses: {", ".join(differing) or "none"}')
    if changes:
        raise SystemExit('One or more gate instructions changed; re-audit semantics')


if __name__ == '__main__':
    main()
