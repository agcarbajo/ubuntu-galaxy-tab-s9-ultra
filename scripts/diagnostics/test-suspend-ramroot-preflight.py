#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('original', type=Path)
parser.add_argument('candidate', type=Path)
args = parser.parse_args()
source = Path(__file__).with_name('suspend-ramroot-preflight').read_text()
original = args.original.read_bytes()
candidate = args.candidate.read_bytes()
assert hashlib.sha256(original).hexdigest() == 'add0ee44a386db86a9860ae6bfe846d3b9424695d05271e93e574fff21c806bd'

for case in ('success', 'missing-backup', 'wrong-backup', 'bad-write'):
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        work = base / 'run/gts9u-suspend'
        work.mkdir(parents=True)
        root = work / 'root'
        saved = base / 'saved/var/lib/gts9u-boot-sets/ubuntu'
        saved.mkdir(parents=True)
        if case != 'missing-backup':
            (saved / 'init_boot.img').write_bytes(original if case != 'wrong-backup' else candidate)
        fake_sys = base / 'sys/class/block'
        for name, label in (('sda35', 'linuxroot'), ('sda22', 'init_boot')):
            path = fake_sys / name / 'uevent'
            path.parent.mkdir(parents=True)
            path.write_text('PARTNAME=' + label + '\n')
        compat = base / 'sys/firmware/devicetree/base/compatible'
        compat.parent.mkdir(parents=True)
        compat.write_text('samsung,gts9uwifi')
        init = base / 'dev/sda22'
        init.parent.mkdir()
        init.write_bytes(candidate)
        proc = base / 'proc'
        proc.mkdir()
        (proc / 'sysrq-trigger').write_text('')
        (proc / 'mounts').write_text('')
        (base / 'kmsg').touch()
        script = source
        for old, new in (('/sys/', str(base / 'sys') + '/'),
                         ('/proc/sysrq-trigger', str(proc / 'sysrq-trigger')),
                         ('/proc/mounts', str(proc / 'mounts')),
                         ('/dev/kmsg', str(base / 'kmsg')),
                         ('/run/gts9u-suspend', str(work)),
                         ('/dev/', str(base / 'dev') + '/'),
                         ('/usr/bin/sha256sum', '/usr/bin/sha256sum')):
            script = script.replace(old, new)
        script = script.replace('mount -t tmpfs tmpfs /run', 'mount -t tmpfs tmpfs ' + str(base / 'run'))
        prelude = f'''
mount() {{
    if [ "$1" = '-t' ] && [ "$2" = 'ext4' ]; then
        /usr/bin/rmdir '{root}'
        ln -s '{base}/saved' '{root}'
        printf '/dev/mock {root} ext4 ro 0 0\n' > '{proc}/mounts'
    fi
}}
umount() {{ /usr/bin/rm -f "$1"; : > '{proc}/mounts'; }}
blockdev() {{ echo 8388608; }}
sync() {{ :; }}
sleep() {{ exit 0; }}
'''
        if case == 'bad-write':
            prelude += 'dd() { printf broken > "$init"; }\n'
        result = subprocess.run(['/bin/sh'], input=prelude + script, text=True,
                                capture_output=True, timeout=25)
        assert result.returncode == 0, (case, result.stderr)
        rebooted = (proc / 'sysrq-trigger').read_text().strip() == 'b'
        if case == 'success':
            assert rebooted and init.read_bytes() == original, case
        else:
            assert not rebooted and not root.is_symlink(), case
            if case in ('missing-backup', 'wrong-backup'):
                assert init.read_bytes() == candidate, case
        print('PASS preflight simulated:', case)
