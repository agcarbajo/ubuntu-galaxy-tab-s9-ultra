# SPDX-License-Identifier: MIT
"""Reading and replacing the four partitions that decide which system boots.

Only `boot`, `init_boot`, `vendor_boot` and `dtbo` differ between Ubuntu and
whichever Android is installed.  `vbmeta` is deliberately absent: Android runs
fine with the unsigned flags=2 vbmeta Ubuntu needs, and rewriting it
invalidates the key Android derives for its metadata-encrypted /data, which
costs a full wipe of its user data every single time.

`super` is absent too, and that is why One UI and LineageOS take turns rather
than coexisting: they share it.  The pairing that works is Ubuntu against
whichever Android is installed.

This module runs as root.  The unprivileged UI reaches it through the two
libexec helpers and polkit.
"""

import hashlib
import json
import os


SETS_DIR = "/var/lib/gts9u-boot-sets"

# The rule that lets an active local session switch systems without a
# password.  tab-companion-boot-noask writes and removes it; it is named here
# so that the one place allowed to read it and the one place allowed to write
# it cannot drift apart.
NOASK_RULE = "/etc/polkit-1/rules.d/49-gts9u-boot-switch.rules"

# Sizes are fixed by the partition table, so a wrong or truncated file is
# caught before anything is written.
PARTITIONS = (
    ("boot", 100663296),
    ("init_boot", 8388608),
    ("vendor_boot", 100663296),
    ("dtbo", 16777216),
)

# Last-resort names, deliberately without version numbers.  A real name comes
# from name.txt, written by whichever system is running; guessing a version
# here is how a tablet on One UI 7 ends up being told it runs One UI 8.
KNOWN_LABELS = {
    "ubuntu": "Ubuntu",
    "oneui": "Android",
    "lineage": "LineageOS",
    "lineageos": "LineageOS",
}


def running_system_name():
    """What the system running right now calls itself."""
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def stamp_running_name(set_id):
    """Records the running system's real name in its own set.

    Each system can only name itself: Ubuntu cannot read Android's /sdcard,
    which is metadata-encrypted.  Android returns the favour by mounting
    linuxroot read-only and asking, so both labels end up true.
    """
    name = running_system_name()
    if not name:
        return
    path = os.path.join(SETS_DIR, set_id, "name.txt")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            if handle.readline().strip() == name:
                return
    except OSError:
        pass
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(name + "\n")
    except OSError:
        pass


def device_for(name):
    return f"/dev/block/by-name/{name}"


def _resolve_device(name):
    """by-name is an Android convention; Ubuntu may only have the raw node."""
    path = device_for(name)
    if os.path.exists(path):
        return path
    # The partition table gives userdata sda34 and linuxroot sda35, so the
    # boot partitions keep their fixed numbers from Samsung's PIT.
    fallback = {
        "boot": "/dev/sda21",
        "init_boot": "/dev/sda22",
        "vendor_boot": "/dev/sda24",
        "dtbo": "/dev/sda30",
    }.get(name)
    return fallback if fallback and os.path.exists(fallback) else None


def sha256(path, limit=None):
    digest = hashlib.sha256()
    remaining = limit
    with open(path, "rb") as handle:
        while True:
            size = 4 << 20 if remaining is None else min(4 << 20, remaining)
            if size <= 0:
                break
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def live_hashes():
    out = {}
    for name, size in PARTITIONS:
        device = _resolve_device(name)
        if device is None:
            return {}
        out[name] = sha256(device, size)
    return out


def _set_label(set_id):
    name_file = os.path.join(SETS_DIR, set_id, "name.txt")
    try:
        with open(name_file, "r", encoding="utf-8") as handle:
            line = handle.readline().strip()
        if line and len(line) <= 40:
            return line
    except OSError:
        pass
    return KNOWN_LABELS.get(set_id.lower(), set_id.capitalize())


def _set_hashes(set_id):
    out = {}
    for name, size in PARTITIONS:
        path = os.path.join(SETS_DIR, set_id, f"{name}.img")
        try:
            if os.path.getsize(path) != size:
                return {}
        except OSError:
            return {}
        out[name] = sha256(path)
    return out


def discover():
    try:
        ids = sorted(
            entry for entry in os.listdir(SETS_DIR)
            if os.path.isdir(os.path.join(SETS_DIR, entry))
        )
    except OSError:
        return []

    sets = []
    for set_id in ids:
        hashes = _set_hashes(set_id)
        sets.append({
            "id": set_id,
            "label": _set_label(set_id),
            "complete": len(hashes) == len(PARTITIONS),
            "hashes": hashes,
        })
    return sets


def identify(live, sets):
    if len(live) != len(PARTITIONS):
        return None
    for entry in sets:
        if not entry["complete"]:
            continue
        if all(live.get(name) == entry["hashes"].get(name) for name, _ in PARTITIONS):
            return entry["id"]
    return None


def _partition_bytes(node):
    """Size of a partition, from sysfs, in bytes.

    /sys reports in 512-byte sectors no matter what the disk's logical sector
    size is, which on this UFS is 4096 — so the number here is eight times the
    GPT's, and multiplying by 512 is what puts it back.
    """
    try:
        with open(f"/sys/class/block/{node}/size", "r", encoding="ascii") as handle:
            return int(handle.read().strip()) * 512
    except OSError:
        return 0


def storage():
    """How much room each system has, and how much of it is used.

    Ubuntu's own usage comes from the filesystem it is running on.  Android's
    cannot be read from here at all: its userdata is metadata-encrypted, so
    only the size of the partition is honest, and the UI says so rather than
    inventing a number.
    """
    info = {}

    try:
        stat = os.statvfs("/")
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        info["ubuntu"] = {"total": total, "used": total - free, "known": True}
    except OSError:
        pass

    android_total = _partition_bytes("sda34")
    if android_total:
        info["android"] = {"total": android_total, "used": 0, "known": False}

    return info


def noask_enabled():
    """Whether switching systems currently skips the password prompt.

    This has to be answered from root.  /etc/polkit-1/rules.d is root:polkitd
    and 0750, so the unprivileged window cannot see the rule even when it is
    installed, and asking polkit instead would not do: the switch action is
    auth_admin_keep, so a recent password would make polkit answer "allowed"
    for a few minutes and the window would report a setting nobody turned on.
    """
    return os.path.exists(NOASK_RULE)


def status():
    live = live_hashes()
    current = identify(live, discover())

    # Only the running system knows its own name, so it writes it down while it
    # can; the list is then re-read so the label reported is the one on disk.
    if current is not None:
        stamp_running_name(current)

    sets = discover()
    return {
        "current": identify(live, sets),
        "sets": [
            {"id": s["id"], "label": s["label"], "complete": s["complete"]}
            for s in sets
        ],
        "storage": storage(),
        "noask": noask_enabled(),
    }


def write_set(set_id, report):
    """Writes one set, verifying every partition by reading it back.

    Nothing reboots here.  A caller that has seen a failure must be able to
    stop: a tablet with three of four partitions replaced still runs the
    system it is on, but only until it is restarted.
    """
    entry = next((s for s in discover() if s["id"] == set_id), None)
    if entry is None or not entry["complete"]:
        report("error", f"El juego «{set_id}» no está o está incompleto.")
        return False

    for name, size in PARTITIONS:
        device = _resolve_device(name)
        if device is None:
            report("error", f"No encuentro la partición {name}.")
            return False

        source = os.path.join(SETS_DIR, set_id, f"{name}.img")
        report("step", f"Escribiendo {name}…")
        try:
            with open(source, "rb") as src, open(device, "wb") as dst:
                while True:
                    chunk = src.read(4 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
        except OSError as error:
            report("error", f"No pude escribir {name}: {error}")
            return False

        if sha256(device, size) != entry["hashes"][name]:
            report("error", f"{name} no coincide al releerla. No reinicies: revísalo.")
            return False
        report("step", f"{name} verificada.")

    report("done", "Las cuatro particiones coinciden.")
    return True


def emit(kind, message):
    """One JSON object per line, so the UI can follow progress as it happens."""
    print(json.dumps({"kind": kind, "message": message}), flush=True)
