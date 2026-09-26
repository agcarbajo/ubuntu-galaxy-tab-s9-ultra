#!/usr/bin/env python3
"""Resolve a persistent PM trace device hash against the current sysfs tree."""

import argparse
import os
from pathlib import Path


def hash_name(name: str) -> int:
    value = 2166136261
    for byte in name.encode("utf-8"):
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value & 0x7FFFFFFF


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hash", type=lambda value: int(value, 0))
    parser.add_argument("--sysfs", type=Path, default=Path("/sys/devices"))
    args = parser.parse_args()
    target = args.hash & 0x7FFFFFFF
    found = False
    for root, dirs, _ in os.walk(args.sysfs):
        for name in dirs:
            if hash_name(name) == target:
                print(Path(root) / name)
                found = True
    if not found:
        parser.exit(1, f"no current sysfs device matches 0x{target:08x}\n")


if __name__ == "__main__":
    main()
