#!/usr/bin/env python3
"""Check native app discovery and desktop override lifecycle in a fresh tree."""
from pathlib import Path
import runpy
import tempfile
from unittest.mock import patch

base = Path(__file__).resolve().parents[1] / 'packaging/ubuntu-gts9u-device/usr/libexec'
scanner = runpy.run_path(str(base / 'ubuntu-gts9u-chromium-desktops'))
runner = runpy.run_path(str(base / 'ubuntu-gts9u-chromium-run'))
assert runner['defaults']([], True, True) == ['--use-angle=vulkan', '--ozone-platform=wayland']
assert runner['defaults'](['--use-angle=gl', '--ozone-platform=x11'], True, True) == []
assert runner['defaults']([], False, True) == []
assert runner['defaults']([], True, False) == ['--use-angle=vulkan']
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    source, output = root / 'source', root / 'output'
    source.mkdir(); output.mkdir()
    app = root / 'an app/App'
    app.parent.mkdir()
    app.write_text('#!/bin/sh\n'); app.chmod(0o755)
    (app.parent / 'resources').mkdir()
    (app.parent / 'resources/app.asar').touch()
    text = '[Desktop Entry]\nName=Example\nExec="' + str(app) + '" %U\nDBusActivatable=true\n[Desktop Action New]\nExec="' + str(app) + '" --new-window %F\n'
    (source / 'example.desktop').write_text(text)
    (source / 'unrelated.desktop').write_text('[Desktop Entry]\nExec=/bin/true\n')
    refresh = scanner['refresh']
    with patch.dict(refresh.__globals__, SOURCE=source, OUTPUT=output, STATE=root / 'state.json'):
        refresh()
        generated = output / 'example.desktop'
        first = generated.read_text()
        assert first.count('Exec=/usr/libexec/ubuntu-gts9u-chromium-run ') == 2
        assert '"' + str(app) + '" %U' in first
        assert 'DBusActivatable=false' in first
        assert not (output / 'unrelated.desktop').exists()
        refresh(); assert generated.read_text() == first
        (source / 'example.desktop').write_text(text.replace('Name=Example', 'Name=Updated'))
        refresh(); assert 'Name=Updated' in generated.read_text()
        (source / 'example.desktop').unlink()
        refresh(); assert not generated.exists()
        (source / 'example.desktop').write_text(text)
        refresh(); generated.write_text('# administrator edit\n')
        refresh(); assert generated.read_text() == '# administrator edit\n'
        refresh(True); assert generated.read_text() == '# administrator edit\n'
        generated.unlink()
        refresh(); assert generated.exists()
        refresh(True); assert not generated.exists()
        (source / 'example.desktop').write_text(text + 'X-GTS9U-Chromium-Defaults=false\n')
        refresh(); assert not generated.exists()
print('PASS: discovery, clean install, updates, arguments, explicit flags, opt-out and safe removal')