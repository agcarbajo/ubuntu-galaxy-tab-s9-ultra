#!/usr/bin/python3
"""Powered-off time, and what happens when the PMIC counter restarts.

The counter is monotonic across Android and Ubuntu, so the anchor plus its
advance is the real time.  When it restarts -- a battery pull, a PMIC reset,
or one of the forced restarts this board needs after a storage resume failure
-- there is no advance to add.  Refusing to set any time at all put the tablet
in 1970 until a network arrived, which is how "sometimes it has the right time
and sometimes it does not" looks from the outside, and in 1970 nothing with a
certificate works.  The last known time is wrong by the time the tablet was
off instead, which is the smaller of the two wrongs.

Nothing here touches the system clock.
"""
from pathlib import Path
import runpy

source = Path(__file__).resolve().parents[1] / 'packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-rtc-time'
restore = runpy.run_path(str(source))['restore_value']
anchor = {'counter': 123456, 'utc': 1792320000}

value, how = restore(anchor, 123456 + 7200)
assert (value, how) == (anchor['utc'] + 7200, 'counter'), (value, how)

# A counter that restarted, and one that claims eleven years of sleep.
for counter in (0, 1, 123455, 123456 + 11 * 366 * 86400):
    value, how = restore(anchor, counter)
    assert how == 'anchor', (counter, how)
    assert value == anchor['utc'], (counter, value)
    assert value > 1735689600, 'the fallback must still be a plausible date'

# Ten years of powered-off time is still taken from the counter.
value, how = restore(anchor, 123456 + 10 * 366 * 86400)
assert how == 'counter' and value > anchor['utc']

# An anchor that was never trustworthy is still refused: a wrong time the
# tablet invented is worse than no time at all.
for bad in ({'counter': 1, 'utc': 0}, {'counter': 1, 'utc': 1700000000}):
    try:
        restore(bad, 2)
        raise AssertionError('an untrusted anchor was accepted')
    except ValueError:
        pass

print('PASS elapsed powered-off time, counter restart falls back to the last '
      'known UTC, and an untrusted anchor is still refused')
