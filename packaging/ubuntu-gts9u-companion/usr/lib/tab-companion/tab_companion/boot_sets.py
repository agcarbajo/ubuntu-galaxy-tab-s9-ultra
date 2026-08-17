# SPDX-License-Identifier: MIT
"""UI-side client for the boot switch, kept off the main thread.

Every privileged step goes through pkexec: reading is allowed silently, and
changing the system asks for a password.  Nothing here touches a block device
directly, which is the same boundary hardware.py draws for sysfs.
"""

import json
import os
import subprocess
import threading

from gi.repository import GLib


STATUS_HELPER = "/usr/libexec/tab-companion-boot-status"
SWITCH_HELPER = "/usr/libexec/tab-companion-boot-switch"
NOASK_HELPER = "/usr/libexec/tab-companion-boot-noask"


def available():
    """Whether this build carries the helpers at all."""
    return os.path.exists(STATUS_HELPER) and os.path.exists(SWITCH_HELPER)


def noask_available():
    """Whether this build can also drop the password prompt.

    Older device packages have the switch helpers but not this one, and the
    row is hidden rather than shown broken.
    """
    return os.path.exists(NOASK_HELPER)


def read_status(on_done):
    """Reads the status off the main thread and calls back on it."""

    def worker():
        result = {"current": None, "sets": [], "error": None}
        try:
            completed = subprocess.run(
                ["pkexec", STATUS_HELPER],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if completed.returncode == 0:
                result.update(json.loads(completed.stdout))
            else:
                result["error"] = completed.stderr.strip() or "no pude leer el estado"
        except Exception as error:  # noqa: BLE001 - surfaced in the UI
            result["error"] = str(error)
        GLib.idle_add(on_done, result)

    threading.Thread(target=worker, daemon=True).start()


def _noask_state():
    """Reads the current state, blocking; False if anything goes wrong.

    This goes through the status helper rather than the noask one because
    reading the rule needs root either way, and boot-status is the reader
    polkit already allows without a password.
    """
    try:
        completed = subprocess.run(
            ["pkexec", STATUS_HELPER],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            return False
        return bool(json.loads(completed.stdout).get("noask"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def set_noask(enabled, on_done):
    """Turns the prompt off or back on, then reports what actually happened.

    The callback gets the state read back from the system rather than the one
    that was asked for, so a cancelled password dialog, a refusal or a crash
    all land the same way: the switch ends up showing what is true.
    """

    def worker():
        try:
            subprocess.run(
                ["pkexec", NOASK_HELPER, "on" if enabled else "off"],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        GLib.idle_add(on_done, _noask_state())

    threading.Thread(target=worker, daemon=True).start()


def switch(set_id, reboot, on_progress, on_done):
    """Writes a set, reporting each line as the helper prints it."""

    def worker():
        ok = False
        try:
            argv = ["pkexec", SWITCH_HELPER, set_id]
            if reboot:
                argv.append("--reboot")
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # pkexec's own refusals are not JSON, and they matter.
                    event = {"kind": "error", "message": line}
                GLib.idle_add(on_progress, event)
            ok = process.wait() == 0
        except Exception as error:  # noqa: BLE001 - surfaced in the UI
            GLib.idle_add(on_progress, {"kind": "error", "message": str(error)})
        GLib.idle_add(on_done, ok)

    threading.Thread(target=worker, daemon=True).start()
