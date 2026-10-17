#!/usr/bin/env python3
"""Freeze the release-specific backend and its isolated arm64 APT runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipapp

REPO = Path(__file__).resolve().parents[1]
DEVICE = "gts9uwifi"
# What the backend imports from Galaxy Companion, and what this port adds.
COMPANION_MODULES = ("update_core.py", "update_bundle.py", "update_policy.py", "device.py", "boot_core.py")
BACKEND_MODULES = ("__init__.py", "migration_core.py", "migration_plan.py")


def root_file(root, name):
    path = root / name.lstrip("/")
    for _ in range(64):
        if path.is_symlink():
            destination = Path(path.readlink())
            path = root / str(destination).lstrip("/") if destination.is_absolute() else path.parent / destination
        else:
            resolved = path.resolve()
            if not resolved.is_relative_to(root.resolve()):
                raise ValueError("Runtime library escaped the build root")
            return resolved
    raise ValueError("Runtime symlink loop")


def export_runtime(root, destination):
    if destination.exists():
        raise ValueError("Choose a new runtime output directory")
    destination.mkdir(parents=True)
    programs = {"bin/apt-get": root_file(root, "/usr/bin/apt-get"),
                "bin/apt-cache": root_file(root, "/usr/bin/apt-cache")}
    for file in (root / "usr/lib/apt/methods").iterdir():
        if file.is_file():
            programs["methods-bin/" + file.name] = root_file(root, str(file.relative_to(root)))
    if (root / "usr/bin/sqv").exists():
        programs["bin/sqv"] = root_file(root, "/usr/bin/sqv")
    libraries = {}
    pending = list(programs.values())
    inspected = set()
    while pending:
        file = pending.pop()
        if file in inspected:
            continue
        inspected.add(file)
        header = subprocess.check_output(["readelf", "-h", str(file)], text=True)
        if "AArch64" not in header:
            raise ValueError("The isolated resolver must contain arm64 ELF files")
        dynamic = subprocess.check_output(["readelf", "-d", str(file)], text=True)
        for name in re.findall(r"\(NEEDED\).*\[([^]]+)\]", dynamic):
            if name in libraries:
                continue
            paths = (root / "usr/lib/aarch64-linux-gnu" / name,
                     root / "lib/aarch64-linux-gnu" / name, root / "usr/lib" / name)
            candidate = next((path for path in paths if path.exists()), None)
            if candidate is None:
                raise ValueError("Missing resolver library: " + name)
            libraries[name] = root_file(root, str(candidate.relative_to(root)))
            pending.append(libraries[name])
    loader = root_file(root, "/usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1")
    libraries["ld-linux-aarch64.so.1"] = loader
    for name, source in {**programs, **{"lib/" + name: file for name, file in libraries.items()}}.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755)
    policy = root / "usr/share/apt/default-sequoia.config"
    if policy.is_file():
        shutil.copyfile(policy, destination / "default-sequoia.config")
    files = {file.relative_to(destination).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
             for file in destination.rglob("*") if file.is_file()}
    (destination / "files.json").write_text(json.dumps(files, indent=2) + "\n")
    print("Frozen resolver:", len(files), "files;", sum(file.stat().st_size for file in destination.rglob("*")
                                                      if file.is_file()), "bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-only", action="store_true")
    args = parser.parse_args()
    if not re.search(r'^VERSION_ID="26\.04"$', (args.root / "usr/lib/os-release").read_text(), re.M):
        parser.error("Resolute build root required")
    if args.runtime_only:
        export_runtime(args.root, args.output)
        return
    companion = REPO / "external/galaxy-companion/packaging/galaxy-companion/usr"
    if not (companion / "lib/galaxy-companion/galaxy_companion").is_dir():
        parser.error("Galaxy Companion submodule is not checked out: run git submodule update --init")
    with tempfile.TemporaryDirectory() as temporary:
        app = Path(temporary)
        # Galaxy Companion's updater, frozen at the pinned submodule commit...
        package = app / "galaxy_companion"
        package.mkdir()
        (package / "__init__.py").write_text(
            (companion / "lib/galaxy-companion/galaxy_companion/__init__.py").read_text())
        for name in COMPANION_MODULES:
            shutil.copyfile(companion / "lib/galaxy-companion/galaxy_companion" / name, package / name)
        # ...this port's backend on top of it...
        backend = app / "gts9u_migration"
        backend.mkdir()
        for name in BACKEND_MODULES:
            shutil.copyfile(REPO / "packaging/gts9u-migration/gts9u_migration" / name, backend / name)
        # ...and the device profile, which the modules read at import time.
        (app / "devices").mkdir()
        profile = companion / "share/galaxy-companion/devices" / (DEVICE + ".json")
        shutil.copyfile(profile, app / "devices" / profile.name)
        (app / "__main__.py").write_text(
            "import os, sys, tempfile, zipfile\n"
            "_profiles = tempfile.mkdtemp(prefix='galaxy-companion-profile-')\n"
            "with zipfile.ZipFile(sys.argv[0]) as _archive:\n"
            "    for _name in _archive.namelist():\n"
            "        if _name.startswith('devices/') and _name.endswith('.json'):\n"
            "            with open(os.path.join(_profiles, os.path.basename(_name)), 'wb') as _out:\n"
            "                _out.write(_archive.read(_name))\n"
            "os.environ['GALAXY_COMPANION_DEVICES_DIR'] = _profiles\n"
            "os.environ['GALAXY_COMPANION_DEVICE'] = '" + DEVICE + "'\n"
            "from gts9u_migration.migration_core import main\nmain()\n")
        export_runtime(args.root, app / "resources/apt")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(app, args.output, interpreter="/usr/bin/python3", compressed=True)
        if args.output.stat().st_size > 32 * 1024**2:
            raise ValueError("Backend exceeds the published bridge's 32 MiB bound")
        print("Frozen migration backend:", args.output)


if __name__ == "__main__":
    main()
