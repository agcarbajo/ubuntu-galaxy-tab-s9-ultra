#!/usr/bin/env python3
"""Package a validated five-image bundle as a manual TWRP ZIP.

Derived from scripts/make-twrp-zip.py of the postmarketOS gts9uwifi port
(MIT). Differences: the Ubuntu installer is used, and an optional unit
activation manifest is packaged so systemd units in the overlay can be
enabled with a real symlink rather than a copied file.

Every ZIP member uses a fixed timestamp, so two builds of identical inputs
produce a byte-identical archive. This script does not flash anything.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import stat
import zipfile
from pathlib import Path


IMAGES = {
    "boot.img": 100663296,
    "init_boot.img": 8388608,
    "vendor_boot.img": 100663296,
    "dtbo.img": 16777216,
    "vbmeta.img": 131072,
}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def zip_info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def add_file(
    zf: zipfile.ZipFile,
    source: Path,
    arcname: str,
    mode: int = 0o644,
) -> None:
    with source.open("rb") as src, zf.open(
        zip_info(arcname, mode), "w", force_zip64=True
    ) as dst:
        shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--project", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--rootfs-overlay",
        type=Path,
        help="directory whose regular files are installed into the microSD rootfs",
    )
    parser.add_argument(
        "--enable-unit",
        action="append",
        default=[],
        metavar="TARGET:UNIT",
        help="enable UNIT in TARGET.wants on the microSD rootfs, e.g. "
        "multi-user.target:ubuntu-gts9u-panel-recover.service",
    )
    parser.add_argument(
        "--label",
        default="Ubuntu 24.04 for SM-X910",
    )
    args = parser.parse_args()

    for name, expected_size in IMAGES.items():
        path = args.bundle / name
        if not path.is_file():
            raise SystemExit(f"missing {path}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise SystemExit(f"{name}: expected {expected_size}, got {actual_size}")

    update_binary = args.project / "configs/twrp/ubuntu-update-binary"
    updater_script = args.project / "configs/twrp/updater-script"
    if not update_binary.is_file() or not updater_script.is_file():
        raise SystemExit("TWRP installer sources are missing")

    enable_lines = []
    for spec in args.enable_unit:
        target, _, unit = spec.partition(":")
        if not target or not unit:
            raise SystemExit(f"malformed --enable-unit: {spec}")
        if "/" in target or "/" in unit or ".." in target or ".." in unit:
            raise SystemExit(f"unsafe --enable-unit: {spec}")
        enable_lines.append(f"{target} {unit}\n")

    manifest = "".join(
        f"{digest(args.bundle / name)}  {name}\n" for name in IMAGES
    )

    overlay_files: list[Path] = []
    overlay_manifest = ""
    if args.rootfs_overlay is not None:
        if not args.rootfs_overlay.is_dir():
            raise SystemExit(
                f"rootfs overlay is not a directory: {args.rootfs_overlay}"
            )
        overlay_files = sorted(
            path for path in args.rootfs_overlay.rglob("*") if path.is_file()
        )
        if not overlay_files:
            raise SystemExit("rootfs overlay contains no regular files")
        overlay_manifest = "".join(
            f"{digest(path)} {stat.S_IMODE(path.stat().st_mode):04o} "
            f"{path.relative_to(args.rootfs_overlay).as_posix()}\n"
            for path in overlay_files
        )
    elif enable_lines:
        raise SystemExit("--enable-unit needs --rootfs-overlay")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zf:
        for name in IMAGES:
            add_file(zf, args.bundle / name, name)
        add_file(
            zf, update_binary, "META-INF/com/google/android/update-binary", 0o755
        )
        add_file(zf, updater_script, "META-INF/com/google/android/updater-script")
        zf.writestr(zip_info("BUNDLE-LABEL"), args.label + "\n")
        zf.writestr(zip_info("SHA256SUMS"), manifest)
        if overlay_files:
            for path in overlay_files:
                relative = path.relative_to(args.rootfs_overlay).as_posix()
                mode = stat.S_IMODE(path.stat().st_mode)
                add_file(zf, path, f"rootfs-overlay/{relative}", mode)
            zf.writestr(zip_info("ROOTFS-OVERLAY-SHA256SUMS"), overlay_manifest)
            if enable_lines:
                zf.writestr(zip_info("ROOTFS-OVERLAY-ENABLE"), "".join(enable_lines))

    print(f"{digest(args.output)}  {args.output.name}")


if __name__ == "__main__":
    main()
