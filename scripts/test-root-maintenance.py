#!/usr/bin/python3
"""Previous-system cleanup against a temporary tree, never a real root."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-root-maintenance'
loader = importlib.machinery.SourceFileLoader('root_maintenance', str(source))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

health = m.advance_health({}, 'boot1', 100, True)
assert health.get('seconds', 0) == 0
m.advance_health(health, 'boot1', 700, True)
assert health['seconds'] == 600
health['clean_boot'] = 'boot1'
m.advance_health(health, 'boot2', 50, True)
assert health['seconds'] == 600
m.advance_health(health, 'boot3', 50, True)
assert health['seconds'] == 0, 'An unclean reboot must reset the seven-day trial'
m.advance_health(health, 'boot3', 650, True)
assert health['seconds'] == 600
m.advance_health(health, 'boot3', 1250, False)
assert health['seconds'] == 0, 'A failed health check must preserve recovery'
m.advance_health(health, 'boot3', 1850, True)
assert health['seconds'] == 0

with tempfile.TemporaryDirectory() as temp:
    base = Path(temp) / 'base'
    slot = base / '.gts9u-root/slots' / ('a' * 32)
    saved = slot / 'root/var/lib/gts9u-boot-sets/ubuntu'
    saved.mkdir(parents=True)
    for name, size in (('boot', 100663296), ('init_boot', 8388608), ('vendor_boot', 100663296), ('dtbo', 16777216)):
        with (saved / (name + '.img')).open('wb') as stream:
            stream.truncate(size)
    for name in ('home/user/data', 'root/private-backup', '.gts9u-root/keep',
                 'usr/old-binary', 'etc/old-config', 'var/lib/old-state/data',
                 'var/lib/gts9u-boot-sets/android/boot.img', 'var/log/old-log'):
        file = base / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('retain' if name.startswith(('home/', 'root/', '.gts9u-root/', 'var/lib/gts9u-boot-sets/')) else 'old')
    recovery = base / 'var/lib/gts9u-boot-backups/android.previous/boot.img'
    recovery.parent.mkdir(parents=True)
    recovery.write_text('retain verified Android recovery')
    old = base / 'var/lib/gts9u-boot-sets/ubuntu'
    old.mkdir()
    (old / 'boot.img').write_text('old boot recovery')
    (base / 'lib').symlink_to('/usr/lib')
    with patch.object(m, 'BASE', base):
        m.publish(slot)
        m.publish(slot)
    assert old.resolve() == saved
    assert (slot / 'previous-boot-set/boot.img').read_text() == 'old boot recovery'
    original_candidates, original_checked = m.candidates, m.checked_paths
    with patch.object(m, 'STATE', Path(temp) / 'state'), patch.object(m, 'selected', return_value=slot), \
         patch.object(m, 'healthy', return_value=True), patch.object(m, 'publish'), \
         patch.object(m, 'candidates', side_effect=lambda: original_candidates(base)), \
         patch.object(m, 'checked_paths', side_effect=lambda paths: original_checked(paths, base)), \
         patch.object(m.os, 'geteuid', return_value=0), patch.object(sys, 'argv', ['maintenance', '--cleanup']):
        m.main()
    assert not (base / 'usr').exists() and not (base / 'etc').exists()
    for name in ('home/user/data', 'root/private-backup', '.gts9u-root/keep', 'var/lib/gts9u-boot-sets/android/boot.img'):
        assert (base / name).read_text() == 'retain', name
    assert (slot / 'previous-system-removed').exists()
    assert recovery.read_text() == 'retain verified Android recovery'
    assert old.resolve() == saved and (saved / 'boot.img').exists()
    outside = Path(temp) / 'outside'
    outside.mkdir()
    try:
        original_checked([outside], base)
        raise AssertionError('Escaping cleanup path accepted')
    except ValueError:
        pass
print('PASS old OS removed; active slot, shared home, private recovery and Android boot set retained')
