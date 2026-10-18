#!/usr/bin/python3
"""Test powered-off time and reset rejection without touching the system clock."""
from pathlib import Path
import runpy

source = Path(__file__).resolve().parents[1] / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-rtc-time'
restore = runpy.run_path(str(source))['restore_value']
anchor = {'counter': 123456, 'utc': 1792320000}
assert restore(anchor, 123456 + 7200) == anchor['utc'] + 7200
for counter in (0, 123455, 123456 + 11 * 366 * 86400):
    try:
        restore(anchor, counter)
        raise AssertionError('Reset or implausible counter accepted')
    except ValueError:
        pass
print('PASS elapsed powered-off time, counter reset and implausible elapsed time')
