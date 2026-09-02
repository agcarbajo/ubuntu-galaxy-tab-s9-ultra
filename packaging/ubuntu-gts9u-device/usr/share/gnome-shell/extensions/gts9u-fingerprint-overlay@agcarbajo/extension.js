// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.agcarbajo.Gts9uFingerprintOverlay';
const OBJECT_PATH = '/io/github/agcarbajo/Gts9uFingerprintOverlay';
const BACKLIGHT = '/sys/class/backlight/ae94000.dsi.0';
const INTERFACE = `
<node>
  <interface name="io.github.agcarbajo.Gts9uFingerprintOverlay">
    <method name="Show"/>
    <method name="Hide"/>
    <property name="Visible" type="b" access="read"/>
  </interface>
</node>`;

export default class Gts9uFingerprintOverlay extends Extension {
    enable() {
        this._active = false;
        this._shade = new St.Widget({
            style_class: 'gts9u-fingerprint-shade',
            reactive: true,
            visible: false,
        });
        this._actor = new St.Widget({
            style_class: 'gts9u-fingerprint-overlay',
            reactive: true,
            visible: false,
        });
        this._actor.connect('button-press-event', () => Clutter.EVENT_STOP);
        this._actor.connect('button-release-event', () => Clutter.EVENT_STOP);
        this._actor.connect('touch-event', () => Clutter.EVENT_STOP);
        this._shade.connect('button-press-event', () => Clutter.EVENT_STOP);
        this._shade.connect('button-release-event', () => Clutter.EVENT_STOP);
        this._shade.connect('touch-event', () => Clutter.EVENT_STOP);
        this._shade.connect('notify::visible', () => this._enforceInactive());
        this._actor.connect('notify::visible', () => this._enforceInactive());
        Main.layoutManager.addTopChrome(this._shade, {trackFullscreen: true});
        Main.layoutManager.addTopChrome(this._actor, {trackFullscreen: true});
        // addTopChrome() maps a newly-added actor regardless of its constructor
        // flag. Authentication must be the only thing that makes either actor
        // visible.
        this._shade.hide();
        this._actor.hide();
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._enforceInactive();
            return GLib.SOURCE_REMOVE;
        });

        this._monitorsChangedId = Main.layoutManager.connect(
            'monitors-changed', () => this._position());
        this._sensorProxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            null,
            'net.hadess.SensorProxy',
            '/net/hadess/SensorProxy',
            'net.hadess.SensorProxy',
            null
        );
        this._sensorChangedId = this._sensorProxy.connect(
            'g-properties-changed', () => this._position());

        this._busId = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            connection => {
                this._dbus = Gio.DBusExportedObject.wrapJSObject(
                    INTERFACE, this);
                this._dbus.export(connection, OBJECT_PATH);
            },
            null,
            null
        );
        this._position();
        this._startPanelPoll();
    }

    disable() {
        this._active = false;
        this._stopPanelPoll();
        this._stopHidePoll();
        this._stopBrightnessPoll();
        this._stopSafetyTimeout();
        if (this._busId) {
            Gio.bus_unown_name(this._busId);
            this._busId = 0;
        }
        this._dbus?.unexport();
        this._dbus = null;
        if (this._sensorChangedId) {
            this._sensorProxy.disconnect(this._sensorChangedId);
            this._sensorChangedId = 0;
        }
        this._sensorProxy = null;
        if (this._monitorsChangedId) {
            Main.layoutManager.disconnect(this._monitorsChangedId);
            this._monitorsChangedId = 0;
        }
        this._actor?.destroy();
        this._actor = null;
        this._shade?.destroy();
        this._shade = null;
    }

    get Visible() {
        return this._active && (this._actor?.visible ?? false);
    }

    Show() {
        this._stopHidePoll();
        this._active = true;
        Main.panel.statusArea.quickSettings?.menu?.close();
        Main.overview.hide();
        this._position();
        this._updateShade();
        this._shade.show();
        this._actor.show();
        this._startBrightnessPoll();
        this._startSafetyTimeout();
        this._dbus?.emit_property_changed(
            'Visible', new GLib.Variant('b', true));
    }

    Hide() {
        this._stopSafetyTimeout();
        if (this._panelFodActive()) {
            this._startHidePoll();
            return;
        }
        this._finishHide();
    }

    _finishHide() {
        this._active = false;
        this._stopHidePoll();
        this._stopBrightnessPoll();
        this._actor.hide();
        this._shade.hide();
        this._dbus?.emit_property_changed(
            'Visible', new GLib.Variant('b', false));
    }

    _panelFodActive() {
        const mode = this._readBacklight('fod_mode');
        return Number.isFinite(mode) && mode !== 0;
    }

    _startPanelPoll() {
        if (this._panelPollId)
            return;

        // fprintd runs as root and cannot authenticate to a user's session
        // bus.  The panel state is the cross-privilege source of truth: show
        // the target whenever libfprint enters optical HBM and remove it once
        // the kernel has completed its cleanup.
        this._panelPollId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, 100, () => {
                const active = this._panelFodActive();
                if (active && !this._active)
                    this.Show();
                else if (!active && this._active)
                    this._finishHide();
                return GLib.SOURCE_CONTINUE;
            });
    }

    _stopPanelPoll() {
        if (this._panelPollId) {
            GLib.source_remove(this._panelPollId);
            this._panelPollId = 0;
        }
    }

    _startHidePoll() {
        if (this._hidePollId)
            return;

        // Keep the shade above the desktop until the DDIC has really left
        // fingerprint HBM. Otherwise one frame of global HBM is visible when
        // the compositor overlay disappears before the kernel-side cleanup.
        this._hidePollId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, 50, () => {
                if (this._panelFodActive())
                    return GLib.SOURCE_CONTINUE;
                this._hidePollId = 0;
                this._finishHide();
                return GLib.SOURCE_REMOVE;
            });
    }

    _stopHidePoll() {
        if (this._hidePollId) {
            GLib.source_remove(this._hidePollId);
            this._hidePollId = 0;
        }
    }

    _orientation() {
        return this._sensorProxy
            ?.get_cached_property('AccelerometerOrientation')
            ?.deep_unpack() ?? 'normal';
    }

    _position() {
        if (!this._actor || !this._shade)
            return;

        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        // Stock geometry: a 14.8 mm target whose centre is 16.7 mm from
        // the short edge. Scale both from the 196 mm / 1848 px panel axis.
        const shortAxis = Math.min(monitor.width, monitor.height);
        const diameter = Math.round(shortAxis * 14.8 / 196);
        const inset = Math.round(shortAxis * 16.7 / 196);
        const orientation = this._orientation();
        let centerX = monitor.x + monitor.width / 2;
        let centerY = monitor.y + monitor.height / 2;

        if (orientation === 'bottom-up')
            centerX = monitor.x + inset;
        else if (orientation === 'left-up')
            centerY = monitor.y + monitor.height - inset;
        else if (orientation === 'right-up')
            centerY = monitor.y + inset;
        else
            centerX = monitor.x + monitor.width - inset;

        this._shade.set_position(monitor.x, monitor.y);
        this._shade.set_size(monitor.width, monitor.height);
        this._actor.set_size(diameter, diameter);
        this._actor.set_position(
            Math.round(centerX - diameter / 2),
            Math.round(centerY - diameter / 2));
    }

    _readBacklight(name) {
        try {
            const file = Gio.File.new_for_path(`${BACKLIGHT}/${name}`);
            const [, contents] = file.load_contents(null);
            return Number(new TextDecoder().decode(contents).trim());
        } catch (error) {
            console.error(`GTS9U fingerprint backlight read failed: ${error.message}`);
            return NaN;
        }
    }

    _shadeOpacity() {
        const brightness = this._readBacklight('brightness');
        const maximum = this._readBacklight('max_brightness');
        if (!Number.isFinite(brightness) || !Number.isFinite(maximum) ||
            maximum <= 0)
            return 160;

        // Samsung's official ANA38407 tables map normal mode to 420 cd/m2 at
        // WRDISBV 2047. Fingerprint HBM uses platform level 385, WRDISBV 1623,
        // approximately 634 cd/m2; 2047 in HBM would instead be 900 cd/m2.
        // Convert the
        // desired luminance ratio back to an sRGB component before expressing
        // it as a black overlay opacity. Applying the linear ratio directly to
        // encoded pixels makes the desktop far darker than its pre-FOD level.
        // The white target is stacked above the shade and keeps full FOD HBM.
        const normalNits = brightness / maximum * 420;
        const ratio = Math.max(0, Math.min(1, normalNits / 634));
        const encodedRatio = ratio <= 0.0031308
            ? 12.92 * ratio
            : 1.055 * Math.pow(ratio, 1 / 2.4) - 0.055;
        return Math.round(255 * (1 - encodedRatio));
    }

    _updateShade() {
        if (this._shade)
            this._shade.opacity = this._shadeOpacity();
    }

    _startBrightnessPoll() {
        this._stopBrightnessPoll();
        this._brightnessPollId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, 100, () => {
                this._updateShade();
                return GLib.SOURCE_CONTINUE;
            });
    }

    _stopBrightnessPoll() {
        if (this._brightnessPollId) {
            GLib.source_remove(this._brightnessPollId);
            this._brightnessPollId = 0;
        }
    }

    _enforceInactive() {
        if (!this._active) {
            this._actor?.hide();
            this._shade?.hide();
        }
    }

    _startSafetyTimeout() {
        this._stopSafetyTimeout();
        this._safetyTimeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, 12, () => {
                this._safetyTimeoutId = 0;
                this.Hide();
                return GLib.SOURCE_REMOVE;
            });
    }

    _stopSafetyTimeout() {
        if (this._safetyTimeoutId) {
            GLib.source_remove(this._safetyTimeoutId);
            this._safetyTimeoutId = 0;
        }
    }
}
