# SPDX-License-Identifier: MIT
"""Unprivileged update controls. All disk changes go through polkit."""
import json
import time
import subprocess
import threading
from pathlib import Path

from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from . import update_bundle as bundle
from .update_core import status
from .i18n import _


def size_label(value):
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GB"
    return f"{value / 1024**2:.1f} MB"


class UpdatePage(Adw.PreferencesPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.busy = False
        self.checked = False
        self.latest = None
        self.repair_tag = None
        self._hold_id = None
        self._repair_pending = False
        self.stage = None
        self._pulse_id = None
        self._transfer_start = None
        self._last_line = ""
        self.add_css_class("updates-page")
        self._css = Gtk.CssProvider()
        self._css.load_from_data(b".updates-page .card, .updates-page .boxed-list { box-shadow: none; }")
        Gtk.StyleContext.add_provider_for_display(self.get_display(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.set_margin_top(18)
        self.set_margin_bottom(18)
        group = Adw.PreferencesGroup()
        self.add(group)
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       css_classes=["card"], margin_top=2, margin_bottom=2)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=28, margin_bottom=24, margin_start=24, margin_end=24)
        hero.append(body)
        group.add(hero)
        self.icon = Gtk.Image(icon_name="software-update-available-symbolic", pixel_size=52,
                              css_classes=["accent"], halign=Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner(width_request=52, height_request=52, halign=Gtk.Align.CENTER)
        self.icon_stack = Gtk.Stack()
        self.icon_stack.add_named(self.icon, "icon")
        self.icon_stack.add_named(self.spinner, "spinner")
        body.append(self.icon_stack)
        self.heading = Gtk.Label(label=_("System updates"), wrap=True,
            justify=Gtk.Justification.CENTER, css_classes=["title-1"])
        self.description = Gtk.Label(label=_("Keep your tablet up to date."), wrap=True,
            justify=Gtk.Justification.CENTER, css_classes=["dim-label"])
        body.append(self.heading)
        body.append(self.description)
        self.release_label = Gtk.Label(wrap=True, css_classes=["accent", "heading"], visible=False)
        body.append(self.release_label)
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        body.append(actions)
        self.check = self._button(actions, _("Check for updates"), self._check)
        self._check_gesture = Gtk.GestureClick(button=1)
        self._check_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._check_gesture.connect("pressed", self._check_pressed)
        self._check_gesture.connect("released", lambda *_: self._cancel_hold())
        self._check_gesture.connect("cancel", lambda *_: self._cancel_hold())
        self.check.add_controller(self._check_gesture)
        motion = Gtk.EventControllerMotion()
        motion.connect("leave", lambda *_: self._cancel_hold())
        self.check.add_controller(motion)
        self.install = self._button(actions, _("Download update"),
            lambda *_: self._confirm(["--latest"], self.latest["tag"]), True)
        self.restart = self._button(actions, _("Restart and install"), self._restart, True)
        self.cancel = self._button(actions, _("Cancel prepared update"), lambda *_: self._start(["--cancel"]))
        actions.reorder_child_after(self.install, None)
        self.progress_group = Adw.PreferencesGroup(visible=False)
        self.add(self.progress_group)
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                              margin_top=12, margin_bottom=12)
        self.phase_label = Gtk.Label(xalign=0, wrap=True, css_classes=["heading"])
        self.progress_bar = Gtk.ProgressBar(show_text=True)
        self.transfer_label = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"])
        for widget in (self.phase_label, self.progress_bar, self.transfer_label):
            progress_box.append(widget)
        steps = Gtk.Box(spacing=8, homogeneous=True, margin_top=4)
        self.steps = []
        for label in ("Download", "Verify", "Prepare", "Ready"):
            step = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            icon = Gtk.Image(icon_name="radio-symbolic")
            step.append(icon)
            step.append(Gtk.Label(label=_(label), wrap=True, justify=Gtk.Justification.CENTER,
                                  css_classes=["caption"]))
            steps.append(step)
            self.steps.append((step, icon))
        progress_box.append(steps)
        self.progress_group.add(progress_box)

        information = Adw.PreferencesGroup()
        self.add(information)
        self.version = Adw.ActionRow(title=_("Installed build"),
            subtitle=bundle.current().get("tag") or _("Version not recorded by this build"))
        self.version.add_prefix(Gtk.Image(icon_name="computer-symbolic"))
        information.add(self.version)
        self.notes = Adw.ExpanderRow(title=_("What's new"), visible=False)
        self.notes_text = Gtk.Label(xalign=0, yalign=0, wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=False, hexpand=True,
            max_width_chars=70, margin_top=18, margin_bottom=18,
            margin_start=20, margin_end=20)
        note_style = Pango.AttrList()
        note_style.insert(Pango.attr_scale_new(1.12))
        self.notes_text.set_attributes(note_style)
        # Let the page scroll the complete notes instead of nesting a short
        # viewport inside the expander. Height follows the wrapped text.
        self.notes.add_row(self.notes_text)
        information.add(self.notes)

        other = Adw.PreferencesGroup(title=_("Other installation options"))
        self.add(other)
        row = Adw.ActionRow(title=_("Install from a ZIP"), subtitle=_("Choose a build saved on your tablet."))
        row.add_prefix(Gtk.Image(icon_name="package-x-generic-symbolic"))
        self.local = Gtk.Button(label=_("Choose file…"), valign=Gtk.Align.CENTER)
        self.local.connect("clicked", self._choose)
        row.add_suffix(self.local)
        row.set_activatable_widget(self.local)
        other.add(row)
        details_group = Adw.PreferencesGroup()
        self.add(details_group)
        self.details = Adw.ExpanderRow(title=_("Technical details"), visible=False)
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=12, right_margin=12, top_margin=12, bottom_margin=12)
        scroll = Gtk.ScrolledWindow(min_content_height=150, max_content_height=200, propagate_natural_height=True)
        scroll.set_child(self.log)
        self.details.add_row(scroll)
        details_group.add(self.details)
        self._refresh()
        self._restore_status()
        self.connect("map", self._mapped)
        self.connect("unmap", lambda *_: (self._stop_pulse(), self._cancel_hold()))

    def _mapped(self, *_args):
        if not self.checked and not self.busy and status().get("state") not in ("ready", "failed"):
            self._check()
        elif self.busy and self.stage not in ("download", "copy"):
            self._start_pulse()

    @staticmethod
    def _button(container, title, callback, primary=False):
        button = Gtk.Button(label=title, css_classes=["pill", "suggested-action"] if primary else ["pill"])
        button.connect("clicked", callback)
        container.append(button)
        return button

    def _hero(self, title, description, icon="software-update-available-symbolic", spinning=False):
        self.heading.set_text(_(title))
        self.description.set_text(_(description))
        self.icon.set_from_icon_name(icon)
        self.icon_stack.set_visible_child_name("spinner" if spinning else "icon")
        self.spinner.set_spinning(spinning)

    def _refresh(self):
        ready = status().get("state") == "ready"
        available = bool(self.latest) and bundle.release_state(self.latest) in ("newer", "unknown")
        self.check.set_visible(not ready and not self.busy)
        self.check.set_sensitive(not self.busy)
        self.install.set_visible(available and not ready and not self.busy)
        self.install.set_sensitive(available and not self.busy and not ready)
        self.local.set_sensitive(not self.busy and not ready)
        self.restart.set_visible(ready)
        self.cancel.set_visible(ready)
        self.restart.set_sensitive(not self.busy)
        self.cancel.set_sensitive(not self.busy)

    def _restore_status(self):
        state = status()
        if state.get("state") == "ready":
            self._progress({"stage": "ready", "completed": 1, "total": 1})
            self._hero("Ready to restart", "Save your work. The update will install when you restart.", "emblem-ok-symbolic")
            self.release_label.set_text(state.get("tag", ""))
            self.release_label.set_visible(True)
        elif state.get("state") == "failed":
            self._hero("The update did not complete", "Open the technical details to see what happened.", "dialog-warning-symbolic")
            self._line(state.get("error", ""))
        elif state.get("state") == "complete":
            self._hero("Update installed", "Your tablet is ready to use.", "emblem-ok-symbolic")

    def _check(self, *_args):
        if self.busy or self._repair_pending:
            return
        self.checked = True
        self.busy = True
        self._stop_pulse()
        self.progress_group.set_visible(False)
        self._refresh()
        self._hero("Checking for updates…", "Looking for the latest build on GitHub.", spinning=True)
        def worker():
            try:
                latest, error = bundle.release(), None
            except Exception as exc:
                latest, error = None, str(exc)
            GLib.idle_add(self._checked, latest, error)
        threading.Thread(target=worker, daemon=True).start()

    def _checked(self, latest, error):
        self.checked = True
        self.busy = False
        self.latest = latest
        self._refresh()
        if error:
            self._hero("Couldn't check for updates", "Check your connection and try again.", "network-offline-symbolic")
            self._line(error)
        elif bundle.release_state(latest) == "unsupported":
            self._hero("Unable to determine update availability", "This build or the published release has no compatible update information.", "dialog-information-symbolic")
        elif bundle.release_state(latest) == "older":
            self._hero("Your build is newer", "The latest GitHub release is older than your installed build.", "emblem-ok-symbolic")
        elif bundle.release_state(latest) == "unknown":
            self._hero("Installed version not identified", "A published build is available, but it cannot be compared with this installation. Review its release notes.")
        elif latest["tag"] == bundle.current().get("tag"):
            self._hero("You are up to date", "You're running the latest published build.", "emblem-ok-symbolic")
        else:
            self._hero("A new build is available", "Ubuntu, drivers and Tab Companion in one update.")
        self.release_label.set_visible(bool(latest))
        if latest:
            self.release_label.set_text(latest["tag"] + ("  ·  " + size_label(latest["size"]) if latest.get("size") else ""))
        self.notes.set_visible(bool(latest and latest.get("notes")))
        self.notes_text.set_text((latest or {}).get("notes", ""))
        return False

    def _stop_pulse(self):
        if self._pulse_id is not None:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None

    def _start_pulse(self):
        if self._pulse_id is None:
            def pulse():
                self.progress_bar.pulse()
                return True
            self._pulse_id = GLib.timeout_add(100, pulse)

    def _progress(self, event):
        stage = event.get("stage")
        titles = {"preflight": "Checking the tablet…", "copy": "Copying the selected ZIP…",
            "download": "Downloading the update…", "verify": "Verifying the build…",
            "dependencies": "Preparing packages…", "ready": "Ready to install"}
        if stage not in titles:
            return False
        if stage != self.stage:
            self._transfer_start = time.monotonic()
        self.stage = stage
        self.progress_group.set_visible(True)
        self.phase_label.set_text(_(titles[stage]))
        index = {"preflight": -1, "copy": 0, "download": 0, "verify": 1, "dependencies": 2, "ready": 4}[stage]
        for n, (box, icon) in enumerate(self.steps):
            box.set_css_classes(["success"] if n < index else (["accent"] if n == index else ["dim-label"]))
            icon.set_from_icon_name("emblem-ok-symbolic" if n < index else
                ("media-playback-start-symbolic" if n == index else "radio-symbolic"))
        done, total = event.get("completed"), event.get("total")
        definite = isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0
        if definite:
            self._stop_pulse()
            fraction = max(0.0, min(1.0, done / total))
            self.progress_bar.set_fraction(fraction)
            self.progress_bar.set_text(_("Ready") if stage == "ready" else f"{fraction:.0%}")
            if stage in ("copy", "download"):
                text = _("{done} of {total}").format(done=size_label(done), total=size_label(total))
                elapsed = time.monotonic() - self._transfer_start
                if elapsed > 1 and done > 0:
                    rate = done / elapsed
                    remaining = max(0, round((total - done) / rate))
                    text += "  ·  " + size_label(rate) + "/s"
                    if remaining > 0:
                        text += "  ·  " + (_("About {minutes} min left").format(minutes=max(1, round(remaining / 60)))
                            if remaining >= 60 else _("Less than a minute left"))
                self.transfer_label.set_text(text)
            else:
                self.transfer_label.set_text(_("Everything is prepared. Installation happens after restart."))
        else:
            self.progress_bar.set_fraction(0)
            self.progress_bar.set_text(_("Working…"))
            self._start_pulse()
            self.transfer_label.set_text(_({"preflight": "Checking power, storage and compatibility.",
                "verify": "Checking integrity and extracting the update.",
                "dependencies": "Downloading any required packages. This may take a few minutes."}.get(stage, "Working…")))
        return False

    def _cancel_hold(self):
        if self._hold_id is not None:
            GLib.source_remove(self._hold_id)
            self._hold_id = None

    def _check_pressed(self, gesture, _count, _x, _y):
        self._cancel_hold()
        if gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self._request_repair()
        else:
            self._hold_id = GLib.timeout_add(3000, self._held_check)

    def _held_check(self):
        self._hold_id = None
        self._check_gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._request_repair()
        return False

    def _request_repair(self):
        if self.busy or self._repair_pending or status().get("state") == "ready":
            return
        self._repair_pending = True
        tag = bundle.current().get("tag")
        if not tag:
            self._repair_result(None, "unknown")
            return
        def worker():
            try:
                info = bundle.release(tag)
                error = None if info.get("supports_updates") and info.get("url") and info.get("tag") == tag else "missing"
            except Exception as exc:
                # Only a missing release means it was not found; network errors
                # should invite retry instead of claiming the release is absent.
                error = "missing" if getattr(exc, "code", None) == 404 or isinstance(exc, ValueError) else "network"
            GLib.idle_add(self._repair_result, tag, error)
        threading.Thread(target=worker, daemon=True).start()

    def _repair_result(self, tag, error):
        self._repair_pending = False
        if error:
            messages = {
                "unknown": "The current version could not be found on GitHub because this installation has no recorded version.",
                "missing": "The current version could not be found on GitHub as a downloadable update for reinstallation.",
                "network": "Couldn't check the current version on GitHub. Check your connection and try again.",
            }
            dialog = Adw.MessageDialog(transient_for=self.window, modal=True,
                heading=_("Unable to reinstall"), body=_(messages[error]))
            dialog.add_response("close", _("Close"))
            dialog.set_close_response("close")
            dialog.present()
        else:
            self.repair_tag = tag
            self._confirm(["--repair"], tag)
        return False

    def _choose(self, *_args):
        chooser = Gtk.FileChooserNative(title=_("Choose a build ZIP…"), transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN, accept_label=_("Open"), cancel_label=_("Cancel"))
        file_filter = Gtk.FileFilter()
        file_filter.set_name("ZIP")
        file_filter.add_pattern("*.zip")
        chooser.add_filter(file_filter)
        chooser.connect("response", self._chosen)
        self.chooser = chooser
        chooser.show()

    def _chosen(self, chooser, response):
        path = chooser.get_file().get_path() if response == Gtk.ResponseType.ACCEPT else None
        chooser.destroy()
        if path:
            self._confirm(["--zip", path], path)

    def _confirm(self, args, label):
        dialog = Adw.MessageDialog(transient_for=self.window, modal=True,
            heading=_("Reinstall the current version?" if args == ["--repair"] else "Prepare system update?"), body=str(label) + "\n\n" + _(
                "Below 20% battery, connect the charger. Installation happens after restart. Only install local ZIPs from a trusted build of this port."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("prepare", _("Reinstall" if args == ["--repair"] else "Prepare update"))
        dialog.set_response_appearance("prepare", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self._start(args) if response == "prepare" else None)
        dialog.present()

    def _start(self, args):
        if self.busy:
            return
        self.busy = True
        self.stage = None
        self._last_line = ""
        self._refresh()
        if args and args[0] == "--zip":
            self.release_label.set_text(Path(args[1]).name)
            self.release_label.set_visible(True)
            self.notes.set_visible(False)
        elif args == ["--repair"]:
            self.release_label.set_text(self.repair_tag or "")
            self.release_label.set_visible(bool(self.repair_tag))
            self.notes.set_visible(False)
        self.log.get_buffer().set_text("")
        self._hero("Preparing your update", "You can install it once everything is ready.", spinning=True)
        if args != ["--cancel"]:
            self._progress({"stage": "preflight"})
        else:
            self._hero("Cancelling prepared update…", "Removing the prepared download.", spinning=True)
        def worker():
            try:
                process = subprocess.Popen(["pkexec", "/usr/libexec/tab-companion-update", "--progress-json", *args],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in process.stdout:
                    GLib.idle_add(self._line, line.rstrip())
                ok = process.wait() == 0
            except Exception as error:
                GLib.idle_add(self._line, str(error))
                ok = False
            GLib.idle_add(self._finished, ok)
        threading.Thread(target=worker, daemon=True).start()

    def _line(self, text):
        try:
            event = json.loads(text)
        except (ValueError, TypeError):
            event = None
        if isinstance(event, dict) and event.get("event") == "progress":
            return self._progress(event)
        if not text:
            return False
        self._last_line = text
        self.details.set_visible(True)
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        if buf.get_line_count() > 150:
            _ok, end = buf.get_iter_at_line(buf.get_line_count() - 150)
            buf.delete(buf.get_start_iter(), end)
        return False

    def _finished(self, ok):
        self.busy = False
        self._stop_pulse()
        self._refresh()
        if not ok:
            self._hero("The update was not prepared", "Your tablet has not restarted. Check the details and try again.", "dialog-warning-symbolic")
            self.phase_label.set_text(_("Preparation stopped"))
            self.progress_bar.set_text(_("Stopped"))
            self.transfer_label.set_text(self._last_line[:300])
            self.details.set_expanded(True)
        elif status().get("state") == "idle":
            self.progress_group.set_visible(False)
            self._hero("Prepared update cancelled", "You can choose another build or check again.")
        else:
            self._restore_status()
        return False

    def _restart(self, *_args):
        dialog = Adw.MessageDialog(transient_for=self.window, modal=True,
            heading=_("Restart and install?"), body=_(
                "Save your work. Below 20% battery, keep the charger connected. Do not turn off the tablet during installation."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("restart", _("Restart and install"))
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._restart_confirmed)
        dialog.present()

    def _restart_confirmed(self, _dialog, response):
        if response == "restart":
            completed = subprocess.run(["systemctl", "reboot"], capture_output=True, text=True)
            if completed.returncode:
                self._line(completed.stderr)
