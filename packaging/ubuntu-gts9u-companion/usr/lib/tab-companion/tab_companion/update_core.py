# SPDX-License-Identifier: MIT
"""Privileged preparation and offline application; never runs the ZIP installer."""
import argparse
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import update_bundle as bundle

STATE = Path("/var/lib/tab-companion-update")
TRANSACTION = STATE / "transaction"
MARKER = Path("/system-update")
UNIT = "gts9u-offline-update.service"
LOCK = "/run/lock/gts9u-boot.lock"
PROGRESS_JSON = False


def progress(stage, completed=None, total=None):
    if PROGRESS_JSON:
        emit(json.dumps({"event": "progress", "stage": stage,
                         "completed": completed, "total": total}))


def emit(message):
    try:
        print(message, flush=True)
    except BrokenPipeError:
        pass  # Closing the UI must not interrupt an authorised preparation.


def boot_lock():
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    s = os.fstat(fd)
    if s.st_uid != 0 or not stat.S_ISREG(s.st_mode):
        os.close(fd)
        raise ValueError("Unsafe boot lock file")
    return os.fdopen(fd, "r+")


def run(argv, capture=False, offline=False):
    result = subprocess.run(argv, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            env={**os.environ, "LC_ALL": "C", "DEBIAN_FRONTEND": "noninteractive",
                                 "NEEDRESTART_MODE": "l",
                                 **({"SYSTEMD_OFFLINE": "1"} if offline else {})})
    return result.stdout.strip() if capture else ""


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def status():
    try:
        return json.loads((STATE / "status.json").read_text())
    except (OSError, ValueError):
        return {"state": "idle"}


def set_status(state, **extra):
    write_json(STATE / "status.json", {"state": state, **extra})


def device_check():
    model = Path("/proc/device-tree/model").read_bytes().rstrip(b"\0")
    if model != b"Samsung Galaxy Tab S9 Ultra Wi-Fi":
        raise ValueError("Updates are only supported on the SM-X910")
    if run(["dpkg", "--print-architecture"], True) != "arm64":
        raise ValueError("Expected arm64 Ubuntu")
    release = Path("/etc/os-release").read_text()
    if '\nID=ubuntu\n' not in '\n' + release or 'VERSION_ID="24.04"' not in release:
        raise ValueError("Only Ubuntu 24.04 is supported")
    if run(["findmnt", "-n", "-o", "LABEL", "/"], True) != "UBTS9U_UFS":
        raise ValueError("The installed root filesystem is not this port's UFS installation")
    # Do not overwrite a saved switch to Android while Linux is still running.
    with partitions()["vendor_boot"].open("rb") as source:
        if b"root=LABEL=UBTS9U_UFS" not in source.read(4096):
            raise ValueError("Boot partitions are not set to Ubuntu; switch back before updating")


def partitions():
    devices = {}
    for part, expected in bundle.PARTITIONS.items():
        candidates = [Path("/dev/disk/by-partlabel") / part, Path("/dev/block/by-name") / part]
        path = next((p.resolve() for p in candidates if p.exists()), None)
        if path is None or not stat.S_ISBLK(path.stat().st_mode):
            raise ValueError("Cannot resolve partition " + part)
        if run(["lsblk", "-dn", "-o", "PARTLABEL", str(path)], True) != part:
            raise ValueError("Partition identity mismatch: " + part)
        if int(run(["blockdev", "--getsize64", str(path)], True)) != expected:
            raise ValueError("Partition size mismatch: " + part)
        devices[part] = path
    return devices


def power_check():
    supplies = Path("/sys/class/power_supply")
    levels = []
    for capacity in supplies.glob("*/capacity"):
        try:
            scope = capacity.parent / "scope"
            # The S Pen is a separate Device-scoped battery and may report
            # ENODATA while charging. It must never gate a system update.
            if scope.exists() and scope.read_text().strip() == "Device":
                continue
            if (capacity.parent / "type").read_text().strip() == "Battery":
                levels.append(int(capacity.read_text()))
        except (OSError, ValueError):
            continue
    if not levels:
        raise ValueError("Cannot check battery level")
    if min(levels) >= 20:
        return
    online = []
    for path in supplies.glob("*/online"):
        try:
            scope = path.parent / "scope"
            if scope.exists() and scope.read_text().strip() == "Device":
                continue
            online.append(path.read_text().strip() == "1")
        except OSError:
            continue
    if not any(online):
        raise ValueError("Battery below 20%: connect the charger before updating")


def owned_directory(path):
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
        raise ValueError("Unsafe updater directory: " + str(path))


def marker_owned():
    return MARKER.is_symlink() and os.readlink(MARKER) == str(TRANSACTION)


def unmark():
    if marker_owned():
        MARKER.unlink()
        os.sync()


def cache_local_packages(transaction, plan):
    """APT --no-download requires local DEBs in its canonical archive cache."""
    cache = transaction / "archives"
    cache.mkdir(exist_ok=True)
    for name in plan["files"]:
        if not name.endswith(".deb"):
            continue
        source = transaction / name
        fields = run(["dpkg-deb", "-f", str(source), "Package", "Version", "Architecture"], True)
        values = dict(line.split(": ", 1) for line in fields.splitlines())
        filename = "{Package}_{Version}_{Architecture}.deb".format(**values).replace(":", "%3a")
        target = cache / filename
        if not target.exists():
            os.link(source, target)
        elif bundle.sha256(target) != bundle.sha256(source):
            raise ValueError("Conflicting cached package: " + filename)


def apt_args(transaction, download=False):
    plan = json.loads((transaction / "plan.json").read_text())
    return ["apt-get", "-y", "--no-remove", "--reinstall",
            "--download-only" if download else "--no-download",
            "-o", "Dpkg::Options::=--force-confold",
            "-o", "Dpkg::Options::=--force-confdef",
            "-o", "Dir::Cache::archives=" + str(transaction / "archives"),
            "install", *[str(transaction / n) for n in plan["files"] if n.endswith(".deb")],
            *plan["apt_packages"]]


def validate_packages(transaction, plan):
    names = set()
    for file in plan["files"]:
        if not file.endswith(".deb"):
            continue
        fields = run(["dpkg-deb", "-f", str(transaction / file), "Package", "Architecture"], True)
        values = dict(line.split(": ", 1) for line in fields.splitlines())
        name = values["Package"]
        if name in names or values["Architecture"] not in ("all", "arm64"):
            raise ValueError("Duplicate package or wrong architecture: " + name)
        names.add(name)
    required = {"ubuntu-gts9u-companion", "ubuntu-gts9u-device", "ubuntu-gts9u-hardware"}
    if not required <= names:
        raise ValueError("The update is missing required port packages")


def install_runner():
    """A frozen copy survives replacement of Companion during apt installation."""
    package = TRANSACTION / "tab_companion"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for name in ("update_core.py", "update_bundle.py"):
        # get_source also works when the legacy bootstrap runs as a zipapp.
        module = sys.modules[__package__ + "." + name[:-3]]
        source = module.__loader__.get_source(module.__name__)
        (package / name).write_text(source)
    (TRANSACTION / "runner.py").write_text(
        "from tab_companion.update_core import main\nmain(['--apply-offline'])\n")
    unit_dir = Path("/etc/systemd/system")
    (unit_dir / UNIT).write_text("""[Unit]
Description=Apply the prepared Galaxy Tab S9 Ultra update
ConditionPathExists=/var/lib/tab-companion-update/transaction/runner.py
DefaultDependencies=no
Requires=sysinit.target
After=sysinit.target
Before=system-update.target
Conflicts=shutdown.target
FailureAction=reboot
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /var/lib/tab-companion-update/transaction/runner.py
TimeoutStartSec=infinity
StandardOutput=journal+console
StandardError=journal+console
""")
    wants = unit_dir / "system-update.target.wants"
    wants.mkdir(exist_ok=True)
    link = wants / UNIT
    if not link.exists():
        link.symlink_to("../" + UNIT)
    run(["systemctl", "daemon-reload"])


def prepare(args):
    progress("preflight")
    device_check()
    power_check()
    if MARKER.exists() or MARKER.is_symlink() or status()["state"] in ("ready", "applying"):
        raise ValueError("An update is already pending. Cancel it first.")
    if TRANSACTION.exists():
        if (TRANSACTION / "backup/complete").exists():
            backups = STATE / "backups"
            backups.mkdir(mode=0o700, exist_ok=True)
            os.rename(TRANSACTION / "backup", backups / str(time.time_ns()))
        shutil.rmtree(TRANSACTION)
    TRANSACTION.mkdir(mode=0o700)
    set_status("preparing")
    try:
        archive = TRANSACTION / "release.zip"
        info = None
        if args.zip:
            # Copy first: a user-selected file must not change after validation.
            source = Path(args.zip)
            fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as src:
                s = os.fstat(src.fileno())
                if not stat.S_ISREG(s.st_mode) or not 0 < s.st_size <= bundle.MAX_PAYLOAD:
                    raise ValueError("Select a regular build ZIP")
                if shutil.disk_usage(STATE).free < s.st_size * 2 + 3 * 1024**3:
                    raise ValueError("Not enough free space to stage and back up the update")
                with archive.open("xb") as dst:
                    remaining = s.st_size
                    progress("copy", 0, s.st_size)
                    while remaining:
                        chunk = src.read(min(4 * 1024**2, remaining))
                        if not chunk:
                            raise ValueError("The selected ZIP changed while being copied")
                        dst.write(chunk)
                        remaining -= len(chunk)
                        progress("copy", s.st_size - remaining, s.st_size)
                    if src.read(1):
                        raise ValueError("The selected ZIP grew while being copied")
        else:
            tag = bundle.current().get("tag") if args.repair else None
            if args.repair and not tag:
                raise ValueError("This installation has no recorded GitHub build. Repair is unavailable.")
            info = bundle.release(tag)
            eligibility = bundle.release_state(info)
            if eligibility == "unsupported":
                raise ValueError("This GitHub release predates safe updates. Your installed system has not been changed.")
            if not args.repair and eligibility == "older":
                raise ValueError("The published release is older than the installed build. Downgrades are not offered.")
            if not args.repair and info["tag"] == bundle.current().get("tag"):
                raise ValueError("This release is already installed")
            if shutil.disk_usage(STATE).free < info["size"] * 2 + 3 * 1024**3:
                raise ValueError("Not enough free space to download and back up the update")
            emit("Downloading " + info["tag"])
            progress("download", 0, info["size"])
            def downloaded(done, total):
                if PROGRESS_JSON:
                    progress("download", done, total)
                else:
                    emit(f"Download: {done * 100 // total}%")
            bundle.download(info, archive, downloaded)
        progress("verify")
        manifest = bundle.inspect(archive)
        payload_size = sum(f["size"] for f in manifest["files"].values())
        if shutil.disk_usage(STATE).free < payload_size * 3 + 3 * 1024**3:
            raise ValueError("Not enough free space for packages, module backup and APT dependencies")
        if info and manifest["tag"] != info["tag"]:
            raise ValueError("The payload version does not match the GitHub release")
        emit("Verifying and extracting the update payload…")
        manifest = bundle.extract(archive, TRANSACTION)
        validate_packages(TRANSACTION, manifest)
        write_json(TRANSACTION / "plan.json", manifest)
        (TRANSACTION / "archives/partial").mkdir(parents=True)
        cache_local_packages(TRANSACTION, manifest)
        emit("Resolving and downloading package dependencies…")
        progress("dependencies")
        if run(["dpkg", "--audit"], True):
            raise ValueError("Repair the existing package installation before updating")
        run(["apt-get", "update"])
        run(apt_args(TRANSACTION, download=True))
        run(["apt-get", "check"])
        backup_bytes = sum(int(line.split()[0]) for line in run(
            ["du", "-sx", "--block-size=1", "/usr/lib/modules", "/etc"], True).splitlines())
        if shutil.disk_usage(STATE).free < backup_bytes + 2 * 1024**3:
            raise ValueError("Insufficient free space for the recovery backup")
        archives = {p.name: bundle.sha256(p) for p in (TRANSACTION / "archives").glob("*.deb")}
        write_json(TRANSACTION / "archives.json", archives)
        (TRANSACTION / "dpkg.sha256").write_text(bundle.sha256("/var/lib/dpkg/status"))
        install_runner()
        archive.unlink()
        set_status("ready", version=manifest["version"], tag=manifest["tag"])
        os.sync()
        MARKER.symlink_to(TRANSACTION)
        os.sync()
        progress("ready", 1, 1)
        emit("Update prepared. Save your work and restart to install it.")
    except Exception as error:
        set_status("failed", error=str(error))
        raise


def copy_partition(src, dst, size):
    """Never truncate block devices; check exact bytes and read back after fsync."""
    with open(src, "rb") as source, open(dst, "r+b", buffering=0) as target:
        remaining = size
        while remaining:
            chunk = source.read(min(4 * 1024**2, remaining))
            if not chunk:
                raise ValueError("Truncated boot image")
            view = memoryview(chunk)
            while view:
                n = target.write(view)
                if not n:
                    raise OSError("Short boot partition write")
                view = view[n:]
            remaining -= len(chunk)
        os.fsync(target.fileno())
    if bundle.sha256(src) != bundle.sha256(dst):
        raise OSError("Boot partition readback mismatch")


def apply_offline():
    if not marker_owned():
        return
    if status().get("state") == "complete":
        # Power may have failed after the success record but before removing
        # system-update. Do not roll back an already committed installation.
        unmark()
        run(["systemctl", "--no-block", "reboot"])
        return
    if subprocess.run(["systemctl", "is-active", "--quiet", "graphical.target"]).returncode == 0:
        raise ValueError("Updates must run outside the graphical session")
    previous = status()
    set_status("applying", tag=previous.get("tag"))
    devices = {}
    backup = TRANSACTION / "backup"
    try:
        device_check()
        power_check()
        if previous["state"] != "applying" and bundle.sha256("/var/lib/dpkg/status") != (TRANSACTION / "dpkg.sha256").read_text():
            raise ValueError("Packages changed after preparation. Prepare the update again.")
        plan = json.loads((TRANSACTION / "plan.json").read_text())
        for name, entry in plan["files"].items():
            if bundle.sha256(TRANSACTION / name) != entry["sha256"]:
                raise ValueError("Staged payload changed: " + name)
        for name, digest in json.loads((TRANSACTION / "archives.json").read_text()).items():
            if bundle.sha256(TRANSACTION / "archives" / name) != digest:
                raise ValueError("Staged dependency changed: " + name)
        devices = partitions()
        if not (backup / "complete").exists():
            if backup.exists():
                shutil.rmtree(backup)
            backup.mkdir()
            emit("Backing up boot images, kernel modules and system configuration…")
            for part, device in devices.items():
                shutil.copyfile(device, backup / (part + ".img"))
            # Release strings can remain unchanged between kernel builds.
            run(["cp", "-a", "/usr/lib/modules", str(backup / "modules")])
            run(["cp", "-a", "/etc", str(backup / "etc")])
            if bundle.IDENTITY.exists():
                shutil.copyfile(bundle.IDENTITY, backup / "identity.json")
            os.sync()
            (backup / "complete").touch()
            os.sync()
        emit("Installing port packages and dependencies…")
        if previous["state"] == "applying":
            run(["dpkg", "--force-confold", "--configure", "-a"], offline=True)
        run(apt_args(TRANSACTION), offline=True)
        run(["apt-get", "check"])
        run(["depmod", "-a", plan["kernel_release"]])
        emit("Writing and verifying the matching boot images…")
        for part, size in bundle.PARTITIONS.items():
            copy_partition(TRANSACTION / (part + ".img"), devices[part], size)
        # Refresh only Ubuntu's saved set; Android's set and vbmeta stay intact.
        saved = Path("/var/lib/gts9u-boot-sets/ubuntu")
        saved.parent.mkdir(parents=True, exist_ok=True)
        new_set = TRANSACTION / "new-ubuntu-set"
        new_set.mkdir(exist_ok=True)
        for part in bundle.PARTITIONS:
            shutil.copyfile(TRANSACTION / (part + ".img"), new_set / (part + ".img"))
        (new_set / "name.txt").write_text("Ubuntu " + plan["tag"] + "\n")
        if saved.exists():
            if (backup / "ubuntu-set").exists():
                shutil.rmtree(saved)
            else:
                os.rename(saved, backup / "ubuntu-set")
        os.rename(new_set, saved)
        write_json(bundle.IDENTITY, {k: plan[k] for k in
                   ("device", "version", "tag", "kernel_release")})
        os.sync()
        set_status("complete", version=plan["version"], tag=plan["tag"])
        emit("Update installed. Restarting…")
    except Exception as error:
        recovery = ""
        if (backup / "complete").exists():
            try:
                for part, size in bundle.PARTITIONS.items():
                    copy_partition(backup / (part + ".img"), devices[part], size)
                run(["cp", "-a", str(backup / "modules") + "/.", "/usr/lib/modules/"])
                if (backup / "identity.json").exists():
                    write_json(bundle.IDENTITY, json.loads((backup / "identity.json").read_text()))
                elif bundle.IDENTITY.exists():
                    bundle.IDENTITY.unlink()
                if (backup / "ubuntu-set").exists():
                    saved = Path("/var/lib/gts9u-boot-sets/ubuntu")
                    if saved.exists():
                        shutil.rmtree(saved)
                    shutil.copytree(backup / "ubuntu-set", saved)
            except Exception as restore_error:
                recovery = "; boot restore failed: " + str(restore_error)
        set_status("failed", error=str(error) + recovery)
        emit("Update failed: " + str(error) + recovery)
        # Keep the device in maintenance mode if restoring boot images failed.
        if recovery:
            run(["systemctl", "--no-block", "start", "emergency.target"])
            return
    finally:
        unmark()
        os.sync()
    run(["systemctl", "--no-block", "reboot"])


def main(argv=None):
    global PROGRESS_JSON
    parser = argparse.ArgumentParser(description="Update the SM-X910 Ubuntu port without replacing user data")
    parser.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--latest", action="store_true")
    group.add_argument("--zip", metavar="FILE")
    group.add_argument("--repair", action="store_true", help=argparse.SUPPRESS)
    group.add_argument("--check", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--cancel", action="store_true")
    group.add_argument("--apply-offline", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    PROGRESS_JSON = args.progress_json
    if args.check:
        print(json.dumps({"current": bundle.current(), "latest": bundle.release()}))
        return
    if args.status:
        print(json.dumps(status()))
        return
    if os.geteuid() != 0:
        parser.error("Run with sudo (or use Tab Companion)")
    os.umask(0o022)
    owned_directory(STATE)
    with boot_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.apply_offline:
            apply_offline()
        elif args.cancel:
            if status()["state"] == "applying":
                raise ValueError("An update is being applied")
            unmark()
            set_status("idle")
            if TRANSACTION.exists():
                if (TRANSACTION / "backup/complete").exists():
                    backups = STATE / "backups"
                    backups.mkdir(mode=0o700, exist_ok=True)
                    os.rename(TRANSACTION / "backup", backups / str(time.time_ns()))
                shutil.rmtree(TRANSACTION)
            emit("Prepared update cancelled")
        else:
            prepare(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit(str(error))
        sys.exit(1)
