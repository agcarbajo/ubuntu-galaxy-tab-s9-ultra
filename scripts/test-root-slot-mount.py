#!/usr/bin/env python3
"""Run the actual slot mount flow in a private namespace on a new ext4 image."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
script = repo / 'packaging/ubuntu-gts9u-device/usr/share/initramfs-tools/scripts/local-bottom/gts9u-root-slot'
if '--inside' not in sys.argv:
    subprocess.run(['unshare', '--mount', '--propagation', 'private', sys.executable,
                    str(Path(__file__).resolve()), '--inside'], check=True)
    sys.exit(0)

with tempfile.TemporaryDirectory(prefix='gts9u-slot-mount-') as temporary:
    base = Path(temporary)
    image = base / 'new-test-filesystem.img'
    with image.open('wb') as stream:
        stream.truncate(128 * 1024**2)
    subprocess.run(['mkfs.ext4', '-q', '-L', 'UBTS9U_UFS', str(image)], check=True)
    root = base / 'mounted-root'
    root.mkdir()
    subprocess.run(['mount', '-o', 'loop', str(image), str(root)], check=True)
    try:
        store = root / '.gts9u-root'
        store.mkdir(mode=0o700)
        slot = store / 'slots' / ('a' * 32)
        target = slot / 'root'
        for directory in ('usr/lib/systemd', 'home', '.gts9u-base'):
            (target / directory).mkdir(parents=True, exist_ok=True)
        (target / '.gts9u-base').chmod(0o700)
        (target / 'usr/lib/os-release').write_text('VERSION_ID="26.04"\n')
        (target / 'usr/lib/systemd/systemd').write_text('simulated init, never executed')
        (target / 'usr/lib/systemd/systemd').chmod(0o755)
        (slot / 'ready').write_text(os.uname().release + '\n')
        (store / 'selected').write_text('a' * 32 + '\n')
        (store / 'selected').chmod(0o600)
        (store / 'pending').write_text('a' * 32 + '\n')
        home = root / 'home'
        home.mkdir()
        sentinel = home / 'user-settings'
        sentinel.write_text('synthetic retained user data')
        inode = sentinel.stat().st_ino
        (root / 'old-system').write_text('original system retained')
        code = script.read_text().replace('. /scripts/functions', "panic() { printf '%s\\n' \"$*\" >&2; exit 1; }")
        runner = base / 'actual-slot-flow.sh'
        runner.write_text(code)
        subprocess.run(['mount', '-o', 'remount,ro', str(root)], check=True)
        subprocess.run(['sh', str(runner)], env={**os.environ, 'rootmnt': str(root)}, check=True)
        assert (root / 'home/user-settings').read_text() == 'synthetic retained user data'
        assert (root / 'home/user-settings').stat().st_ino == inode
        assert (root / '.gts9u-base/old-system').read_text() == 'original system retained'
        assert (root / 'usr/lib/os-release').read_text() == 'VERSION_ID="26.04"\n'
        assert (root / '.gts9u-base/.gts9u-root/slots' / ('a' * 32) / 'tried').read_text() == 'trial\n'
        (root / 'home/new-user-setting').write_text('writable shared home after trial activation')
        source = subprocess.check_output(['findmnt', '-no', 'SOURCE', str(root)], text=True).strip()
        assert '[' in source, source
        print('PASS real ext4 slot activation, original-root retention and shared-home inode identity')
    finally:
        subprocess.run(['umount', '-R', str(root)], check=True)
