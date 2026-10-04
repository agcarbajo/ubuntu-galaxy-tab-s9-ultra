#!/usr/bin/env python3
"""GTK and fake desktop notification bus; no Internet, device or systemd writes.

Run with a compiled schema, GSETTINGS_BACKEND=memory and a private session bus.
"""
from pathlib import Path
import sys
import tempfile
import subprocess
import types
from unittest.mock import patch
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"))
from tab_companion import main, update_monitor as monitor, update_page
from tab_companion.window import CompanionWindow

main._ = update_page._ = lambda text: text
Adw.init()
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
              "RequestName", GLib.Variant("(su)", ("org.freedesktop.Notifications", 0)),
              GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, -1, None)
interface = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
<arg type="u" direction="out"/></method>
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
</interface></node>''').interfaces[0]
messages = []
def method(_bus, _sender, _path, _interface, name, parameters, invocation):
    if name == "Notify":
        messages.append(parameters.unpack())
        invocation.return_value(GLib.Variant("(u)", (1,)))
    elif name == "GetCapabilities":
        invocation.return_value(GLib.Variant("(as)", (["body", "actions"],)))
    else:
        invocation.return_value(GLib.Variant("()", ()))
bus.register_object("/org/freedesktop/Notifications", interface, method, None, None)

def drain(seconds=0.5):
    loop = GLib.MainLoop()
    GLib.timeout_add(int(seconds * 1000), lambda: (loop.quit(), False)[1])
    loop.run()

with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", XDG_CACHE_HOME=cache), \
     patch.object(monitor.bundle, "current", return_value={"version": "1.3.0", "tag": "v1.3.0"}), \
     patch.object(update_page, "status", return_value={"state": "idle"}):
    app = main.CompanionApplication()
    app.register(None)
    with patch.object(main.update_bundle, "release") as request:
        app._weekly_check()
        request.assert_not_called()  # default opt-out
    settings = Gio.Settings.new("io.github.agcarbajo.TabCompanion")
    settings.set_boolean("weekly-update-checks", True)
    info = {"tag": "v1.4.0", "supports_updates": True, "sha256": "a" * 64, "size": 1024}
    with patch.object(main.update_bundle, "release", return_value=info) as request:
        app._weekly_check()
        drain(1)
        request.assert_called_once()
        app._weekly_check()
        request.assert_called_once()  # successful check consumed this week
    with patch.object(app, "_weekly_check") as requested:
        bus.call("io.github.agcarbajo.TabCompanion", "/io/github/agcarbajo/TabCompanion",
                 "org.freedesktop.Application", "ActivateAction",
                 GLib.Variant("(sava{sv})", ("check-updates", [], {})), None,
                 Gio.DBusCallFlags.NONE, 30000, None, None, None)
        drain()
        requested.assert_called_once()  # same action used by the timer helper
    assert len(messages) == 1, messages
    assert messages[0][3] == "Update available"
    assert "v1.4.0" in messages[0][4]
    assert "default" in messages[0][5]
    assert messages[0][6]["desktop-entry"] == "io.github.agcarbajo.TabCompanion"
    app.hold()
    app._weekly_result(info, None)
    drain()
    assert len(messages) == 1  # same asset does not notify twice
    window = Adw.ApplicationWindow(application=app, default_width=760, default_height=740)
    window.settings = settings
    window.view_stack = Adw.ViewStack()
    window.view_stack.add_titled_with_icon(Gtk.Label(label="Preview"), "pen", "S Pen", "input-tablet-symbolic")
    window.update_page = update_page.UpdatePage(window)
    window.update_stack_page = window.view_stack.add_titled_with_icon(
        window.update_page, "updates", "Updates", "software-update-available-symbolic")
    window.refresh_update_badge = types.MethodType(CompanionWindow.refresh_update_badge, window)
    window.refresh_update_badge()
    assert window.update_stack_page.get_needs_attention()
    toolbar = Adw.ToolbarView()
    toolbar.set_content(window.view_stack)
    toolbar.add_bottom_bar(Adw.ViewSwitcherBar(stack=window.view_stack, reveal=True))
    window.set_content(toolbar)
    window.update_page._checked(info, None)
    with patch.object(update_page.Gio.Subprocess, "new") as start:
        window.update_page.weekly.set_active(False)
        start.assert_not_called()
        window.update_page.weekly.set_active(True)
        start.assert_called_once()
    window.present()
    drain()
    with patch.object(app, "activate"):
        app.activate_action("open-updates", None)
    assert window.view_stack.get_visible_child_name() == "updates"
    with patch.object(monitor.bundle, "current", return_value={"version": "1.4.0", "tag": "v1.4.0"}):
        window.refresh_update_badge()
        assert not window.update_stack_page.get_needs_attention()
    window.close()
print("PASS: opt-in, weekly check, real notification D-Bus, deduplication, badge and notification action")
