# SPDX-License-Identifier: MIT
"""Bounded, read-only cover diagnostics. Never read evdev events or I2C registers."""
import glob
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import struct
import time

DRIVER = "/sys/bus/i2c/drivers/samsung-gts9u-stm32-pogo"
RELEVANT = re.compile(r"pogo|stm32|MAX77816|geni_i2c|i2c.*002a", re.I)
PRIVATE_EVENT = re.compile(r"last_key|key.?code|scan.?code|key event|raw.packet|\[B?[PRM]\]", re.I)


def read(path, limit=16384):
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace").strip()
    except OSError as error:
        return "Unavailable: " + error.strerror


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors="replace",
                                timeout=12, env={**os.environ, "LC_ALL": "C"})
        return {"exit": result.returncode, "output": result.stdout[-262144:],
                "error": result.stderr[-2048:]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"error": str(error)}


def safe_diagnostics(text):
    # Older kernels expose the last key's scan code. Keep only aggregate counts.
    return re.sub(r"\blast_key=\S+", "last_key=[omitted]", text)


def filtered_log(result, relevant=True):
    result["output"] = "\n".join(
        line for line in result.get("output", "").splitlines()
        if (not relevant or RELEVANT.search(line)) and not PRIVATE_EVENT.search(line))
    return result


def input_snapshot():
    devices = []
    for entry in sorted(glob.glob("/sys/class/input/event*")):
        path = Path(entry)
        name = read(path / "device/name")
        if not re.search(r"Book Cover|pogo|Tab Companion virtual keyboard", name, re.I):
            continue
        item = {"event": path.name, "name": name,
                "sysfs": str(path.resolve()),
                "attributes": {field: read(path / "device" / field) for field in (
                    "phys", "properties", "id/bustype", "id/vendor", "id/product", "id/version",
                    "capabilities/ev", "capabilities/key", "capabilities/abs", "capabilities/rel")}}
        props = command(["udevadm", "info", "--query=property", "--path=" + str(path)])
        item["udev"] = [line for line in props.get("output", "").splitlines()
                        if line.startswith(("ID_INPUT", "ID_VENDOR_ID=", "ID_MODEL_ID=", "ID_PATH=", "LIBINPUT_"))]
        # Query fixed axis geometry only; deliberately discard the current value.
        item["axis_geometry"] = {}
        try:
            fd = os.open("/dev/input/" + path.name, os.O_RDONLY | os.O_NONBLOCK)
            try:
                for axis in (0, 1, 47, 48, 53, 54):
                    try:
                        data = fcntl.ioctl(fd, 0x80184540 + axis, bytes(24))
                        values = struct.unpack("=6i", data)[1:]
                        item["axis_geometry"][str(axis)] = dict(zip(
                            ("minimum", "maximum", "fuzz", "flat", "resolution"), values))
                    except OSError:
                        pass
            finally:
                os.close(fd)
        except OSError:
            pass
        devices.append(item)
    return devices


def driver_snapshot():
    devices = {}
    for entry in sorted(glob.glob(DRIVER + "/*-002a")):
        path = Path(entry)
        devices[path.name] = {name: safe_diagnostics(read(path / name)) for name in (
            "diagnostics", "power/runtime_status", "power/control", "power/wakeup")}
    return devices


def collect_privileged(seconds=20):
    report = {"format": 1, "duration_seconds": seconds,
              "privacy": "System snapshots exclude historical key codes, touch coordinates, serials and user files. Authorized test-period keys are stored separately in keyboard_capture.",
              "samples": [], "inputs_before": input_snapshot()}
    start = time.monotonic()
    # Record connection/IRQ/recovery counters across several 3-second cycles.
    for index in range(seconds + 1):
        report["samples"].append({"seconds": round(time.monotonic() - start, 3),
                                   "devices": driver_snapshot(),
                                   "input_nodes": [Path(p).name for p in glob.glob("/sys/class/input/event*")
                                       if re.search(r"Book Cover|pogo|Tab Companion virtual keyboard",
                                                    read(Path(p) / "device/name"), re.I)]})
        if index < seconds:
            time.sleep(max(0, start + index + 1 - time.monotonic()))
    report["inputs_after"] = input_snapshot()
    report["device_tree"] = {}
    for entry in glob.glob(DRIVER + "/*-002a"):
        node = Path(entry) / "of_node"
        properties = {}
        for name in ("compatible", "reg", "interrupts-extended", "data-gpios", "connected-gpios",
                     "reset-gpios", "boot-gpios", "vddo-supply", "wakeup-source"):
            try:
                properties[name] = (node / name).read_bytes()[:128].hex()
            except OSError:
                pass
        report["device_tree"][Path(entry).name] = properties
    for boot in ("0", "-1"):
        report["kernel_boot_" + boot] = filtered_log(command([
            "journalctl", "--no-pager", "--quiet", "-k", "-b", boot,
            "-n", "4000", "-o", "short-monotonic"]))
        report["firmware_service_boot_" + boot] = filtered_log(command([
            "journalctl", "--no-pager", "--quiet", "-b", boot,
            "-u", "ubuntu-gts9u-pogo-firmware.service", "-n", "150", "-o", "cat"]), False)
    report["interrupts"] = [line for line in read("/proc/interrupts", 65536).splitlines()
                             if RELEVANT.search(line)]
    report["firmware_service"] = command(["systemctl", "show", "ubuntu-gts9u-pogo-firmware.service",
        "-p", "ActiveState", "-p", "SubState", "-p", "Result", "-p", "ExecMainStatus"])
    report["libinput_version"] = command(["libinput", "--version"])
    firmware = Path("/lib/firmware/keyboard_stm/stm32_gts9family.bin")
    try:
        report["firmware_sha256"] = hashlib.sha256(firmware.read_bytes()).hexdigest()
    except OSError as error:
        report["firmware_sha256"] = str(error)
    return report


def collect_session():
    from gi.repository import Gio
    from . import VERSION
    report = {"companion_version": VERSION, "kernel": os.uname().release,
              "architecture": os.uname().machine, "release": read("/usr/lib/gts9u-release.json"),
              "os_release": read("/etc/os-release"), "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown")}
    report["packages"] = command(["dpkg-query", "-W", "ubuntu-gts9u-companion", "ubuntu-gts9u-device",
                                    "ubuntu-gts9u-hardware", "libinput10", "mutter", "gnome-shell"])
    report["settings"] = {}
    for schema, keys in {
        "org.gnome.desktop.peripherals.touchpad": ("send-events", "tap-to-click", "natural-scroll",
            "speed", "click-method", "disable-while-typing", "left-handed"),
        "io.github.agcarbajo.TabCompanion": ("keyboard-mapping-version",),
    }.items():
        source = Gio.SettingsSchemaSource.get_default().lookup(schema, True)
        if source:
            settings = Gio.Settings.new(schema)
            report["settings"][schema] = {key: settings.get_value(key).unpack() for key in keys if source.has_key(key)}
    report["hardware_service"] = command(["systemctl", "--user", "show", "tab-companion-hardware.service",
        "-p", "ActiveState", "-p", "SubState", "-p", "Result", "-p", "NRestarts"])
    return report
