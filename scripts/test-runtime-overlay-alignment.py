#!/usr/bin/python3
"""libfdt rejects an unaligned embedded blob even when fdtoverlay accepts it."""
import argparse
import subprocess
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--vmlinux', required=True)
args = parser.parse_args()
symbols = subprocess.check_output(['nm', '-n', args.vmlinux], text=True)
for name in ('gts9u_performance_overlay', 'gts9u_displayport_audio_overlay'):
    rows = [line.split() for line in symbols.splitlines() if line.endswith(' ' + name)]
    assert len(rows) == 1, 'Missing embedded overlay: ' + name
    assert int(rows[0][0], 16) % 8 == 0, 'libfdt would reject an unaligned overlay: ' + name
print('PASS actual linked overlay addresses meet libfdt 8-byte alignment')
