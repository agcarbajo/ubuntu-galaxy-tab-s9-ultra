#!/usr/bin/env python3
"""Extract a trusted published image into a disposable migration baseline."""
import argparse
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"))
from tab_companion import update_bundle as bundle


def prepare(archive, expected_hash, output):
    archive = archive.resolve(strict=True)
    output = output.resolve()
    if output.exists() or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(output)):
        raise ValueError("Choose a new absolute Linux fixture path without spaces")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or bundle.sha256(archive) != expected_hash:
        raise ValueError("The baseline ZIP does not match the trusted published digest")
    manifest = bundle.inspect(archive)
    if manifest["suite"] != "noble" or manifest["version"] != "1.3.0":
        raise ValueError("The migration baseline must be the published Noble port 1.3.0")
    with zipfile.ZipFile(archive) as source:
        entry = source.getinfo("rootfs.img")
        if (not 0 < entry.file_size <= 32 * 1024**3 or
                stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
            raise ValueError("Invalid baseline root filesystem image")
        output.mkdir(parents=True)
        image = output / "rootfs.img"
        with source.open(entry) as original, image.open("xb") as target:
            shutil.copyfileobj(original, target, 4 * 1024**2)
    root = output / "root"
    root.mkdir()
    subprocess.run(["debugfs", "-R", "rdump / " + str(root), str(image)],
                   check=True, capture_output=True, text=True)
    release = (root / "etc/os-release").read_text()
    if not re.search(r'^ID=ubuntu$', release, re.M) or not re.search(
            r'^VERSION_ID="24\.04"$', release, re.M):
        raise ValueError("Extracted baseline is not Ubuntu 24.04")
    identity = json.loads((root / "usr/lib/gts9u-release.json").read_text())
    if identity.get("version") != "1.3.0" or identity.get("device") != "gts9uwifi":
        raise ValueError("Extracted baseline port identity does not match the ZIP")
    if not (root / "var/lib/dpkg/status").is_file():
        raise ValueError("Extracted baseline has no package database")
    (output / "provenance.json").write_text(json.dumps({
        "zip_sha256": expected_hash, "version": manifest["version"],
        "suite": manifest["suite"], "purpose": "disposable-migration-fixture",
        "tablet_data": False,
    }, indent=2) + "\n")
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = prepare(args.zip, args.sha256, args.output)
    print("Published 1.3.0 migration fixture:", root)
    print("No installed system was changed; this is not an update payload.")


if __name__ == "__main__":
    main()
