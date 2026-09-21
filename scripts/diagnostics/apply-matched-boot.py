import argparse
import fcntl
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, '/usr/lib/tab-companion')
from tab_companion import update_core as update
from tab_companion import update_bundle as bundle

SIZE = 100663296
SAVED = Path('/var/lib/gts9u-boot-sets/ubuntu/boot.img')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def dtb(image):
    length = struct.unpack_from('<I', image, 8)[0]
    decoder = zlib.decompressobj(31)
    decoder.decompress(image[4096:4096 + length])
    require(decoder.eof, 'Truncated kernel payload')
    return decoder.unused_data


def atomic_copy(source, target):
    fd, name = tempfile.mkstemp(prefix=target.name + '.update-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as dst, source.open('rb') as src:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    fd = os.open(target.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    require(bundle.sha256(source) == bundle.sha256(target), 'Saved boot set readback failed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    for name in ('baseline', 'boot', 'device', 'fingerprint'):
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--reboot', action='store_true')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Root is required')
    directory = args.directory.resolve()
    update.owned_directory(directory)
    with update.boot_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        update.device_check()
        update.power_check()
        require(not os.path.lexists('/system-update'), 'A system update is already pending')
        require(update.status().get('state') in ('idle', 'complete'), 'Resolve the existing update state first')
        devices = update.partitions()
        candidate = directory / 'boot.img'
        device_deb = directory / 'ubuntu-gts9u-device_2.54_arm64.deb'
        fingerprint_deb = directory / 'libfprint-gts9u48.deb'
        for path, expected in ((candidate, args.boot_sha256), (device_deb, args.device_sha256),
                               (fingerprint_deb, args.fingerprint_sha256)):
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                    'Unsafe staged file: ' + str(path))
            require(bundle.sha256(path) == expected, 'Staged file hash mismatch: ' + path.name)
        original = devices['boot'].read_bytes()
        new = candidate.read_bytes()
        require(len(new) == SIZE and len(original) == SIZE, 'Wrong image size')
        require(bundle.sha256(devices['boot']) == args.baseline_sha256, 'Live boot changed')
        require(bundle.sha256(SAVED) == args.baseline_sha256, 'Saved Ubuntu boot differs from the live boot')
        require(new[:8] == original[:8] == b'ANDROID!' and new[12:4096] == original[12:4096],
                'Boot header changed')
        require(dtb(new) == dtb(original), 'Appended DTB changed')
        require(not update.run(['dpkg', '--audit'], True), 'dpkg is not clean')
        modules = Path('/usr/lib/modules') / os.uname().release / 'updates/qcom_spss_irq.ko'
        owner = Path('/usr/libexec/ubuntu-gts9u-fingerprint-secure-owner')
        hardware = {str(path): bundle.sha256(path) for path in (modules, owner)}
        retained = {name: bundle.sha256(path) for name, path in devices.items() if name != 'boot'}
        android = {str(path): bundle.sha256(path) for path in Path('/var/lib/gts9u-boot-sets/android').glob('*.img')}
        update.run(['apt-get', '-s', '--no-remove', 'install', str(device_deb), str(fingerprint_deb)])
        print('PREFLIGHT PASS: Ubuntu identity, power, images, hashes, DTB, package plan and boot lock', flush=True)
        if not args.execute:
            return
        require(shutil.disk_usage(directory).free > 512 * 1024**2, 'Insufficient backup space')
        backup = directory / 'backup'
        backup.mkdir(mode=0o700, exist_ok=False)
        for name, path in devices.items():
            shutil.copyfile(path, backup / (name + '.img'))
            require(bundle.sha256(backup / (name + '.img')) == bundle.sha256(path), 'Backup readback failed')
        shutil.copy2(SAVED, backup / 'saved-ubuntu-boot.img')
        for name in ('/usr/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0',
                     '/usr/libexec/ubuntu-gts9u-fingerprint-ui',
                     '/usr/share/dbus-1/system.d/io.github.agcarbajo.Gts9uFingerprintUI.conf'):
            shutil.copy2(name, backup / Path(name).name)
        shutil.copytree('/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo', backup / 'overlay')
        update.write_json(backup / 'baseline.json', {'boot': args.baseline_sha256, 'retained': retained,
                          'android': android, 'hardware': hardware})
        os.sync()
        boot_started = False
        try:
            update.run(['systemctl', 'stop', 'display-manager.service'])
            update.run(['apt-get', '-y', '--no-remove', '-o', 'Dpkg::Options::=--force-confold',
                        'install', str(device_deb), str(fingerprint_deb)])
            update.run(['apt-get', 'check'])
            require(not update.run(['dpkg', '--audit'], True), 'Package configuration is incomplete')
            require(all(bundle.sha256(Path(path)) == digest for path, digest in hardware.items()),
                    'The matching IRQ module or secure owner changed')
            require(bundle.sha256(devices['boot']) == args.baseline_sha256, 'Boot changed during package install')
            boot_started = True
            update.copy_partition(candidate, devices['boot'], SIZE)
            atomic_copy(candidate, SAVED)
            require(all(bundle.sha256(devices[name]) == digest for name, digest in retained.items()),
                    'An unrelated boot partition changed')
            require(all(bundle.sha256(Path(path)) == digest for path, digest in android.items()),
                    'An Android boot backup changed')
            update.write_json(directory / 'applied.json', {'boot': args.boot_sha256,
                              'previous_boot': args.baseline_sha256, 'backup': str(backup)})
            os.sync()
        except Exception as error:
            if boot_started:
                update.copy_partition(backup / 'boot.img', devices['boot'], SIZE)
                atomic_copy(backup / 'saved-ubuntu-boot.img', SAVED)
            update.write_json(directory / 'failed.json', {'error': str(error), 'boot_restored': boot_started})
            raise
        print('APPLIED: boot and saved Ubuntu set verified; other partitions and Android backups unchanged', flush=True)
        if args.reboot:
            update.run(['systemctl', '--no-block', 'reboot'])


if __name__ == '__main__':
    main()
