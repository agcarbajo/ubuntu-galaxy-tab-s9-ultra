#!/usr/bin/env python3
"""Stage owner-supplied X910XXS5CYG1 firmware; no device or partitions are written."""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


def validate_mdt(directory, name, start, size):
    data = (directory / (name + '.mdt')).read_bytes()
    if data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError(f'{name}: expected ELF32 little-endian MDT')
    phoff = struct.unpack_from('<I', data, 28)[0]
    entsize, count = struct.unpack_from('<HH', data, 42)
    if entsize != 32 or phoff + count * entsize > len(data):
        raise ValueError(f'{name}: invalid program header table')
    for i in range(count):
        kind, _, _, addr, filesz, memsz, flags, _ = struct.unpack_from('<8I', data, phoff + i*32)
        # Qualcomm hash segments are authenticated by PAS, not loaded to DDR.
        if kind != 1 or (flags >> 24) & 7 == 2:
            continue
        if memsz and not (start <= addr and addr + memsz <= start + size):
            raise ValueError(f'{name}: segment {i} exceeds the reserved memory')
        if filesz:
            part = directory / f'{name}.b{i:02d}'
            if part.stat().st_size != filesz:
                raise ValueError(f'{name}: wrong size for {part.name}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--non-hlos', type=Path, required=True, help='Decompressed BL NON-HLOS.bin')
    p.add_argument('--dspso', type=Path, required=True, help='Decompressed BL dspso.bin')
    p.add_argument('--output', type=Path, required=True, help='New output rootfs directory')
    a = p.parse_args()
    if a.output.exists():
        p.error('output must not already exist')
    manifest = Path(__file__).resolve().parents[1] / 'configs/npu/stock-cdsp.sha256'
    with tempfile.TemporaryDirectory(prefix='gts9u-cdsp-') as temporary:
        stage = Path(temporary)
        (stage/'cdsp').mkdir()
        (stage/'dsp').mkdir()
        subprocess.run(['mcopy', '-i', str(a.non_hlos.resolve()), '::/image/cdsp*', str(stage/'cdsp')], check=True)
        subprocess.run(['debugfs', '-R', f'rdump /cdsp {stage}/dsp', str(a.dspso.resolve())], check=True)
        expected = {}
        for line in manifest.read_text().splitlines():
            checksum, name = line.split(None, 1)
            expected[name.strip()] = checksum
        actual = {str(f.relative_to(stage)) for f in stage.rglob('*') if f.is_file()}
        if actual != expected.keys():
            raise ValueError(f'Unexpected firmware file set: {actual ^ expected.keys()}')
        for name, checksum in expected.items():
            if hashlib.sha256((stage/name).read_bytes()).hexdigest() != checksum:
                raise ValueError(f'Firmware checksum mismatch: {name}')
        validate_mdt(stage/'cdsp', 'cdsp', 0x9c900000, 0x2000000)
        validate_mdt(stage/'cdsp', 'cdsp_dtb', 0x9e900000, 0x80000)
        # Validate fully before creating the output tree.
        shutil.copytree(stage/'cdsp', a.output/'usr/lib/firmware/qcom/sm8550')
        shutil.copytree(stage/'dsp/cdsp', a.output/'usr/share/qcom/sm8550/Samsung/gts9uwifi/cdsp')
        print(f'Verified and staged {len(expected)} files in {a.output}')


if __name__ == '__main__':
    main()
