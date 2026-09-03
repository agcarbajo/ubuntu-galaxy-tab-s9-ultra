# SPDX-License-Identifier: MIT
"""Shared-system fingerprint settings, not a separate biometric store."""
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .fingerprint import FingerprintManager
from .fingerprint_state import FINGERS, MAX_PRINTS
from .i18n import _

FINGER_NAMES = dict(zip(FINGERS, (
    "Right index finger", "Left index finger", "Right thumb", "Left thumb",
    "Right middle finger", "Left middle finger", "Right ring finger",
    "Left ring finger", "Right little finger", "Left little finger")))


def finger_label(finger):
    return _(FINGER_NAMES.get(finger, "Fingerprint"))


class FingerprintPage(Adw.PreferencesPage):
    def __init__(self, window):
        super().__init__(margin_top=18, margin_bottom=18)
        self.window = window
        self.manager = FingerprintManager(self.updated, self.finished)
        self.prints = []
        self.loaded = False
        self.rows = []
        self.closing = False
        self.last_line = None
        self.choosing = False

        intro = Adw.PreferencesGroup(title=_("Fingerprint"))
        link = Gtk.Label(xalign=0, wrap=True, use_markup=True)
        link.set_markup(_("You can also manage these same fingerprints in <a href=\"ubuntu-settings\">Ubuntu Settings</a>."))
        link.connect("activate-link", self.open_settings)
        intro.add(link)
        self.add(intro)

        self.saved = Adw.PreferencesGroup(title=_("Saved fingerprints"))
        self.add_button = Gtk.Button(label=_("Add fingerprint"), css_classes=["suggested-action"], valign=Gtk.Align.CENTER, sensitive=False)
        self.add_button.connect("clicked", self.choose_finger)
        self.saved.set_header_suffix(self.add_button)
        self.add(self.saved)

        scan = Adw.PreferencesGroup(title=_("Recognize a fingerprint"))
        self.scan_group = scan
        row = Adw.ActionRow(title=_("Which finger is this?"), subtitle=_("Scan a saved finger to identify it. This does not unlock anything or change your fingerprints."))
        self.scan_button = Gtk.Button(label=_("Scan fingerprint"), valign=Gtk.Align.CENTER, sensitive=False)
        self.scan_button.connect("clicked", lambda _button: self.begin("scan"))
        row.add_suffix(self.scan_button)
        scan.add(row)
        self.add(scan)

        self.operation = Adw.PreferencesGroup(title=_("Reader"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12)
        self.symbol = Gtk.Image(icon_name="auth-fingerprint-symbolic", pixel_size=48)
        box.append(self.symbol)
        self.status = Gtk.Label(label=_("Ready"), wrap=True, css_classes=["title-3"])
        box.append(self.status)
        self.feedback = Gtk.Label(label=_("Choose Add fingerprint or Scan fingerprint to begin."), wrap=True, justify=Gtk.Justification.CENTER)
        box.append(self.feedback)
        self.progress = Gtk.ProgressBar(show_text=True, visible=False)
        box.append(self.progress)
        self.samples = Gtk.Label(wrap=True, css_classes=["dim-label"], visible=False)
        box.append(self.samples)
        self.inactivity = Gtk.Label(label=_("Automatically cancels after 30 seconds without touching the reader. Each new touch renews this time."), wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"])
        box.append(self.inactivity)
        self.cancel_button = Gtk.Button(label=_("Cancel"), halign=Gtk.Align.CENTER, visible=False)
        self.cancel_button.connect("clicked", lambda _b: self.cancel())
        box.append(self.cancel_button)
        self.operation.add(box)
        self.add(self.operation)

        diagnostics = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow(title=_("Diagnostics"), subtitle=_("Results are saved even when an operation is cancelled."))
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
        scroll = Gtk.ScrolledWindow(min_content_height=120, max_content_height=180, propagate_natural_height=True,
                                   hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.log)
        expander.add_row(scroll)
        diagnostics.add(expander)
        refresh = Adw.ActionRow(title=_("Synchronize with Ubuntu Settings"), subtitle=_("The same fingerprints are used by both applications and the lock screen."))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Refresh"), valign=Gtk.Align.CENTER)
        self.refresh_button.connect("clicked", lambda _button: self.refresh())
        refresh.add_suffix(self.refresh_button)
        diagnostics.add(refresh)
        self.add(diagnostics)
        self.connect("map", lambda _page: self.refresh())
        window.connect("notify::is-active", lambda *_args: self.refresh() if window.is_active() and self.get_mapped() else None)
        self.session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.lock_subscription = self.session_bus.signal_subscribe(
            "org.gnome.ScreenSaver", "org.gnome.ScreenSaver", "ActiveChanged", "/org/gnome/ScreenSaver",
            None, Gio.DBusSignalFlags.NONE, self.lock_changed)

    @property
    def running(self):
        return self.manager.running

    def lock_changed(self, _bus, _sender, _path, _interface, _signal, params):
        if params.unpack()[0]:
            self.cancel()

    def refresh(self):
        if not self.running and not self.closing and not self.choosing:
            self.manager.start("list")

    def set_controls(self):
        busy = self.running
        self.add_button.set_sensitive(self.loaded and not busy and len(self.prints) < MAX_PRINTS)
        self.scan_button.set_sensitive(self.loaded and not busy and bool(self.prints))
        self.refresh_button.set_sensitive(not busy)
        for row in self.rows:
            row.set_sensitive(not busy)

    def render_prints(self):
        for row in self.rows:
            self.saved.remove(row)
        self.rows = []
        self.saved.set_description(_("{count} of {maximum} fingerprints registered").format(count=len(self.prints), maximum=MAX_PRINTS))
        if not self.prints:
            row = Adw.ActionRow(title=_("No fingerprints yet"), subtitle=_("Add a finger to use fingerprint login in Ubuntu."))
            row.add_prefix(Gtk.Image(icon_name="auth-fingerprint-symbolic"))
            self.saved.add(row)
            self.rows.append(row)
        for finger in self.prints:
            row = Adw.ActionRow(title=finger_label(finger), subtitle=_("Available in Companion and Ubuntu"))
            row.add_prefix(Gtk.Image(icon_name="auth-fingerprint-symbolic"))
            remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Delete {finger}").format(finger=finger_label(finger)), valign=Gtk.Align.CENTER, css_classes=["flat"])
            remove.connect("clicked", self.confirm_delete, finger)
            row.add_suffix(remove)
            self.saved.add(row)
            self.rows.append(row)
        self.set_controls()

    def choose_finger(self, _button):
        self.choosing = True
        chooser = Adw.Window(transient_for=self.window, modal=True, title=_("Add fingerprint"), default_width=400, default_height=560)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        choices = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                              margin_start=16, margin_end=16, margin_top=16, margin_bottom=16)
        for finger in FINGERS:
            if finger in self.prints:
                continue
            row = Adw.ActionRow(title=finger_label(finger), activatable=True)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", self.finger_chosen, chooser, finger)
            choices.append(row)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(choices)
        toolbar.set_content(scroll)
        chooser.set_content(toolbar)
        chooser.connect("close-request", lambda _window: (setattr(self, "choosing", False), False)[1])
        chooser.present()

    def finger_chosen(self, _row, chooser, finger):
        self.begin("enroll", finger)
        chooser.close()

    def confirm_delete(self, _button, finger):
        self.choosing = True
        dialog = Adw.MessageDialog(transient_for=self.window, modal=True,
            heading=_("Delete {finger}?").format(finger=finger_label(finger)),
            body=_("This removes this fingerprint from Companion and Ubuntu login. Your other fingerprints and password are not changed."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        def respond(_dialog, response):
            if response == "delete":
                self.begin("delete", finger)
            self.choosing = False
        dialog.connect("response", respond)
        dialog.present()

    def begin(self, mode, finger=None):
        if self.running:
            return
        self.log.get_buffer().set_text("")
        self.last_line = None
        self.manager.start(mode, finger)
        self.set_controls()

    def cancel(self):
        self.manager.stop()

    def updated(self, state):
        if state["mode"] == "list":
            self.set_controls()
            return
        status = state["status"]
        busy = self.running
        # Keep guidance/progress/Cancel on screen during enrollment, including
        # narrow portrait windows, instead of below the entire saved list.
        self.saved.set_visible(not busy)
        self.scan_group.set_visible(not busy)
        self.cancel_button.set_visible(busy)
        self.cancel_button.set_sensitive(status != "stopping")
        self.set_controls()
        enrolling = state["mode"] == "enroll"
        self.progress.set_visible(enrolling)
        self.samples.set_visible(enrolling)
        if state["aggregates"] or not state["contact_seen"] or status == "completed":
            coverage = state["coverage"]
            accepted = state["accepted"]
            self.progress.set_fraction(coverage / 100)
            self.progress.set_text(f"{coverage}%")
            self.samples.set_label(_("{accepted} valid readings · approximately {remaining} more · {retries} retries").format(
                accepted=accepted, remaining=max(0, 17 - accepted) if status != "completed" else 0, retries=state["retries"]))
        else:
            # Native stages measure algorithm progress, NOT finger placements.
            fraction = min(0.99, state["stages"] / max(1, state["total_stages"]))
            self.progress.set_fraction(fraction)
            self.progress.set_text(f"{round(fraction * 100)}%")
            self.samples.set_label(_("{stages} of {total} processing stages · {retries} retries").format(stages=state["stages"], total=state["total_stages"], retries=state["retries"]))
        title = {
            "starting": _("Preparing reader…"), "running": _("Registering {finger}").format(finger=finger_label(state.get("finger"))) if enrolling else _("Reading fingerprint…"),
            "stopping": _("Stopping safely…"), "completed": _("Fingerprint registered"),
            "matched": _("Recognized: {finger}").format(finger=finger_label(state.get("matched_finger"))),
            "not-matched": _("Fingerprint not recognized"), "deleted": _("Fingerprint deleted"),
            "cancelled": _("Cancelled"), "timeout": _("Cancelled due to inactivity"), "failed": _("Could not complete the operation"),
        }.get(status, _("Ready"))
        self.status.set_label(title)
        text = {
            "place": _("Place your finger on the fingerprint icon, hold briefly, then lift it completely."),
            "hold": _("Keep your finger still while the reader lights up."),
            "accepted": _("Good reading. Lift your finger and touch again at a slightly different angle."),
            "retry": _("The reading was not clear. Lift your finger, cover the reader fully and try again."),
            "next": _("Lift your finger and touch again to check the next saved fingerprint."),
        }.get(state.get("feedback"), "")
        if status == "running" and not enrolling and state.get("candidate"):
            text += "\n" + _("Checking {finger} ({index}/{count})").format(finger=finger_label(state["candidate"]), index=state["index"], count=state["count"])
        if status == "completed":
            text = _("Ready to use in Ubuntu login and the lock screen. The reader has been released.")
        elif status == "matched":
            text = _("This is one of your saved fingerprints. No settings were changed.")
        elif status == "not-matched":
            text = _("None of your saved fingerprints matched. You can scan again.")
        elif status == "deleted":
            text = _("Your other fingerprints and password are unchanged.")
        elif status in ("cancelled", "timeout"):
            text = _("The reader is available again. You can start another operation.")
        elif status == "failed":
            text = self.error_text(state.get("error"))
        elif status == "starting":
            text = _("Ubuntu may ask for authorization. Do not touch the reader until the icon appears.")
        self.feedback.set_label(text)
        for css in ("error", "success"):
            self.feedback.remove_css_class(css)
        if status == "running" and state.get("feedback") == "retry":
            self.feedback.add_css_class("error")
        elif status == "running" and state.get("feedback") == "accepted":
            self.feedback.add_css_class("success")
        self.symbol.set_from_icon_name("emblem-ok-symbolic" if status in ("completed", "matched", "deleted") else "dialog-warning-symbolic" if status in ("failed", "not-matched") else "auth-fingerprint-symbolic")
        for css in ("success", "error"):
            self.status.remove_css_class(css)
        if status in ("completed", "matched"):
            self.status.add_css_class("success")
        elif status in ("failed", "not-matched"):
            self.status.add_css_class("error")
        self.inactivity.set_visible(status in ("running", "starting"))
        self.inactivity.set_label(_("Touch the reader within {seconds} seconds to continue.").format(seconds=state["remaining"]) if status == "running" and state["remaining"] <= 10 else _("Automatically cancels after 30 seconds without touching the reader. Each new touch renews this time."))
        line = f"{status} · {state.get('last_result', '')} · {state['coverage']}% · {state['accepted']} · {state['retries']}"
        if line != self.last_line:
            self.last_line = line
            buffer = self.log.get_buffer()
            buffer.insert(buffer.get_end_iter(), line + "\n")

    @staticmethod
    def error_text(error):
        if error in ("AlreadyInUse", "ClaimDevice"):
            return _("The reader is in use. Close the fingerprint dialog in Ubuntu Settings and try again.")
        if error in ("PermissionDenied", "NotAuthorized"):
            return _("Authorization was denied. Unlock your session and try again.")
        if error in ("NoEnrolledPrints",):
            return _("No saved fingerprints were found. Add one first.")
        if error == "AlreadyEnrolled":
            return _("That finger is already registered, or all ten spaces are occupied. Refresh the list.")
        return _("The reader could not complete the request. Try again; details are saved in Diagnostics.")

    def finished(self, state):
        self.cancel_button.set_visible(False)
        self.saved.set_visible(True)
        self.scan_group.set_visible(True)
        if state["mode"] == "list":
            if state["status"] == "listed":
                self.prints = state["prints"]
                self.loaded = True
                self.render_prints()
            else:
                self.loaded = False
                self.saved.set_description(self.error_text(state.get("error")))
        elif self.manager.log_path:
            buffer = self.log.get_buffer()
            buffer.insert(buffer.get_end_iter(), self.manager.log_path + "\n")
        self.set_controls()
        if self.closing:
            self.window.close()
        elif state["mode"] != "list":
            self.refresh()

    def open_settings(self, _label, _uri):
        if self.running:
            self.feedback.set_label(_("Finish or cancel the current operation before opening Ubuntu Settings."))
            return True
        try:
            app = Gio.DesktopAppInfo.new("gnome-users-panel.desktop")
            if app is None:
                app = Gio.AppInfo.create_from_commandline("gnome-control-center system users", None, Gio.AppInfoCreateFlags.NONE)
            app.launch([], Gdk.Display.get_default().get_app_launch_context())
        except GLib.Error:
            self.feedback.set_label(_("Could not open Ubuntu Settings."))
        return True

    def dispose(self):
        if self.lock_subscription:
            self.session_bus.signal_unsubscribe(self.lock_subscription)
            self.lock_subscription = 0
