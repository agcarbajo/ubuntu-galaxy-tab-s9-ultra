#!/usr/bin/env python3
"""Package the UFS repartitioner as a TWRP ZIP.

The archive carries no images at all: the whole payload is the installer plus
one number, the share of `userdata` that stays with Android.  That number is
baked in at build time rather than asked for on the tablet, because TWRP has no
way to prompt and a split is not something to get wrong by a stray tap.

Every ZIP member uses a fixed timestamp, so two builds of identical inputs
produce a byte-identical archive.  This script does not flash anything.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import stat
import zipfile
from pathlib import Path


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


def add_file(zf: zipfile.ZipFile, source: Path, arcname: str, mode: int) -> None:
    with source.open("rb") as src, zf.open(zip_info(arcname, mode), "w") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--project", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--android-percent",
        type=int,
        default=50,
        help="share of the current userdata left to Android (default 50)",
    )
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    # The same bounds the installer enforces on the tablet.  Checking here as
    # well means a bad number is caught by the person building the ZIP rather
    # than by somebody standing in front of a recovery screen.
    if not 5 <= args.android_percent <= 95:
        raise SystemExit("--android-percent must be between 5 and 95")

    update_binary = args.project / "configs/twrp/repartition-update-binary"
    updater_script = args.project / "configs/twrp/updater-script"
    if not update_binary.is_file() or not updater_script.is_file():
        raise SystemExit("TWRP installer sources are missing")

    contract = (
        "# GTS9U-REPARTITION-CONTRACT: rewrites gpt entries 34 and 35 "
        "and formats userdata and metadata only"
    )
    text = update_binary.read_text(encoding="utf-8")
    if contract not in text.splitlines():
        raise SystemExit("the repartitioner does not carry its contract line")

    linux_percent = 100 - args.android_percent
    label = args.label or (
        f"SM-X910 UFS split: {args.android_percent}% Android / "
        f"{linux_percent}% Linux"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zf:
        add_file(
            zf, update_binary, "META-INF/com/google/android/update-binary", 0o755
        )
        add_file(
            zf, updater_script, "META-INF/com/google/android/updater-script", 0o644
        )
        zf.writestr(zip_info("BUNDLE-LABEL"), label + "\n")
        zf.writestr(zip_info("ANDROID-PERCENT"), f"{args.android_percent}\n")
        zf.writestr(
            zip_info("SHA256SUMS"),
            f"{digest(update_binary)}  update-binary\n",
        )

    print(f"{digest(args.output)}  {args.output.name}")


if __name__ == "__main__":
    main()
