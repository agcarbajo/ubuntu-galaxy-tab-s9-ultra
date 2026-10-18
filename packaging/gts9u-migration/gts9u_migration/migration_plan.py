"""Bounded package plans and preservation checks for the Resolute transition."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

from galaxy_companion import update_bundle as bundle

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


def parse_plan(text, installed=None, compare=None, manual=None, protected=frozenset()):
    """A frozen install/remove plan from APT's simulated actions.

    Removals are allowed when they were reviewed (OBSOLETE), or when the
    package was installed automatically and APT no longer needs it, which is
    how library ABI renames between releases show up (`manual` is the set of
    packages the user installed by hand; without it only reviewed removals
    pass).  A package the user installed that would be removed, and any
    package the release itself ships (`protected`), stop the migration; every
    such name is reported at once."""
    installed = installed or {}
    manual = None if manual is None else frozenset(manual)
    lost, port = [], []
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
            if name in protected:
                port.append(name)
            elif name not in OBSOLETE and (manual is None or name in manual):
                lost.append(name)
            removals.add(name)
    if port:
        raise ValueError("The migration would remove packages this release ships: " + ", ".join(sorted(port)))
    if lost:
        raise ValueError("Unreviewed package removal (installed by you, no Ubuntu 26.04 version from an "
                         "enabled source): " + ", ".join(sorted(lost)))
    if not installs or len(installs) > 4096:
        raise ValueError("Missing or excessive migration package plan")
    if set(installs) & removals:
        raise ValueError("A package cannot be installed and removed in the same migration")
    for name in removals & REPLACEMENTS.keys():
        if REPLACEMENTS[name] not in installs:
            raise ValueError("A reviewed ABI removal requires its replacement in the same transaction")
    return {"install": installs, "remove": sorted(removals)}


def parse_selection(text, installed=None, manual=None, protected=frozenset()):
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
    return parse_plan("\n".join(records), installed, manual=manual, protected=protected)


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


UBUNTU_ARCHIVES = ("ports.ubuntu.com", "archive.ubuntu.com", "security.ubuntu.com")


def _entries_from_list(text):
    for line in text.splitlines():
        words = line.split("#", 1)[0].split()
        if not words or words[0] != "deb":
            continue
        options = {}
        if len(words) > 1 and words[1].startswith("["):
            closing = next(i for i, word in enumerate(words) if word.endswith("]"))
            for option in " ".join(words[1:closing + 1]).strip("[]").split():
                key, _, value = option.partition("=")
                options[key.lower()] = value
            words = [words[0]] + words[closing + 1:]
        if len(words) < 3:
            continue
        yield {"uris": [words[1]], "suites": [words[2]], "components": words[3:],
               "signed_by": options.get("signed-by", ""), "architectures": options.get("arch", "").replace(",", " "),
               "raw": None}


def _entries_from_sources(text):
    for stanza in [block for block in text.split("\n\n") if block.strip()]:
        fields, current = {}, None
        for line in stanza.splitlines():
            if line.startswith("#"):
                continue
            if line[:1] in (" ", "\t") and current:
                fields[current] += "\n" + line
                continue
            key, _, value = line.partition(":")
            current = key.strip().lower()
            fields[current] = value.strip()
        if "deb" not in fields.get("types", "").split() or fields.get("enabled", "yes").lower() == "no":
            continue
        yield {"uris": fields.get("uris", "").split(), "suites": fields.get("suites", "").split(),
               "components": fields.get("components", "").split(), "signed_by": fields.get("signed-by", ""),
               "architectures": fields.get("architectures", ""), "raw": stanza}


def third_party_sources(apt_dir, source="noble", target="resolute", available=None):
    """Third-party APT sources carried across the release migration.

    Entries for the Ubuntu archive are left to the migration.  An entry whose
    suites are release-independent (`stable`, `./`) is kept as it is; one whose
    suites name the source release is kept with the target release's name when
    `available(uri, suite)` confirms the repository publishes it, and dropped
    otherwise.  Returns (deb822 text, kept descriptions, dropped descriptions)."""
    stanzas, kept, dropped = [], [], []
    files = [apt_dir / "sources.list"] if (apt_dir / "sources.list").is_file() else []
    files += sorted((apt_dir / "sources.list.d").glob("*.list")) + sorted((apt_dir / "sources.list.d").glob("*.sources"))
    for file in files:
        parse = _entries_from_sources if file.suffix == ".sources" else _entries_from_list
        for entry in parse(file.read_text(errors="replace")):
            if not entry["uris"] or any(host in uri for uri in entry["uris"] for host in UBUNTU_ARCHIVES):
                continue
            suites = entry["suites"]
            named = [s for s in suites if s == source or s.startswith(source + "-")]
            label = " ".join(entry["uris"]) + " " + " ".join(suites)
            if named and len(named) != len(suites):
                dropped.append(label)
                continue
            if named:
                suites = [target + s[len(source):] for s in suites]
                if available is None or not all(available(uri, suite) for uri in entry["uris"] for suite in suites):
                    dropped.append(label)
                    continue
            lines = ["Types: deb", "URIs: " + " ".join(entry["uris"]), "Suites: " + " ".join(suites)]
            if entry["components"]:
                lines.append("Components: " + " ".join(entry["components"]))
            if entry["architectures"]:
                lines.append("Architectures: " + entry["architectures"])
            if entry["signed_by"]:
                lines.append("Signed-By: " + entry["signed_by"])
            stanzas.append("\n".join(lines))
            kept.append(" ".join(entry["uris"]) + " " + " ".join(suites))
    return ("\n\n".join(stanzas) + "\n") if stanzas else "", kept, dropped
