#!/usr/bin/env python3
"""Interactive updater for any installed SM-X910 Ubuntu port version.

It runs Galaxy Companion's updater from one pinned revision of that repository
with this tablet's device profile, so it works on installations that still
have Tab Companion or no companion at all."""
import importlib
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

REPOSITORY = 'agcarbajo/galaxy-companion'
PACKAGE = '/packaging/galaxy-companion/usr/'
MODULES = ('update_bundle.py', 'update_core.py', 'update_policy.py', 'device.py', 'boot_core.py')
PROFILE = 'gts9uwifi'


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'Gts9u-Legacy-Updater/1'})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Refusing an insecure download')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Unexpected download size')
    return data


def update(core, bundle, repair=False):
    tag = bundle.current().get('tag') if repair else None
    if repair and not tag:
        raise ValueError('This installation has no recorded GitHub build. Repair is unavailable.')
    release = bundle.release(tag) if repair else bundle.release()
    state = bundle.release_state(release)
    if not repair and state in ('current', 'older'):
        print('You already have the latest published version or a newer build.')
        return
    if state == 'unsupported':
        raise ValueError('The latest release does not support system updates.')
    print(('Reinstalling: ' if repair else 'Latest release: ') + release['tag'])
    print('Save your work. This will prepare the update and restart to install it.')
    print('Your data and settings will be preserved.')
    if input('Are you ready? Type y to update [y/N]: ').strip().lower() != 'y':
        print('Cancelled. No update was prepared.')
        return
    core.main(['--repair'] if repair else ['--latest'])
    if core.status().get('state') != 'ready':
        raise RuntimeError('Update preparation did not complete; not restarting.')
    print('Update ready. Restarting to install...')
    subprocess.run(['systemctl', 'reboot'], check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair', action='store_true', help='Reinstall the recorded build with the current updater backend')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise SystemExit('Run this script with sudo.')
    # Resolve main once so every backend module and the device profile come
    # from the same revision.
    commit = json.loads(fetch('https://api.github.com/repos/' + REPOSITORY +
                              '/commits/main', 1024 * 1024))['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid repository revision')
    prefix = 'https://raw.githubusercontent.com/' + REPOSITORY + '/' + commit + PACKAGE
    with tempfile.TemporaryDirectory(prefix='gts9u-updater-') as directory:
        package = Path(directory) / 'galaxy_companion'
        package.mkdir()
        (package / '__init__.py').write_bytes(b'')
        for name in MODULES:
            (package / name).write_bytes(fetch(prefix + 'lib/galaxy-companion/galaxy_companion/' + name, 1024 * 1024))
        profiles = Path(directory) / 'devices'
        profiles.mkdir()
        (profiles / (PROFILE + '.json')).write_bytes(
            fetch(prefix + 'share/galaxy-companion/devices/' + PROFILE + '.json', 1024 * 1024))
        # This script is the SM-X910 port's: force its profile rather than
        # match the device tree, which the privileged step re-reads anyway.
        os.environ['GALAXY_COMPANION_DEVICES_DIR'] = str(profiles)
        os.environ['GALAXY_COMPANION_DEVICE'] = PROFILE
        sys.path.insert(0, directory)
        core = importlib.import_module('galaxy_companion.update_core')
        bundle = importlib.import_module('galaxy_companion.update_bundle')
        update(core, bundle, repair=args.repair)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled.', file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
