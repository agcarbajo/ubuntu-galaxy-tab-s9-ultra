# SPDX-License-Identifier: MIT
import datetime
import json
import subprocess
import threading
import os
from pathlib import Path
import tempfile

from gi.repository import Adw, Gio, GLib, Gtk
from .i18n import _
from .keyboard_diagnostics import collect_session

def add_to_about(about):
    # Place the action beside Debugging Information, inside Troubleshooting.
    def find_group(widget):
        if isinstance(widget, Adw.ActionRow):
            target = widget.get_action_target_value()
            if widget.get_action_name() == "navigation.push" and target and target.unpack() == "debuginfo":
                parent = widget.get_parent()
                while parent and not isinstance(parent, Adw.PreferencesGroup):
                    parent = parent.get_parent()
                return parent
        child = widget.get_first_child()
        while child:
            group = find_group(child)
            if group is not None:
                return group
            child = child.get_next_sibling()
        return None
    group = find_group(about)
    if group is None:
        return None
    row = Adw.ActionRow(title=_("Save keyboard cover logs…"),
        subtitle=_("Diagnose keyboard and touchpad connection problems."), activatable=True)
    row.add_suffix(Gtk.Image(icon_name="document-save-symbolic"))
    row.connect("activated", lambda *_args: confirm(about))
    group.add(row)
    return row


def message(parent, title, body):
    dialog = Adw.MessageDialog(transient_for=parent, modal=True, heading=title, body=body)
    dialog.add_response("close", _("Close"))
    dialog.present()


def confirm(parent):
    dialog = Adw.MessageDialog(transient_for=parent, modal=True,
        heading=_("Collect keyboard cover logs?"),
        body=_("For 20 seconds after authorization, this test records the cover keyboard’s key presses, releases and repeats, including keys that could reveal what you type. Do not enter passwords or sensitive information. The report is saved locally in your diagnostics folder; nothing is sent automatically."))
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("collect", _("Collect logs"))
    dialog.set_response_appearance("collect", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _dialog, response: collect(parent) if response == "collect" else None)
    dialog.present()


def collect(parent):
    progress = Adw.Window(transient_for=parent, modal=True, deletable=False,
                         title=_("Collecting keyboard cover logs…"), default_width=440)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                  margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
    box.append(Gtk.Spinner(spinning=True, height_request=32))
    box.append(Gtk.Label(label=_("Keep the cover connected and try its keyboard and touchpad."),
                         wrap=True, max_width_chars=48))
    progress.set_content(box)
    progress.present()
    capture_label = Gtk.Label(wrap=True, max_width_chars=48)
    box.append(capture_label)
    def show_capture():
        capture_label.set_text(_("Recording key presses for 20 seconds. Do not type sensitive information."))
        return False
    def worker():
        try:
            report = {"created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      "session": collect_session()}
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            def capture_call(method):
                return bus.call_sync("io.github.agcarbajo.TabCompanion.Hardware",
                    "/io/github/agcarbajo/TabCompanion/Hardware",
                    "io.github.agcarbajo.TabCompanion.Hardware", method, None, None,
                    Gio.DBusCallFlags.NONE, 3000, None)
            started = False
            with subprocess.Popen(["pkexec", "/usr/libexec/tab-companion-keyboard-diagnostics", "--record-keys"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8") as process:
                timeout = threading.Timer(120, process.kill)
                timeout.start()
                try:
                    authorized = process.stdout.readline()
                    if not authorized:
                        _out, error = process.communicate()
                        if process.returncode == 126:
                            GLib.idle_add(progress.close)
                            return
                        raise RuntimeError(error.strip() or "Diagnostic authorization failed")
                    if json.loads(authorized).get("event") != "authorized":
                        raise RuntimeError("Unexpected collector response")
                    capture_call("BeginKeyboardCapture")
                    started = True
                    GLib.idle_add(show_capture)
                    output, error = process.communicate(input="start\n", timeout=90)
                    keys = json.loads(capture_call("FinishKeyboardCapture").unpack()[0])
                    started = False
                    if process.returncode:
                        raise RuntimeError(error.strip() or "Collector failed")
                    report["system"] = json.loads(output)
                    report["keyboard_capture"] = keys
                finally:
                    timeout.cancel()
                    if process.poll() is None:
                        process.kill()
                    if started:
                        try:
                            capture_call("FinishKeyboardCapture")
                        except GLib.Error:
                            pass  # Service expires the buffer even if the UI vanishes.
            GLib.idle_add(finished, json.dumps(report, ensure_ascii=False, indent=2) + "\n", None)
        except Exception as error:
            GLib.idle_add(finished, None, str(error))
    def finished(text, error):
        progress.close()
        if error:
            message(parent, _("Could not collect keyboard cover logs"), error)
        else:
            save(parent, text)
        return False
    threading.Thread(target=worker, daemon=True).start()


def save_report(text):
    documents = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
    destinations = [Path(documents or Path.home()) / "Tab Companion" / "Diagnostics",
                    Path.home() / ".local/state/tab-companion/diagnostics"]
    last_error = None
    for directory in destinations:
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            prefix = "keyboard-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-"
            fd, filename = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                os.unlink(filename)
                raise
            return Path(filename)
        except OSError as error:
            last_error = error
    raise last_error


def save(parent, text):
    try:
        path = save_report(text)
        message(parent, _("Keyboard cover logs saved"), _("Report saved to: {path}").format(path=path)
                + "\n\n" + _("Review the recorded key presses before sharing this report."))
    except OSError as error:
        # Keep the completed report alive so a transient storage error can be retried.
        dialog = Adw.MessageDialog(transient_for=parent, modal=True,
            heading=_("Could not save keyboard cover logs"), body=str(error))
        dialog.add_response("close", _("Close"))
        dialog.add_response("retry", _("Retry"))
        dialog.connect("response", lambda _d, response: save(parent, text) if response == "retry" else None)
        dialog.present()
