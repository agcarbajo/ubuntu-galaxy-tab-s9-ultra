# SPDX-License-Identifier: MIT
"""Graphical evdev key chooser used by the simulated-key action."""

from gi.repository import Adw, Gdk, Gtk

from .i18n import _


MODIFIERS = {
    29: "Ctrl",
    42: "Shift",
    56: "Alt",
    100: "AltGr",
    125: "Super",
}

KEY_ROWS = (
    (("Esc", 1), ("F1", 59), ("F2", 60), ("F3", 61), ("F4", 62),
     ("F5", 63), ("F6", 64), ("F7", 65), ("F8", 66), ("F9", 67),
     ("F10", 68), ("F11", 87), ("F12", 88)),
    (("`", 41), ("1", 2), ("2", 3), ("3", 4), ("4", 5), ("5", 6),
     ("6", 7), ("7", 8), ("8", 9), ("9", 10), ("0", 11), ("-", 12),
     ("=", 13), ("⌫", 14)),
    (("Tab", 15), ("Q", 16), ("W", 17), ("E", 18), ("R", 19),
     ("T", 20), ("Y", 21), ("U", 22), ("I", 23), ("O", 24),
     ("P", 25), ("[", 26), ("]", 27), ("\\", 43)),
    (("Caps Lock", 58), ("A", 30), ("S", 31), ("D", 32), ("F", 33),
     ("G", 34), ("H", 35), ("J", 36), ("K", 37), ("L", 38),
     (";", 39), ("'", 40), ("Enter", 28)),
    (("Shift", 42), ("Z", 44), ("X", 45), ("C", 46), ("V", 47),
     ("B", 48), ("N", 49), ("M", 50), (",", 51), (".", 52),
     ("/", 53), ("↑", 103)),
    (("Ctrl", 29), ("Super", 125), ("Alt", 56), ("Space", 57),
     ("AltGr", 100), ("←", 105), ("↓", 108), ("→", 106)),
    (("Insert", 110), ("Home", 102), ("Page Up", 104), ("Delete", 111),
     ("End", 107), ("Page Down", 109), ("Print", 99), ("Menu", 127),
     ("Pause", 119)),
)

KEY_NAMES = {code: label for row in KEY_ROWS for label, code in row}
KEY_NAMES.update(MODIFIERS)
MODIFIER_KEYVALS = {
    Gdk.KEY_Control_L: 29,
    Gdk.KEY_Control_R: 29,
    Gdk.KEY_Shift_L: 42,
    Gdk.KEY_Shift_R: 42,
    Gdk.KEY_Alt_L: 56,
    Gdk.KEY_Meta_L: 125,
    Gdk.KEY_Meta_R: 125,
    Gdk.KEY_Super_L: 125,
    Gdk.KEY_Super_R: 125,
    Gdk.KEY_ISO_Level3_Shift: 100,
}


def parse_chord(value):
    try:
        codes = tuple(int(part) for part in value.split("+") if part)
    except ValueError:
        return ()
    if not codes or len(codes) > 8 or any(code < 1 or code > 767 for code in codes):
        return ()
    return codes


def chord_label(value):
    codes = parse_chord(value)
    if not codes:
        return _("No key selected")
    return " + ".join(_(KEY_NAMES.get(code, _("Key {code}").format(code=code))) for code in codes)


class KeyChooser(Adw.Window):
    """Pick one key or shortcut graphically, or capture a physical key press."""

    def __init__(self, parent, current, selected):
        super().__init__(transient_for=parent, modal=True, title=_("Simulate a key"))
        self.set_default_size(900, 610)
        self._selected = selected
        self._modifiers = set()
        self._modifier_buttons = {}

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        hint = Adw.ActionRow(
            title=_("Choose a key on screen or press it on a physical keyboard"),
            subtitle=_("Enable Ctrl, Shift, Alt or Super first to create a shortcut."),
        )
        hint.add_prefix(Gtk.Image(icon_name="input-keyboard-symbolic"))
        self.current_label = Gtk.Label(label=chord_label(current), css_classes=["accent"])
        hint.add_suffix(self.current_label)
        content.append(hint)

        keyboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        keyboard.set_halign(Gtk.Align.CENTER)
        for row_definition in KEY_ROWS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            row.set_halign(Gtk.Align.CENTER)
            for label, code in row_definition:
                button = Gtk.ToggleButton(label=_(label)) if code in MODIFIERS else Gtk.Button(label=_(label))
                button.add_css_class("keyboard-key")
                button.set_size_request(self._key_width(label), 42)
                if code in MODIFIERS:
                    button.connect("toggled", self._modifier_toggled, code)
                    self._modifier_buttons[code] = button
                else:
                    button.connect("clicked", self._screen_key, code)
                row.append(button)
            keyboard.append(row)

        scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        scroll.set_child(keyboard)
        content.append(scroll)
        toolbar.set_content(content)
        self.set_content(toolbar)

        controller = Gtk.EventControllerKey.new()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self._physical_key)
        self.add_controller(controller)

    @staticmethod
    def _key_width(label):
        if label in {"Space"}:
            return 220
        if len(label) >= 7:
            return 82
        if len(label) >= 4:
            return 66
        return 48

    def _modifier_toggled(self, button, code):
        if button.get_active():
            self._modifiers.add(code)
        else:
            self._modifiers.discard(code)
        self._show_pending()

    def _show_pending(self):
        if self._modifiers:
            value = "+".join(str(code) for code in self._ordered_modifiers())
            self.current_label.set_label(chord_label(value) + " + …")

    def _ordered_modifiers(self):
        return tuple(code for code in MODIFIERS if code in self._modifiers)

    def _screen_key(self, _button, code):
        self._finish(self._ordered_modifiers() + (code,))

    def _physical_key(self, _controller, keyval, keycode, state):
        modifier = MODIFIER_KEYVALS.get(keyval)
        if modifier is not None:
            self._modifiers.add(modifier)
            button = self._modifier_buttons.get(modifier)
            if button is not None:
                button.set_active(True)
            return True

        # GTK/XKB hardware keycodes are the Linux evdev code plus eight.
        code = int(keycode) - 8
        if code < 1 or code > 767:
            return False
        physical_modifiers = set(self._modifiers)
        if state & Gdk.ModifierType.CONTROL_MASK:
            physical_modifiers.add(29)
        if state & Gdk.ModifierType.SHIFT_MASK:
            physical_modifiers.add(42)
        if state & Gdk.ModifierType.ALT_MASK:
            physical_modifiers.add(56)
        if state & Gdk.ModifierType.SUPER_MASK:
            physical_modifiers.add(125)
        ordered = tuple(item for item in MODIFIERS if item in physical_modifiers)
        self._finish(ordered + (code,))
        return True

    def _finish(self, codes):
        value = "+".join(str(code) for code in codes)
        self._selected(value)
        self.close()
