# SPDX-License-Identifier: MIT

import os

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import VERSION
from . import boot_sets
from .actions import ACTIONS, action_index, action_label
from .hardware import HardwareClient
from .i18n import _, N_
from .key_selector import KeyChooser, chord_label


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
KEYBOARD_HAPTIC_DURATIONS_MS = (24, 42, 66)

KEYS = (
    ("galaxy-ai", "Galaxy AI", N_("Tab Companion by default")),
    ("dex", "DeX", N_("Maximize or restore the current window by default")),
    ("finder", "Finder", N_("System search by default")),
    ("settings", N_("Settings"), N_("System Settings by default")),
    ("fn-f1", "Fn + F1", N_("Files by default")),
    ("fn-f2", "Fn + F2", N_("Web browser by default")),
    ("fn-f3", "Fn + F3", N_("Terminal by default")),
    ("fn-f4", "Fn + F4", N_("Applications by default")),
    ("fn-f5", "Fn + F5", N_("Overview by default")),
    ("fn-f6", "Fn + F6", N_("Home by default")),
    ("fn-f7", "Fn + F7", N_("Brightness down by default")),
    ("fn-f8", "Fn + F8", N_("Brightness up by default")),
    ("fn-f9", "Fn + F9", N_("Mute by default")),
    ("fn-f10", "Fn + F10", N_("Volume down by default")),
    ("fn-f11", "Fn + F11", N_("Volume up by default")),
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
        elif action_id == "key":
            GLib.idle_add(self.parent_window._choose_key, self.setting)
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
        self._updating_remote_switch = False
        self.hardware.connect("state-changed", self._update_hardware)
        self.settings.connect("changed::known-keyboard-model", self._known_keyboard_changed)
        self.settings.connect("changed::known-keyboard-name", self._known_keyboard_changed)
        self.settings.connect("changed::spen-remote-enabled", self._remote_settings_changed)
        self.settings.connect("changed::spen-remote-mode", self._remote_settings_changed)
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
        self.view_stack.add_titled_with_icon(
            self._haptics_page(), "haptics", _("Haptics"), "phone-symbolic"
        )
        if boot_sets.available():
            self.view_stack.add_titled_with_icon(
                self._system_page(), "dualboot", _("Dualboot"), "drive-multidisk-symbolic"
            )
        switcher = Adw.ViewSwitcherBar(stack=self.view_stack, reveal=True)
        toolbar.set_content(self.view_stack)
        toolbar.add_bottom_bar(switcher)
        self.set_content(toolbar)

        # Opening straight on a page is only for photographing the UI on a
        # headless compositor, where there is no pointer to click a tab with.
        initial = os.environ.get("TAB_COMPANION_PAGE")
        if initial and self.view_stack.get_child_by_name(initial) is not None:
            self.view_stack.set_visible_child_name(initial)

    @staticmethod
    def _page():
        page = Adw.PreferencesPage()
        page.set_margin_top(18)
        page.set_margin_bottom(18)
        return page

    # -- dual boot -----------------------------------------------------------

    @staticmethod
    def _format_size(value):
        """Sizes people recognise: GB as the disk is sold, not GiB."""
        gb = value / 1_000_000_000
        if gb >= 100:
            return f"{gb:.0f} GB"
        return f"{gb:.1f} GB"

    def _system_page(self):
        """Which system boots next, how much room each has, and how to swap.

        Everything privileged happens in the libexec helpers behind polkit;
        this page only asks and reports.  It has two faces: the dual-boot one,
        and a plain explanation for a tablet that only carries Linux.
        """
        self.boot_stack = Gtk.Stack(vexpand=True)

        self.boot_empty = Adw.StatusPage(
            icon_name="drive-multidisk-symbolic",
            title=_("Dual boot is not set up"),
            description=_(
                "This tablet only has Linux installed. When Android shares the "
                "storage with it, this page lets you restart into either system."
            ),
        )
        self.boot_stack.add_named(self.boot_empty, "empty")

        page = self._page()

        # One list, not two: which system is running and which one you can
        # switch to are the same question asked from either side.
        self.boot_systems = Adw.PreferencesGroup(
            title=_("Systems"),
            description=_(
                "Ubuntu and Android take turns on the four boot partitions. "
                "The tablet restarts into the one you choose; your files stay "
                "where they are."
            ),
        )
        self.boot_loading_row = Adw.ActionRow(
            title=_("Reading…"),
            subtitle=_("Checking the boot partitions."),
        )
        self.boot_systems.add(self.boot_loading_row)
        page.add(self.boot_systems)

        self.boot_storage = Adw.PreferencesGroup(
            title=_("Storage"),
            description=_("Each system has its own share of the internal storage."),
        )
        page.add(self.boot_storage)

        self.boot_progress = Adw.PreferencesGroup()
        self.boot_progress_label = Gtk.Label(
            wrap=True,
            xalign=0,
            margin_top=6,
            margin_bottom=6,
            margin_start=12,
            margin_end=12,
        )
        self.boot_progress.add(self.boot_progress_label)
        self.boot_progress.set_visible(False)
        page.add(self.boot_progress)

        shortcut = Adw.PreferencesGroup(title=_("Shortcut"))
        self.boot_tile_row = Adw.SwitchRow(
            title=_("Show in quick settings"),
            subtitle=_("Adds a button to the system menu that restarts into the other system."),
        )
        self.boot_tile_row.set_active(self._shell_extension_enabled())
        self.boot_tile_row.connect("notify::active", self._boot_tile_toggled)
        shortcut.add(self.boot_tile_row)
        page.add(shortcut)

        # Phrased as what it does, not as what it removes: a switch called
        # "ask for the password" would read inverted against the helper it
        # drives, and this is not a setting to be confused about.
        self.boot_noask_group = Adw.PreferencesGroup(title=_("Password"))
        self.boot_noask_row = Adw.SwitchRow(
            title=_("Switch systems without the password"),
            subtitle=_(
                "There is no confirmation window: the password is the "
                "confirmation. Without it, anyone holding the unlocked tablet "
                "can restart it into the other system."
            ),
        )
        self.boot_noask_row.add_prefix(Gtk.Image(icon_name="dialog-password-symbolic"))
        self._updating_noask_switch = False
        self.boot_noask_row.set_sensitive(False)
        self.boot_noask_row.connect("notify::active", self._boot_noask_toggled)
        self.boot_noask_group.add(self.boot_noask_row)
        self.boot_noask_group.set_visible(boot_sets.noask_available())
        page.add(self.boot_noask_group)

        self.boot_stack.add_named(page, "content")
        self.boot_stack.set_visible_child_name("content")

        self._boot_rows = []
        self._boot_storage_rows = []
        # The switch is filled in by the same reading that fills the list;
        # boot-status carries it, so it costs no second call and no prompt.
        self._boot_refresh()
        return self.boot_stack

    def _storage_widget(self, store):
        """One bar for the whole disk, split by system.

        Adwaita has no storage widget, so this is drawn: a single rounded bar
        whose width is the internal storage, divided in proportion to each
        system's partition.  Linux shows what it uses inside its own share;
        Android's share is drawn plain, because its usage genuinely cannot be
        read from here — it encrypts its data — and a bar that guessed would be
        worse than one that admits it.
        """
        linux = store.get("ubuntu")
        android = store.get("android")
        total = (linux["total"] if linux else 0) + (android["total"] if android else 0)
        if not total:
            return None

        # Muted so the bar reads as one object, not two competing colours.
        used_rgba = Gdk.RGBA()
        used_rgba.parse("#3584e4")
        free_rgba = Gdk.RGBA()
        free_rgba.parse("#3584e4")
        free_rgba.alpha = 0.28
        android_rgba = Gdk.RGBA()
        android_rgba.parse("#26a269")
        android_rgba.alpha = 0.55

        segments = []
        if linux:
            if linux["known"] and linux["used"]:
                segments.append((linux["used"] / total, used_rgba))
                segments.append(((linux["total"] - linux["used"]) / total, free_rgba))
            else:
                segments.append((linux["total"] / total, free_rgba))
        if android:
            segments.append((android["total"] / total, android_rgba))

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=14,
            margin_bottom=14,
            margin_start=12,
            margin_end=12,
        )

        # Without hexpand a DrawingArea is allocated no width at all, and the
        # bar silently draws into nothing.
        area = Gtk.DrawingArea(content_height=18, hexpand=True)
        area.set_draw_func(self._draw_storage_bar, segments)
        box.append(area)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        if linux:
            legend.append(self._legend_item(
                used_rgba,
                "Linux",
                _("{used} of {total} used").format(
                    used=self._format_size(linux["used"]),
                    total=self._format_size(linux["total"]),
                ),
            ))
        if android:
            legend.append(self._legend_item(
                android_rgba,
                "Android",
                self._format_size(android["total"]),
            ))
        box.append(legend)

        box.append(Gtk.Label(
            label=_("Android's usage cannot be read from Linux: it encrypts its data."),
            css_classes=["dim-label", "caption"],
            xalign=0,
            wrap=True,
        ))
        return box

    @staticmethod
    def _draw_storage_bar(_area, cr, width, height, segments):
        radius = height / 2
        cr.new_path()
        cr.arc(radius, radius, radius, 1.5708, 4.7124)
        cr.arc(width - radius, radius, radius, 4.7124, 1.5708)
        cr.close_path()
        cr.clip()

        cr.set_source_rgba(0.5, 0.5, 0.5, 0.18)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        x = 0.0
        for fraction, rgba in segments:
            span = width * fraction
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            cr.rectangle(x, 0, span, height)
            cr.fill()
            x += span

        # A hairline where the two systems meet, so the split is readable even
        # when the colours sit close together.
        if len(segments) > 1:
            boundary = width * sum(f for f, _ in segments[:-1])
            cr.set_source_rgba(1, 1, 1, 0.55)
            cr.rectangle(boundary - 1, 0, 2, height)
            cr.fill()

    @staticmethod
    def _legend_item(rgba, title, detail):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dot = Gtk.DrawingArea(content_width=12, content_height=12, valign=Gtk.Align.CENTER)

        def draw_dot(_area, cr, width, height, _data=None):
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, max(rgba.alpha, 0.75))
            cr.arc(width / 2, height / 2, min(width, height) / 2, 0, 6.2832)
            cr.fill()

        dot.set_draw_func(draw_dot)
        row.append(dot)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.append(Gtk.Label(label=title, css_classes=["heading"], xalign=0))
        text.append(Gtk.Label(label=detail, css_classes=["dim-label", "caption"], xalign=0))
        row.append(text)
        return row

    # The quick settings entry is a GNOME Shell extension, and GNOME keeps the
    # list of enabled ones in its own setting.  Editing that list is the whole
    # of turning it on and off; there is no separate switch to flip.
    SHELL_EXTENSION_UUID = "dualboot@agcarbajo.github.io"

    def _shell_extension_enabled(self):
        try:
            shell = Gio.Settings.new("org.gnome.shell")
        except GLib.Error:
            return False
        return self.SHELL_EXTENSION_UUID in shell.get_strv("enabled-extensions")

    def _boot_tile_toggled(self, row, _param):
        try:
            shell = Gio.Settings.new("org.gnome.shell")
        except GLib.Error:
            return
        enabled = list(shell.get_strv("enabled-extensions"))
        if row.get_active():
            if self.SHELL_EXTENSION_UUID not in enabled:
                enabled.append(self.SHELL_EXTENSION_UUID)
        else:
            enabled = [uuid for uuid in enabled if uuid != self.SHELL_EXTENSION_UUID]
        shell.set_strv("enabled-extensions", enabled)

    def _boot_refresh(self):
        boot_sets.read_status(self._boot_status_ready)

    def _boot_status_ready(self, status):
        if self.boot_loading_row is not None:
            self.boot_systems.remove(self.boot_loading_row)
            self.boot_loading_row = None
        for row in self._boot_rows:
            self.boot_systems.remove(row)
        self._boot_rows = []
        for row in self._boot_storage_rows:
            self.boot_storage.remove(row)
        self._boot_storage_rows = []

        # Absent when the reading failed, and then the switch stays untouched
        # and insensitive rather than claiming a state nobody could read.
        if "noask" in status:
            self._boot_noask_settled(bool(status["noask"]))

        if status.get("error"):
            self.boot_stack.set_visible_child_name("content")
            row = Adw.ActionRow(
                title=_("Could not read the system"),
                subtitle=status["error"],
            )
            self.boot_systems.add(row)
            self._boot_rows.append(row)
            return False

        sets = status.get("sets", [])
        current = status.get("current")

        # One system is not a dual boot, so say that instead of showing an
        # empty switcher the owner cannot act on.
        if len(sets) < 2:
            self.boot_stack.set_visible_child_name("empty")
            return False
        self.boot_stack.set_visible_child_name("content")

        if current is None:
            row = Adw.ActionRow(
                title=_("Unknown system"),
                subtitle=_("The boot partitions do not match any stored set."),
            )
            row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            self.boot_systems.add(row)
            self._boot_rows.append(row)

        # The running system first: it is the answer to "where am I", and the
        # rest of the list is then plainly "where else can I go".
        for entry in sorted(sets, key=lambda e: e["id"] != current):
            row = Adw.ActionRow(title=entry["label"])
            row.add_prefix(Gtk.Image(icon_name=self._icon_for(entry["id"])))

            if entry["id"] == current:
                row.set_subtitle(_("In use now"))
                badge = Gtk.Image(icon_name="object-select-symbolic", valign=Gtk.Align.CENTER)
                badge.add_css_class("accent")
                row.add_suffix(badge)
            elif entry["complete"]:
                row.set_subtitle(_("Ready to boot."))
                button = Gtk.Button(
                    label=_("Restart into this system"),
                    valign=Gtk.Align.CENTER,
                    css_classes=["suggested-action"],
                )
                button.connect("clicked", self._boot_switch_clicked, entry["id"])
                row.add_suffix(button)
            else:
                row.set_subtitle(_("Its images are missing or the wrong size."))

            self.boot_systems.add(row)
            self._boot_rows.append(row)

        widget = self._storage_widget(status.get("storage", {}))
        if widget is not None:
            self.boot_storage.add(widget)
            self._boot_storage_rows.append(widget)
        return False

    @staticmethod
    def _icon_for(set_id):
        return ("computer-symbolic" if "ubuntu" in set_id.lower()
                else "phone-symbolic")

    def _boot_switch_clicked(self, button, set_id):
        button.set_sensitive(False)
        self.boot_progress.set_visible(True)
        self.boot_progress_label.set_text(_("Writing the boot partitions…"))
        boot_sets.switch(set_id, True, self._boot_progress, self._boot_finished)

    def _boot_progress(self, event):
        self.boot_progress_label.set_text(event.get("message", ""))
        return False

    def _boot_finished(self, ok):
        if not ok:
            self.boot_progress_label.set_text(
                _("It did not finish. Nothing was restarted; check the message above.")
            )
            self._boot_refresh()
        return False

    def _boot_noask_settled(self, enabled):
        """Where the switch lands, both on first reading and after a change.

        It is set from the state read back off the system, never from the one
        the tap asked for, so cancelling the password dialog reverts the row
        by simply telling it the truth.
        """
        self._updating_noask_switch = True
        self.boot_noask_row.set_active(enabled)
        self._updating_noask_switch = False
        self.boot_noask_row.set_sensitive(True)
        return False

    def _boot_noask_toggled(self, row, _param):
        if self._updating_noask_switch:
            return
        # pkexec waits on a password dialog, which would freeze the window if
        # it ran here.  The row stays insensitive until the answer comes back.
        row.set_sensitive(False)
        boot_sets.set_noask(row.get_active(), self._boot_noask_settled)

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

        remote = Adw.PreferencesGroup(
            title=_("Remote features"),
            description=_("Use Bluetooth for air gestures or pointer mode."),
        )
        self.remote_switch = Adw.SwitchRow(
            title=_("Enable S Pen remote features"),
            subtitle=_("When disabled, Bluetooth disconnects and the S Pen remains available for writing."),
        )
        self.remote_switch.add_prefix(Gtk.Image(icon_name="bluetooth-active-symbolic"))
        self.remote_switch.connect(
            "notify::active", self._remote_switch_changed
        )
        self.bluetooth_warning = Adw.ActionRow(
            title=_("Bluetooth is turned off"),
            subtitle=_("Turn on Bluetooth to use S Pen remote features."),
        )
        self.bluetooth_warning.add_prefix(
            Gtk.Image(icon_name="bluetooth-disabled-symbolic")
        )
        remote.add(self.bluetooth_warning)
        remote.add(self.remote_switch)
        self.remote_mode_row = Adw.ComboRow(
            title=_("Remote mode"),
            subtitle=_("Air gestures and pointer mode cannot be used at the same time."),
            model=Gtk.StringList.new([_("Air gestures"), _("Pointer")]));
        self.remote_mode_row.add_prefix(Gtk.Image(icon_name="input-mouse-symbolic"))
        self.remote_mode_row.set_selected(
            1 if self.settings.get_string("spen-remote-mode") == "pointer" else 0
        )
        self.remote_mode_row.connect("notify::selected", self._remote_mode_selected)
        remote.add(self.remote_mode_row)

        status = Adw.PreferencesGroup(title=_("Battery"))
        self.battery_group = status
        self.battery_row = Adw.ActionRow(title=_("S Pen battery"))
        self.battery_icon = Gtk.Image(icon_name="battery-missing-symbolic")
        self.battery_row.add_prefix(self.battery_icon)
        self.battery_bar = Gtk.ProgressBar(width_request=220, valign=Gtk.Align.CENTER, show_text=True)
        self.battery_row.add_suffix(self.battery_bar)
        status.add(self.battery_row)
        page.add(status)

        behaviour = Adw.PreferencesGroup(
            title=_("S Pen behaviour"),
            description=_("Control touch rejection and when the digitizer is active."),
        )
        reject_touch = Adw.SwitchRow(
            title=_("Ignore finger touches while hovering"),
            subtitle=_("Reject finger input as soon as the S Pen approaches the screen."),
        )
        reject_touch.add_prefix(Gtk.Image(icon_name="touch-disabled-symbolic"))
        self.settings.bind(
            "ignore-finger-while-hovering", reject_touch, "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        behaviour.add(reject_touch)
        dock_disable = Adw.SwitchRow(
            title=_("Disable the digitizer while docked"),
            subtitle=_("Ignore every S Pen on the screen while the bundled pen is inserted."),
        )
        dock_disable.add_prefix(Gtk.Image(icon_name="system-shutdown-symbolic"))
        self.settings.bind(
            "disable-digitizer-when-docked", dock_disable, "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        behaviour.add(dock_disable)
        page.add(behaviour)
        page.add(remote)

        gestures = Adw.PreferencesGroup(
            title=_("Air actions"),
            description=_("Choose what the S Pen button and each air gesture should do."),
        )
        self.gesture_group = gestures
        for key, title, subtitle in GESTURES:
            gestures.add(self._action_row("gesture-" + key, _(title), _(subtitle)))
        page.add(gestures)

        pointer = Adw.PreferencesGroup(
            title=_("Pointer mode"),
            description=_("Move the S Pen in the air like a Wii Remote. Its button acts as the primary mouse button and supports dragging. Automatic screen rotation is unavailable while this mode is active."),
        )
        self.pointer_group = pointer
        pointer.add(self._scale_setting_row(
            "pointer-sensitivity", _("Sensitivity"),
            _("Controls how far the pointer moves."), 25, 300, 5,
            "preferences-system-symbolic",
        ))
        pointer.add(self._scale_setting_row(
            "pointer-smoothing", _("Smoothing"),
            _("Reduces hand jitter at the cost of a little response time."), 0, 90, 5,
            "weather-clear-symbolic",
        ))
        acceleration = Adw.SwitchRow(
            title=_("Pointer acceleration"),
            subtitle=_("Move farther when the S Pen is swung faster."),
        )
        acceleration.add_prefix(Gtk.Image(icon_name="speedometer-symbolic"))
        self.settings.bind(
            "pointer-acceleration", acceleration, "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        pointer.add(acceleration)
        page.add(pointer)
        self._update_remote_sections()
        return page

    def _scale_setting_row(self, setting, title, subtitle, lower, upper, step, icon):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.add_prefix(Gtk.Image(icon_name=icon))
        scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment(
                value=self.settings.get_int(setting), lower=lower, upper=upper,
                step_increment=step, page_increment=step * 4,
            ),
            draw_value=True,
            digits=0,
            width_request=240,
            valign=Gtk.Align.CENTER,
        )
        scale.connect(
            "value-changed",
            lambda widget: self.settings.set_int(setting, round(widget.get_value())),
        )
        row.add_suffix(scale)
        return row

    def _remote_mode_selected(self, row, _param):
        self.settings.set_string(
            "spen-remote-mode", "pointer" if row.get_selected() == 1 else "gestures"
        )

    def _remote_switch_changed(self, row, _param):
        if self._updating_remote_switch or not self.hardware.state.bluetooth_available:
            return
        self.settings.set_boolean("spen-remote-enabled", row.get_active())

    def _remote_settings_changed(self, *_args):
        if hasattr(self, "remote_mode_row"):
            expected = 1 if self.settings.get_string("spen-remote-mode") == "pointer" else 0
            if self.remote_mode_row.get_selected() != expected:
                self.remote_mode_row.set_selected(expected)
            self._update_remote_sections()
            self._update_hardware()

    def _update_remote_sections(self):
        bluetooth = self.hardware.state.bluetooth_available
        requested = self.settings.get_boolean("spen-remote-enabled")
        enabled = bluetooth and requested
        pointer = self.settings.get_string("spen-remote-mode") == "pointer"
        self._updating_remote_switch = True
        self.remote_switch.set_active(enabled)
        self._updating_remote_switch = False
        self.remote_switch.set_sensitive(bluetooth)
        self.bluetooth_warning.set_visible(not bluetooth)
        self.remote_mode_row.set_sensitive(enabled)
        self.battery_group.set_visible(enabled)
        self.gesture_group.set_visible(enabled and not pointer)
        self.pointer_group.set_visible(enabled and pointer)

    def _haptics_page(self):
        page = self._page()
        group = Adw.PreferencesGroup(
            title=_("On-screen keyboard"),
            description=_("The vibration motor has a fixed intensity; strength changes the pulse duration."),
        )
        enabled = Adw.SwitchRow(
            title=_("Vibrate on key press"),
            subtitle=_("Applies only to GNOME's on-screen keyboard."),
        )
        enabled.add_prefix(Gtk.Image(icon_name="input-keyboard-symbolic"))
        self.settings.bind(
            "keyboard-haptics-enabled", enabled, "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        group.add(enabled)
        self.haptics_strength = Adw.ComboRow(
            title=_("Strength"),
            subtitle=_("Used by the on-screen keyboard and the test button."),
            model=Gtk.StringList.new([_("Light"), _("Medium"), _("Strong")]),
        )
        strength = min(3, max(1, self.settings.get_int("keyboard-haptics-strength")))
        self.haptics_strength.set_selected(strength - 1)
        self.haptics_strength.connect("notify::selected", self._haptics_strength_selected)
        group.add(self.haptics_strength)
        self.haptics_test = Adw.ActionRow(
            title=_("Test selected strength"),
            subtitle=_("Reproduces exactly one on-screen keyboard key press."),
        )
        test = Gtk.Button(label=_("Test"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        test.connect("clicked", self._test_haptics)
        self.haptics_test.add_suffix(test)
        self.haptics_test.set_activatable_widget(test)
        group.add(self.haptics_test)
        page.add(group)

        notifications = Adw.PreferencesGroup(title=_("Notifications"))
        notification_enabled = Adw.SwitchRow(
            title=_("Vibrate for notifications"),
            subtitle=_("Feel a vibration when a new notification arrives."),
        )
        notification_enabled.add_prefix(
            Gtk.Image(icon_name="preferences-system-notifications-symbolic")
        )
        self.settings.bind(
            "notification-haptics-enabled", notification_enabled, "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        notifications.add(notification_enabled)
        page.add(notifications)
        return page

    def _haptics_strength_selected(self, row, _param):
        self.settings.set_int("keyboard-haptics-strength", row.get_selected() + 1)

    def _test_haptics(self, _button):
        strength = min(3, max(
            1, self.settings.get_int("keyboard-haptics-strength")
        ))
        self.hardware.vibrate(KEYBOARD_HAPTIC_DURATIONS_MS[strength - 1], 65535)

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
        if action_id == "key" and target:
            return icon_label(icon, chord_label(target))
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

    def _choose_key(self, setting):
        current = self.settings.get_value("action-targets").unpack().get(setting, "")
        KeyChooser(
            self, current,
            lambda value: self._save_target(setting, "key", value),
        ).present()
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

    def _update_hardware(self, *_args):
        state = self.hardware.state
        self._update_remote_sections()
        remote_enabled = (
            state.bluetooth_available
            and self.settings.get_boolean("spen-remote-enabled")
        )
        if not remote_enabled:
            status = _("Inserted") if state.pen_state == "docked" else _("Not inserted")
        else:
            pointer = self.settings.get_string("spen-remote-mode") == "pointer"
            status = {
                "docked": _("Docked and charging") if state.pen_charging else _("Docked"),
                "nearby": _("Connected and ready for pointer mode") if pointer else _("Connected and ready for air gestures"),
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
        self.haptics_test.set_subtitle(
            _("Reproduces exactly one on-screen keyboard key press.")
            if state.haptics_available
            else _("The updated kernel is required")
        )
        self.haptics_test.set_sensitive(state.haptics_available)
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
            f"\nHaptics: {'available' if state.haptics_available else 'unavailable'}"
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
        about.add_credit_section(
            _("Air pointer inspiration"),
            ["PenMouse S — Jakub J (@jojczak)"],
        )
        about.add_link(
            _("PenMouse S on GitHub"),
            "https://github.com/jojczak/PenMouseS",
        )
        about.present()
