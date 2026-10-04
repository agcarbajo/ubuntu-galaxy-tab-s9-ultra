#!/usr/bin/env python3
"""Run the real frozen cross-suite transaction in an inactive disposable root."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'packaging/ubuntu-gts9u-companion/usr/lib/tab-companion'))
from tab_companion import migration_core as migration, migration_plan as plans, update_policy as policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--archives-from', type=Path)
    args = parser.parse_args()
    source = args.source_root.resolve(strict=True)
    output = args.output.absolute()
    if source == Path('/') or output.exists() != args.resume or str(output).startswith('/mnt/'):
        parser.error('Use the trusted Noble fixture and a new Linux output path, or explicitly resume a fixture')
    if policy.ubuntu_suite(source / 'etc/os-release') != 'noble':
        parser.error('The full transition test requires the original Noble fixture')
    if not args.resume:
        package = REPO / 'packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion'
        with zipfile.ZipFile(args.backend) as program:
            for name in ('migration_core.py', 'migration_plan.py', 'update_core.py', 'update_bundle.py', 'update_policy.py'):
                if program.read('tab_companion/' + name) != (package / name).read_bytes():
                    raise ValueError('The tested migration source must match the frozen release backend')
    if not args.inside:
        subprocess.run(['unshare', '--mount', '--propagation', 'private', sys.executable,
            str(Path(__file__).resolve()), *sys.argv[1:], '--inside'], check=True)
        return
    output.mkdir(parents=True, exist_ok=args.resume)
    baseline = output / 'source'
    if not args.resume:
        baseline.mkdir()
        subprocess.run(['rsync', '-aHAXS', '--numeric-ids', '--one-file-system',
                        str(source) + '/', str(baseline) + '/'], check=True)
    elif migration.bundle.sha256(baseline / 'var/lib/dpkg/status') != migration.bundle.sha256(source / 'var/lib/dpkg/status'):
        raise ValueError('The retained baseline was modified; choose a new fixture')
    home = baseline / 'home/migration-fixture'
    home.mkdir(exist_ok=args.resume)
    if not args.resume:
        (home / 'retained-settings').write_text('synthetic shared-home preservation fixture\n')
    subprocess.run(['ssh-keygen', '-A', '-f', str(baseline)], check=True)
    subprocess.run(['systemd-machine-id-setup', '--root=' + str(baseline)], check=True)
    before = migration.installed_versions(baseline)
    original_status = migration.bundle.sha256(baseline / 'var/lib/dpkg/status')
    transaction = output / 'transaction'
    runtime = migration.AptRuntime(transaction)
    if args.resume:
        manifest = migration.bundle.inspect(args.zip)
        for name, entry in manifest['files'].items():
            if migration.bundle.sha256(transaction / name) != entry['sha256']:
                raise ValueError('A retained fixture payload changed')
        migration.core.cache_local_packages(transaction, {'files': {
            file.relative_to(transaction).as_posix(): {} for file in (transaction / 'UPDATE/debs').glob('*.deb')}})
        plan = runtime.selection(['dist-upgrade'], {**before, 'ubuntu-gts9u-migration': '0'})
    else:
        transaction.mkdir(mode=0o700)
        manifest = migration.bundle.extract(args.zip, transaction)
        runtime.extract(args.backend)
        runtime.configure(baseline)
        migration.core.cache_local_packages(transaction, manifest)
        if args.archives_from:
            for file in args.archives_from.glob('*.deb'):
                if file.is_symlink() or file.name.startswith('ubuntu-gts9u-migration_'):
                    continue
                target = transaction / 'archives' / file.name
                if target.exists():
                    if migration.bundle.sha256(target) != migration.bundle.sha256(file):
                        raise ValueError('Conflicting reused archive')
                else:
                    shutil.copyfile(file, target)
        print('Resolving the real authenticated Resolute package transaction...', flush=True)
        plan = runtime.resolve(manifest, before)
    archives = migration.verify_archives(transaction, plan)
    (transaction / 'packages.json').write_text(json.dumps(plan, indent=2) + '\n')
    (transaction / 'archives.json').write_text(json.dumps(archives, indent=2) + '\n')
    slot = migration.create_slot(baseline)
    root = migration.clone_system(baseline, slot)
    print('Applying the frozen package plan to the inactive root...', flush=True)
    migration.apply_packages(root, transaction, plan, runtime)
    plans.restore_compatibility_files(baseline, root)
    plans.check_preservation(baseline, root)
    if policy.ubuntu_suite(root / 'etc/os-release') != 'resolute':
        raise ValueError('The inactive root did not reach Ubuntu 26.04')
    installed = migration.installed_versions(root)
    for name, version in plan['install'].items():
        if installed.get(name) != version:
            raise ValueError('The installed version differs from the frozen plan: ' + name)
    if any(name in installed for name in plan['remove']):
        raise ValueError('The reviewed obsolete package was not replaced')
    if migration.bundle.sha256(baseline / 'var/lib/dpkg/status') != original_status:
        raise ValueError('The original system root was modified by the transaction')
    if (home / 'retained-settings').read_text() != 'synthetic shared-home preservation fixture\n':
        raise ValueError('The original shared home was modified')
    result = {'passed': True, 'target_suite': 'resolute', 'installs': len(plan['install']),
        'zip_sha256': migration.bundle.sha256(args.zip),
        'reviewed_removals': plan['remove'], 'downloaded_archives': len(archives),
        'original_root_retained': True, 'shared_home_retained': True,
        'protected_identity_retained': True, 'physical_boot_validated': False,
        'selected_root': str(root)}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
