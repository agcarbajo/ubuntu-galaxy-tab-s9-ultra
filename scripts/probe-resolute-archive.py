#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Simulate the current desktop package list in an isolated Resolute root."""
import argparse
import re
import subprocess
from pathlib import Path


def package_names(build_script):
    source = build_script.read_text()
    names = []
    for variable in ("base_packages", "desktop_packages"):
        match = re.search(r"^" + variable + r"='([^']*)'", source, re.M | re.S)
        if not match:
            raise ValueError("Cannot find " + variable)
        names.extend(part.strip() for part in match.group(1).split(",") if part.strip())
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True,
                        help="isolated arm64 Resolute mmdebstrap directory")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if root == Path("/") or root == Path("/root"):
        parser.error("refusing a host filesystem root")
    release = (root / "etc/os-release").read_text()
    if not re.search(r'^ID=ubuntu$', release, re.M) or not re.search(
            r'^VERSION_ID="26\.04"$', release, re.M):
        parser.error("target is not Ubuntu 26.04")
    script = Path(__file__).resolve().parent / "build-ubuntu-rootfs.sh"
    packages = package_names(script)
    result = subprocess.run(
        ["chroot", str(root), "apt-get", "-s", "-o", "APT::Install-Recommends=false",
         "install", *packages], text=True, capture_output=True)
    print("Requested packages:", len(packages))
    print("Exit status:", result.returncode)
    installed = [line for line in result.stdout.splitlines() if line.startswith("Inst ")]
    print("Resolved archive installs:", len(installed))
    selected = {"gnome-shell", "mutter", "gnome-settings-daemon", "libfprint-2-2",
                "libfprint-2-tod1", "gir1.2-mutter-18", "ubuntu-desktop-minimal"}
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith(("Remv ", "E: ", "W: ")) or (
                line.startswith("Inst ") and line.split()[1] in selected):
            print(line)
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
