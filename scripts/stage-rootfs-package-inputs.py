#!/usr/bin/env python3
"""Stage an explicit, hash-locked local package selection for a fresh rootfs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[1]


def fields(file):
    text = subprocess.check_output(['dpkg-deb', '-f', str(file), 'Package', 'Version', 'Architecture'], text=True)
    return dict(line.split(': ', 1) for line in text.splitlines())


def digest(file):
    result = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            result.update(block)
    return result.hexdigest()


def stage(source, manifest, destination, suite, include_npu):
    inventory = json.loads(manifest.read_text())
    if inventory.get('suite') != suite or not isinstance(inventory.get('files'), dict):
        raise ValueError('Local package lock does not match the rootfs suite')
    selected = {}
    for name, checksum in inventory['files'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.+~:%-]+\.deb', name):
            raise ValueError('Unsafe local package input name')
        file = source / name
        if file.is_symlink() or digest(file) != checksum:
            raise ValueError('Local package input checksum mismatch')
        metadata = fields(file)
        if metadata['Architecture'] not in ('arm64', 'all') or metadata['Package'] in selected:
            raise ValueError('Foreign architecture or duplicate local package input')
        selected[metadata['Package']] = (file, metadata['Version'])
    camera = 'libcamera0.7' if suite == 'resolute' else 'libcamera-gts9u'
    required = {'libssc', 'hexagonrpcd', 'iio-sensor-proxy', 'libfprint-2-2', camera,
        'libspa-0.2-libcamera-gts9u', 'ubuntu-gts9u-device', 'ubuntu-gts9u-companion',
        'fastfetch', 'v4l2-relayd-gts9u', 'fprintd', 'libpam-fprintd',
        'ubuntu-gts9u-fingerprint-firmware',
        'gnome-settings-daemon', 'gnome-settings-daemon-common'}
    if suite == 'resolute':
        required.add('libfprint-2-tod1')
    if include_npu:
        required.add('ubuntu-gts9u-npu')
    if not required.issubset(selected):
        raise ValueError('Missing local package inputs: ' + ', '.join(sorted(required - selected.keys())))
    control = REPO / 'packaging/ubuntu-gts9u-device/DEBIAN' / ('control-resolute' if suite == 'resolute' else 'control')
    expected = {'ubuntu-gts9u-device': re.search(r'^Version: (.+)$', control.read_text(), re.M)[1],
        'ubuntu-gts9u-companion': re.search(r'^Version: (.+)$',
            (REPO / 'packaging/ubuntu-gts9u-companion/DEBIAN/control').read_text(), re.M)[1],
        'fprintd': (REPO / 'packaging/fprintd' / ('version-resolute' if suite == 'resolute' else 'version')).read_text().strip()}
    expected['libpam-fprintd'] = expected['fprintd']
    expected['gnome-settings-daemon'] = ('50.0-1ubuntu1+gts9u1' if suite == 'resolute'
                                         else '46.0-1ubuntu1.24.04.1+gts9u1')
    expected['gnome-settings-daemon-common'] = expected['gnome-settings-daemon']
    for name, version in expected.items():
        if selected[name][1] != version:
            raise ValueError('Local package version does not match the source recipe: ' + name)
    spec = importlib.util.spec_from_file_location('update_payload_builder', REPO / 'scripts/build-update-payload.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.validate_package_ownership(file for file, _ in selected.values())
    if destination.exists():
        raise ValueError('Choose a new local package staging directory')
    destination.mkdir(parents=True)
    for name, (file, version) in sorted(selected.items()):
        shutil.copyfile(file, destination / file.name)
        print('Locked local package:', name, version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--suite', choices=('noble', 'resolute'), required=True)
    parser.add_argument('--without-npu', action='store_true')
    parser.add_argument('--write-lock', action='store_true')
    parser.add_argument('--overrides', type=Path)
    args = parser.parse_args()
    if args.write_lock:
        if args.manifest.exists():
            parser.error('Refusing to overwrite an existing package lock')
        source = args.source
        if args.overrides:
            if not args.destination or args.destination.exists():
                parser.error('Package overrides require a new selection directory')
            selected = {}
            for file in source.glob('*.deb'):
                name = fields(file)['Package']
                if name in selected:
                    raise ValueError('The original package selection contains duplicate names')
                selected[name] = file
            for file in args.overrides.glob('*.deb'):
                metadata = fields(file)
                previous = selected.get(metadata['Package'])
                if previous and subprocess.run(['dpkg', '--compare-versions', metadata['Version'],
                        'gt', fields(previous)['Version']]).returncode:
                    raise ValueError('An override must have a newer Debian version')
                selected[metadata['Package']] = file
            args.destination.mkdir(parents=True)
            for file in selected.values():
                shutil.copyfile(file, args.destination / file.name)
            source = args.destination
        args.manifest.write_text(json.dumps({'suite': args.suite,
            'files': {file.name: digest(file) for file in sorted(source.glob('*.deb'))}}, indent=2) + '\n')
    else:
        if not args.destination:
            parser.error('--destination is required when staging inputs')
        stage(args.source, args.manifest, args.destination, args.suite, not args.without_npu)


if __name__ == '__main__':
    main()
