# SPDX-License-Identifier: MIT

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import threading
from gi.repository import Adw, Gio, GLib

from . import APP_ID, VERSION
from .window import CompanionWindow
from . import update_bundle, update_monitor
from .i18n import _


class CompanionApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.connect("activate", self._activate)
        self.connect("command-line", self._command_line)
        action = Gio.SimpleAction.new("open-updates", None)
        action.connect("activate", self._open_updates)
        self.add_action(action)
        check = Gio.SimpleAction.new("check-updates", None)
        check.connect("activate", lambda *_: self._weekly_check())
        self.add_action(check)
        self._checking_updates = False

    def _command_line(self, _app, command):
        args = command.get_arguments()[1:]
        if "--check-updates" in args:
            self._weekly_check()
        elif "--updates" in args:
            self._open_updates()
        else:
            self.activate()
        return 0

    def _open_updates(self, *_args):
        self.activate()
        self.props.active_window.view_stack.set_visible_child_name("updates")

    def _weekly_check(self):
        settings = Gio.Settings.new(APP_ID)
        if (self._checking_updates or not settings.get_boolean("weekly-update-checks")
                or not update_monitor.due(update_monitor.load())):
            return
        self._checking_updates = True
        self.hold()
        def worker():
            try:
                info, error = update_bundle.release(), None
            except Exception as exc:
                info, error = None, str(exc)
            GLib.idle_add(self._weekly_result, info, error)
        threading.Thread(target=worker, daemon=True).start()

    def _weekly_result(self, info, error):
        try:
            # The preference may have changed while the network request ran.
            if info and Gio.Settings.new(APP_ID).get_boolean("weekly-update-checks"):
                value, key = update_monitor.record(info, notify=True)
                if key:
                    notification = Gio.Notification.new(_("Update available"))
                    notification.set_body(_("Build {version} is available. Open Tab Companion to review it.").format(version=info["tag"]))
                    notification.set_icon(Gio.ThemedIcon.new("software-update-available-symbolic"))
                    notification.set_default_action("app.open-updates")
                    self.send_notification("system-update", notification)
                    update_monitor.notified(key)
                elif not update_monitor.available(value):
                    self.withdraw_notification("system-update")
                window = self.props.active_window
                if window:
                    window.refresh_update_badge()
                    if not window.update_page.busy:
                        window.update_page._checked(info, None)
        finally:
            self._checking_updates = False
            self.release()
        return False

    def _activate(self, _app):
        window = self.props.active_window
        if window is None:
            window = CompanionWindow(self)
        window.present()


def main(argv):
    return CompanionApplication().run(argv)
