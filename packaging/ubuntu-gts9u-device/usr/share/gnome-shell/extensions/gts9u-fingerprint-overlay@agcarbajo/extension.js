// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {sensorGeometry, panelMonitor} from './geometry.js';
import {ShellUserVerifier} from 'resource:///org/gnome/shell/gdm/util.js';
import {recoverClosedCancellation} from './authRecovery.js';
import {visualState} from './visualState.js';
import {keyboardCovers} from './keyboardGuard.js';
import {AuthKeyboard, isTypingKeyboard} from './authKeyboard.js';
import {KeyboardEventGuard} from './keyboardEvents.js';
import {getLoginManager} from 'resource:///org/gnome/shell/misc/loginManager.js';

const BUS_NAME = 'io.github.agcarbajo.Gts9uFingerprintOverlay';
const OBJECT_PATH = '/io/github/agcarbajo/Gts9uFingerprintOverlay';
const BACKLIGHT = '/sys/class/backlight/ae94000.dsi.0';
const ACTIVE_LEASE = '/run/gts9u-fingerprint/active';
const UI_BUS_NAME = 'io.github.agcarbajo.Gts9uFingerprintUI';
const UI_PATH = '/io/github/agcarbajo/Gts9uFingerprintUI';
const INTERFACE = `
<node>
  <interface name="io.github.agcarbajo.Gts9uFingerprintOverlay">
    <method name="Show"/>
    <method name="Hide"/>
    <method name="GetDiagnostics"><arg type="s" direction="out"/></method>
    <property name="Visible" type="b" access="read"/>
  </interface>
</node>`;

export default class Gts9uFingerprintOverlay extends Extension {
    enable() {
        this._originalCancel = ShellUserVerifier.prototype.cancel;
        this._recoveryCancel = recoverClosedCancellation(this._originalCancel,
            error => error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CLOSED) ?? false,
            () => console.log('GTS9U auth: cleared closed GDM verification connection'));
        ShellUserVerifier.prototype.cancel = this._recoveryCancel;
        this._displayCancellable = new Gio.Cancellable();
        this._session = null;
        this._uiAllowed = false;
        this._uiReadyUntil = 0;
        this._uiLastPulse = 0;
        this._uiPending = false;
        this._uiLastSent = null;
        this._feedbackUntil = 0;
        this._keyboardEventGuard = new KeyboardEventGuard(Main.keyboard,
            event => global.stage.get_event_actor(event));
        this._enableAuthKeyboard();
        const lifetime = this._displayCancellable;
        getLoginManager().getCurrentSessionProxy().then(session => {
            if (this._displayCancellable === lifetime)
                this._session = session;
        }).catch(error => console.error(`GTS9U fingerprint session: ${error.message}`));
        this._panel = null;
        this._active = false;
        this._illuminated = false;
        this._shade = new St.Widget({
            style_class: 'gts9u-fingerprint-shade',
            reactive: false,
            visible: false,
        });
        this._icon = new St.Icon({
            icon_name: 'auth-fingerprint-symbolic',
            style_class: 'gts9u-fingerprint-icon',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            reactive: false,
        });
        this._actor = new St.Bin({
            style_class: 'gts9u-fingerprint-waiting',
            child: this._icon,
            reactive: false,
            visible: false,
        });
        this._feedback = new St.Label({
            text: '', style_class: 'gts9u-fingerprint-feedback',
            reactive: false, visible: false,
        });
        this._feedback.clutter_text.line_wrap = true;
        this._shade.connect('notify::visible', () => this._enforceInactive());
        this._actor.connect('notify::visible', () => this._enforceInactive());
        // The shade only compensates global HBM. It must never intercept the
        // password field, accessibility controls, keyboard or cancel button.
        Main.layoutManager.addTopChrome(this._shade,
            {trackFullscreen: true, affectsInputRegion: false});
        // FOD contacts are consumed by Goodix, not by a Shell actor. Keep every
        // overlay element out of input picking, including during GDM handoff.
        Main.layoutManager.addTopChrome(this._actor,
            {trackFullscreen: true, affectsInputRegion: false});
        Main.layoutManager.addTopChrome(this._feedback,
            {trackFullscreen: true, affectsInputRegion: false});
        // addTopChrome() maps a newly-added actor regardless of its constructor
        // flag. Authentication must be the only thing that makes either actor
        // visible.
        this._shade.hide();
        this._actor.hide();
        this._feedback.hide();
        this._feedback.connect('notify::visible', () => {
            if (!this._canShowTarget() || GLib.get_monotonic_time() >= this._feedbackUntil)
                this._feedback.hide();
        });
        this._initialHideId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._initialHideId = 0;
            this._enforceInactive();
            return GLib.SOURCE_REMOVE;
        });

        this._monitorsChangedId = Main.layoutManager.connect(
            'monitors-changed', () => this._refreshMonitor());
        this._displayChangedId = Gio.DBus.session.signal_subscribe(
            'org.gnome.Mutter.DisplayConfig', 'org.gnome.Mutter.DisplayConfig',
            'MonitorsChanged', '/org/gnome/Mutter/DisplayConfig', null,
            Gio.DBusSignalFlags.NONE, () => this._refreshMonitor());

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
        this._refreshMonitor();
        this._startPanelPoll();
    }

    disable() {
        this._keyboardEventGuard?.destroy();
        this._keyboardEventGuard = null;
        if (ShellUserVerifier.prototype.cancel === this._recoveryCancel)
            ShellUserVerifier.prototype.cancel = this._originalCancel;
        this._originalCancel = null;
        this._recoveryCancel = null;
        this._displayCancellable.cancel();
        this._displayCancellable = null;
        this._session = null;
        this._uiAllowed = false;
        this._uiReadyUntil = 0;
        this._panel = null;
        if (this._initialHideId) {
            GLib.source_remove(this._initialHideId);
            this._initialHideId = 0;
        }
        this._active = false;
        this._stopPanelPoll();
        this._authKeyboard?.destroy();
        this._authKeyboard = null;
        for (const id of this._seatSignals ?? [])
            this._seat.disconnect(id);
        this._seatSignals = [];
        this._seat = null;
        this._stopHidePoll();
        this._stopBrightnessPoll();
        this._stopSafetyTimeout();
        if (this._busId) {
            Gio.bus_unown_name(this._busId);
            this._busId = 0;
        }
        this._dbus?.unexport();
        this._dbus = null;
        if (this._displayChangedId) {
            Gio.DBus.session.signal_unsubscribe(this._displayChangedId);
            this._displayChangedId = 0;
        }
        if (this._monitorsChangedId) {
            Main.layoutManager.disconnect(this._monitorsChangedId);
            this._monitorsChangedId = 0;
        }
        this._actor?.destroy();
        this._actor = null;
        this._icon = null;
        this._shade?.destroy();
        this._shade = null;
        this._disconnectFeedback();
        this._feedback?.destroy();
        this._feedback = null;
    }

    get Visible() {
        return this._active && (this._actor?.visible ?? false);
    }

    Show() {
        this._stopHidePoll();
        this._active = true;
        // Rendering the target must not close native menus, change focus or
        // interfere with a modal transition in either the user or GDM Shell.
        this._position();
        this._setIllumination(this._panelFodActive());
        if (this._canShowTarget())
            this._actor.show();
        this._startSafetyTimeout();
        this._dbus?.emit_property_changed(
            'Visible', new GLib.Variant('b', true));
    }

    Hide() {
        this._stopSafetyTimeout();
        if (this._visualState().active) {
            this._startHidePoll();
            return;
        }
        this._finishHide();
    }

    _finishHide() {
        this._active = false;
        this._illuminated = false;
        this._stopSafetyTimeout();
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

    _visualState() {
        let lease = '';
        try {
            const [, bytes] = Gio.File.new_for_path(ACTIVE_LEASE).load_contents(null);
            lease = new TextDecoder().decode(bytes);
        } catch (_) {
            // Normally absent when fprintd is idle or not running.
        }
        return visualState(lease, GLib.get_monotonic_time(), this._panelFodActive());
    }

    _setIllumination(illuminated) {
        this._illuminated = illuminated;
        this._actor.set_style_class_name(illuminated
            ? 'gts9u-fingerprint-overlay' : 'gts9u-fingerprint-waiting');
        this._icon.visible = !illuminated;
        if (illuminated) {
            this._updateShade();
            this._shade.show();
            this._startBrightnessPoll();
        } else {
            this._stopBrightnessPoll();
            this._shade.hide();
        }
    }

    _canShowTarget() {
        return this._panel && this._uiAllowed &&
            GLib.get_monotonic_time() < this._uiReadyUntil;
    }

    _disconnectFeedback() {
        if (this._feedbackVerifier && this._feedbackSignal) {
            try {
                this._feedbackVerifier.disconnect(this._feedbackSignal);
            } catch (_) {
                // Native prompt may already have destroyed its signal handlers.
            }
        }
        this._feedbackVerifier = null;
        this._feedbackSignal = 0;
    }

    _updateFeedback() {
        const verifier = Main.screenShield?._dialog?._authPrompt?._userVerifier;
        if (verifier !== this._feedbackVerifier) {
            this._disconnectFeedback();
            this._feedbackUntil = 0;
            if (verifier) {
                this._feedbackVerifier = verifier;
                // Mirror only the existing localized fingerprint error; never
                // intercept, answer, cancel or complete an authentication.
                this._feedbackSignal = verifier.connect('show-message',
                    (_source, service, message, type) => {
                        if (service === 'gdm-fingerprint' && type === 3 && message) {
                            this._feedback.text = String(message).slice(0, 180);
                            this._feedbackUntil = GLib.get_monotonic_time() + 4_000_000;
                        }
                    });
            }
        }
        if (this._canShowTarget() && GLib.get_monotonic_time() < this._feedbackUntil)
            this._feedback.show();
        else
            this._feedback.hide();
    }

    _keyboardCoversTarget() {
        if (!this._panel)
            return true;
        const box = Main.layoutManager.keyboardBox;
        if (!box?.visible)
            return false;
        const children = box.get_children();
        const showing = Main.keyboard.visible || children.some(child =>
            child.visible && child.opacity > 0);
        const [x, y] = box.get_transformed_position();
        const [width, height] = box.get_transformed_size();
        const {monitor, transform} = this._panel;
        return keyboardCovers(sensorGeometry(monitor, transform),
            {x, y, width, height}, showing);
    }

    _enableAuthKeyboard() {
        this._seat = Clutter.get_default_backend().get_default_seat();
        this._keyboardsDirty = true;
        this._physicalKeyboard = null;
        this._keyboardsNextScan = 0;
        this._keyboardFailed = false;
        this._seatSignals = ['device-added', 'device-removed'].map(signal =>
            this._seat.connect(signal, () => { this._keyboardsDirty = true; }));
        try {
            this._authKeyboard = new AuthKeyboard(Main.keyboard, {
                schedule: callback => GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    callback();
                    return GLib.SOURCE_REMOVE;
                }),
                cancel: id => GLib.source_remove(id),
                refreshFocus: keyboard => {
                    // Read only the focus's type, never its text. Let the
                    // native keyboard perform its own open/focus handling.
                    if (global.stage.key_focus instanceof Clutter.Text)
                        keyboard?._onKeyFocusChanged();
                },
                report: enabled => console.log(`GTS9U input: auth keyboard fallback=${enabled}`),
            });
        } catch (error) {
            this._authKeyboard = null;
            console.error(`GTS9U input: ${error.message}`);
        }
    }

    _syncAuthKeyboard() {
        if (this._keyboardFailed)
            return;
        try {
            this._syncAuthKeyboardState();
        } catch (error) {
            // A native keyboard API failure must not stop the panel poll or
            // its safety lease. Restore native policy and log once.
            this._keyboardFailed = true;
            try {
                this._authKeyboard?.destroy();
            } catch (_) {
                // destroy restores the native method before synchronizing it.
            }
            this._authKeyboard = null;
            console.error(`GTS9U input: auth keyboard disabled: ${error.message}`);
        }
    }

    _syncAuthKeyboardState() {
        const now = GLib.get_monotonic_time();
        if (this._keyboardsDirty || now >= this._keyboardsNextScan) {
            this._keyboardsDirty = false;
            this._keyboardsNextScan = now + 1_000_000;
            this._physicalKeyboard = this._scanPhysicalKeyboards();
        }
        this._authKeyboard?.sync({
            active: this._session?.Active,
            authenticating: Main.sessionMode.isGreeter || Main.screenShield?.locked,
            panelPresent: Boolean(this._panel),
            physicalKeyboard: this._physicalKeyboard,
        });
    }

    _scanPhysicalKeyboards() {
        // Companion grabs and forwards the real cover. Mutter's device list
        // may omit that original device; inspect the actual kernel inventory.
        // Periodic refresh also catches hotplug not exposed to the compositor.
        const dir = Gio.File.new_for_path('/sys/class/input');
        const files = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        try {
            for (let file = files.next_file(null); file; file = files.next_file(null)) {
                const event = file.get_name();
                if (!/^event\d+$/.test(event))
                    continue;
                const root = `/sys/class/input/${event}/device`;
                const read = suffix => {
                    const [, bytes] = Gio.File.new_for_path(`${root}/${suffix}`).load_contents(null);
                    return new TextDecoder().decode(bytes).trim();
                };
                try {
                    if (isTypingKeyboard({name: read('name'), vendor: read('id/vendor'),
                        product: read('id/product'), keys: read('capabilities/key')}) !== false)
                        return true;
                } catch (_) {
                    return true; // Hotplug/unknown data: don't force an OSK.
                }
            }
            return false;
        } finally {
            files.close(null);
        }
    }

    GetDiagnostics() {
        // Read-only state for intermittent post-login input failures. No key
        // contents, finger images, credentials, user names or auth answers.
        return JSON.stringify({
            version: 14,
            sessionActive: Boolean(this._session?.Active),
            greeter: Boolean(Main.sessionMode.isGreeter),
            locked: Boolean(Main.screenShield?.locked),
            modalCount: Main.modalCount,
            actionMode: Main.actionMode,
            touchMode: this._seat?.get_touch_mode() ?? null,
            physicalKeyboard: this._physicalKeyboard,
            keyboardFallback: this._authKeyboard?.fallback ?? false,
            keyboardFailed: this._keyboardFailed,
            targetlessKeyboardEvents: this._keyboardEventGuard?.targetlessEvents ?? 0,
            keyboardExists: Boolean(Main.keyboard.keyboardActor),
            keyboardVisible: Boolean(Main.keyboard.visible),
            active: this._active,
            targetVisible: Boolean(this._actor?.visible),
            targetReactive: Boolean(this._actor?.reactive),
            shadeVisible: Boolean(this._shade?.visible),
            uiAllowed: this._uiAllowed,
        });
    }

    _pulseAvailability() {
        const now = GLib.get_monotonic_time();
        this._uiAllowed = Boolean(this._panel && this._session?.Active &&
            !this._keyboardCoversTarget());
        if (!this._session?.Active) {
            this._uiReadyUntil = 0;
            return; // An inactive session must not overwrite the active one's lease.
        }
        if (this._uiPending || (this._uiLastSent === this._uiAllowed &&
            now - this._uiLastPulse < 500_000))
            return;
        const available = this._uiAllowed;
        const lifetime = this._displayCancellable;
        this._uiPending = true;
        this._uiLastPulse = now;
        this._uiLastSent = available;
        Gio.DBus.system.call(UI_BUS_NAME, UI_PATH, UI_BUS_NAME, 'Pulse',
            new GLib.Variant('(sb)', [this._session.Id, available]), null,
            Gio.DBusCallFlags.NONE, 1000, lifetime, (connection, result) => {
                if (this._displayCancellable !== lifetime)
                    return;
                this._uiPending = false;
                try {
                    connection.call_finish(result);
                    this._uiReadyUntil = available ? GLib.get_monotonic_time() + 1_500_000 : 0;
                } catch (_) {
                    this._uiReadyUntil = 0;
                    // Retry at the normal heartbeat rate, without flooding the journal.
                }
            });
    }

    _startPanelPoll() {
        if (this._panelPollId)
            return;

        // The root-owned lease shows the waiting icon without raising HBM.
        // Actual panel state alone controls the circle and compensation.
        // Physical contact arrives through Goodix, which suppresses ordinary
        // touch events in the sensor region: no Shell click is required.
        this._panelPollId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, 50, () => {
                this._syncAuthKeyboard();
                this._pulseAvailability();
                const {active, illuminated} = this._visualState();
                if (active && !this._active)
                    this.Show();
                else if (!active && this._active)
                    this._finishHide();
                if (active && illuminated !== this._illuminated)
                    this._setIllumination(illuminated);
                if (active && this._canShowTarget())
                    this._actor.show();
                else
                    this._actor.hide();
                this._updateFeedback();
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
                if (this._visualState().active)
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

    _refreshMonitor() {
        // Do not make synchronous calls back into our own compositor. Reject
        // stale callbacks on disable/re-enable or rapid display changes.
        const cancellable = this._displayCancellable;
        const request = (this._displayRequest ?? 0) + 1;
        this._displayRequest = request;
        this._panel = null;
        this._actor?.hide();
        Gio.DBus.session.call('org.gnome.Mutter.DisplayConfig',
            '/org/gnome/Mutter/DisplayConfig', 'org.gnome.Mutter.DisplayConfig',
            'GetCurrentState', null, null, Gio.DBusCallFlags.NONE, 2000,
            cancellable, (connection, result) => {
                try {
                    const state = connection.call_finish(result).deep_unpack();
                    if (cancellable !== this._displayCancellable ||
                        request !== this._displayRequest || cancellable.is_cancelled())
                        return;
                    this._panel = panelMonitor(state[2], Main.layoutManager.monitors);
                    this._position();
                    if (this._active && this._canShowTarget())
                        this._actor.show();
                } catch (error) {
                    if (!cancellable.is_cancelled())
                        console.error(`GTS9U fingerprint display state: ${error.message}`);
                }
            });
    }

    _position() {
        if (!this._actor || !this._shade)
            return;

        if (!this._panel)
            return;
        const {monitor, transform} = this._panel;
        const target = sensorGeometry(monitor, transform);
        if (!target) {
            this._actor.hide();
            return;
        }
        this._shade.set_position(monitor.x, monitor.y);
        this._shade.set_size(monitor.width, monitor.height);
        this._actor.set_size(target.width, target.height);
        this._actor.set_position(target.x, target.y);
        this._icon.icon_size = Math.round(Math.min(target.width, target.height) * 0.68);
        const labelWidth = Math.min(280, monitor.width - 16);
        this._feedback.set_width(labelWidth);
        this._feedback.set_position(
            Math.max(monitor.x + 8, Math.min(monitor.x + monitor.width - labelWidth - 8,
                target.x + target.width / 2 - labelWidth / 2)),
            Math.max(monitor.y + 8, target.y - 64));
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
        if (!this._canShowTarget())
            this._actor?.hide();
        if (!this._illuminated || !this._active)
            this._shade?.hide();
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
