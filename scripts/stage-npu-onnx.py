#!/usr/bin/env python3
"""Build an isolated ONNX/QNN runtime bundle from pinned official artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ndk', type=Path, required=True)
    parser.add_argument('--downloads', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    cache, output = args.downloads.resolve(), args.output.resolve()
    if output.exists():
        parser.error('output must be a new directory')
    cc = args.ndk.resolve() / 'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android30-clang'
    readelf = cc.with_name('llvm-readelf')
    if not cc.is_file() or not shutil.which('patchelf'):
        parser.error('NDK r26d and patchelf are required')
    artifacts = json.loads((repo / 'configs/npu/onnx-artifacts.json').read_text())
    cache.mkdir(parents=True, exist_ok=True)
    for name, artifact in artifacts.items():
        target = cache / name
        if not target.exists():
            temporary = cache / (name + '.download')
            urllib.request.urlretrieve(artifact['url'], temporary)
            if digest(temporary) != artifact['sha256']:
                raise ValueError('Downloaded artifact hash mismatch: ' + name)
            temporary.rename(target)
        if digest(target) != artifact['sha256']:
            raise ValueError('Cached artifact hash mismatch: ' + name)
    for directory in ('bin', 'lib', 'dsp', 'models', 'licenses', 'integration'):
        (output / directory).mkdir(parents=True, exist_ok=True)
    extract = {
        'ort.aar': {'libonnxruntime.so': 'lib'},
        'qnn-ep.aar': {'libonnxruntime_providers_qnn.so': 'lib'},
        'qnn.aar': {'libQnnHtp.so': 'lib', 'libQnnHtpPrepare.so': 'lib',
                    'libQnnHtpV73Stub.so': 'lib', 'libQnnSystem.so': 'lib',
                    'libQnnHtpV73Skel.so': 'dsp'},
    }
    for archive, libraries in extract.items():
        with zipfile.ZipFile(cache / archive) as z:
            for name, destination in libraries.items():
                (output / destination / name).write_bytes(z.read('jni/arm64-v8a/' + name))
            for name in z.namelist():
                if not name.endswith('/') and re.search(r'license|notice', Path(name).name, re.I):
                    (output / 'licenses' / (archive + '-' + Path(name).name)).write_bytes(z.read(name))
    # The Android ORT binary links libandroid even though it imports no API from
    # it. QNN needs none of its NNAPI-specific dynamic interfaces. Verify that
    # condition before removing this unused load-time dependency for Ubuntu.
    library = output / 'lib/libonnxruntime.so'
    symbols = subprocess.check_output([str(readelf), '--dyn-syms', '--wide', str(library)], text=True)
    if re.search(r'UND.*(?:\bA[A-Z]\w+|@LIBANDROID)', symbols):
        raise ValueError('ORT now imports Android native APIs; reassess compatibility')
    subprocess.run(['patchelf', '--remove-needed', 'libandroid.so', str(library)], check=True)
    common = [str(cc), '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(cache)]
    subprocess.run(common + [str(repo / 'scripts/npu-onnx-run.c'), '-ldl', '-lm',
                            '-o', str(output / 'bin/onnx-run')], check=True)
    subprocess.run(common + ['-shared', '-fPIC', str(repo / 'scripts/npu-ort-discovery.c'), '-ldl',
                            '-o', str(output / 'lib/libgts9u_ort_qnn.so')], check=True)
    shutil.copy2(repo / 'scripts/gts9u-ai.py', output / 'bin/gts9u-ai')
    for name in ('gts9u-ai', 'onnx-run'):
        (output / 'bin' / name).chmod(0o755)
    for name in ('mobilenetv2-12.onnx', 'imagenet_classes.txt'):
        shutil.copy2(cache / name, output / 'models')
    for name in artifacts:
        if name.endswith('-LICENSE'):
            shutil.copy2(cache / name, output / 'licenses')
    for name in ('49-gts9u-npu.rules', 'gts9u-npu-tmpfiles.conf'):
        shutil.copy2(repo / 'configs/npu' / name, output / 'integration')
    manifest = {'artifacts': artifacts, 'backend': 'HTP', 'onnxruntime': '1.26.0',
                'qnn_ep': '2.5.0', 'qnn_maven': '2.49.0',
                'compatibility': 'Unused libandroid dependency removed; verified Linux FastRPC discovery adapter',
                'files': {str(f.relative_to(output)): digest(f)
                          for f in sorted(output.rglob('*')) if f.is_file()}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Staged ONNX runtime:', output)


if __name__ == '__main__':
    main()
