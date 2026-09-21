import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def symbols(path):
    return {fields[1]: fields[0] for line in path.read_text().splitlines()
            if len(fields := line.split()) >= 2}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    source = args.base / 'build/linux-src-release-1.2.0'
    objects = args.base / 'build/linux-release-1.2.0'
    baseline = args.output / 'baseline'
    crtc = source / 'drivers/gpu/drm/msm/disp/dpu1/dpu_crtc.c'
    atomic = source / 'drivers/gpu/drm/msm/msm_atomic.c'
    config = objects / '.config'
    certificate = objects / 'certs/signing_key.x509'
    release = (objects / 'include/config/kernel.release').read_text().strip()
    require(release == '7.2.0-rc3-dirty', 'Unexpected kernel release')
    for current, saved in ((crtc, baseline / 'dpu_crtc.c'),
                           (atomic, baseline / 'msm_atomic.c'),
                           (objects / 'arch/arm64/boot/Image', baseline / 'Image'),
                           (config, baseline / '.config'),
                           (certificate, baseline / 'signing_key.x509')):
        require(digest(current) == digest(saved), f'Baseline changed: {current}')
    old_symbols = symbols(baseline / 'vmlinux.symvers')
    patch = repo / 'kernel/patches/msm-dpu-reassign-resources-with-encoder.patch'
    require('dpu_crtc_needs_dspp' not in crtc.read_text(), 'Display patch is already staged')
    subprocess.run(['patch', '--batch', '--fuzz=0', '-d', str(source), '-p1'],
                   input=patch.read_text(), text=True, check=True)
    epoch = subprocess.check_output(['git', '-C', str(source), 'log', '-1', '--format=%ct'], text=True).strip()
    timestamp = subprocess.check_output(['date', '-u', '-d', '@' + epoch], text=True).strip()
    env = dict(os.environ, PATH='/usr/lib/llvm-22/bin:' + os.environ['PATH'],
               KBUILD_BUILD_USER='ubuntu', KBUILD_BUILD_HOST='gts9uwifi',
               KBUILD_BUILD_VERSION='2', SOURCE_DATE_EPOCH=epoch,
               KBUILD_BUILD_TIMESTAMP=timestamp)
    subprocess.run(['make', '-C', str(source), 'O=' + str(objects), 'ARCH=arm64', 'LLVM=1',
                    f'-j{min(os.cpu_count() or 1, 16)}', 'Image.gz'], env=env,
                   cwd=args.base, check=True)
    require(digest(config) == digest(baseline / '.config'), 'Kernel configuration changed')
    require(digest(certificate) == digest(baseline / 'signing_key.x509'),
            'Module trust certificate changed')
    require((objects / 'include/config/kernel.release').read_text().strip() == release,
            'Kernel release changed')
    new_symbols = symbols(objects / 'vmlinux.symvers')
    changed = [name for name, crc in old_symbols.items() if new_symbols.get(name) != crc]
    require(not changed, 'Existing exported ABI changed: ' + ', '.join(changed[:20]))
    image = args.output / 'Image'
    require(not image.exists(), 'Refusing to overwrite candidate Image')
    shutil.copy2(objects / 'arch/arm64/boot/Image', image)
    require(gzip.decompress((objects / 'arch/arm64/boot/Image.gz').read_bytes()) == image.read_bytes(),
            'Compressed kernel differs')
    metadata = {'image': digest(image), 'kernel_release': release,
                'config': digest(config), 'certificate': digest(certificate),
                'unchanged_exported_symbols': len(old_symbols),
                'new_symbols': sorted(new_symbols.keys() - old_symbols.keys()),
                'patch': digest(patch), 'sources': {'dpu_crtc.c': digest(crtc),
                                                    'msm_atomic.c': digest(atomic)}}
    (args.output / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
