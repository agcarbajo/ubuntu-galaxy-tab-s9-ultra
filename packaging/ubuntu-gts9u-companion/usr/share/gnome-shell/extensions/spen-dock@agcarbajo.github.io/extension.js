// SPDX-License-Identifier: MIT
//
// The panel that One UI shows when the S Pen goes back in its silo: the pen
// itself, the way round it went in, and how much charge it has.
//
// Two things decide how it looks.  The silo is on one physical edge of the
// tablet, and that edge moves around the screen as the display rotates, so the
// panel asks Mutter which way the display is turned and slides in from wherever
// that edge currently is.  And the contents are laid out against that edge
// rather than against the screen: the pen lies along the edge, the charge sits
// below it, and only the text is turned back upright so it still reads.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.agcarbajo.TabCompanion.Hardware';
const OBJECT_PATH = '/io/github/agcarbajo/TabCompanion/Hardware';
const DISPLAY_BUS = 'org.gnome.Mutter.DisplayConfig';
const DISPLAY_PATH = '/org/gnome/Mutter/DisplayConfig';

const SETTING = 'pen-dock-popup';
const VISIBLE_MS = 2600;
const SLIDE_MS = 260;
const MARGIN = 24;

// The driver clears the pen's direction the instant it senses the pen and only
// fills it in once the garage answers over i2c.  Measured on this tablet, that
// takes about 1.07 s, twice running, so the panel waits for the real direction
// instead of drawing the fallback and flipping the pen over in front of you.
// The cap is what keeps a silent garage from swallowing the panel entirely.
const ORIENTATION_WAIT_MS = 1500;

// Which screen edge the silo is on, per Mutter display transform: 0 upright,
// 1 rotated 90, 2 upside down, 3 rotated 270.  Anchored on a measurement --
// with the display at transform 0 the silo is the edge one step anticlockwise
// from the charging port -- and stepped round from there.  The flipped
// transforms (4-7) fold onto the first four with a modulo, which is right
// because mirroring the panel does not move the silo.
const EDGE_FOR_TRANSFORM = ['north', 'east', 'south', 'west'];

// The pen lies along the edge, so it stands up on the sideways ones.  Only the
// pen turns: the panel and the charge line stay in screen coordinates, which is
// what keeps the text readable without a counter-rotation whose layout box
// would not turn with it and would spill out of the rounded background.
// The artwork is 760x150, so the short side follows the long one at almost
// exactly a fifth of it; keeping that ratio is what stops the pen looking
// stretched.  The panel grows with it, mostly sideways.
const PEN_LONG = 420;
const PEN_SHORT = Math.round(PEN_LONG * 150 / 760);

const SPenDockPopup = GObject.registerClass({
    Signals: {'dismissed': {}},
}, class SPenDockPopup extends St.BoxLayout {
    constructor() {
        super({
            style_class: 'spen-dock-popup',
            vertical: true,
            reactive: true,
            track_hover: false,
            can_focus: false,
        });

        this.set_pivot_point(0.5, 0.5);

        // Two actors, because a rotated actor keeps the allocation it had: the
        // outer box reserves the space the turned pen really needs, and the art
        // inside it is what turns.  One actor would either squash the pen or
        // hang it outside the rounded background.
        this._penBox = new St.Widget({x_align: Clutter.ActorAlign.CENTER});
        this._penArt = new St.Widget({style_class: 'spen-dock-pen'});
        this._penArt.set_pivot_point(0.5, 0.5);
        this._penBox.add_child(this._penArt);
        this.add_child(this._penBox);

        this._charge = new St.BoxLayout({
            style_class: 'spen-dock-charge',
            vertical: false,
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._percent = new St.Label({
            style_class: 'spen-dock-percent',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._batteryIcon = new St.Icon({
            style_class: 'spen-dock-battery',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._charge.add_child(this._percent);
        this._charge.add_child(this._batteryIcon);
        this.add_child(this._charge);

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
        // The artwork is the same file the app's own S Pen page uses.
        const tipRight = orientation === 'tip-right';
        this._penArt.remove_style_class_name(tipRight ? 'tip-left' : 'tip-right');
        this._penArt.add_style_class_name(tipRight ? 'tip-right' : 'tip-left');

        this._percent.text = battery < 0 ? '--%' : `${battery}%`;

        // Yaru and Adwaita both carry the level icons in tens, and the charging
        // variant is the one with the bolt through it.
        const level = battery < 0 ? 100 : Math.min(100, Math.max(0, Math.round(battery / 10) * 10));
        this._batteryIcon.icon_name = charging
            ? `battery-level-${level}-charging-symbolic`
            : `battery-level-${level}-symbolic`;
    }

    // Lay the panel out against the edge: the pen along it and nearest to it,
    // the charge line just inside.  On the sideways edges the pen stands up and
    // the panel runs across instead of down, which is the same arrangement seen
    // from the edge -- and the text never turns, so it always reads.
    setEdge(edge) {
        const sideways = edge === 'east' || edge === 'west';
        this.vertical = !sideways;

        const boxW = sideways ? PEN_SHORT : PEN_LONG;
        const boxH = sideways ? PEN_LONG : PEN_SHORT;
        this._penBox.set_size(boxW, boxH);
        this._penArt.set_size(PEN_LONG, PEN_SHORT);
        this._penArt.set_position(
            Math.round((boxW - PEN_LONG) / 2),
            Math.round((boxH - PEN_SHORT) / 2));
        this._penArt.rotation_angle_z = sideways ? 90 : 0;

        // The pen is the half that touches the edge, so on the far edges it has
        // to come second in screen order to still end up nearest.
        const penFirst = edge === 'north' || edge === 'west';
        this.set_child_at_index(this._penBox, penFirst ? 0 : 1);
        this.set_child_at_index(this._charge, penFirst ? 1 : 0);
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
        this._pendingId = 0;

        this._popup = new SPenDockPopup();
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
        this._cancelPending();
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

        // Pulling the pen out again cancels a panel that has not appeared yet.
        if (!docked) {
            this._cancelPending();
            return;
        }

        // Already up: keep it honest, in case the direction or the charge lands
        // after it appeared.
        if (this._popup.visible) {
            this._refresh();
            return;
        }

        // Waiting for the direction: show the moment it arrives.
        if (this._pendingId) {
            if (this._orientation() !== 'unknown')
                this._showNow();
            return;
        }

        if (was === docked || was === null)
            return;
        if (!this._settings.get_boolean(SETTING))
            return;

        if (this._orientation() !== 'unknown') {
            this._showNow();
            return;
        }
        this._pendingId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, ORIENTATION_WAIT_MS, () => {
                this._pendingId = 0;
                this._showNow();
                return GLib.SOURCE_REMOVE;
            });
    }

    _orientation() {
        return this._proxy.get_cached_property('PenOrientation')?.unpack() ?? 'unknown';
    }

    _showNow() {
        this._cancelPending();
        this._refresh();
        this._show();
    }

    _cancelPending() {
        if (this._pendingId) {
            GLib.source_remove(this._pendingId);
            this._pendingId = 0;
        }
    }

    _refresh() {
        this._popup.update(
            this._orientation(),
            this._proxy.get_cached_property('PenBattery')?.unpack() ?? -1,
            this._proxy.get_cached_property('PenCharging')?.unpack() ?? false);
    }

    // Where the panel sits against its edge, and where it starts from so that
    // it slides out of that edge rather than drifting in from a corner.  The
    // panel itself is never rotated, so its footprint is simply its size.
    _placement() {
        const monitor = Main.layoutManager.primaryMonitor;
        const edge = EDGE_FOR_TRANSFORM[this._transform % 4];
        const w = this._popup.width;
        const h = this._popup.height;
        const centredX = Math.round(monitor.x + (monitor.width - w) / 2);
        const centredY = Math.round(monitor.y + (monitor.height - h) / 2);

        switch (edge) {
        case 'north':
            return {edge,
                rest: [centredX, monitor.y + MARGIN],
                from: [centredX, monitor.y - h]};
        case 'south':
            return {edge,
                rest: [centredX, monitor.y + monitor.height - h - MARGIN],
                from: [centredX, monitor.y + monitor.height]};
        case 'west':
            return {edge,
                rest: [monitor.x + MARGIN, centredY],
                from: [monitor.x - w, centredY]};
        default:
            return {edge,
                rest: [monitor.x + monitor.width - w - MARGIN, centredY],
                from: [monitor.x + monitor.width, centredY]};
        }
    }

    _show() {
        this._cancelTimeout();
        // The arrangement decides the size, so the edge is applied before the
        // placement asks how big the panel turned out to be.
        this._popup.setEdge(EDGE_FOR_TRANSFORM[this._transform % 4]);
        this._popup.visible = true;
        this._popup.get_parent()?.queue_relayout();
        const {rest, from} = this._placement();

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
        const {from} = this._placement();
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
