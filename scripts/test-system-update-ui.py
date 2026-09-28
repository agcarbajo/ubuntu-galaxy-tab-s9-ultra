#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run on a GTK4 desktop. Opens a temporary preview; never prepares an update."""
from pathlib import Path
import sys
from unittest.mock import patch
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"))
from tab_companion import update_page

# Assertions must not depend on the desktop user's saved language preference.
update_page._ = lambda text: text

Adw.init()
with patch.object(update_page.Gio.Subprocess, "new"), patch.object(update_page.bundle, "current", return_value={}), patch.object(
        update_page, "status", return_value={"state": "idle"}):
    window = Adw.Window(title="Tab Companion — update preview", default_width=760, default_height=740)
    page = update_page.UpdatePage(window)
    window.set_content(page)
    with patch.object(update_page, "status", return_value={"state": "failed", "error": "APT stopped"}):
        page._restore_status()
        with patch.object(page, "_check") as check:
            page._mapped()
            check.assert_not_called()
        assert page.heading.get_text() == "The update did not complete"
    from tab_companion.update_translations import ES
    assert ES["Technical details"] == "Detalles t\u00e9cnicos"
    assert ES["Choose file\u2026"] == "Elegir archivo\u2026"
    for i in range(160):
        page._line("Test progress " + str(i))
    assert page.log.get_buffer().get_line_count() <= 150
    from unittest.mock import Mock
    from gi.repository import Gdk, Gtk
    gesture = Mock()
    gesture.get_current_event_state.return_value = Gdk.ModifierType.SHIFT_MASK
    with patch.object(page, "_request_repair") as request:
        page._check_pressed(gesture, 1, 0, 0)
        request.assert_called_once()
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
    gesture.get_current_event_state.return_value = Gdk.ModifierType(0)
    with patch.object(page, "_request_repair") as request:
        page._check_pressed(gesture, 1, 0, 0)
        assert page._hold_id is not None
        page._cancel_hold()
        assert page._hold_id is None
        request.assert_not_called()
        page._held_check()
        request.assert_called_once()
    with patch.object(update_page.Adw, "MessageDialog") as dialog:
        page._request_repair()
        assert "no recorded version" in dialog.call_args.kwargs["body"]
        for reason in ("missing", "network"):
            page._repair_result("v1.0.0", reason)
            assert dialog.return_value.present.called
    with patch.object(page, "_confirm") as confirm:
        page._repair_result("v1.0.0", None)
        confirm.assert_called_once_with(["--repair"], "v1.0.0")
    page._checked({"tag": "v1.0.0", "supports_updates": False}, None)
    assert not page.install.get_visible()
    page._checked({"tag": "v9.9.9", "supports_updates": True}, None)
    assert page.install.get_sensitive()
    page._checked(None, "Offline test")
    assert not page.install.get_sensitive()
    with patch.object(update_page.bundle, "current", return_value={"tag":"v1.2.0", "version":"1.2.0"}), \
         patch.object(update_page.threading, "Thread"):
        current = {"tag":"v1.2.0", "supports_updates":True, "notes":"## Installed\n**Old fix**"}
        page._checked(current, None)
        assert not page.notes.get_visible()
        assert "Old fix" in page.installed_notes.get_text()
        newer = {"tag":"v1.3.0", "supports_updates":True, "notes":"## Update\n**New fix**"}
        page._checked(newer, None)
        assert page.notes.get_visible()
        assert "New fix" in page.notes_text.get_text()
        assert "New fix" not in page.installed_notes.get_text()
        assert "Old fix" in page.installed_notes.get_text()
        page._checked(None, "Offline")
        assert not page.notes.get_visible()
        assert "Old fix" in page.installed_notes.get_text()
    page._line('{"event":"progress","stage":"download","completed":52428800,"total":104857600}')
    assert page.progress_bar.get_fraction() == 0.5
    assert page.progress_bar.get_text() == "50%"
    assert "50.0 MB" in page.transfer_label.get_text()
    page._progress({"stage": "verify"})
    assert page._pulse_id is not None
    page._progress({"stage": "dependencies"})
    page._progress({"stage": "ready", "completed": 1, "total": 1})
    assert page.progress_bar.get_fraction() == 1
    assert page._pulse_id is None
    with patch.object(update_page, "status", return_value={"state": "ready", "tag": "v9.9.9"}):
        page._refresh()
        page._restore_status()
        assert page.restart.get_visible() and not page.local.get_sensitive()
    page._finished(False)
    assert page.details.get_expanded()
    from tab_companion import window as window_module
    from types import SimpleNamespace
    window.hardware = SimpleNamespace(state=SimpleNamespace(
        pen_state="nearby", pen_orientation="tip-left", pen_battery=70,
        keyboard_model="EF-DX920", remapping_available=True,
        button_actions_available=True, haptics_available=True))
    with patch.object(window_module.Adw, "AboutWindow") as about, \
         patch.object(window_module, "add_keyboard_diagnostics"), \
         patch.object(window_module.system_summary, "rows", return_value=[
             ("Port version", "v1.2.0"), ("Kernel", "7.2"), ("Ubuntu", "Ubuntu 24.04"),
             ("Processor", "SM8550"), ("RAM", "12 GiB"), ("Uptime", "1 h")]):
        window_module.CompanionWindow._show_about(window, None)
        comments = about.call_args.kwargs["comments"]
        for value in ("v1.2.0", "7.2", "Ubuntu 24.04", "SM8550", "12 GiB", "1 h"):
            assert value in comments
        assert "<b>" in comments
        about.return_value.present.assert_called_once()
    window.present()
    loop = GLib.MainLoop()
    def finish():
        window.close()
        loop.quit()
        return False
    GLib.timeout_add_seconds(3, finish)
    loop.run()
print("GTK4/Adwaita update page: PASS")
