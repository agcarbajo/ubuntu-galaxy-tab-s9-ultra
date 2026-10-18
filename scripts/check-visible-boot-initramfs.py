#!/usr/bin/env python3
"""Validate the generated splash, ELF dependency closure and init_boot budget."""

from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

archive = Path(sys.argv[1])
assert archive.stat().st_size <= 8314880, 'initramfs exceeds v4 + AVB budget'
with tempfile.TemporaryDirectory(prefix='gts9u-initrd-check-') as directory:
    root = Path(directory)
    data = subprocess.check_output(['lz4', '-dc', str(archive)])
    subprocess.run(['cpio', '-id', '--quiet'], input=data, cwd=root, check=True)
    paths = list(root.rglob('*'))
    # run_scripts() sources each stage's ORDER even when a hook was injected
    # after mkinitramfs. Missing ORDER terminates PID 1 before root selection.
    for stage in (root / 'scripts').iterdir():
        if not stage.is_dir():
            continue
        hooks = [path for path in stage.iterdir()
                 if path.is_file() and path.name != 'ORDER' and path.stat().st_mode & 0o111]
        if not hooks:
            continue
        order = stage / 'ORDER'
        assert order.is_file(), f'Missing hook dispatch table: {order.relative_to(root)}'
        commands = order.read_text().splitlines()
        for hook in hooks:
            command = '/' + hook.relative_to(root).as_posix() + ' "$@"'
            assert command in commands, f'Undispatched initramfs hook: {hook.relative_to(root)}'
    names = {path.name for path in paths}
    seen = set()
    missing = []
    checked = 0
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        st = path.stat()
        if st.st_ino in seen:
            continue
        seen.add(st.st_ino)
        with path.open('rb') as handle:
            magic = handle.read(4)
        if magic != b'\x7fELF':
            continue
        result = subprocess.check_output(['readelf', '-d', str(path)], text=True)
        checked += 1
        for needed in re.findall(r'\(NEEDED\).*?\[(.*?)\]', result):
            if needed not in names:
                missing.append((str(path.relative_to(root)), needed))
    assert not missing, missing
    theme = root / 'usr/share/plymouth/themes/gts9u-ubuntu'
    for name, size in [('watermark.png', (248, 88)), ('throbber-0001.png', (32, 32))]:
        assert struct.unpack('>II', (theme / name).read_bytes()[16:24]) == size
    assert (root / 'usr/sbin/e2fsck').exists()
    launcher = (root / 'scripts/init-premount/plymouth').read_text()
    commands = [line for line in launcher.splitlines()
                if line.lstrip().startswith('/usr/sbin/plymouthd ')]
    assert len(commands) == 1, 'Expected one early Plymouth daemon launcher'
    for flag in ('--graphical-boot', '--ignore-serial-consoles'):
        assert flag in commands[0].split(), 'Early Plymouth launcher lacks ' + flag
    assert (root / 'usr/share/plymouth/themes/default.plymouth').readlink() == Path('/usr/share/plymouth/themes/gts9u-ubuntu/gts9u-ubuntu.plymouth')
    print(f'OK: {checked} ELF files, no missing DT_NEEDED libraries; theme, sizes, fsck and AVB budget verified')
