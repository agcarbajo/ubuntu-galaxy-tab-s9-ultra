#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build an archive-only GNOME 50 arm64 root for offline compatibility work.

This diagnostic root deliberately excludes all port packages and is not a
flashable image or an update payload.
"""
import argparse
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists; select a new isolated directory")
    source = (Path(__file__).resolve().parent / "build-ubuntu-rootfs.sh").read_text()
    packages = []
    for variable in ("base_packages", "desktop_packages"):
        match = re.search(r"^" + variable + r"='([^']*)'", source, re.M | re.S)
        if not match:
            parser.error("package list missing: " + variable)
        packages.extend(value.strip() for value in match.group(1).split(",")
                        if value.strip())
    print("Archive package requests:", len(packages), flush=True)
    mirror = "http://ports.ubuntu.com/ubuntu-ports"
    subprocess.run([
        "mmdebstrap", "--architecture=arm64", "--variant=important",
        "--components=main,restricted,universe,multiverse",
        "--include=" + ",".join(packages),
        "resolute", str(output),
        f"deb {mirror} resolute main restricted universe multiverse",
        f"deb {mirror} resolute-updates main restricted universe multiverse",
        f"deb {mirror} resolute-security main restricted universe multiverse",
    ], check=True)
    subprocess.run(["chroot", str(output), "dpkg", "--audit"], check=True)
    subprocess.run(["chroot", str(output), "apt-get", "check"], check=True)
    print("Archive-only Resolute desktop root built:", output)


if __name__ == "__main__":
    main()
