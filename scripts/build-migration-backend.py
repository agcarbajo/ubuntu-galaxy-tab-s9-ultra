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
    with tempfile.TemporaryDirectory() as temporary:
        app = Path(temporary)
        source = REPO / "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion/tab_companion"
        package = app / "tab_companion"
        package.mkdir()
        (package / "__init__.py").write_text("")
        for name in ("update_core.py", "update_bundle.py", "update_policy.py",
                     "migration_plan.py", "migration_core.py"):
            shutil.copyfile(source / name, package / name)
        (app / "__main__.py").write_text("from tab_companion.migration_core import main\nmain()\n")
        export_runtime(args.root, app / "resources/apt")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(app, args.output, interpreter="/usr/bin/python3", compressed=True)
        if args.output.stat().st_size > 32 * 1024**2:
            raise ValueError("Backend exceeds the published bridge's 32 MiB bound")
        print("Frozen migration backend:", args.output)


if __name__ == "__main__":
    main()
