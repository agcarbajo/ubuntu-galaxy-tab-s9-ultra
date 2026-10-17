#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the safe-update contract and every payload byte before publishing."""
import hashlib
import os
from pathlib import Path
import sys
import zipfile

os.environ.setdefault("GALAXY_COMPANION_DEVICE", "gts9uwifi")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "external/galaxy-companion/packaging/galaxy-companion/usr/lib/galaxy-companion"))
from galaxy_companion.update_bundle import inspect


def validate(path):
    manifest = inspect(path)
    with zipfile.ZipFile(path) as archive:
        for name, entry in manifest["files"].items():
            digest = hashlib.sha256()
            with archive.open(name) as source:
                for chunk in iter(lambda: source.read(4 * 1024**2), b""):
                    digest.update(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError("Update payload checksum mismatch: " + name)
    print("PASS update payload", manifest["tag"])


if __name__ == "__main__":
    validate(sys.argv[1])
