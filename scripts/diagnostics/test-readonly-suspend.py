#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile

source = Path(__file__).with_name('readonly-suspend.sh').read_text()
with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)
    (base / 'bin').mkdir()
    (base / 'run').mkdir()
    (base / 'dev').mkdir()
    (base / 'proc').mkdir()
    (base / 'sys').mkdir()
    (base / 'proc/model').write_bytes(b'Samsung Galaxy Tab S9 Ultra Wi-Fi\0')
    for relative, value in (('sys/battery', '60'), ('sys/mem_sleep', 's2idle [deep]'),
                            ('sys/fail', '0'), ('sys/irq', '21'), ('mode', 'rw'),
                            ('gdm', '1'), ('swap', '1'), ('card', '1')):
        (base / relative).write_text(value)
    (base / 'dev/sda35').write_bytes(bytes(8 * 1024 * 1024))
    (base / 'dev/linuxroot').symlink_to('sda35')
    replacements = {
        'export PATH=/usr/sbin:/usr/bin:/sbin:/bin': f'export PATH={base}/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        'state=/run/gts9u-readonly-suspend': f'state={base}/run/gts9u-readonly-suspend',
        'root_label=/dev/disk/by-partlabel/linuxroot': f'root_label={base}/dev/linuxroot',
        '/proc/device-tree/model': str(base / 'proc/model'),
        '/sys/class/power_supply/sm5714-battery/capacity': str(base / 'sys/battery'),
        '/sys/power/mem_sleep': str(base / 'sys/mem_sleep'),
        '/sys/power/suspend_stats/fail': str(base / 'sys/fail'),
        '/sys/power/pm_wakeup_irq': str(base / 'sys/irq'),
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    scripts = {
        'findmnt': f'''#!/bin/sh
case "$*" in
  '-no OPTIONS /') printf '%s,noatime\n' "$(cat '{base}/mode')";;
  '-no SOURCE /') echo '{base}/dev/sda35';;
  '-rn -o SOURCE,TARGET,OPTIONS')
    echo '{base}/dev/sda35 / ext4 rw,noatime'
    if [ "$(cat '{base}/card')" = 1 ]; then echo '/dev/mmcblk1p1 /media/card rw,nosuid'; fi;;
esac
''',
        'blockdev': '#!/bin/sh\necho 0\n',
        'python3': '#!/bin/sh\nexit 0\n',
        'gts9u-update': '#!/bin/sh\necho complete\n',
        'swapon': f'''#!/bin/sh
case "$1" in
  --show=NAME,USED) [ "$(cat '{base}/swap')" = 1 ] && echo '/swapfile 0B';;
  --show=NAME) [ "$(cat '{base}/swap')" = 1 ] && echo /swapfile;;
  /swapfile) echo 1 > '{base}/swap';;
esac
''',
        'swapoff': f'#!/bin/sh\necho 0 > "{base}/swap"\n',
        'systemctl': f'''#!/bin/sh
case "$1" in
  is-active) test "$(cat '{base}/gdm')" = 1;;
  stop) echo 0 > '{base}/gdm';;
  start) echo 1 > '{base}/gdm';;
esac
''',
        'mount': f'''#!/bin/sh
case "$2" in
  remount,ro) test ! -e '{base}/mount-fail' || exit 1; echo ro > '{base}/mode';;
  remount,rw) echo rw > '{base}/mode';;
esac
''',
    }
    for name, data in scripts.items():
        path = base / 'bin' / name
        path.write_text(data)
        path.chmod(0o755)

    def run(action, success=True):
        result = subprocess.run(['/bin/sh', '-c', source.split('\ncase "${1:-}" in')[0] + '\n' + action],
                                capture_output=True, text=True, timeout=25)
        assert (result.returncode == 0) == success, (action, result.stdout, result.stderr)
        return result

    run('check', success=False)
    assert (base / 'mode').read_text() == 'rw'
    (base / 'card').write_text('0')
    run('check')
    (base / 'mount-fail').touch()
    run('prepare', success=False)
    assert (base / 'mode').read_text().strip() == 'rw'
    assert (base / 'gdm').read_text().strip() == '1'
    assert (base / 'swap').read_text().strip() == '1'
    (base / 'mount-fail').unlink()
    (base / 'run/gts9u-readonly-suspend/status').unlink()
    (base / 'run/gts9u-readonly-suspend').rmdir()
    run('prepare')
    assert (base / 'mode').read_text().strip() == 'ro'
    assert (base / 'gdm').read_text().strip() == '0'
    assert (base / 'swap').read_text().strip() == '0'
    run('probe')
    run('rollback')
    assert (base / 'mode').read_text().strip() == 'rw'
    assert (base / 'gdm').read_text().strip() == '1'
    assert (base / 'swap').read_text().strip() == '1'
    print('PASS: refuses writable removable media, prepares read-only root, checks storage, restores swap and GDM')
