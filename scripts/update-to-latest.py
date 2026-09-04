#!/usr/bin/env python3
"""Interactive updater for any installed SM-X910 Ubuntu port version."""
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

REPOSITORY = 'agcarbajo/ubuntu-galaxy-tab-s9-ultra'


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'Gts9u-Legacy-Updater/1'})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Refusing an insecure download')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Unexpected download size')
    return data


def update(core, bundle):
    release = bundle.release()
    state = bundle.release_state(release)
    if state in ('current', 'older'):
        print('You already have the latest published version or a newer build.')
        return
    if state == 'unsupported':
        raise ValueError('The latest release does not support system updates.')
    print('Latest release: ' + release['tag'])
    print('Save your work. This will prepare the update and restart to install it.')
    print('Your data and settings will be preserved.')
    if input('Are you ready? Type y to update [y/N]: ').strip().lower() != 'y':
        print('Cancelled. No update was prepared.')
        return
    core.main(['--latest'])
    if core.status().get('state') != 'ready':
        raise RuntimeError('Update preparation did not complete; not restarting.')
    print('Update ready. Restarting to install...')
    subprocess.run(['systemctl', 'reboot'], check=True)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run this script with sudo.')
    # Resolve main once so both backend modules come from the same source revision.
    commit = json.loads(fetch('https://api.github.com/repos/' + REPOSITORY +
                              '/commits/main', 1024 * 1024))['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid repository revision')
    prefix = ('https://raw.githubusercontent.com/' + REPOSITORY + '/' + commit +
              '/packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion/')
    with tempfile.TemporaryDirectory(prefix='gts9u-updater-') as directory:
        package = Path(directory) / 'tab_companion'
        package.mkdir()
        (package / '__init__.py').write_bytes(b'')
        for name in ('update_bundle.py', 'update_core.py'):
            (package / name).write_bytes(fetch(prefix + name, 1024 * 1024))
        sys.path.insert(0, directory)
        core = importlib.import_module('tab_companion.update_core')
        bundle = importlib.import_module('tab_companion.update_bundle')
        update(core, bundle)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled.', file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
