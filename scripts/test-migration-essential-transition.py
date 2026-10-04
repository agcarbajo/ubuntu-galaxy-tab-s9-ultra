#!/usr/bin/env python3
"""Exercise coreutils/sudo ordering only in a new disposable Noble root."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'packaging/ubuntu-gts9u-companion/usr/lib/tab-companion'))
from tab_companion import migration_core as migration, migration_plan as plans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--resolver-transaction', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inside', action='store_true')
    args = parser.parse_args()
    source = args.source_root.resolve(strict=True)
    reference = args.resolver_transaction.resolve(strict=True)
    destination = args.output.absolute()
    if source == Path('/') or destination.exists() or str(destination).startswith('/mnt/'):
        parser.error('Use a disposable fixture and a new Linux output path')
    if not args.inside:
        subprocess.run(['unshare', '--mount', '--propagation', 'private', sys.executable,
            str(Path(__file__).resolve()), *sys.argv[1:], '--inside'], check=True)
        return
    destination.mkdir(parents=True)
    root = destination / 'root'
    root.mkdir()
    subprocess.run(['rsync', '-aHAXS', '--numeric-ids', '--one-file-system',
                    str(source) + '/', str(root) + '/'], check=True)
    transaction = destination / 'transaction'
    transaction.mkdir()
    for name in ('resolver', 'lists', 'preferences.d'):
        (transaction / name).symlink_to(reference / name, target_is_directory=True)
    for name in ('ubuntu.sources', 'migration.sources'):
        shutil.copyfile(reference / name, transaction / name)
    for name in ('archives/partial', 'log'):
        (transaction / name).mkdir(parents=True)
    configuration = (reference / 'apt.conf').read_text().replace(str(reference), str(transaction))
    configuration = configuration.replace(str(transaction / 'source-status'), str(root / 'var/lib/dpkg/status'))
    (transaction / 'apt.conf').write_text(configuration)
    policy = root / 'usr/sbin/policy-rc.d'
    policy.write_text('#!/bin/sh\nexit 101\n')
    policy.chmod(0o755)
    runtime = migration.AptRuntime(transaction)
    environment = {**os.environ, 'APT_CONFIG': str(runtime.config), 'LC_ALL': 'C',
                   'DEBIAN_FRONTEND': 'noninteractive', 'SYSTEMD_OFFLINE': '1'}
    options = ['-o', 'APT::Solver=internal', '--no-remove', '-y']
    with (destination / 'download.log').open('w') as log:
        subprocess.run(runtime.command([*options, '--download-only', 'install', 'coreutils', 'sudo']),
            env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    mounts = []
    try:
        for source_mount, target in [(Path('/' + name), root / name) for name in ('dev', 'proc', 'sys')] + [
                (reference, root / reference.relative_to('/')),
                (transaction, root / transaction.relative_to('/'))]:
            target.mkdir(parents=True, exist_ok=True)
            subprocess.run(['mount', '--bind', str(source_mount), str(target)], check=True)
            mounts.append(target)
        with (destination / 'install.log').open('w') as log:
            subprocess.run(['chroot', str(root), 'env', 'APT_CONFIG=' + str(runtime.config),
                'DEBIAN_FRONTEND=noninteractive', 'SYSTEMD_OFFLINE=1',
                *runtime.command([*options, '--no-download', '-o', 'Dir::State::status=/var/lib/dpkg/status',
                    '-o', 'Dpkg::Options::=--force-confold', 'install', 'coreutils', 'sudo'])],
                stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(runtime.command(['-o', 'APT::Solver=internal', 'check']), env=environment, check=True)
        audit = subprocess.check_output(['chroot', str(root), 'dpkg', '--audit'], text=True)
        if audit:
            raise ValueError('The essential transition left an inconsistent package database')
        plans.check_preservation(source, root)
        result = subprocess.check_output(['chroot', str(root), 'dpkg-query', '-W',
            'coreutils', 'coreutils-from-uutils', 'sudo', 'sudo-common'], text=True)
        (destination / 'result.json').write_text(json.dumps({'passed': True, 'packages': result}) + '\n')
        print('PASS actual isolated essential-package transition and preserved identities\n' + result)
    finally:
        for target in reversed(mounts):
            subprocess.run(['umount', str(target)], check=True)


if __name__ == '__main__':
    main()
