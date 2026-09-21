#!/usr/bin/env python3
import re
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
crtc_original = Path(sys.argv[1]).read_text()
atomic_original = Path(sys.argv[2]).read_text()


def function(source, name):
    match = re.search(rf'^(?:static )?[^\n]+\b{name}\([^;]*\)\n\{{', source, re.M)
    assert match, f'{name} not found'
    start = match.start()
    brace = source.index('{', match.start())
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f'{name} is incomplete')


with tempfile.TemporaryDirectory(prefix='gts9u-dpu-test-') as tmp:
    tree = Path(tmp)
    crtc = tree / 'drivers/gpu/drm/msm/disp/dpu1/dpu_crtc.c'
    atomic = tree / 'drivers/gpu/drm/msm/msm_atomic.c'
    crtc.parent.mkdir(parents=True)
    atomic.parent.mkdir(parents=True, exist_ok=True)
    crtc.write_text(crtc_original)
    atomic.write_text(atomic_original)
    patch = repo / 'kernel/patches/msm-dpu-reassign-resources-with-encoder.patch'
    subprocess.run(['patch', '--batch', '--fuzz=0', '-d', tmp, '-p1'],
                   input=patch.read_text(), text=True, check=True)
    crtc_source = crtc.read_text()
    atomic_source = atomic.read_text()

needs = function(crtc_source, 'dpu_crtc_needs_dspp')
assert 'crtc_state->ctm || crtc_state->gamma_lut' in needs
has = function(crtc_source, 'dpu_crtc_has_dspp')
assert '!cstate->num_mixers' in has
assert '!cstate->mixers[i].hw_dspp' in has
mode = function(crtc_source, 'dpu_crtc_check_mode_changed')
assert 'dpu_crtc_needs_dspp(new_crtc_state)' in mode
assert '!dpu_crtc_has_dspp(old_crtc_state)' in mode
assert 'new_crtc_state->mode_changed = true' in mode
check = function(crtc_source, 'dpu_crtc_atomic_check')
reservation = check[:check.index('dpu_crtc_assign_resources')]
assert 'crtc_state->mode_changed || crtc_state->connectors_changed' in reservation
assert 'color_mgmt_changed' not in reservation
msm = function(atomic_source, 'msm_atomic_check')
assert 'allow_modeset' not in msm
assert 'for_each_oldnew_crtc_in_state' not in msm
print('PASS: colour-only updates retain resources; new DSPP use requests a modeset')
