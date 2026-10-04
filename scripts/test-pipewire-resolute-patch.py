#!/usr/bin/env python3
"""Apply the orientation patch without fuzz to the pinned Ubuntu SPA source."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
patch = repo / 'packaging/pipewire/patches/resolute-0001-libcamera-suppress-redundant-video-transform.patch'
data = patch.read_bytes()
assert b'\r' not in data, 'The patch must use LF line endings'
assert data.endswith(b'\n'), 'The patch must end with a newline'
with tempfile.TemporaryDirectory() as temporary:
    source = Path(temporary) / 'spa/plugins/libcamera/libcamera-source.cpp'
    source.parent.mkdir(parents=True)
    source.write_bytes(Path(sys.argv[1]).read_bytes())
    hunk = re.split(r'@@[^@]*@@\n', data.decode(), maxsplit=1)[1]
    old = ''.join(line[1:] for line in hunk.splitlines(keepends=True) if line.startswith((' ', '-')))
    assert old in source.read_text(), 'The pinned source differs from the patch context: ' + repr(old)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', temporary], input=data, check=True)
    result = source.read_text()
    assert 'b->videotransform->transform = SPA_META_TRANSFORMATION_None;' in result
    assert 'libcamera_orientation_to_spa_transform_value(impl->config->orientation)' not in result
print('PASS exact Resolute SPA orientation patch and LF format')
