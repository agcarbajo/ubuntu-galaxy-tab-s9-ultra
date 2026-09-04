#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the non-destructive payload alongside the full installation image."""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipapp
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--bootstrap", type=Path, required=True)
    a = p.parse_args()
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+~]*", a.version):
        p.error("version must be a Debian-compatible release number without a leading v")
    repo = Path(__file__).resolve().parents[1]
    out = a.base / "out/update-payload"
    if out.exists():
        shutil.rmtree(out)
    debs = out / "debs"
    debs.mkdir(parents=True)
    rootfs = a.base / "rootfs"
    kernel = a.base / "out/kernel-gts9uwifi"
    kernel_release = (kernel / "kernel.release").read_text().strip()
    # local-debs is the exact selection installed in this build, not a directory
    # of stale packages from previous releases.
    for source in (a.base / "out/local-debs").glob("*.deb"):
        fields = subprocess.check_output(["dpkg-deb", "-f", str(source), "Package", "Version"], text=True)
        values = dict(line.split(": ", 1) for line in fields.splitlines())
        installed = subprocess.check_output(["chroot", str(rootfs), "dpkg-query", "-W",
                                            "-f", "${Version}", values["Package"]], text=True)
        if installed != values["Version"]:
            raise SystemExit("Stale local package: " + source.name)
        shutil.copyfile(source, debs / source.name)
    with tempfile.TemporaryDirectory(dir=a.base / "out") as tmp:
        stage = Path(tmp)
        shutil.copytree(a.base / "out/rootfs-overlay", stage, dirs_exist_ok=True, symlinks=True)
        boot = stage / "boot"
        boot.mkdir()
        for file in (rootfs / "boot").iterdir():
            if file.is_file() and not file.is_symlink():
                shutil.copy2(file, boot / file.name)
        shutil.copy2(kernel / "sm8550-samsung-gts9uwifi.dtb", boot)
        # Fresh-image settings must use conffile semantics on existing systems.
        # Machine identity, accounts, locales, passwords and home never enter
        # this package. More port defaults belong in the device package.
        for name in ("etc/netplan/01-network-manager-all.yaml",
                     "etc/ssh/sshd_config.d/10-gts9uwifi.conf",
                     "etc/systemd/journald.conf.d/10-gts9uwifi-persistent.conf",
                     "etc/apt/preferences.d/no-distro-kernel"):
            src = rootfs / name
            if src.exists():
                (stage / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, stage / name)
        control = stage / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            "Package: ubuntu-gts9u-hardware\nVersion: " + a.version +
            "\nArchitecture: arm64\nMaintainer: Ubuntu gts9uwifi port contributors <noreply@example.invalid>\n"
            "Description: Firmware, modules and boot files matching the SM-X910 release\n")
        (control / "conffiles").write_text("".join(
            "/" + f.relative_to(stage).as_posix() + "\n" for f in sorted((stage / "etc").rglob("*"))
            if f.is_file() and not f.is_symlink()))
        # The SPSS module is owned by ubuntu-gts9u-device, never duplicate it.
        for file in (stage / "usr/lib/modules").rglob("qcom_spss_irq.ko"):
            file.unlink()
        for file in sorted(stage.rglob("*"), reverse=True):
            os.utime(file, (0, 0), follow_symlinks=False)
        os.utime(stage, (0, 0))
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage),
                        str(debs / ("ubuntu-gts9u-hardware_" + a.version + "_arm64.deb"))], check=True)
    identity = {"device": "gts9uwifi", "version": a.version, "tag": "v" + a.version,
                "kernel_release": kernel_release}
    (rootfs / "usr/lib/gts9u-release.json").write_text(json.dumps(identity) + "\n")
    # Generated from the same rootfs input list; do not copy dpkg's database or
    # reinstall every application the image happened to pull in as a dependency.
    required = (rootfs / "usr/lib/gts9u-required-packages.txt").read_text().split()
    (out / "metadata.json").write_text(json.dumps({**identity, "format": 1,
        "architecture": "arm64", "suite": "noble", "apt_packages": required}, indent=2) + "\n")
    with tempfile.TemporaryDirectory() as tmp:
        app = Path(tmp)
        package = app / "tab_companion"
        package.mkdir()
        (package / "__init__.py").write_text("")
        source = repo / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion"
        for name in ("update_core.py", "update_bundle.py"):
            shutil.copyfile(source / name, package / name)
        (app / "__main__.py").write_text(
            "from tab_companion.update_core import main\n"
            "import sys\ntry:\n    main()\nexcept Exception as e:\n    print(e, file=sys.stderr)\n    sys.exit(1)\n")
        for file in app.rglob("*"):
            os.utime(file, (315532800, 315532800))
        a.bootstrap.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(app, a.bootstrap, interpreter="/usr/bin/env python3")
    print("Update payload:", out)


if __name__ == "__main__":
    main()
