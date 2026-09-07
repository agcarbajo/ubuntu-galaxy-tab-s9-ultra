#!/usr/bin/env python3
"""Build an isolated Android-ABI HTP diagnostic runtime for Ubuntu/SM8550.

Requires the owner's extracted Bionic libraries and CDSP files. Does not install
anything on the host or tablet. Real HTP execution passes with the experimental
CDSP session and power owner. See docs/npu-status.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

RPC_COMMIT = '9d409211527f5c853351a8c014c2bcb271bc6f2d'
AAR_SHA256 = '4cc58d8b303bf157e8706aa53912c2ef548175b76ece5a5b38a7e1b45974cea4'
QNN_LIBS = ('libQnnHtp.so', 'libQnnHtpPrepare.so', 'libQnnHtpV73Stub.so',
            'libQnnSystem.so', 'libQnnHtpV73Skel.so')
BIONIC_LIBS = ('libc.so', 'libdl.so', 'libm.so', 'libdl_android.so',
               'liblog.so', 'libc++.so', 'libdmabufheap.so')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('ndk', 'fastrpc-source', 'qnn-headers', 'aar', 'bionic', 'dsp', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    for name, value in vars(a).items():
        setattr(a, name, value.resolve())
    if a.output.exists():
        p.error('output must be a new directory')
    if digest(a.aar) != AAR_SHA256:
        p.error('expected the pinned Qualcomm qnn-runtime 2.45.0 AAR')
    revision = subprocess.check_output(
        ['git', '-C', str(a.fastrpc_source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != RPC_COMMIT:
        p.error('FastRPC source HEAD must be ' + RPC_COMMIT)
    ndkbin = a.ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    cc = ndkbin / 'aarch64-linux-android30-clang'
    for path in [cc, a.qnn_headers / 'QnnInterface.h', a.bionic / 'linker64'] + [
            a.bionic / name for name in BIONIC_LIBS]:
        if not path.is_file():
            p.error('missing input: ' + str(path))
    if not (a.dsp / 'fastrpc_shell_unsigned_3').is_file():
        p.error('DSP directory must include the stock fastrpc_shell_unsigned_3')

    root = a.output / 'opt/gts9u-npu-bionic'
    for name in ('lib', 'bin', 'dsp', 'licenses'):
        (root / name).mkdir(parents=True)
    build = a.output / 'build/fastrpc'
    subprocess.run(['git', 'clone', '--no-hardlinks', '--no-checkout',
                    str(a.fastrpc_source), str(build)], check=True)
    subprocess.run(['git', '-C', str(build), 'checkout', '--detach', RPC_COMMIT], check=True)
    shell_patch = Path(__file__).resolve().parents[1] / 'configs/npu/fastrpc-shell-search-path.patch'
    subprocess.run(['git', '-C', str(build), 'apply', '--check', str(shell_patch)], check=True)
    subprocess.run(['git', '-C', str(build), 'apply', str(shell_patch)], check=True)
    env = dict(os.environ, PATH=str(ndkbin) + os.pathsep + os.environ['PATH'])
    subprocess.run(['autoreconf', '-fi'], cwd=build, env=env, check=True)
    subprocess.run(['./configure', '--host=aarch64-linux-android',
                    'CC=aarch64-linux-android30-clang', 'CXX=aarch64-linux-android30-clang++',
                    'AR=llvm-ar', 'RANLIB=llvm-ranlib', 'STRIP=llvm-strip',
                    '--prefix=/opt/gts9u-npu-bionic'], cwd=build, env=env, check=True)
    subprocess.run(['make', '-C', 'src', '-j4', 'libcdsprpc.la'],
                   cwd=build, env=env, check=True)
    probe = Path(__file__).resolve().with_name('probe-npu-htp.c')
    subprocess.run([str(cc), '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(a.qnn_headers), str(probe), '-ldl', '-lm',
                    '-o', str(root / 'bin/probe-npu-htp')], check=True)
    shutil.copy2(build / 'src/.libs/libcdsprpc.so', root / 'lib')
    for name in BIONIC_LIBS:
        shutil.copy2(a.bionic / name, root / 'lib')
    shutil.copy2(a.bionic / 'linker64', root / 'bin')
    (root / 'bin/linker64').chmod(0o755)
    with zipfile.ZipFile(a.aar) as z:
        for name in QNN_LIBS:
            candidates = [n for n in z.namelist()
                          if n.startswith('jni/arm64-v8a/') and Path(n).name == name]
            if len(candidates) != 1:
                raise ValueError('missing or ambiguous ARM64 library: ' + name)
            destination = 'dsp' if name.endswith('Skel.so') else 'lib'
            (root / destination / name).write_bytes(z.read(candidates[0]))
        for name in z.namelist():
            if not name.endswith('/') and any(s in Path(name).name.lower()
                                               for s in ('license', 'notice')):
                (root / 'licenses' / Path(name).name).write_bytes(z.read(name))
    for path in a.dsp.iterdir():
        if path.is_file():
            if (root / 'dsp' / path.name).exists():
                raise ValueError('stock DSP file collides with QNN: ' + path.name)
            shutil.copy2(path, root / 'dsp')
    for name in ('LICENSE', 'LICENSE.txt', 'NOTICE'):
        if (build / name).is_file():
            shutil.copy2(build / name, root / 'licenses' / ('fastrpc-' + name))
    wrapper = root / 'bin/test-htp'
    wrapper.write_text('''#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec timeout -k 5 120 env LD_LIBRARY_PATH="$base/lib" \\
  ADSP_LIBRARY_PATH="$base/dsp" DSP_LIBRARY_PATH="$base/dsp" \\
  "$base/bin/linker64" "$base/bin/probe-npu-htp" "$@"
''')
    wrapper.chmod(0o755)
    manifest = {'status': 'experimental: HTP inference passed with prepared CDSP and power owner',
                'fastrpc_commit': RPC_COMMIT, 'aar_sha256': AAR_SHA256,
                'fastrpc_shell_search_patch_sha256': digest(shell_patch),
                'probe_sha256': digest(probe),
                'files': {str(f.relative_to(root)): digest(f)
                          for f in sorted(root.rglob('*')) if f.is_file()}}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Staged diagnostic runtime:', root)


if __name__ == '__main__':
    main()
