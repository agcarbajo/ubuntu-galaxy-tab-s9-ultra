# SPDX-License-Identifier: MIT

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio

from . import APP_ID, VERSION
from .window import CompanionWindow


class CompanionApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self._activate)

    def _activate(self, _app):
        window = self.props.active_window
        if window is None:
            window = CompanionWindow(self)
        window.present()


def main(argv):
    return CompanionApplication().run(argv)
