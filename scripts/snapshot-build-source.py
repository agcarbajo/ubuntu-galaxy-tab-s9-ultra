#!/usr/bin/env python3
"""Freeze project build inputs so long-running scripts cannot change in flight."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = args.output.absolute()
    if target.exists() or str(target).startswith('/mnt/') or ' ' in str(target):
        parser.error('Choose a new immutable Linux source snapshot path without spaces')
    target.mkdir(parents=True)
    for name in ('configs', 'kernel', 'packaging', 'scripts', 'tests', 'docs'):
        shutil.copytree(REPO / name, target / name, symlinks=True,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('AGENTS.md', 'README.md', 'VERSION', 'LICENSE'):
        shutil.copyfile(REPO / name, target / name)
    files = {}
    for file in sorted(target.rglob('*')):
        if file.is_symlink():
            data = str(file.readlink()).encode()
        elif file.is_file():
            data = file.read_bytes()
        else:
            continue
        files[file.relative_to(target).as_posix()] = hashlib.sha256(data).hexdigest()
    revision = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    (target / 'BUILD-SOURCE.json').write_text(json.dumps({'port_revision': revision,
        'source_tree_sha256': digest, 'files': files}, indent=2) + '\n')
    print('Frozen build source:', target, '; files:', len(files), '; SHA-256:', digest)


if __name__ == '__main__':
    main()
