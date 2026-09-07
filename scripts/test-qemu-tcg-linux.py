#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded RAM-only Linux shell boot. Never attaches host storage/network."""
import argparse
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel', required=True, type=Path)
p.add_argument('--initrd', required=True, type=Path)
p.add_argument('--log', required=True, type=Path)
p.add_argument('--qemu', default='qemu-system-aarch64')
p.add_argument('--timeout', type=int, default=120)
a = p.parse_args()
if not 1 <= a.timeout <= 3600:
    p.error('--timeout must be between 1 and 3600 seconds')
for f in (a.kernel, a.initrd):
    if not f.is_file():
        p.error(f'not a file: {f}')
cmd = [a.qemu, '-machine', 'virt,gic-version=3', '-accel', 'tcg,thread=multi',
       '-cpu', 'max', '-m', '512M', '-smp', '1', '-display', 'none',
       '-serial', 'stdio', '-monitor', 'none', '-nic', 'none', '-no-reboot',
       '-kernel', str(a.kernel), '-initrd', str(a.initrd),
       '-append', 'console=ttyAMA0 earlycon=pl011,mmio32,0x9000000 rdinit=/bin/sh nokaslr panic=1']
print('TCG only; no host disk, network, or hardware passthrough', flush=True)
print('Command:', ' '.join(cmd), flush=True)
start = time.monotonic()
output = bytearray()
sent = False
timed_out = False
output_limit = False
with a.log.open('xb') as log:
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic()-start > a.timeout:
                timed_out = True
                proc.terminate()
                break
            for key, _ in selector.select(timeout=0.5):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                log.write(chunk)
                log.flush()
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                if len(output) > 16 * 1024 * 1024:
                    output_limit = True
                    proc.terminate()
                    selector.unregister(key.fileobj)
                    break
                if not sent and (b'job control turned off' in output or b'/ # ' in output or
                                 b"Enter 'help' for a list of built-in commands." in output):
                    proc.stdin.write(b"echo GUEST_SHELL_READY; uname -m; mkdir -p /proc && mount -t proc proc /proc && cat /proc/version && echo GUEST_PROBE_COMPLETE; /usr/bin/poweroff\n")
                    proc.stdin.flush()
                    sent = True
    finally:
        selector.close()
        try:
            rc = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.wait()
        proc.stdin.close()
        proc.stdout.close()
    elapsed = time.monotonic()-start
    # Exclude command echoes: markers must appear as standalone guest output.
    lines = [line.strip() for line in output.decode(errors='replace').splitlines()]
    passed = not timed_out and not output_limit and rc == 0 and all(x in lines for x in (
        'GUEST_SHELL_READY', 'aarch64', 'GUEST_PROBE_COMPLETE')) and 'reboot: Power down' in output.decode(errors='replace')
    result = f'\nTCG_SHELL_PASS={passed} QEMU_RC={rc} TIMEOUT={timed_out} OUTPUT_LIMIT={output_limit} elapsed={elapsed:.2f}s\n'
    log.write(result.encode())
    print(result, flush=True)
sys.exit(0 if passed else 1)
