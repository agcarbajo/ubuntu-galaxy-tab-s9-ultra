import Gio from 'gi://Gio';
import GObject from 'gi://GObject';

import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';

const HELPER = '/usr/bin/gts9u-flashlight';

const FlashlightToggle = GObject.registerClass(
class FlashlightToggle extends QuickSettings.QuickToggle {
    constructor() {
        super({
            // The source string is English so that any language without a
            // translation falls back to something readable, rather than
            // showing Spanish to someone who picked Japanese.
            title: _('Flashlight'),
            iconName: 'gts9u-flashlight-symbolic',
            toggleMode: true,
        });

        this._syncing = false;
        this._changedId = this.connect('notify::checked', () => {
            if (!this._syncing)
                this._setHardware(this.checked);
        });
        this.syncFromHardware();
    }

    _readHardware() {
        try {
            const file = Gio.File.new_for_path(
                '/sys/class/leds/white:flash/brightness');
            const [, contents] = file.load_contents(null);
            return Number(new TextDecoder().decode(contents).trim()) > 0;
        } catch (error) {
            console.error(`GTS9U flashlight status failed: ${error.message}`);
            return false;
        }
    }

    syncFromHardware() {
        this._syncing = true;
        this.checked = this._readHardware();
        this._syncing = false;
    }

    _setHardware(enabled) {
        let process;
        try {
            process = Gio.Subprocess.new(
                [HELPER, enabled ? 'on' : 'off'],
                Gio.SubprocessFlags.NONE);
        } catch (error) {
            console.error(`GTS9U flashlight launch failed: ${error.message}`);
            this.syncFromHardware();
            return;
        }

        process.wait_check_async(null, (source, result) => {
            try {
                source.wait_check_finish(result);
            } catch (error) {
                console.error(`GTS9U flashlight command failed: ${error.message}`);
                this.syncFromHardware();
            }
        });
    }

    turnOff() {
        try {
            Gio.Subprocess.new([HELPER, 'off'], Gio.SubprocessFlags.NONE);
        } catch (error) {
            console.error(`GTS9U flashlight shutdown failed: ${error.message}`);
        }
    }

    destroy() {
        if (this._changedId) {
            this.disconnect(this._changedId);
            this._changedId = 0;
        }
        super.destroy();
    }
});

const FlashlightIndicator = GObject.registerClass(
class FlashlightIndicator extends QuickSettings.SystemIndicator {
    constructor() {
        super();

        this._toggle = new FlashlightToggle();
        this.quickSettingsItems.push(this._toggle);

        this._indicator = this._addIndicator();
        this._indicator.icon_name = 'gts9u-flashlight-symbolic';
        this._indicator.visible = this._toggle.checked;
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
        this._indicator = new FlashlightIndicator();
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator.destroy();
        this._indicator = null;
    }
}
