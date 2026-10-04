"""Bounded package plans and preservation checks for the Resolute transition."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

from . import update_bundle as bundle

REPLACEMENTS = {
    "libgjs0g": "libgjs0", "keyboxd": "gpg",
    "libgstreamer-plugins-good1.0-0": "libgstreamer-plugins-extra1.0-0",
    "libimobiledevice6": "libimobiledevice-1.0-6",
    "libtracker-sparql-3.0-0": "libtinysparql-3.0-0",
    "libexiv2-27": "libexiv2-28", "libgusb2": "libgusb2a",
    "libgtk-4-media-gstreamer": "libgtk-4-1",
    "liblttng-ust-ctl5t64": "liblttng-ust-ctl6",
}
OBSOLETE = frozenset(REPLACEMENTS) | frozenset((
    "libcamera-gts9u", "libcamera-ipa", "libcamera-tools", "libcamera-dev",
    "gstreamer1.0-libcamera", "gir1.2-mutter-14", "libmutter-14-0",
    "gnome-shell-extension-ubuntu-dock", "gnome-shell-extension-appindicator",
    "gnome-shell-extension-desktop-icons-ng", "gnome-shell-extension-ubuntu-tiling-assistant",
    "gnome-shell-extension-tiling-assistant", "gnome-shell-extension-ubuntu-tiling-assistant-common",
))
VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+:~_-]{0,199}\Z")
INSTALL = re.compile(r"^Inst ([a-z0-9][a-z0-9+.:~-]*)(?: \[[^\]]+\])? \(([^ ]+)")
REMOVE = re.compile(r"^Remv ([a-z0-9][a-z0-9+.:~-]*)\b")
PRESERVED = (
    "etc/machine-id", "etc/hostname", "etc/timezone", "etc/localtime", "etc/default/locale",
    "etc/default/keyboard", "etc/NetworkManager/system-connections",
    "var/lib/fprint", "var/lib/bluetooth", "var/lib/tailscale",
    "var/lib/gts9u-boot-sets/android",
)


def package_name(value):
    if not isinstance(value, str) or not bundle.PACKAGE.fullmatch(value):
        raise ValueError("Invalid migration package name")
    return value.removesuffix(":arm64")


def parse_plan(text, installed=None, compare=None):
    installed = installed or {}
    compare = compare or (lambda new, old: subprocess.run(
        ["dpkg", "--compare-versions", new, "lt", old], capture_output=True).returncode == 0)
    installs, removals = {}, set()
    for line in text.splitlines():
        match = INSTALL.match(line)
        if match:
            name, version = package_name(match[1]), match[2]
            if not VERSION.fullmatch(version) or name in installs and installs[name] != version:
                raise ValueError("Invalid or conflicting migration package version")
            if name in installed and compare(version, installed[name]):
                raise ValueError("The migration would downgrade an installed package")
            if name.startswith(("linux-image-", "linux-modules-", "linux-generic")):
                raise ValueError("An archive kernel cannot replace the board kernel")
            installs[name] = version
        match = REMOVE.match(line)
        if match:
            name = package_name(match[1])
            if name not in OBSOLETE:
                raise ValueError("Unreviewed package removal: " + name)
            removals.add(name)
    if not installs or len(installs) > 4096:
        raise ValueError("Missing or excessive migration package plan")
    if set(installs) & removals:
        raise ValueError("A package cannot be installed and removed in the same migration")
    for name in removals & REPLACEMENTS.keys():
        if REPLACEMENTS[name] not in installs:
            raise ValueError("A reviewed ABI removal requires its replacement in the same transaction")
    return {"install": installs, "remove": sorted(removals)}


def parse_selection(text, installed=None):
    headers = {"The following packages will be REMOVED:": "remove",
               "The following NEW packages will be installed:": "new",
               "The following packages will be upgraded:": "upgrade"}
    counts = {"remove": 0, "new": 0, "upgrade": 0}
    records, section, summary = [], None, None
    for line in text.splitlines():
        if "will be DOWNGRADED:" in line or "will be REINSTALLED:" in line:
            raise ValueError("Unexpected downgrade or reinstall in migration selection")
        if line in headers:
            section = headers[line]
            continue
        match = re.fullmatch(r"(\d+) upgraded, (\d+) newly installed, (\d+) to remove and (\d+) not upgraded\.", line)
        if match:
            summary = tuple(int(value) for value in match.groups()[:3])
            section = None
            continue
        if not line.startswith(" "):
            section = None
        if section is None:
            continue
        match = re.fullmatch(r"\s+([a-z0-9][a-z0-9+.:~-]*) \(([^ ()]+)(?: => ([^ ()]+))?\)", line)
        if not match or not VERSION.fullmatch(match[2]) or match[3] and not VERSION.fullmatch(match[3]):
            raise ValueError("Unexpected package selection entry")
        name = package_name(match[1])
        if section == "upgrade" and not match[3] or section != "upgrade" and match[3]:
            raise ValueError("Inconsistent package selection operation")
        if installed is not None and section != "new" and installed.get(name) != match[2]:
            raise ValueError("Selection no longer matches the installed package version")
        counts[section] += 1
        records.append("Remv " + name + " [" + match[2] + "]" if section == "remove" else
                       "Inst " + name + " (" + (match[3] or match[2]) + " selected)")
    if summary != (counts["upgrade"], counts["new"], counts["remove"]):
        raise ValueError("Missing or inconsistent package selection summary")
    return parse_plan("\n".join(records), installed)


def requested_packages(installed, required):
    names = {package_name(name) for name in installed} | {package_name(name) for name in required}
    if len(names) > 4096:
        raise ValueError("Excessive installed package inventory")
    return sorted(names - OBSOLETE) + [name + "-" for name in sorted(names & OBSOLETE)]


def account_identity(root):
    passwd = {}
    for line in (root / "etc/passwd").read_text().splitlines():
        fields = line.split(":")
        if len(fields) != 7:
            raise ValueError("Invalid account database")
        if int(fields[2]) == 0 or 1000 <= int(fields[2]) < 65534:
            passwd[fields[0]] = line
    shadow = {line.partition(":")[0]: line for line in (root / "etc/shadow").read_text().splitlines()
              if line.partition(":")[0] in passwd}
    return passwd, shadow


def preservation_inventory(root):
    entries = {}
    paths = [root / name for name in PRESERVED]
    ssh = root / "etc/ssh"
    if ssh.is_dir():
        paths.extend(ssh.glob("ssh_host_*"))
    for start in paths:
        members = [start]
        if start.is_dir() and not start.is_symlink():
            members.extend(start.rglob("*"))
        for path in members:
            if not path.exists() and not path.is_symlink():
                continue
            info = path.lstat()
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                digest = hashlib.sha256(os.readlink(path).encode()).hexdigest()
            elif stat.S_ISREG(info.st_mode):
                digest = bundle.sha256(path)
            elif stat.S_ISDIR(info.st_mode):
                digest = "directory"
            else:
                raise ValueError("Unsupported preserved-state file type")
            entries[name] = (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid, digest)
    return entries


def restore_compatibility_files(source, target):
    old, new = source / "etc/timezone", target / "etc/timezone"
    if old.is_file() and not old.is_symlink() and not new.exists() and not new.is_symlink():
        shutil.copy2(old, new)
        info = old.stat()
        os.chown(new, info.st_uid, info.st_gid)
    old, new = source / "etc/localtime", target / "etc/localtime"
    if old.is_symlink():
        if new.exists() or new.is_symlink():
            new.unlink()
        new.symlink_to(old.readlink())
        info = old.lstat()
        os.chown(new, info.st_uid, info.st_gid, follow_symlinks=False)
    elif old.is_file():
        if new.is_symlink():
            new.unlink()
        shutil.copy2(old, new)
        info = old.stat()
        os.chown(new, info.st_uid, info.st_gid)


def check_preservation(source, target):
    if account_identity(source) != account_identity(target):
        raise ValueError("Migration changed an existing user identity or password record")
    if preservation_inventory(source) != preservation_inventory(target):
        raise ValueError("Migration changed protected system identity or application state")
