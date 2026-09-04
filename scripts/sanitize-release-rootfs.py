#!/usr/bin/env python3
"""Reject personal image data and remove build-generated SSH host identities."""
import pathlib
import sys


def sanitize(root):
    root = pathlib.Path(root).resolve()
    if root == pathlib.Path('/') or not (root / 'etc/os-release').is_file():
        raise ValueError('expected an offline Ubuntu root filesystem')
    issues = []
    for line in (root / 'etc/passwd').read_text(encoding='utf-8').splitlines():
        if 1000 <= int(line.split(':')[2]) < 65534:
            issues.append('personal user account')
    for line in (root / 'etc/shadow').read_text(encoding='utf-8').splitlines():
        password = line.split(':')[1]
        if password and not password.startswith(('!', '*')):
            issues.append('configured account password')
    for name in ('home', 'root/.ssh', 'etc/skel/.ssh',
                 'etc/NetworkManager/system-connections', 'var/lib/fprint',
                 'var/lib/tab-companion-update'):
        directory = root / name
        if directory.exists() and any(p.is_file() for p in directory.rglob('*')):
            issues.append('personal data in ' + name)
    for name in ('root/.bash_history', 'root/.python_history', 'root/.git-credentials'):
        if (root / name).exists():
            issues.append('private history in ' + name)
    for name in ('etc/machine-id', 'var/lib/dbus/machine-id'):
        path = root / name
        if path.is_file() and not path.is_symlink() and path.read_bytes().strip():
            issues.append('machine identity in ' + name)
    if issues:
        raise ValueError('refusing to publish: ' + '; '.join(issues))
    # openssh-server generates these during package installation. Fresh images
    # must not share them; ssh-keygen -A generates missing keys on the device.
    unit = root / 'usr/lib/systemd/system/ubuntu-gts9u-ssh-host-keys.service'
    if not unit.is_file():
        raise ValueError('missing first-boot SSH host-key generation unit')
    for path in (root / 'etc/ssh').glob('ssh_host_*_key*'):
        if path.is_file() or path.is_symlink():
            path.unlink()
    print('Release rootfs: no personal accounts/data; build SSH identities removed.')


if __name__ == '__main__':
    sanitize(sys.argv[1])
