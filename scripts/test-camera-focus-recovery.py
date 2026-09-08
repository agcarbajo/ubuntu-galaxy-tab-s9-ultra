#!/usr/bin/env python3
"""Private staged capture with one bounded lens perturbation; no live install.

This checks recovery from optical defocus, not tracking of a moving scene.
The perturbation uses the normal V4L2 lens control, only after our capture has
delivered 240 frames. No images are saved. Run with camera applications closed.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--stage', type=Path, required=True)
args = p.parse_args()
stage = args.stage.resolve(strict=True)
assert Path('/sys/class/video4linux/v4l-subdev33/name').read_text().strip() == 'dw9808-vcm 2-000c'
lens = '/dev/v4l-subdev33'

def read_lens():
    r = subprocess.run(['v4l2-ctl', '-d', lens, '--get-ctrl', 'focus_absolute'],
                       capture_output=True, text=True, check=True)
    return int(r.stdout.split(':')[1])

def set_lens(value):
    subprocess.run(['v4l2-ctl', '-d', lens, '--set-ctrl', f'focus_absolute={value}'], check=True)

env = os.environ.copy()
env.update(LD_LIBRARY_PATH=str(stage/'usr/lib/aarch64-linux-gnu'),
           LIBCAMERA_IPA_MODULE_PATH=str(stage/'usr/lib/aarch64-linux-gnu/libcamera/ipa'),
           LIBCAMERA_IPA_PROXY_PATH=str(stage/'usr/libexec/libcamera'),
           LIBCAMERA_SOFTISP_MODE='gpu')
proc = subprocess.Popen(['timeout', '--kill-after=3', '30', str(stage/'usr/bin/cam'),
                         '-c', '3', '-s', 'width=640,height=480,pixelformat=XRGB8888',
                         '--strict-formats', '--metadata', '--capture=600'],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
frame = -1
previous = None
state = None
initial = None
perturbed = False
recovered = False
recovery_scan = False
started = time.monotonic()
try:
    for line in proc.stdout:
        match = re.search(r'seq:\s*(\d+)', line)
        if match:
            frame = int(match[1])
            if frame == 240:
                assert state == 2, 'Initial optical focus was not acquired; do not perturb the lens'
                initial = read_lens()
                target = initial + 256 if initial <= 767 else initial - 256
                set_lens(target)
                perturbed = True
                print(f'Perturbation at frame {frame}: {initial} -> {target}', flush=True)
        if 'AfState =' in line:
            state = int(line.split('=')[1])
            if perturbed and state == 1:
                recovery_scan = True
            if perturbed and recovery_scan and state == 2 and abs(read_lens()-initial) <= 96:
                recovered = True
            if state != previous:
                print(f'frame={frame} t={time.monotonic()-started:.2f} AfState={state} lens={read_lens()}', flush=True)
                previous = state
    rc = proc.wait()
    assert rc == 0 and frame == 599, f'Capture incomplete: rc={rc}, frame={frame}'
    assert perturbed and recovered, 'No confirmed focus recovery after perturbation'
    print('PASS: physical lens defocused and reacquired during staged capture')
finally:
    if proc.poll() is None:
        if perturbed:
            set_lens(initial)
        proc.terminate()
        proc.wait(timeout=5)
