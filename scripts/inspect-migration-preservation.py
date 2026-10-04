#!/usr/bin/env python3
"""Report changed protected paths in a disposable fixture without printing data."""
import argparse
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'packaging/ubuntu-gts9u-companion/usr/lib/tab-companion'))
from tab_companion import migration_plan as plans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--restore-compatibility', action='store_true')
    args = parser.parse_args()
    source = args.fixture.resolve(strict=True) / 'source'
    if source == Path('/') or not (source / '.gts9u-root/slots').is_dir():
        parser.error('Use a previously created disposable migration fixture')
    baseline = plans.preservation_inventory(source)
    for slot in sorted((source / '.gts9u-root/slots').iterdir()):
        root = slot / 'root'
        if not root.is_dir():
            continue
        print('Inactive slot:', slot.name)
        if args.restore_compatibility:
            plans.restore_compatibility_files(source, root)
        target = plans.preservation_inventory(root)
        for name in sorted(baseline.keys() | target.keys()):
            old, new = baseline.get(name), target.get(name)
            if old == new:
                continue
            print(name, 'source_missing=' + str(old is None), 'target_missing=' + str(new is None),
                  'attributes_changed=' + str(old is not None and new is not None and old[:3] != new[:3]),
                  'contents_changed=' + str(old is not None and new is not None and old[3] != new[3]))
        print('Account identity equal:', plans.account_identity(source) == plans.account_identity(root))


if __name__ == '__main__':
    main()
