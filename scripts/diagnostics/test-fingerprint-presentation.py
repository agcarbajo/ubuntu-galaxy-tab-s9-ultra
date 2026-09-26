import os
from pathlib import Path
import sys
import time

ACTIVE = Path('/run/gts9u-fingerprint/active')
REQUEST = Path('/run/gts9u-fingerprint/light')
RELEASE = Path('/run/gts9u-fingerprint/last-release')
PRESENTED = Path('/run/gts9u-fingerprint-ui/presented')
LEASE = Path('/run/gts9u-fingerprint-ui/ready')
MODE = Path('/sys/class/backlight/ae94000.dsi.0/fod_mode')


def observe():
    def read(path):
        try:
            return path.read_text(encoding='ascii')
        except OSError:
            return ''

    start = time.monotonic()
    previous = None
    lit = False
    finished = None
    while time.monotonic() - start < 60:
        parts = read(REQUEST).split()
        token = int(parts[1]) if len(parts) == 2 and parts[0] == 'prepare' and parts[1].isdigit() else 0
        released_parts = read(RELEASE).split()
        releasing = (len(released_parts) == 2 and released_parts[0] == 'release' and
                     released_parts[1].isdigit() and
                     0 <= time.monotonic_ns() // 1000 - int(released_parts[1]) < 1_000_000)
        state = (read(ACTIVE).startswith('active '), read(LEASE).startswith('ready '),
                 bool(token), releasing,
                 bool(token) and read(PRESENTED) == f'ready {token + 1_000_000}\n',
                 read(MODE).strip())
        if state != previous:
            elapsed = (time.monotonic() - start) * 1000
            print(f'{elapsed:.1f} ms active={int(state[0])} ui={int(state[1])} '
                  f'prepare={int(state[2])} release={int(state[3])} '
                  f'presented={int(state[4])} hbm={state[5]}', flush=True)
            previous = state
        lit |= state[5] == '1'
        if lit and not state[2] and state[5] == '0':
            finished = finished or time.monotonic()
        else:
            finished = None
        if finished and time.monotonic() - finished > 2:
            break
        time.sleep(0.01)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root is required for the synthetic display-only request')
    if REQUEST.exists() or MODE.read_text().strip() != '0':
        raise SystemExit('A real illumination operation may be active; refusing to interfere')
    if not ACTIVE.parent.is_dir():
        raise SystemExit('Start fprintd to create its runtime directory first')
    token = time.monotonic_ns() // 1000
    state = f'active {token + 2_000_000}\n'
    request = f'prepare {token}\n'
    expected = f'ready {token + 1_000_000}\n'
    created_active = not ACTIVE.exists()
    try:
        if created_active:
            ACTIVE.write_text(state)
            ACTIVE.chmod(0o644)
        with REQUEST.open('x') as stream:
            stream.write(request)
        REQUEST.chmod(0o644)
        while time.monotonic_ns() // 1000 - token < 950_000:
            if MODE.read_text().strip() != '0':
                raise RuntimeError('HBM became active; stop this display-only test')
            if PRESENTED.exists() and PRESENTED.read_text() == expected:
                delay = (time.monotonic_ns() // 1000 - token) / 1000
                print(f'PASS: Shell/broker acknowledgement after {delay:.1f} ms; HBM remained off')
                return
            time.sleep(0.01)
        raise RuntimeError('The active Shell did not acknowledge the compensation frame')
    finally:
        owned = [(REQUEST, request), (PRESENTED, expected)]
        if created_active:
            owned.append((ACTIVE, state))
        for path, contents in owned:
            if path.exists() and path.read_text() == contents:
                path.unlink()


if __name__ == '__main__':
    if sys.argv[1:] == ['--observe']:
        observe()
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit('usage: test-fingerprint-presentation.py [--observe]')
