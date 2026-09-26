#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check current desktop patches against exact Ubuntu 26.04 source packages."""
import argparse
import subprocess
import urllib.request
from pathlib import Path


SOURCES = (
    ("gnome-settings-daemon", "50.0", "50.0-1ubuntu1",
     "https://ports.ubuntu.com/ubuntu-ports/pool/main/g/gnome-settings-daemon/",
     "packaging/gnome-settings-daemon/skip-unchanged-ambient-brightness.patch"),
    ("mutter", "50.1", "50.1-0ubuntu2.4",
     "https://ports.ubuntu.com/ubuntu-ports/pool/main/m/mutter/",
     "packaging/mutter/preserve-crtc-plane-assignments.patch"),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name, upstream, version, url, relative_patch in SOURCES:
        directory = workdir / name
        directory.mkdir(exist_ok=True)
        files = [f"{name}_{upstream}.orig.tar.xz",
                 f"{name}_{version}.debian.tar.xz", f"{name}_{version}.dsc"]
        for filename in files:
            target = directory / filename
            if not target.is_file():
                with urllib.request.urlopen(url + filename, timeout=60) as response:
                    target.write_bytes(response.read())
        tree = directory / "tree"
        if not tree.exists():
            subprocess.run(["dpkg-source", "-x", str(directory / files[-1]), str(tree)],
                           check=True)
        result = subprocess.run(["patch", "--dry-run", "--batch", "--fuzz=0", "-p1"],
                                cwd=tree, input=(repo / relative_patch).read_bytes(),
                                capture_output=True)
        print(name, version, "patch clean" if result.returncode == 0 else "patch needs rebase")
        if result.returncode:
            failures += 1
            print(result.stdout.decode(errors="replace")[-2000:])
            print(result.stderr.decode(errors="replace")[-2000:])
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
