# SPDX-License-Identifier: MIT

from gi.repository import Adw, Gio, GLib, Gtk

from . import VERSION
from .actions import ACTIONS, ACTION_IDS, action_index
from .hardware import HardwareClient


GESTURES = (
    ("single-press", "Single press", "Press and release the S Pen button"),
    ("double-press", "Double press", "Press the button twice"),
    ("long-press", "Press and hold", "Keep the button pressed"),
    ("swipe-up", "Swipe up", "Hold the button and move up"),
    ("swipe-down", "Swipe down", "Hold the button and move down"),
    ("swipe-left", "Swipe left", "Hold the button and move left"),
    ("swipe-right", "Swipe right", "Hold the button and move right"),
    ("circle-clockwise", "Clockwise circle", "Draw a clockwise circle in the air"),
    ("circle-counterclockwise", "Counter-clockwise circle", "Draw a counter-clockwise circle"),
)

KEYS = (
    ("galaxy-ai", "Galaxy AI", "Dedicated AI key"),
    ("dex", "DeX", "Desktop mode key"),
    ("search-settings", "Search / Settings", "Search and settings key"),
    ("fn-f1", "Fn + F1", "Function shortcut 1"),
    ("fn-f2", "Fn + F2", "Function shortcut 2"),
    ("fn-f3", "Fn + F3", "Function shortcut 3"),
    ("fn-f4", "Fn + F4", "Function shortcut 4"),
    ("fn-f5", "Fn + F5", "Function shortcut 5"),
)


class CompanionWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Tab Companion")
        self.set_default_size(960, 760)
        self.settings = Gio.Settings.new("io.github.agcarbajo.TabCompanion")
        self.hardware = HardwareClient()
        self.hardware.connect("state-changed", self._update_hardware)
        self._build()
        self._update_hardware()

    def _build(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Tab Companion", css_classes=["title"]))
        about = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="About")
        about.connect("clicked", self._show_about)
        header.pack_end(about)
        toolbar.add_top_bar(header)

        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self.view_stack.add_titled_with_icon(self._pen_page(), "pen", "S Pen", "input-tablet-symbolic")
        self.view_stack.add_titled_with_icon(
            self._keyboard_page(), "keyboard", "Cover keyboard", "input-keyboard-symbolic"
        )

        switcher = Adw.ViewSwitcherBar(stack=self.view_stack, reveal=True)
        toolbar.set_content(self.view_stack)
        toolbar.add_bottom_bar(switcher)
        self.set_content(toolbar)

    @staticmethod
    def _page():
        page = Adw.PreferencesPage()
        page.set_margin_top(18)
        page.set_margin_bottom(18)
        return page

    def _pen_page(self):
        page = self._page()

        hero = Adw.PreferencesGroup()
        picture = Gtk.Picture.new_for_resource(
            "/io/github/agcarbajo/TabCompanion/images/spen-tip-left.svg"
        )
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_size_request(-1, 150)
        self.pen_picture = picture
        hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hero_box.set_margin_top(12)
        hero_box.set_margin_bottom(10)
        hero_box.append(picture)
        self.pen_status = Gtk.Label(css_classes=["title-2"])
        self.pen_detail = Gtk.Label(css_classes=["dim-label"])
        hero_box.append(self.pen_status)
        hero_box.append(self.pen_detail)
        hero.add(hero_box)
        page.add(hero)

        status = Adw.PreferencesGroup(title="Status")
        self.battery_row = Adw.ActionRow(title="Battery", subtitle="Not exposed by the hardware")
        self.battery_row.add_prefix(Gtk.Image(icon_name="battery-missing-symbolic"))
        status.add(self.battery_row)
        self.ble_row = Adw.ActionRow(title="Bluetooth", subtitle="S Pen is not paired")
        self.ble_row.add_prefix(Gtk.Image(icon_name="bluetooth-disabled-symbolic"))
        status.add(self.ble_row)
        page.add(status)

        gestures = Adw.PreferencesGroup(
            title="Air actions",
            description="Assignments are saved now; motion gestures become active after BLE support is available.",
        )
        for key, title, subtitle in GESTURES:
            gestures.add(self._action_row("gesture-" + key, title, subtitle))
        page.add(gestures)
        return page

    def _keyboard_page(self):
        page = self._page()
        status = Adw.PreferencesGroup(title="Cover keyboard")
        self.keyboard_row = Adw.ActionRow(
            title="EF-DX920", subtitle="Waiting for the hardware service"
        )
        self.keyboard_row.add_prefix(Gtk.Image(icon_name="input-keyboard-symbolic"))
        status.add(self.keyboard_row)
        page.add(status)

        mappings = Adw.PreferencesGroup(
            title="Special keys",
            description="Choose what each dedicated or Fn shortcut should do.",
        )
        for key, title, subtitle in KEYS:
            mappings.add(self._action_row("key-" + key, title, subtitle, learn=True))
        page.add(mappings)
        return page

    def _action_row(self, setting, title, subtitle, learn=False):
        model = Gtk.StringList.new([action.label for action in ACTIONS])
        row = Adw.ComboRow(title=title, subtitle=subtitle, model=model)
        row.set_selected(action_index(self.settings.get_string(setting)))
        row.connect("notify::selected", self._action_changed, setting)
        edit = Gtk.Button(
            icon_name="document-edit-symbolic",
            tooltip_text="Set application ID or custom command",
            valign=Gtk.Align.CENTER,
            css_classes=["flat"],
        )
        edit.connect("clicked", self._edit_target, setting, title)
        row.add_suffix(edit)
        if learn:
            capture = Gtk.Button(
                icon_name="media-record-symbolic",
                tooltip_text="Learn the next key pressed",
                valign=Gtk.Align.CENTER,
                css_classes=["flat"],
            )
            capture.connect("clicked", self._learn_key, setting)
            row.add_suffix(capture)
        return row

    def _action_changed(self, row, _param, setting):
        selected = row.get_selected()
        if selected < len(ACTION_IDS):
            self.settings.set_string(setting, ACTION_IDS[selected])

    def _edit_target(self, _button, setting, title):
        targets = self.settings.get_value("action-targets").unpack()
        entry = Gtk.Entry(
            text=targets.get(setting, ""),
            placeholder_text="Application desktop ID or shell command",
            hexpand=True,
        )
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Target for {title}",
            body="Used when the selected action is Open an application or Custom command.",
            extra_child=entry,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._target_response, setting, entry)
        dialog.present()

    def _target_response(self, _dialog, response, setting, entry):
        if response == "save":
            targets = self.settings.get_value("action-targets").unpack()
            target = entry.get_text().strip()
            if target:
                targets[setting] = target
            else:
                targets.pop(setting, None)
            self.settings.set_value("action-targets", GLib.Variant("a{ss}", targets))

    def _learn_key(self, _button, setting):
        self.hardware.begin_key_capture(setting)

    def _update_hardware(self, *_args):
        state = self.hardware.state
        status = {
            "docked": "Docked and charging" if state.pen_charging else "Docked",
            "nearby": "Undocked and nearby",
            "unpaired": "Not paired",
            "unavailable": "Hardware service unavailable",
        }.get(state.pen_state, "Unknown state")
        self.pen_status.set_label(status)

        orientation = {
            "tip-right": "Tip pointing right",
            "tip-left": "Tip pointing left",
        }.get(state.pen_orientation, "Orientation not available")
        self.pen_detail.set_label(orientation)
        resource = {
            "tip-right": "/io/github/agcarbajo/TabCompanion/images/spen-tip-right.svg",
            "tip-left": "/io/github/agcarbajo/TabCompanion/images/spen-tip-left.svg",
        }.get(
            state.pen_orientation,
            "/io/github/agcarbajo/TabCompanion/images/spen-tip-left.svg",
        )
        self.pen_picture.set_resource(resource)
        self.pen_picture.set_can_shrink(True)
        self.pen_picture.set_halign(Gtk.Align.CENTER)

        if state.pen_battery >= 0:
            self.battery_row.set_subtitle(f"{state.pen_battery}%")
        elif state.pen_state == "docked":
            charge = "Charging" if state.pen_charging else "Not charging"
            self.battery_row.set_subtitle(f"{charge}; percentage is not exposed")
        else:
            self.battery_row.set_subtitle("Not exposed by the hardware")
        self.ble_row.set_subtitle(
            "Bluetooth controller available" if state.bluetooth_available else "S Pen is not paired"
        )
        if state.capturing_key:
            keyboard = "Press the key to assign it"
        elif state.keyboard_present and state.remapping_available:
            keyboard = "Connected; remapping active"
        elif state.keyboard_present:
            keyboard = "Connected; remapping unavailable"
        else:
            keyboard = "Waiting for the hardware service"
        self.keyboard_row.set_subtitle(keyboard)

    def _show_about(self, _button):
        state = self.hardware.state
        debug = (
            f"S Pen: {state.pen_state}\n"
            f"Orientation: {state.pen_orientation}\n"
            f"Battery: {state.pen_battery}\n"
            f"Cover keyboard: {'present' if state.keyboard_present else 'not reported'}\n"
            f"Remapping: {'available' if state.remapping_available else 'unavailable'}\n"
            f"Last special key: {state.last_special_key or 'none'}"
        )
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="Tab Companion",
            application_icon="io.github.agcarbajo.TabCompanion",
            developer_name="Ubuntu gts9uwifi port contributors",
            version=VERSION,
            website="https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra",
            issue_url="https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/issues",
            license_type=Gtk.License.MIT_X11,
            comments="S Pen and cover keyboard settings for the Galaxy Tab S9 Ultra.",
            debug_info=debug,
            debug_info_filename="tab-companion-hardware.txt",
        )
        about.add_credit_section("Hardware enablement", ["Ubuntu gts9uwifi port contributors"])
        about.present()
