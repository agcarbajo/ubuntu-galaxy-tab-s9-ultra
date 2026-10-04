#!/usr/bin/env python3
"""Exercise the real early recovery flow only on new file-backed loop devices."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'packaging/ubuntu-gts9u-device/usr/share/initramfs-tools/scripts/local-bottom/gts9u-root-slot'
SIZES = {'boot': 100663296, 'init_boot': 8388608, 'vendor_boot': 100663296, 'dtbo': 16777216}


def digest(file):
    result = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            result.update(block)
    return result.hexdigest()


def main():
    if '--inside' not in sys.argv:
        subprocess.run(['unshare', '--mount', '--propagation', 'private', sys.executable,
                        str(Path(__file__).resolve()), '--inside'], check=True)
        return
    with tempfile.TemporaryDirectory(prefix='gts9u-root-recovery-') as temporary:
        base = Path(temporary)
        image = base / 'new-root-filesystem.img'
        with image.open('wb') as stream:
            stream.truncate(512 * 1024**2)
        subprocess.run(['mkfs.ext4', '-q', str(image)], check=True)
        root = base / 'root'
        root.mkdir()
        subprocess.run(['mount', '-o', 'loop', str(image), str(root)], check=True)
        devices = []
        try:
            store = root / '.gts9u-root'
            store.mkdir(mode=0o700)
            identifier = 'a' * 32
            slot = store / 'slots' / identifier
            backup = slot / 'backup'
            backup.mkdir(parents=True)
            (slot / 'tried').write_text('trial\n')
            (store / 'selected').write_text(identifier + '\n')
            (store / 'pending').write_text(identifier + '\n')
            (root / 'var/lib/tab-companion-update').mkdir(parents=True)
            (root / 'etc').mkdir()
            (root / 'etc/system-update').symlink_to('/var/lib/tab-companion-update/transaction')
            labels = base / 'private-partlabels'
            labels.mkdir()
            hashes = {}
            for part, size in SIZES.items():
                old = backup / (part + '.img')
                with old.open('wb') as stream:
                    stream.write(('synthetic old ' + part).encode())
                    stream.truncate(size)
                hashes[part] = digest(old)
                target = base / ('new-device-' + part + '.img')
                with target.open('wb') as stream:
                    stream.write(('synthetic trial ' + part).encode())
                    stream.truncate(size)
                device = subprocess.check_output(['losetup', '--find', '--show', str(target)], text=True).strip()
                devices.append(device)
                (labels / part).symlink_to(device)
            (backup / 'SHA256SUMS').write_text(''.join(value + '  ' + part + '.img\n' for part, value in hashes.items()))
            runner = base / 'actual-recovery-flow.sh'
            code = SCRIPT.read_text().replace('. /scripts/functions', "panic() { printf '%s\\n' \"$*\" >&2; exit 1; }")
            code = code.replace('/dev/disk/by-partlabel', str(labels)).replace('    reboot -f', '    exit 0')
            runner.write_text(code)
            subprocess.run(['mount', '-o', 'remount,ro', str(root)], check=True)
            subprocess.run(['sh', str(runner)], env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'rootmnt': str(root)}, check=True)
            for part in SIZES:
                if digest(labels / part) != hashes[part]:
                    raise ValueError('Recovery readback differs from the old boot image')
            if (store / 'selected').exists() or (store / 'pending').exists() or (root / 'etc/system-update').is_symlink():
                raise ValueError('Recovery did not clear its own trial/update markers')
            if (slot / 'result').read_text() != 'rolled-back\n':
                raise ValueError('Recovery did not retain its rollback result')
            if json.loads((root / 'var/lib/tab-companion-update/status.json').read_text())['state'] != 'failed':
                raise ValueError('Recovery did not report the failed trial')
            print('PASS actual early rollback, four loop-device readbacks and retained old-root status; no physical partitions used')
        finally:
            for device in devices:
                subprocess.run(['losetup', '--detach', device], check=True)
            subprocess.run(['umount', str(root)], check=True)


if __name__ == '__main__':
    main()
