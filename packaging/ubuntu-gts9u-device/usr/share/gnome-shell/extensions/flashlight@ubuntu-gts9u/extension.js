import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Slider} from 'resource:///org/gnome/shell/ui/slider.js';

const HELPER = '/usr/bin/gts9u-flashlight';
const BRIGHTNESS = '/sys/class/leds/white:flash/brightness';
const MAX_BRIGHTNESS = '/sys/class/leds/white:flash/max_brightness';
const SCHEMA = 'io.github.agcarbajo.GTS9UFlashlight';

function readNumber(path) {
    try {
        const [, contents] = Gio.File.new_for_path(path).load_contents(null);
        return Number(new TextDecoder().decode(contents).trim());
    } catch (error) {
        console.error(`GTS9U flashlight read failed: ${error.message}`);
        return NaN;
    }
}

// The schema ships with this package, but the tile should not take the whole
// panel down if it is ever missing.
function openSettings() {
    const source = Gio.SettingsSchemaSource.get_default();
    if (!source?.lookup(SCHEMA, true))
        return null;
    return new Gio.Settings({schema_id: SCHEMA});
}

const BrightnessItem = GObject.registerClass(
class BrightnessItem extends PopupMenu.PopupBaseMenuItem {
    constructor(maximum, onChange) {
        super({activate: false});

        this._maximum = maximum;
        this._onChange = onChange;
        this._updating = false;

        this.add_child(new St.Icon({
            style_class: 'popup-menu-icon',
            icon_name: 'gts9u-flashlight-symbolic',
        }));

        this._slider = new Slider(0);
        this._slider.x_expand = true;
        this._sliderId = this._slider.connect('notify::value', () => {
            if (!this._updating)
                this._onChange(this.level);
        });
        this.add_child(this._slider);

        // The row is the slider: let every press go to it rather than closing
        // the menu, which is how the sound and display sliders behave.
        this.connect('key-press-event',
            (actor, event) => this._slider.emit('key-press-event', event));
    }

    get level() {
        return Math.max(1, Math.round(this._slider.value * this._maximum));
    }

    setLevel(level) {
        this._updating = true;
        this._slider.value = Math.min(1, Math.max(0, level / this._maximum));
        this._updating = false;
    }
});

const FlashlightToggle = GObject.registerClass(
class FlashlightToggle extends QuickSettings.QuickMenuToggle {
    constructor(settings) {
        super({
            // The source string is English so that any language without a
            // translation falls back to something readable, rather than
            // showing Spanish to someone who picked Japanese.
            title: _('Flashlight'),
            iconName: 'gts9u-flashlight-symbolic',
            toggleMode: true,
        });

        this._settings = settings;
        this._syncing = false;

        const maximum = readNumber(MAX_BRIGHTNESS);
        this._maximum = Number.isFinite(maximum) && maximum > 0 ? maximum : 255;

        this.menu.setHeader('gts9u-flashlight-symbolic', _('Flashlight'));
        this._brightness = new BrightnessItem(
            this._maximum, level => this._setLevel(level));
        this.menu.addMenuItem(this._brightness);

        this._changedId = this.connect('notify::checked', () => {
            if (!this._syncing)
                this._apply(this.checked);
        });

        // Someone else -- a pen gesture, a cover key -- may have changed the
        // LED without going through this tile.  They say so here, and the LED
        // is then read back rather than trusted.
        this._settingsId = this._settings?.connect(
            'changed::on', () => this.syncFromHardware());

        this.syncFromHardware();
    }

    get _level() {
        const stored = this._settings?.get_int('brightness') ?? 128;
        return Math.min(this._maximum, Math.max(1, stored));
    }

    syncFromHardware() {
        const level = readNumber(BRIGHTNESS);
        const lit = Number.isFinite(level) && level > 0;
        this._syncing = true;
        this.checked = lit;
        this._syncing = false;
        this._brightness.setLevel(lit ? level : this._level);
        this.subtitle = lit
            ? `${Math.round(100 * (lit ? level : this._level) / this._maximum)}%`
            : null;
    }

    _setLevel(level) {
        this._settings?.set_int('brightness', level);
        if (this.checked)
            this._apply(true, level);
        else
            this.subtitle = null;
    }

    _apply(enabled, level = this._level) {
        const argv = enabled ? [HELPER, 'on', String(level)] : [HELPER, 'off'];
        let process;
        try {
            process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        } catch (error) {
            console.error(`GTS9U flashlight launch failed: ${error.message}`);
            this.syncFromHardware();
            return;
        }

        process.wait_check_async(null, (source, result) => {
            try {
                source.wait_check_finish(result);
                // Announce it so anything watching agrees with the LED.
                this._settings?.set_boolean('on', enabled);
                this.subtitle = enabled
                    ? `${Math.round(100 * level / this._maximum)}%` : null;
            } catch (error) {
                console.error(`GTS9U flashlight command failed: ${error.message}`);
                this.syncFromHardware();
            }
        });
    }

    turnOff() {
        try {
            Gio.Subprocess.new([HELPER, 'off'], Gio.SubprocessFlags.NONE);
            this._settings?.set_boolean('on', false);
        } catch (error) {
            console.error(`GTS9U flashlight shutdown failed: ${error.message}`);
        }
    }

    destroy() {
        if (this._changedId) {
            this.disconnect(this._changedId);
            this._changedId = 0;
        }
        if (this._settingsId) {
            this._settings.disconnect(this._settingsId);
            this._settingsId = 0;
        }
        super.destroy();
    }
});

const FlashlightIndicator = GObject.registerClass(
class FlashlightIndicator extends QuickSettings.SystemIndicator {
    constructor(settings) {
        super();

        this._toggle = new FlashlightToggle(settings);
        this.quickSettingsItems.push(this._toggle);

        this._indicator = this._addIndicator();
        this._indicator.icon_name = 'gts9u-flashlight-symbolic';
        this._indicator.visible = this._toggle.checked;
        // Bound to the toggle, and the toggle follows the LED however it was
        // changed, so a shortcut lights the status icon too.
        this._checkedId = this._toggle.connect('notify::checked', () => {
            this._indicator.visible = this._toggle.checked;
        });
    }

    destroy() {
        this._toggle.turnOff();
        if (this._checkedId) {
            this._toggle.disconnect(this._checkedId);
            this._checkedId = 0;
        }
        this.quickSettingsItems.forEach(item => item.destroy());
        super.destroy();
    }
});

export default class FlashlightExtension extends Extension {
    enable() {
        this._settings = openSettings();
        this._indicator = new FlashlightIndicator(this._settings);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator.destroy();
        this._indicator = null;
        this._settings = null;
    }
}
