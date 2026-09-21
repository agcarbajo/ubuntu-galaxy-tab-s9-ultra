import os
from pathlib import Path
import time

ACTIVE = Path('/run/gts9u-fingerprint/active')
REQUEST = Path('/run/gts9u-fingerprint/light')
PRESENTED = Path('/run/gts9u-fingerprint-ui/presented')
MODE = Path('/sys/class/backlight/ae94000.dsi.0/fod_mode')


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
    main()
