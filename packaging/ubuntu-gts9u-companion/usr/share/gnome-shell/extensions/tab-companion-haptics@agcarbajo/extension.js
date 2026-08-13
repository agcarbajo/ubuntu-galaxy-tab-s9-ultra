// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.agcarbajo.TabCompanion.Hardware';
const OBJECT_PATH = '/io/github/agcarbajo/TabCompanion/Hardware';

export default class TabCompanionHaptics extends Extension {
    enable() {
        this._settings = new Gio.Settings({
            schema_id: 'io.github.agcarbajo.TabCompanion',
        });
        this._proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            null,
            BUS_NAME,
            OBJECT_PATH,
            BUS_NAME,
            null
        );
        this._capturedId = global.stage.connect(
            'captured-event', this._capturedEvent.bind(this));
    }

    disable() {
        if (this._capturedId) {
            global.stage.disconnect(this._capturedId);
            this._capturedId = 0;
        }
        this._proxy = null;
        this._settings = null;
    }

    _capturedEvent(_stage, event) {
        if (event.type() !== Clutter.EventType.TOUCH_BEGIN ||
            !Main.keyboard.visible ||
            !this._settings.get_boolean('keyboard-haptics-enabled'))
            return Clutter.EVENT_PROPAGATE;

        const keyboard = Main.keyboard.keyboardActor;
        let actor = global.stage.get_event_actor(event);
        let keyFound = false;
        for (; actor && actor !== keyboard; actor = actor.get_parent()) {
            if (actor.has_style_class_name?.('keyboard-key'))
                keyFound = true;
        }
        if (!keyFound || actor !== keyboard)
            return Clutter.EVENT_PROPAGATE;

        const strength = Math.max(1, Math.min(3,
            this._settings.get_int('keyboard-haptics-strength')));
        const durations = [8, 14, 22];
        this._proxy.call(
            'Vibrate',
            new GLib.Variant('(uu)', [durations[strength - 1], 65535]),
            Gio.DBusCallFlags.NONE,
            500,
            null,
            null
        );
        return Clutter.EVENT_PROPAGATE;
    }
}
