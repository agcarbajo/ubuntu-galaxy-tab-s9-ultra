# SPDX-License-Identifier: MIT
"""Read a small public system summary without subprocesses or user data."""
import math
import os
from pathlib import Path
from html import escape
from . import update_bundle
from .i18n import _


def read(path):
    try:
        return Path(path).read_text().strip().replace("\0", "")
    except (OSError, UnicodeError):
        return ""


def rows():
    unknown = _("Unknown")
    installed = update_bundle.current()
    release = {}
    for line in read("/etc/os-release").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            release[key] = value.strip('"\'')
    cpu = next((line.split(":", 1)[1].strip() for line in read("/proc/cpuinfo").splitlines()
                if line.startswith(("model name", "Hardware")) and ":" in line), "")
    compatible = read("/proc/device-tree/compatible")
    if "qcom,sm8550" in compatible:
        cpu = "Qualcomm Snapdragon 8 Gen 2 for Galaxy (SM8550)"
    cpu = cpu or read("/sys/devices/soc0/machine") or unknown
    memory, uptime = unknown, unknown
    try:
        total = next(line.split()[1] for line in read("/proc/meminfo").splitlines() if line.startswith("MemTotal:"))
        memory = _("{size} GiB usable").format(size=f"{int(total) / 1024**2:.1f}")
    except (StopIteration, ValueError):
        pass
    try:
        seconds = float(read("/proc/uptime").split()[0])
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Invalid uptime")
        days, minutes = divmod(int(seconds) // 60, 1440)
        hours, minutes = divmod(minutes, 60)
        uptime = _("{days} d · {hours} h · {minutes} min").format(days=days, hours=hours, minutes=minutes)
    except (IndexError, ValueError):
        pass
    return [(_("Port version"), str(installed.get("tag") or installed.get("version") or unknown)),
            (_("Kernel"), os.uname().release),
            ("Ubuntu", release.get("PRETTY_NAME") or unknown),
            (_("Processor"), cpu), (_("RAM"), memory), (_("Uptime"), uptime)]


def markup(values):
    return "<b>" + escape(_("System build")) + "</b>\n" + "\n".join(
        f"<b>{escape(title)}:</b> {escape(value)}" for title, value in values)


def text(values):
    return "\n".join(f"{title}: {value}" for title, value in values)
