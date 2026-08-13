# SPDX-License-Identifier: MIT

from gi.repository import Adw, Gio, GLib, Gtk

from . import VERSION
from .actions import ACTIONS, action_index, action_label
from .hardware import HardwareClient
from .i18n import _, N_


GESTURES = (
    ("single-press", N_("Single press"), N_("Press and release the S Pen button")),
    ("double-press", N_("Double press"), N_("Press the button twice")),
    ("long-press", N_("Press and hold"), N_("Keep the button pressed")),
    ("swipe-up", N_("Swipe up"), N_("Hold the button and move up")),
    ("swipe-down", N_("Swipe down"), N_("Hold the button and move down")),
    ("swipe-left", N_("Swipe left"), N_("Hold the button and move left")),
    ("swipe-right", N_("Swipe right"), N_("Hold the button and move right")),
    ("circle-clockwise", N_("Clockwise circle"), N_("Draw a clockwise circle in the air")),
    ("circle-counterclockwise", N_("Counter-clockwise circle"), N_("Draw a counter-clockwise circle")),
)

KEYS = (
    ("galaxy-ai", "Galaxy AI", N_("Dedicated AI key")),
    ("dex", "DeX", N_("Desktop mode key")),
    ("finder", "Finder", N_("Finder key without Fn")),
    ("settings", N_("Settings"), "Fn + Finder"),
    ("fn-f1", "Fn + F1", N_("Function shortcut 1")),
    ("fn-f2", "Fn + F2", N_("Function shortcut 2")),
    ("fn-f3", "Fn + F3", N_("Function shortcut 3")),
    ("fn-f4", "Fn + F4", N_("Function shortcut 4")),
    ("fn-f5", "Fn + F5", N_("Function shortcut 5")),
    ("fn-f6", "Fn + F6", N_("Home by default")),
    ("fn-f7", "Fn + F7", N_("Brightness down by default")),
    ("fn-f8", "Fn + F8", N_("Brightness up by default")),
    ("fn-f9", "Fn + F9", N_("Mute by default")),
    ("fn-f10", "Fn + F10", N_("Volume down by default")),
    ("fn-f11", "Fn + F11", N_("Volume up by default")),
    ("fn-f12", "Fn + F12", N_("Keyboard-specific function")),
)

COMPATIBLE_KEYBOARDS = (
    ("EF-DX900", "Galaxy Tab S8 Ultra Book Cover Keyboard", False, True),
    ("EF-DX910", "Galaxy Tab S9 Ultra Book Cover Keyboard Slim", False, False),
    ("EF-DX915", "Galaxy Tab S9 Ultra Book Cover Keyboard", False, True),
    ("EF-DX920", "Galaxy Tab S10 Ultra | S9 Ultra Book Cover Keyboard Slim (AI Key)", True, False),
    ("EF-DX925", "Galaxy Tab S10 Ultra | S9 Ultra Book Cover Keyboard (AI Key)", True, True),
)


def icon_label(icon_name, label, spacing=7):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    box.append(Gtk.Image(icon_name=icon_name))
    box.append(Gtk.Label(label=label))
    return box


class AppChooser(Adw.Window):
    def __init__(self, parent, current, selected):
        super().__init__(transient_for=parent, modal=True, title=_("Choose an application"))
        self.set_default_size(520, 650)
        self._selected = selected
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        search = Gtk.SearchEntry(placeholder_text=_("Search applications"))
        search.set_margin_top(12)
        search.set_margin_bottom(8)
        search.set_margin_start(12)
        search.set_margin_end(12)
        content.append(search)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.listbox.set_margin_bottom(12)
        self.listbox.set_margin_start(12)
        self.listbox.set_margin_end(12)
        apps = sorted(
            (app for app in Gio.AppInfo.get_all() if app.should_show() and app.get_id()),
            key=lambda app: app.get_display_name().casefold(),
        )
        for app in apps:
            row = Adw.ActionRow(title=app.get_display_name(), subtitle=app.get_id(), activatable=True)
            icon = app.get_icon()
            row.add_prefix(
                Gtk.Image.new_from_gicon(icon)
                if icon is not None
                else Gtk.Image(icon_name="application-x-executable-symbolic")
            )
            check = Gtk.Image(icon_name="object-select-symbolic")
            check.set_visible(app.get_id() == current)
            row.add_suffix(check)
            row._search_text = f"{app.get_display_name()} {app.get_id()}".casefold()
            row.connect("activated", self._choose, app.get_id())
            self.listbox.append(row)
        search.connect("search-changed", self._search_changed)

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.listbox)
        content.append(scroll)
        toolbar.set_content(content)
        self.set_content(toolbar)

    def _search_changed(self, entry):
        query = entry.get_text().strip().casefold()
        self.listbox.set_filter_func(lambda row: not query or query in row._search_text)

    def _choose(self, _row, desktop_id):
        self._selected(desktop_id)
        self.close()


class ActionChooser(Adw.Window):
    """Non-recycling action list; avoids Gtk.DropDown touch/scroll mis-hits."""

    def __init__(self, parent, title, setting):
        super().__init__(transient_for=parent, modal=True, title=title)
        self.set_default_size(460, 610)
        self.parent_window = parent
        self.setting = setting
        current = parent.settings.get_string(setting)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        choices = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        choices.set_margin_top(12)
        choices.set_margin_bottom(12)
        choices.set_margin_start(12)
        choices.set_margin_end(12)
        for action in ACTIONS:
            row = Adw.ActionRow(title=_(action.label), activatable=True)
            row.add_prefix(Gtk.Image(icon_name=action.icon_name))
            check = Gtk.Image(icon_name="object-select-symbolic")
            check.set_visible(action.action_id == current)
            row.add_suffix(check)
            row.connect("activated", self._choose, action.action_id)
            choices.append(row)

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(choices)
        toolbar.set_content(scroll)
        self.set_content(toolbar)

    def _choose(self, _row, action_id):
        self.close()
        if action_id == "app":
            GLib.idle_add(self.parent_window._choose_application, self.setting)
        elif action_id == "command":
            GLib.idle_add(self.parent_window._edit_command, self.setting)
        else:
            self.parent_window.settings.set_string(self.setting, action_id)


class CompanionWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Tab Companion")
        self.set_default_size(960, 760)
        self.settings = Gio.Settings.new("io.github.agcarbajo.TabCompanion")
        self.hardware = HardwareClient()
        self.action_buttons = {}
        self.key_rows = {}
        self.hardware.connect("state-changed", self._update_hardware)
        self.settings.connect("changed::known-keyboard-model", self._known_keyboard_changed)
        self.settings.connect("changed::known-keyboard-name", self._known_keyboard_changed)
        self._build()
        self._update_hardware()

    def _build(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Tab Companion", css_classes=["title"]))
        about = Gtk.Button(icon_name="help-about-symbolic", tooltip_text=_("About"))
        about.connect("clicked", self._show_about)
        header.pack_end(about)
        toolbar.add_top_bar(header)

        self.view_stack = Adw.ViewStack(vexpand=True)
        self.view_stack.add_titled_with_icon(self._pen_page(), "pen", "S Pen", "input-tablet-symbolic")
        self.view_stack.add_titled_with_icon(
            self._keyboard_page(), "keyboard", _("Cover keyboard"), "input-keyboard-symbolic"
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
        picture = Gtk.Picture.new_for_resource("/io/github/agcarbajo/TabCompanion/images/spen-tip-left.svg")
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_size_request(-1, 150)
        self.pen_picture = picture
        hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hero_box.set_margin_top(12)
        hero_box.set_margin_bottom(10)
        hero_box.append(picture)
        self.pen_status = Gtk.Label(css_classes=["title-2"], wrap=True, justify=Gtk.Justification.CENTER)
        hero_box.append(self.pen_status)
        hero.add(hero_box)
        page.add(hero)

        status = Adw.PreferencesGroup(title=_("Battery"))
        self.battery_row = Adw.ActionRow(title=_("S Pen battery"))
        self.battery_icon = Gtk.Image(icon_name="battery-missing-symbolic")
        self.battery_row.add_prefix(self.battery_icon)
        self.battery_bar = Gtk.ProgressBar(width_request=220, valign=Gtk.Align.CENTER, show_text=True)
        self.battery_row.add_suffix(self.battery_bar)
        status.add(self.battery_row)
        page.add(status)

        gestures = Adw.PreferencesGroup(
            title=_("Air actions"),
            description=_("Choose what the S Pen button and each air gesture should do."),
        )
        for key, title, subtitle in GESTURES:
            gestures.add(self._action_row("gesture-" + key, _(title), _(subtitle)))
        page.add(gestures)
        return page

    def _keyboard_page(self):
        page = self._page()
        self.keyboard_empty = Adw.PreferencesGroup()
        empty = Adw.StatusPage(
            icon_name="input-keyboard-symbolic",
            title=_("Connect a compatible keyboard cover to continue"),
            description=_("Tab Companion will remember it, so you can configure it later even when it is disconnected."),
        )
        compatible = Gtk.Button(css_classes=["pill"], halign=Gtk.Align.CENTER)
        compatible.set_child(icon_label("view-list-symbolic", _("Compatible keyboards")))
        compatible.connect("clicked", self._show_compatible_keyboards)
        empty.set_child(compatible)
        self.keyboard_empty.add(empty)
        page.add(self.keyboard_empty)

        self.keyboard_status_group = Adw.PreferencesGroup(title=_("Cover keyboard"))
        header_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        compatible_small = Gtk.Button(icon_name="view-list-symbolic", tooltip_text=_("Compatible keyboards"), css_classes=["flat"])
        compatible_small.connect("clicked", self._show_compatible_keyboards)
        header_buttons.append(compatible_small)
        self.keyboard_status_group.set_header_suffix(header_buttons)
        self.keyboard_row = Adw.ActionRow()
        self.keyboard_row.add_prefix(Gtk.Image(icon_name="input-keyboard-symbolic"))
        self.forget_keyboard_button = Gtk.Button(
            icon_name="window-close-symbolic",
            tooltip_text=_("Forget this keyboard"),
            valign=Gtk.Align.CENTER,
            css_classes=["flat"],
        )
        self.forget_keyboard_button.connect("clicked", self._forget_keyboard)
        self.keyboard_row.add_suffix(self.forget_keyboard_button)
        self.keyboard_status_group.add(self.keyboard_row)
        page.add(self.keyboard_status_group)

        self.keyboard_mappings = Adw.PreferencesGroup(
            title=_("Special keys"),
            description=_("Choose what each dedicated or Fn shortcut should do."),
        )
        reset = Gtk.Button(css_classes=["flat"])
        reset.set_child(icon_label("edit-undo-symbolic", _("Restore defaults")))
        reset.connect("clicked", self._confirm_reset_keyboard)
        self.keyboard_mappings.set_header_suffix(reset)
        for key, title, subtitle in KEYS:
            row = self._action_row("key-" + key, _(title), _(subtitle))
            self.key_rows[key] = row
            self.keyboard_mappings.add(row)
        page.add(self.keyboard_mappings)
        return page

    def _action_row(self, setting, title, subtitle):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        choose = Gtk.Button(tooltip_text=_("Choose action"), valign=Gtk.Align.CENTER)
        choose.connect("clicked", self._choose_action, setting, title)
        row.add_suffix(choose)
        self.action_buttons[setting] = choose
        self.settings.connect("changed::" + setting, self._setting_changed, setting)
        self.settings.connect("changed::action-targets", self._target_changed, setting)
        self._refresh_action_button(setting)
        return row

    def _action_button_content(self, setting):
        action_id = self.settings.get_string(setting)
        action = ACTIONS[action_index(action_id)]
        label = action_label(action_id)
        targets = self.settings.get_value("action-targets").unpack()
        target = targets.get(setting, "")
        icon = action.icon_name
        if action_id == "app" and target:
            app = Gio.DesktopAppInfo.new(target)
            if app is not None:
                label = app.get_display_name()
                if app.get_icon() is not None:
                    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
                    box.append(Gtk.Image.new_from_gicon(app.get_icon()))
                    box.append(Gtk.Label(label=label, ellipsize=3, max_width_chars=24))
                    return box
        return icon_label(icon, label)

    def _refresh_action_button(self, setting):
        button = self.action_buttons.get(setting)
        if button is not None:
            button.set_child(self._action_button_content(setting))

    def _choose_action(self, _button, setting, title):
        ActionChooser(self, _("Action for {title}").format(title=title), setting).present()

    def _setting_changed(self, _settings, _key, setting):
        self._refresh_action_button(setting)

    def _target_changed(self, _settings, _key, setting):
        self._refresh_action_button(setting)

    def _choose_application(self, setting):
        current = self.settings.get_value("action-targets").unpack().get(setting, "")
        AppChooser(self, current, lambda app_id: self._save_target(setting, "app", app_id)).present()
        return GLib.SOURCE_REMOVE

    def _edit_command(self, setting):
        current = self.settings.get_value("action-targets").unpack().get(setting, "")
        entry = Gtk.Entry(text=current, placeholder_text=_("Command to execute"), hexpand=True)
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Run a command"),
            body=_("Enter the command exactly as it should run in your user session."),
            extra_child=entry,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.connect("response", self._command_response, setting, entry)
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _command_response(self, _dialog, response, setting, entry):
        if response == "save" and entry.get_text().strip():
            self._save_target(setting, "command", entry.get_text().strip())

    def _save_target(self, setting, action, target):
        targets = self.settings.get_value("action-targets").unpack()
        targets[setting] = target
        self.settings.set_value("action-targets", GLib.Variant("a{ss}", targets))
        self.settings.set_string(setting, action)

    def _show_compatible_keyboards(self, _button):
        window = Adw.Window(transient_for=self, modal=True, title=_("Compatible keyboards"))
        window.set_default_size(560, 560)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        group = Adw.PreferencesGroup(
            title=_("Samsung keyboard covers"),
            description=_("Declared by the Galaxy Tab S9 Ultra firmware. Only EF-DX920 has been physically validated on this port."),
        )
        group.set_margin_top(18)
        group.set_margin_bottom(18)
        group.set_margin_start(18)
        group.set_margin_end(18)
        for model, name, has_ai, has_touchpad in COMPATIBLE_KEYBOARDS:
            details = []
            if has_ai:
                details.append(_("AI key"))
            if has_touchpad:
                details.append(_("touchpad"))
            support = _("Physically validated") if model == "EF-DX920" else _("Firmware-declared; not physically tested")
            subtitle = f"{model} · {support}"
            if details:
                subtitle += " · " + ", ".join(details)
            row = Adw.ActionRow(title=name, subtitle=subtitle)
            row.add_prefix(Gtk.Image(icon_name="input-keyboard-symbolic"))
            group.add(row)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(group)
        toolbar.set_content(scroll)
        window.set_content(toolbar)
        window.present()

    def _confirm_reset_keyboard(self, _button):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Restore all keyboard mappings?"),
            body=_("Every special key will return to its original action."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Restore"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._reset_keyboard_response)
        dialog.present()

    def _reset_keyboard_response(self, _dialog, response):
        if response != "reset":
            return
        for key, _title, _subtitle in KEYS:
            self.settings.reset("key-" + key)
        self.settings.reset("keyboard-source-codes")
        targets = self.settings.get_value("action-targets").unpack()
        targets = {key: value for key, value in targets.items() if not key.startswith("key-")}
        self.settings.set_value("action-targets", GLib.Variant("a{ss}", targets))

    def _forget_keyboard(self, _button):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Forget this keyboard?"),
            body=_("It will appear again automatically the next time you connect it."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("forget", _("Forget"))
        dialog.set_response_appearance("forget", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._forget_keyboard_response)
        dialog.present()

    def _forget_keyboard_response(self, _dialog, response):
        if response == "forget":
            self.settings.reset("known-keyboard-model")
            self.settings.reset("known-keyboard-name")

    def _known_keyboard_changed(self, *_args):
        self._update_keyboard()

    def _update_keyboard(self):
        state = self.hardware.state
        connected = state.keyboard_present and bool(state.keyboard_model)
        model = state.keyboard_model if connected else self.settings.get_string("known-keyboard-model")
        name = state.keyboard_name if connected else self.settings.get_string("known-keyboard-name")
        known = bool(model)
        self.keyboard_empty.set_visible(not known)
        self.keyboard_status_group.set_visible(known)
        self.keyboard_mappings.set_visible(known)
        if not known:
            return
        self.keyboard_row.set_title(name or _("Samsung Book Cover Keyboard"))
        connection = _("Connected") if connected else _("Disconnected")
        self.keyboard_row.set_subtitle(f"{model} · {connection}")
        self.forget_keyboard_button.set_visible(not connected)
        self.key_rows["galaxy-ai"].set_visible(model in {"EF-DX920", "EF-DX925"})
        if model == "EF-DX920":
            self.key_rows["fn-f12"].set_subtitle(_("No event from the EF-DX920 firmware"))
        else:
            self.key_rows["fn-f12"].set_subtitle(_("Keyboard-specific function"))

    def _update_hardware(self, *_args):
        state = self.hardware.state
        status = {
            "docked": _("Docked and charging") if state.pen_charging else _("Docked"),
            "nearby": _("Connected and ready for air gestures"),
            "paired": _("Insert the S Pen to reconnect it"),
            "unpaired": _("Not paired"),
            "unavailable": _("Hardware service unavailable"),
        }.get(state.pen_state, _("Unknown state"))
        self.pen_status.set_label(status)
        resource = {
            "tip-right": "/io/github/agcarbajo/TabCompanion/images/spen-tip-right.svg",
            "tip-left": "/io/github/agcarbajo/TabCompanion/images/spen-tip-left.svg",
        }.get(state.pen_orientation, "/io/github/agcarbajo/TabCompanion/images/spen-tip-left.svg")
        self.pen_picture.set_resource(resource)
        self.pen_picture.set_can_shrink(True)
        self.pen_picture.set_halign(Gtk.Align.CENTER)

        if state.pen_battery >= 0:
            self.battery_icon.set_from_icon_name("battery-good-symbolic")
            self.battery_bar.set_fraction(state.pen_battery / 100)
            self.battery_bar.set_text(f"{state.pen_battery}%")
            self.battery_row.set_subtitle(_("Last measured level") if state.pen_state == "paired" else "")
        else:
            self.battery_icon.set_from_icon_name("battery-missing-symbolic")
            self.battery_bar.set_fraction(0)
            self.battery_bar.set_text(_("Unknown"))
            self.battery_row.set_subtitle(_("Insert the S Pen to read its battery"))
        self._update_keyboard()

    def _show_about(self, _button):
        state = self.hardware.state
        debug = (
            f"S Pen: {state.pen_state}\n"
            f"Orientation: {state.pen_orientation}\n"
            f"Battery: {state.pen_battery}\n"
            f"Cover keyboard: {state.keyboard_model or 'not reported'}\n"
            f"Remapping: {'available' if state.remapping_available else 'unavailable'}\n"
            f"S Pen button actions: {'available' if state.button_actions_available else 'unavailable'}"
        )
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="Tab Companion",
            application_icon="io.github.agcarbajo.TabCompanion",
            developer_name=_("Ubuntu gts9uwifi port contributors"),
            version=VERSION,
            website="https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra",
            issue_url="https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/issues",
            license_type=Gtk.License.MIT_X11,
            comments=_("S Pen and cover keyboard settings for the Galaxy Tab S9 Ultra."),
            debug_info=debug,
            debug_info_filename="tab-companion-hardware.txt",
        )
        about.add_credit_section(_("Hardware enablement"), [_("Ubuntu gts9uwifi port contributors")])
        about.present()
