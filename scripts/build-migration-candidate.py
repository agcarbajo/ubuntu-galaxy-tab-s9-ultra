#!/usr/bin/env python3
"""Package an update-only Resolute candidate without publishing or deploying it."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
__import__("os").environ.setdefault("GALAXY_COMPANION_DEVICE", "gts9uwifi")
sys.path.insert(0, str(REPO / 'external/galaxy-companion/packaging/galaxy-companion/usr/lib/galaxy-companion'))
from galaxy_companion import update_bundle as bundle


def run(arguments, **kwargs):
    return subprocess.run([str(value) for value in arguments], check=True, **kwargs)


def output(arguments):
    return subprocess.check_output([str(value) for value in arguments], text=True).strip()


def verify_kernel(base):
    kernel = base / 'out/kernel-gts9uwifi'
    objects = base / 'build/linux-gts9uwifi'
    if (kernel / 'config').read_bytes() != (objects / '.config').read_bytes():
        raise ValueError('Staged kernel configuration differs from its object tree')
    release = (kernel / 'kernel.release').read_text().strip()
    serial = output(['openssl', 'x509', '-inform', 'DER', '-in',
        objects / 'certs/signing_key.x509', '-noout', '-serial']).split('=', 1)[1].upper()
    modules = [file for file in (kernel / 'modules-root').rglob('*')
        if file.is_file() and '.ko' in file.suffixes]
    if not modules:
        raise ValueError('The candidate has no matching kernel modules')
    for file in modules:
        if output(['modinfo', '-F', 'vermagic', file]).split()[0] != release:
            raise ValueError('Mismatched module release: ' + file.name)
        if output(['modinfo', '-F', 'sig_key', file]).replace(':', '').upper() != serial:
            raise ValueError('Mismatched module signing certificate: ' + file.name)
    dtb_hash = bundle.sha256(kernel / 'sm8550-samsung-gts9uwifi.dtb')
    if dtb_hash != '613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4':
        raise ValueError('The candidate changed the physically booted board DTB')
    return {'release': release, 'modules_verified': len(modules), 'certificate_serial': serial,
        'config_sha256': bundle.sha256(kernel / 'config'),
        'symbol_crcs_sha256': bundle.sha256(objects / 'Module.symvers'),
        'image_sha256': bundle.sha256(kernel / 'Image.gz'), 'dtb_sha256': dtb_hash}


def verify_packaged_modules(workspace, archive, kernel, payload=None):
    payload = payload or workspace / 'out/update-payload'
    manifest = bundle.inspect(archive)
    count = 0
    with tempfile.TemporaryDirectory() as temporary:
        for name, entry in manifest['files'].items():
            if not name.startswith('UPDATE/debs/'):
                continue
            deb = payload / 'debs' / Path(name).name
            if bundle.sha256(deb) != entry['sha256']:
                raise ValueError('Package differs from the candidate manifest')
            with tempfile.TemporaryFile() as stream:
                run(['dpkg-deb', '--fsys-tarfile', deb], stdout=stream)
                stream.seek(0)
                with tarfile.open(fileobj=stream, mode='r|') as contents:
                    for member in contents:
                        if not member.isfile() or '.ko' not in Path(member.name).suffixes:
                            continue
                        file = Path(temporary) / Path(member.name).name
                        with contents.extractfile(member) as source, file.open('wb') as target:
                            shutil.copyfileobj(source, target)
                        if output(['modinfo', '-F', 'vermagic', file]).split()[0] != kernel['release']:
                            raise ValueError('Packaged module has a different kernel release')
                        key = output(['modinfo', '-F', 'sig_key', file]).replace(':', '').upper()
                        if key != kernel['certificate_serial']:
                            raise ValueError('Packaged module has a different signing certificate')
                        count += 1
    if not count:
        raise ValueError('No signed kernel modules were packaged')
    print('Verified packaged module releases and certificates:', count)
    return count


def export_candidate(archive, directory):
    report_path = archive.with_suffix('.validation.json')
    report = json.loads(report_path.read_text())
    if report['sha256'] != bundle.sha256(archive) or report['bytes'] != archive.stat().st_size:
        raise ValueError('Candidate differs from its verified build report')
    if not directory.is_dir():
        raise ValueError('The artifact export directory must already exist')
    for source in (archive, report_path):
        destination = directory / source.name
        if destination.exists():
            raise ValueError('Refusing to overwrite an existing artifact: ' + destination.name)
    for source in (archive, report_path):
        destination = directory / source.name
        shutil.copyfile(source, destination)
        if bundle.sha256(source) != bundle.sha256(destination):
            raise ValueError('Artifact transfer checksum mismatch')
    print('Verified candidate exported to:', directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--version', default='1.4.0')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--export-dir', type=Path)
    parser.add_argument('--export-existing', action='store_true')
    parser.add_argument('--verify-existing', action='store_true')
    args = parser.parse_args()
    if args.verify_existing:
        report = json.loads(args.output.with_suffix('.validation.json').read_text())
        if report['sha256'] != bundle.sha256(args.output):
            raise ValueError('Candidate differs from its verified build report')
        run([sys.executable, REPO / 'scripts/validate-update-zip.py', args.output])
        verify_packaged_modules(args.workspace, args.output, report['kernel'])
        return
    if args.export_existing:
        if not args.export_dir:
            parser.error('--export-existing requires --export-dir')
        export_candidate(args.output, args.export_dir)
        return
    base = args.base.resolve(strict=True)
    root = args.rootfs.resolve(strict=True)
    if root == Path('/') or args.workspace.exists() or args.output.exists():
        parser.error('Use an isolated root and new workspace/output paths')
    if str(args.workspace).startswith('/mnt/') or ' ' in str(args.workspace):
        parser.error('Candidate builds require a Linux filesystem path without spaces')
    kernel = verify_kernel(base)
    environment = {**os.environ, 'UBUNTU_WORKDIR': str(base)}
    run(['bash', REPO / 'scripts/validate-bundle.sh'], env=environment)
    run([sys.executable, REPO / 'scripts/check-visible-boot-initramfs.py',
         base / 'out/migration-initramfs.lz4'])
    audit = output(['chroot', root, 'dpkg', '--audit'])
    if audit:
        raise ValueError('Candidate root has an inconsistent package database')
    run(['chroot', root, 'apt-get', 'check'])
    args.workspace.mkdir(parents=True)
    stage = args.workspace / 'out'
    stage.mkdir()
    for name in ('kernel-gts9uwifi', 'rootfs-overlay', 'local-debs'):
        (stage / name).symlink_to(base / 'out' / name, target_is_directory=True)
    backend = stage / 'migration-updater.pyz'
    run([sys.executable, REPO / 'scripts/build-migration-backend.py',
         '--root', root, '--output', backend])
    run([sys.executable, REPO / 'scripts/build-update-payload.py', '--base', args.workspace,
         '--rootfs', root, '--version', args.version, '--suite', 'resolute', '--update-format', '2',
         '--migration-backend', backend, '--bootstrap', stage / 'update-bootstrap.pyz'])
    run([sys.executable, REPO / 'scripts/make-twrp-zip.py', base / 'out/bundle', args.output,
         '--update-payload', stage / 'update-payload', '--update-only',
         '--label', 'EXPERIMENTAL Ubuntu 26.04 / GNOME 50 / ' + kernel['release'] +
         ' for SM-X910; migration validation only, not TWRP'])
    run([sys.executable, REPO / 'scripts/validate-update-zip.py', args.output])
    run([sys.executable, backend, '--probe', args.output])
    manifest = bundle.inspect(args.output)
    packaged_modules = verify_packaged_modules(args.workspace, args.output, kernel)
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Candidate ZIP CRC failure')
        names = archive.namelist()
        if any(name.startswith(('META-INF/', 'rootfs-overlay/')) for name in names) or any(
                name in names for name in ('rootfs.img', 'vbmeta.img')):
            raise ValueError('An update-only candidate must not contain installation assets')
    report = {'candidate': args.output.name, 'sha256': bundle.sha256(args.output),
        'bytes': args.output.stat().st_size, 'kernel': kernel, 'payload_files': len(manifest['files']),
        'packaged_modules_verified': packaged_modules,
        'suite': manifest['suite'], 'version': manifest['version'],
        'checks': ['kernel-config', 'module-release-and-certificate', 'board-dtb',
            'android-v4-bundle', 'initramfs-elf-closure-and-size', 'root-dpkg-and-apt',
            'exact-installed-local-package-versions', 'package-file-ownership',
            'payload-sha256', 'zip-crc', 'backend-probe', 'no-destructive-installer'],
        'installation_approved': False, 'physical_validation': False,
        'pending': ['successful full Noble-to-Resolute package transaction',
            'real recovery acceptance', 'official stable ZIP authentication',
            'GNOME 50 and Linux 7.2.9 hardware acceptance']}
    report_path = args.output.with_suffix('.validation.json')
    if report_path.exists():
        raise ValueError('Refusing to overwrite an existing validation report')
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if args.export_dir:
        export_candidate(args.output, args.export_dir)


if __name__ == '__main__':
    main()
