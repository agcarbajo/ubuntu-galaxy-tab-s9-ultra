#!/usr/bin/env python3
"""Inspect an isolated migration resolver without touching the running system."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
__import__("os").environ.setdefault("GALAXY_COMPANION_DEVICE", "gts9uwifi")
sys.path.insert(0, str(REPO / 'external/galaxy-companion/packaging/galaxy-companion/usr/lib/galaxy-companion'))
sys.path.insert(0, str(REPO / 'packaging/gts9u-migration'))
from gts9u_migration import migration_core as migration, migration_plan as plans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transaction', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--solver', choices=('internal', '3.0'), default='internal')
    parser.add_argument('--defer-configuration', action='store_true')
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--package', action='append', default=[])
    parser.add_argument('--all-immediate', action='store_true')
    parser.add_argument('--print-uris', action='store_true')
    args = parser.parse_args()
    root = args.source_root.resolve(strict=True)
    transaction = args.transaction.resolve(strict=True)
    if root == Path('/') or transaction == migration.core.TRANSACTION:
        parser.error('Only isolated build fixtures are accepted')
    runtime = migration.AptRuntime(transaction)
    arguments = (['--print-uris', '--download-only', '-V', '-y'] if args.print_uris else ['--simulate'])
    arguments += ['-o', 'APT::Solver=' + args.solver]
    if args.defer_configuration:
        arguments += ['-o', 'APT::Immediate-Configure=false']
    if args.all_immediate:
        arguments += ['-o', 'APT::Immediate-Configure-All=true']
    for name in args.package:
        plans.package_name(name)
    arguments += ['install', *args.package] if args.package else ['dist-upgrade']
    command = ['apt-get', *arguments] if args.native else runtime.command(arguments)
    name = 'probe-' + ('uris-' if args.print_uris else '') + ('native-' if args.native else '') + args.solver + ('-deferred' if args.defer_configuration else '')
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=args.timeout,
            env={**os.environ, 'APT_CONFIG': str(runtime.config), 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired as error:
        text = (error.stdout or b'') + b'\n' + (error.stderr or b'')
        (transaction / (name + '.timeout.txt')).write_bytes(text)
        raise SystemExit('Resolver timed out; retained partial output is not an approved package plan')
    (transaction / (name + '.txt')).write_text(result.stdout + '\n' + result.stderr)
    print('Simulation exit:', result.returncode)
    for line in result.stdout.splitlines():
        if line.startswith(('Remv ', 'Inst coreutils', 'Inst sudo', 'Conf coreutils', 'Conf sudo')):
            print(line)
    print(result.stderr)
    if result.returncode:
        raise SystemExit(result.returncode)
    if args.print_uris:
        installed = {**migration.installed_versions(root), 'ubuntu-gts9u-migration': '0'}
        plan = plans.parse_selection(result.stdout, installed)
        (transaction / (name + '.json')).write_text(json.dumps(plan, indent=2) + '\n')
        print('Verified dependency selection:', len(plan['install']), 'installs; removals:', plan['remove'])
        print('Dependency selection completed; this is not installation validation')
        return
    plan = plans.parse_plan(result.stdout, migration.installed_versions(root))
    (transaction / (name + '.json')).write_text(json.dumps(plan, indent=2) + '\n')
    print('Verified plan:', len(plan['install']), 'installs; removals:', plan['remove'])


if __name__ == '__main__':
    main()
