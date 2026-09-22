import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def connected_outputs(root=Path('/sys/class/drm')):
    return [path for path in sorted(root.iterdir())
            if ('-DP-' in path.name or '-HDMI-' in path.name) and
            (path / 'status').read_text().strip() == 'connected']


def snapshot():
    connectors = {}
    for path in sorted(Path('/sys/class/drm').glob('card*-*')):
        if (path / 'status').exists():
            connectors[path.name] = {name: (path / name).read_text().strip()
                                     for name in ('status', 'modes', 'enabled') if (path / name).exists()}
    print(json.dumps(connectors, indent=2), flush=True)
    for state in sorted(Path('/sys/kernel/debug/dri').glob('*/state')):
        print(str(state), flush=True)
        print(state.read_text(), flush=True)


def terminate(_signum, _frame):
    raise SystemExit(143)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180:
        parser.error('--seconds must be between 1 and 180')
    if not connected_outputs():
        print('SKIP: connect the external monitor and adapter before capturing a modeset.')
        return 77
    if os.geteuid() != 0:
        parser.error('root is required to temporarily enable DRM atomic diagnostics')
    debug = Path('/sys/module/drm/parameters/debug')
    original = debug.read_text()
    start = int(time.time())
    snapshot()
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        debug.write_text(f'{int(original.strip(), 0) | 0x114}\n')
        print(f'Change one external-display setting now. Capturing for {args.seconds} seconds.', flush=True)
        time.sleep(args.seconds)
        snapshot()
    finally:
        debug.write_text(original)
        signal.signal(signal.SIGTERM, previous)
        subprocess.run(['journalctl', '-b', '_TRANSPORT=kernel', '--no-pager',
                        f'--since=@{start}', '-g', 'drm|dpu|msm_dp|smmu'], check=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
