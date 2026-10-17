#!/usr/bin/env python3
"""Verify clean-install and update assets in the same release without deploying."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
__import__("os").environ.setdefault("GALAXY_COMPANION_DEVICE", "gts9uwifi")
sys.path.insert(0, str(REPO / 'external/galaxy-companion/packaging/galaxy-companion/usr/lib/galaxy-companion'))
from galaxy_companion import update_bundle as bundle


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--migration-result', type=Path)
    parser.add_argument('--export-dir', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--export-updater-deb', type=Path)
    args = parser.parse_args()
    helpers = load('candidate_helpers', REPO / 'scripts/build-migration-candidate.py')
    environment = {**os.environ, 'UBUNTU_WORKDIR': str(args.base), 'BUNDLE_OUT_DIR': str(args.bundle)}
    subprocess.run(['bash', str(REPO / 'scripts/validate-bundle.sh'), str(args.zip)], env=environment, check=True)
    load('update_validator', REPO / 'scripts/validate-update-zip.py').validate(args.zip)
    subprocess.run([sys.executable, str(args.backend), '--probe', str(args.zip)], check=True)
    kernel = helpers.verify_kernel(args.base)
    modules = helpers.verify_packaged_modules(args.base, args.zip, kernel, args.payload)
    manifest = bundle.inspect(args.zip)
    with zipfile.ZipFile(args.zip) as archive:
        required = {'rootfs.img', 'ROOTFS-IMAGE', 'META-INF/com/google/android/update-binary',
                    'META-INF/com/google/android/updater-script', 'UPDATE/manifest.json', 'UPDATE/updater.pyz'}
        if not required.issubset(archive.namelist()):
            raise ValueError('The combined release is missing one of its installation paths')
        checksum, size, mib, name = archive.read('ROOTFS-IMAGE').decode().split()
        if name != 'rootfs.img' or int(size) != int(mib) * 1024**2 or archive.getinfo(name).file_size != int(size):
            raise ValueError('The clean root image size/manifest is inconsistent')
        digest = hashlib.sha256()
        with archive.open(name) as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b''):
                digest.update(block)
        if digest.hexdigest() != checksum:
            raise ValueError('The clean root image checksum is inconsistent')
        root_image = {'bytes': int(size), 'sha256': checksum}
    if helpers.output(['chroot', args.rootfs, 'dpkg', '--audit']):
        raise ValueError('The clean root package database is inconsistent')
    subprocess.run(['chroot', str(args.rootfs), 'apt-get', 'check'], check=True)
    migration = json.loads(args.migration_result.read_text()) if args.migration_result else None
    if migration and (not migration.get('passed') or migration.get('target_suite') != 'resolute'
            or migration.get('zip_sha256') != bundle.sha256(args.zip)):
        raise ValueError('The full migration result must pass for this exact combined ZIP')
    report = {'candidate': args.zip.name, 'sha256': bundle.sha256(args.zip), 'bytes': args.zip.stat().st_size,
        'suite': manifest['suite'], 'version': manifest['version'], 'kernel': kernel,
        'packaged_modules_verified': modules, 'rootfs_image': root_image,
        'clean_install_assets_verified': True, 'update_assets_verified': True,
        'full_migration_test': migration, 'physical_validation': False,
        'local_zip_minimum_companion_version': manifest.get('minimum_local_updater_version'),
        'github_download_authentication_preserved': True,
        'pending': ['physical clean install and migration boot/recovery acceptance']}
    destination = args.report or args.zip.with_suffix('.validation.json')
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing combined validation report')
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if args.export_dir:
        helpers.export_candidate(args.zip, args.export_dir)
        if args.export_updater_deb:
            file = args.export_updater_deb
            entry = manifest['files'].get('UPDATE/debs/' + file.name)
            destination = args.export_dir / file.name
            if not entry or entry['sha256'] != bundle.sha256(file) or destination.exists():
                raise ValueError('The prerequisite updater package must match the ZIP and have a new export path')
            shutil.copyfile(file, destination)
            if bundle.sha256(destination) != entry['sha256']:
                raise ValueError('Prerequisite updater transfer checksum mismatch')
            print('Verified prerequisite updater exported:', destination)


if __name__ == '__main__':
    main()
