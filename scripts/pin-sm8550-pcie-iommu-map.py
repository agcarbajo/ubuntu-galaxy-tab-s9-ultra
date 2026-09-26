#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Keep the ABL-facing SM8550 PCIe map identical to the booted board DTB.

Linux 7.2.8 corrected two iommu-map entries in sm8550.dtsi. The resulting
DTB changes shape even though the board DTS is pinned. Samsung ABL has
rejected other structural DTB changes before Linux starts; a new mapping
must be tested separately instead of silently entering the release image.
"""
import argparse
from pathlib import Path


def pin(path: Path) -> str:
    data = path.read_text()
    changed = 0
    for stream in ("1400", "1401", "1480", "1481"):
        old = f"&apps_smmu 0x{stream} 0x1>"
        new = f"&apps_smmu 0x{stream} 0x0 0x1>"
        old_count, new_count = data.count(old), data.count(new)
        if (old_count, new_count) == (0, 1):
            data = data.replace(new, old)
            changed += 1
        elif (old_count, new_count) != (1, 0):
            raise ValueError(f"unexpected PCIe iommu-map entry for {stream}")
    if changed not in (0, 4):
        raise ValueError("mixed SM8550 PCIe iommu-map layouts")
    if changed:
        path.write_text(data)
    return "restored booted PCIe iommu-map" if changed else "booted PCIe iommu-map already present"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dtsi", type=Path)
    args = parser.parse_args()
    print(pin(args.dtsi))


if __name__ == "__main__":
    main()
