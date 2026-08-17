// SPDX-License-Identifier: MIT
//
// The panel that One UI shows when the S Pen goes back in its silo: the pen
// itself, the way round it went in, and how much charge it has.
//
// Two things decide where it appears.  The silo is on one physical edge of the
// tablet -- the right one, holding it upright with the charging port down --
// and that edge moves around the screen as the display rotates, so the panel
// asks Mutter which way the display is turned and slides in from wherever that
// edge currently is.  Everything else is the system's own OSD styling, so it
// looks like it belongs.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.agcarbajo.TabCompanion.Hardware';
const OBJECT_PATH = '/io/github/agcarbajo/TabCompanion/Hardware';
const DISPLAY_BUS = 'org.gnome.Mutter.DisplayConfig';
const DISPLAY_PATH = '/org/gnome/Mutter/DisplayConfig';

const SETTING = 'pen-dock-popup';
const VISIBLE_MS = 2600;
const SLIDE_MS = 260;
const MARGIN = 28;

// Where the silo is, per Mutter display transform.  Index is the transform:
// 0 upright, 1 rotated 90, 2 upside down, 3 rotated 270.  Verified by rotating
// the tablet through all four and watching which screen edge the pen went in
// from; the flipped transforms (4-7) mirror the first four and are folded in
// with a modulo, which is right because a mirrored panel does not move the
// silo.
const EDGE_FOR_TRANSFORM = ['east', 'south', 'west', 'north'];

const SPenDockPopup = GObject.registerClass({
    Signals: {'dismissed': {}},
}, class SPenDockPopup extends St.BoxLayout {
    constructor(extensionPath) {
        super({
            style_class: 'spen-dock-popup',
            vertical: false,
            reactive: true,
            track_hover: false,
            can_focus: false,
        });

        this._path = extensionPath;

        this._pen = new St.Icon({style_class: 'spen-dock-pen', y_align: Clutter.ActorAlign.CENTER});
        this.add_child(this._pen);

        const text = new St.BoxLayout({
            vertical: true,
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'spen-dock-text',
        });
        this._title = new St.Label({style_class: 'spen-dock-title', text: _('S Pen')});
        this._charge = new St.Label({style_class: 'spen-dock-charge'});
        text.add_child(this._title);
        text.add_child(this._charge);
        this.add_child(text);

        // A tap puts it away early, the same as the volume OSD.
        this.connect('button-press-event', () => {
            this.emit('dismissed');
            return Clutter.EVENT_STOP;
        });
        this.connect('touch-event', event => {
            if (event.type() === Clutter.EventType.TOUCH_BEGIN) {
                this.emit('dismissed');
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
    }

    update(orientation, battery, charging) {
        // tip-left / tip-right is which way round the pen is sitting; showing
        // the wrong one is the sort of small lie that makes a panel feel fake.
        const file = orientation === 'tip-right'
            ? 'spen-tip-right.svg' : 'spen-tip-left.svg';
        this._pen.gicon = Gio.FileIcon.new(
            Gio.File.new_for_path(GLib.build_filenamev([this._path, file])));

        if (battery < 0)
            this._charge.text = _('Charge unknown');
        else if (charging)
            this._charge.text = `${battery}% · ${_('charging')}`;
        else
            this._charge.text = `${battery}%`;
    }
});

export default class SPenDockExtension extends Extension {
    enable() {
        // The schema is installed system-wide by this package, not carried in
        // the extension directory, so it is opened directly.
        this._settings = new Gio.Settings({
            schema_id: 'io.github.agcarbajo.TabCompanion',
        });
        this._transform = 0;
        this._wasDocked = null;
        this._timeoutId = 0;

        this._popup = new SPenDockPopup(this.path);
        this._popup.opacity = 0;
        this._popup.visible = false;
        Main.layoutManager.addTopChrome(this._popup, {affectsInputRegion: true});
        this._popup.connect('dismissed', () => this._hide());

        this._proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            null, BUS_NAME, OBJECT_PATH, BUS_NAME, null);
        this._propsId = this._proxy.connect(
            'g-properties-changed', () => this._onProperties());

        // Seed the remembered state so that enabling the extension with the pen
        // already docked does not fire the panel at you.
        this._wasDocked = this._proxy.get_cached_property('PenState')?.unpack() === 'docked';

        this._readTransform();
        this._displayId = Gio.DBus.session.signal_subscribe(
            DISPLAY_BUS, DISPLAY_BUS, 'MonitorsChanged', DISPLAY_PATH, null,
            Gio.DBusSignalFlags.NONE, () => this._readTransform());
    }

    disable() {
        // The panel must not outlive a lock or a session switch, so this tears
        // everything down rather than just hiding it.
        this._cancelTimeout();
        if (this._displayId) {
            Gio.DBus.session.signal_unsubscribe(this._displayId);
            this._displayId = 0;
        }
        if (this._propsId) {
            this._proxy?.disconnect(this._propsId);
            this._propsId = 0;
        }
        this._proxy = null;
        if (this._popup) {
            Main.layoutManager.removeChrome(this._popup);
            this._popup.destroy();
            this._popup = null;
        }
        this._settings = null;
    }

    _readTransform() {
        Gio.DBus.session.call(
            DISPLAY_BUS, DISPLAY_PATH, DISPLAY_BUS, 'GetCurrentState',
            null, null, Gio.DBusCallFlags.NONE, -1, null,
            (bus, result) => {
                try {
                    const reply = bus.call_finish(result);
                    const logical = reply.get_child_value(2);
                    if (logical.n_children() === 0)
                        return;
                    // (x, y, scale, transform, primary, monitors, properties)
                    this._transform = logical.get_child_value(0).get_child_value(3).get_uint32();
                } catch (error) {
                    // A missing transform only costs the panel its edge, so it
                    // keeps the last one rather than refusing to appear.
                    console.debug(`S Pen dock: display state failed: ${error.message}`);
                }
            });
    }

    _onProperties() {
        const state = this._proxy.get_cached_property('PenState')?.unpack();
        const docked = state === 'docked';
        const was = this._wasDocked;
        this._wasDocked = docked;

        if (!docked || was === docked || was === null)
            return;
        if (!this._settings.get_boolean(SETTING))
            return;

        this._popup.update(
            this._proxy.get_cached_property('PenOrientation')?.unpack() ?? 'unknown',
            this._proxy.get_cached_property('PenBattery')?.unpack() ?? -1,
            this._proxy.get_cached_property('PenCharging')?.unpack() ?? false);
        this._show();
    }

    _edgePosition() {
        const monitor = Main.layoutManager.primaryMonitor;
        const edge = EDGE_FOR_TRANSFORM[this._transform % 4];
        const w = this._popup.width;
        const h = this._popup.height;
        const cx = monitor.x + Math.round((monitor.width - w) / 2);
        const cy = monitor.y + Math.round((monitor.height - h) / 2);

        switch (edge) {
        case 'north':
            return {rest: [cx, monitor.y + MARGIN], from: [cx, monitor.y - h]};
        case 'south':
            return {rest: [cx, monitor.y + monitor.height - h - MARGIN],
                from: [cx, monitor.y + monitor.height]};
        case 'west':
            return {rest: [monitor.x + MARGIN, cy], from: [monitor.x - w, cy]};
        default:
            return {rest: [monitor.x + monitor.width - w - MARGIN, cy],
                from: [monitor.x + monitor.width, cy]};
        }
    }

    _show() {
        this._cancelTimeout();
        this._popup.visible = true;
        // The size is only known once it has been laid out, and the slide needs
        // it, so the position is set after a forced allocation pass.
        this._popup.get_parent()?.queue_relayout();
        const {rest, from} = this._edgePosition();

        this._popup.remove_all_transitions();
        this._popup.set_position(from[0], from[1]);
        this._popup.ease({
            x: rest[0],
            y: rest[1],
            opacity: 255,
            duration: SLIDE_MS,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });

        this._timeoutId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, VISIBLE_MS, () => {
                this._timeoutId = 0;
                this._hide();
                return GLib.SOURCE_REMOVE;
            });
    }

    _hide() {
        this._cancelTimeout();
        if (!this._popup?.visible)
            return;
        const {from} = this._edgePosition();
        this._popup.remove_all_transitions();
        this._popup.ease({
            x: from[0],
            y: from[1],
            opacity: 0,
            duration: SLIDE_MS,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                if (this._popup)
                    this._popup.visible = false;
            },
        });
    }

    _cancelTimeout() {
        if (this._timeoutId) {
            GLib.source_remove(this._timeoutId);
            this._timeoutId = 0;
        }
    }
}
