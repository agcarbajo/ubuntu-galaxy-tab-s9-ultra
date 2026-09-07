#!/usr/bin/env python3
"""Build an isolated experimental ARM64 HTP bundle from pinned public packages."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, required=True,
                        help='New staging root; creates opt/gts9u-npu below it')
    parser.add_argument('--firmware', type=pathlib.Path, required=True,
                        help='Staging root produced by stage-npu-firmware.py')
    parser.add_argument('--cache', type=pathlib.Path, required=True)
    parser.add_argument('--cc', default='aarch64-linux-gnu-gcc')
    args = parser.parse_args()
    repo = pathlib.Path(__file__).resolve().parent.parent
    manifest = json.loads((repo / 'configs/npu/runtime-packages.json').read_text())
    if args.output.exists():
        parser.error('--output must not exist')
    stock = args.firmware / 'usr/share/qcom/sm8550/Samsung/gts9uwifi/cdsp'
    if not (stock / 'fastrpc_shell_unsigned_3').is_file():
        parser.error('--firmware is missing the verified CDSP shell')
    for line in (repo / 'configs/npu/stock-cdsp.sha256').read_text().splitlines():
        checksum, name = line.split(None, 1)
        if name.startswith('dsp/cdsp/'):
            source = stock / name.removeprefix('dsp/cdsp/')
            if hashlib.sha256(source.read_bytes()).hexdigest() != checksum:
                raise ValueError(f'Stock DSP checksum mismatch: {source}')
    args.cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gts9u-npu-runtime-') as tmp:
        root = pathlib.Path(tmp)
        extracted = root / 'packages'
        for package in manifest['packages']:
            archive = args.cache / pathlib.Path(package['Filename']).name
            if not archive.exists():
                partial = archive.with_suffix('.partial')
                urllib.request.urlretrieve(manifest['base_url'] + package['Filename'], partial)
                partial.rename(archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != package['SHA256']:
                raise ValueError(f'Package SHA256 mismatch: {archive}')
            subprocess.run(['dpkg-deb', '-x', str(archive), str(extracted)], check=True)
        bundle = root / 'staged/opt/gts9u-npu'
        for directory in ('lib', 'bin', 'dsp'):
            (bundle / directory).mkdir(parents=True)
        for name in ('libQnnHtp.so', 'libQnnHtpPrepare.so', 'libQnnHtpV73Stub.so',
                     'libQnnHtpV73CalculatorStub.so', 'libQnnSystem.so'):
            shutil.copy2(extracted / 'usr/lib' / name, bundle / 'lib')
        for source in (extracted / 'usr/lib/aarch64-linux-gnu').glob('*.so*'):
            shutil.copy2(source, bundle / 'lib' / source.name, follow_symlinks=False)
        (bundle / 'lib/libcdsprpc.so').symlink_to('libcdsprpc.so.1')
        shutil.copy2(extracted / 'usr/bin/qnn-platform-validator', bundle / 'bin')
        dsp = extracted / 'usr/share/qcom/sa8775p/Qualcomm/SA8775P-RIDE/dsp/cdsp'
        for name in ('libQnnHtpV73Skel.so', 'libQnnHtpV73.so'):
            shutil.copy2(dsp / name, bundle / 'dsp')
        shutil.copytree(stock, bundle / 'dsp', dirs_exist_ok=True)
        subprocess.run([args.cc, '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(extracted / 'usr/include/QNN'),
                        str(repo / 'scripts/probe-npu-htp.c'), '-ldl', '-lm',
                        '-o', str(bundle / 'bin/probe-npu-htp')], check=True)
        runner = bundle / 'bin/test-htp'
        runner.write_text('#!/bin/sh\nset -eu\n'
                          'base=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
                          'export LD_LIBRARY_PATH="$base/lib"\n'
                          'export ADSP_LIBRARY_PATH="$base/dsp"\n'
                          'export DSP_LIBRARY_PATH="$base/dsp"\n'
                          'exec timeout -k 5 120 "$base/bin/probe-npu-htp" "$@"\n')
        runner.chmod(0o755)
        shutil.copy2(repo / 'configs/npu/runtime-packages.json', bundle)
        shutil.copytree(root / 'staged', args.output, symlinks=True)
    print(f'Experimental HTP bundle: {args.output / "opt/gts9u-npu"}')
    print('Diagnostic bundle only: this QAIRT build rejects SM8550 (SoC model 43).')
    print('No services installed; hardware inference must pass before enabling at boot.')


if __name__ == '__main__':
    main()
