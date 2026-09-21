import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zlib


SOURCES = {
    'sm5714_battery.c': 'drivers/power/supply/sm5714_battery.c',
    'sm5440_direct.c': 'drivers/power/supply/sm5440_direct.c',
    'panel-samsung-ana38407.c': 'drivers/gpu/drm/panel/panel-samsung-ana38407.c',
}


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
    parser.add_argument('--baseline-sha256', required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    source = args.base / 'build/linux-src-release-1.2.0'
    objects = args.base / 'build/linux-release-1.2.0'
    baseline = args.base / 'out/bundle/boot.img'
    require(digest(baseline) == args.baseline_sha256, 'Baseline does not match the tablet')
    boot = baseline.read_bytes()
    require(boot[:8] == b'ANDROID!' and len(boot) == 100663296, 'Wrong baseline container')
    decoder = zlib.decompressobj(31)
    raw = decoder.decompress(boot[4096:]) + decoder.flush()
    require(decoder.eof, 'Invalid baseline kernel stream')
    require(raw == (objects / 'arch/arm64/boot/Image').read_bytes(), 'Object tree is not the installed kernel')
    config = objects / '.config'
    certificate = objects / 'certs/signing_key.x509'
    release = (objects / 'include/config/kernel.release').read_text().strip()
    require(release == '7.2.0-rc3-dirty', 'Unexpected baseline release')
    compiler = '/usr/lib/llvm-22/bin/clang'
    expected_cc = next(line.split('=', 1)[1].strip('"') for line in config.read_text().splitlines()
                       if line.startswith('CONFIG_CC_VERSION_TEXT='))
    actual_cc = subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]
    require(actual_cc == expected_cc, 'Compiler differs from the installed kernel build')
    for name, target in SOURCES.items():
        original = subprocess.check_output(['git', '-C', str(repo), 'show', f'HEAD:kernel/drivers/{name}'])
        require((source / target).read_bytes() == original, f'Unreviewed changes in {target}')
    args.output.mkdir(parents=True, exist_ok=False)
    backup = args.output / 'baseline'
    backup.mkdir(mode=0o700)
    for name, target in SOURCES.items():
        shutil.copy2(source / target, backup / name)
    shutil.copy2(baseline, backup / 'boot.img')
    for name in ('.config', 'vmlinux.symvers', 'Module.symvers', 'include/config/kernel.release', 'certs/signing_key.x509'):
        shutil.copy2(objects / name, backup / Path(name).name)
    old_symbols = symbols(backup / 'vmlinux.symvers')
    expected_config, expected_certificate = digest(config), digest(certificate)
    for name, target in SOURCES.items():
        shutil.copy2(repo / 'kernel/drivers' / name, source / target)
    epoch = subprocess.check_output(['git', '-C', str(source), 'log', '-1', '--format=%ct'], text=True).strip()
    timestamp = subprocess.check_output(['date', '-u', '-d', '@' + epoch], text=True).strip()
    env = dict(os.environ, PATH='/usr/lib/llvm-22/bin:' + os.environ['PATH'],
               KBUILD_BUILD_USER='ubuntu', KBUILD_BUILD_HOST='gts9uwifi',
               KBUILD_BUILD_VERSION='2', SOURCE_DATE_EPOCH=epoch, KBUILD_BUILD_TIMESTAMP=timestamp)
    subprocess.run(['make', '-C', str(source), 'O=' + str(objects), 'ARCH=arm64', 'LLVM=1',
                    f'-j{min(os.cpu_count() or 1, 16)}', 'Image.gz'], env=env, cwd=args.base, check=True)
    require(digest(config) == expected_config, 'Kernel configuration changed')
    require(digest(certificate) == expected_certificate, 'Module trust certificate changed')
    require((objects / 'include/config/kernel.release').read_text().strip() == release, 'Module release changed')
    new_symbols = symbols(objects / 'vmlinux.symvers')
    changed = [name for name, crc in old_symbols.items() if new_symbols.get(name) != crc]
    require(not changed, 'Existing exported ABI changed: ' + ', '.join(changed[:20]))
    image = args.output / 'Image'
    shutil.copy2(objects / 'arch/arm64/boot/Image', image)
    require(gzip.decompress((objects / 'arch/arm64/boot/Image.gz').read_bytes()) == image.read_bytes(),
            'Compressed kernel differs')
    metadata = {'baseline_boot': args.baseline_sha256, 'image': digest(image), 'kernel_release': release,
                'config': expected_config, 'certificate': expected_certificate,
                'unchanged_exported_symbols': len(old_symbols),
                'new_symbols': sorted(new_symbols.keys() - old_symbols.keys()),
                'sources': {name: digest(repo / 'kernel/drivers' / name) for name in SOURCES}}
    (args.output / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
