// Exercise the actual extension methods with lightweight actors, without
// importing GNOME resources, authenticating, or accessing hardware.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isTypingKeyboard} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/authKeyboard.js';
const source = readFileSync(new URL('../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/extension.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace('export default class', 'return class');
const timers = new Map();
let nextTimer = 1;
const GLib = {
    get_monotonic_time() { return 1000; },
    PRIORITY_DEFAULT: 0, SOURCE_CONTINUE: true, SOURCE_REMOVE: false,
    timeout_add(_priority, _interval, callback) {
        timers.set(nextTimer, callback);
        return nextTimer++;
    },
    timeout_add_seconds(...args) { return this.timeout_add(...args); },
    source_remove(id) { timers.delete(id); },
};
const Main = {panel: {statusArea: {quickSettings: {menu: {close() {
    assert.fail('Overlay must not close a native menu');
}}}}}, overview: {hide() { assert.fail('Overlay must not hide overview'); }}};
const Type = new Function('Extension', 'GLib', 'Main', source)(class {}, GLib, Main);
const overlay = new Type();
const actor = () => ({
    visible: false,
    show() { this.visible = true; }, hide() { this.visible = false; },
    set_style_class_name(value) { this.style_class = value; },
});
overlay._actor = actor();
overlay._shade = actor();
overlay._icon = actor();
overlay._panel = {};
overlay._uiAllowed = true;
overlay._uiReadyUntil = 1500000;
overlay._pulseAvailability = () => {};
overlay._syncAuthKeyboard = () => {};
overlay._updateFeedback = () => {};
overlay._position = () => {};
overlay._updateShade = () => {};
let state = {active: true, illuminated: false};
overlay._visualState = () => state;
overlay._panelFodActive = () => state.illuminated;
overlay.Show();
assert(overlay.Visible && overlay._icon.visible && !overlay._shade.visible);
assert.equal(overlay._actor.style_class, 'gts9u-fingerprint-waiting');
assert(!overlay._brightnessPollId);
// Layout manager must not accidentally remap the black shade while waiting.
overlay._shade.show();
overlay._enforceInactive();
assert(!overlay._shade.visible);
overlay._startPanelPoll();
const poll = timers.get(overlay._panelPollId);
state = {active: true, illuminated: true};
poll();
assert(overlay.Visible && !overlay._icon.visible && overlay._shade.visible);
assert.equal(overlay._actor.style_class, 'gts9u-fingerprint-overlay');
assert(overlay._brightnessPollId);
overlay.Hide();
assert(overlay.Visible && overlay._shade.visible); // Keep compensation until HBM ends.
state = {active: true, illuminated: false};
poll();
assert(overlay.Visible && overlay._icon.visible && !overlay._shade.visible);
assert(!overlay._brightnessPollId);
overlay._uiAllowed = false;
poll();
assert(!overlay.Visible && !overlay._shade.visible);
overlay._actor.show();
overlay._enforceInactive();
assert(!overlay.Visible); // Layout remapping must not steal an OSK key.
overlay._uiAllowed = true;
poll();
assert(overlay.Visible && overlay._icon.visible);
overlay._uiReadyUntil = 999;
poll();
assert(!overlay.Visible); // Lost broker/expired acknowledgement.
overlay._uiReadyUntil = 1500000;
poll();
assert(overlay.Visible);
state = {active: false, illuminated: false};
poll();
assert(!overlay.Visible && !overlay._shade.visible);
assert(!overlay._hidePollId && !overlay._safetyTimeoutId);
overlay._actor.show();
overlay._shade.show();
overlay._enforceInactive();
assert(!overlay.Visible && !overlay._shade.visible);
overlay._stopPanelPoll();
assert.equal(timers.size, 0);
console.log('PASS: 12 overlay waiting/capture/keyboard/lease/cleanup transitions (mock actors, not rendering)');

const feedback = new Type();
feedback._feedback = actor();
let callback;
let disconnects = 0;
const verifier = {
    connect(signal, handler) { assert.equal(signal, 'show-message'); callback = handler; return 1; },
    disconnect(id) { assert.equal(id, 1); disconnects++; },
};
Main.screenShield = {_dialog: {_authPrompt: {_userVerifier: verifier}}};
let targetVisible = true;
feedback._canShowTarget = () => targetVisible;
feedback._updateFeedback();
callback(verifier, 'gdm-password', 'Private password message', 3);
feedback._updateFeedback();
assert(!feedback._feedback.visible);
callback(verifier, 'gdm-fingerprint', 'Place finger', 2);
feedback._updateFeedback();
assert(!feedback._feedback.visible);
callback(verifier, 'gdm-fingerprint', 'Huella no reconocida', 3);
feedback._updateFeedback();
assert(feedback._feedback.visible);
assert.equal(feedback._feedback.text, 'Huella no reconocida');
targetVisible = false;
feedback._updateFeedback();
assert(!feedback._feedback.visible);
Main.screenShield._dialog = null;
feedback._updateFeedback();
assert.equal(disconnects, 1);
assert(!feedback._feedback.visible);
console.log('PASS: 5 native feedback filtering/lifetime cases (no auth methods invoked)');

// No overlay actor should participate in input picking during a seat handoff.
assert.match(source, /this\._actor = new St\.Bin\(\{[^}]*reactive: false,/);
assert.match(source, /addTopChrome\(this\._actor,\s*\{trackFullscreen: true, affectsInputRegion: false\}\)/);
assert(!/this\._actor\.connect\('(touch|button-press|button-release)-event'/.test(source));
Main.sessionMode = {isGreeter: false};
Main.screenShield = {locked: false};
Main.keyboard = {keyboardActor: null, visible: false};
Main.modalCount = 0;
Main.actionMode = 1;
overlay._seat = {get_touch_mode: () => true};
overlay._physicalKeyboard = true;
overlay._session = {Active: true};
const diagnostics = JSON.parse(overlay.GetDiagnostics());
assert.equal(diagnostics.version, 14);
assert.equal(diagnostics.sessionActive, true);
assert.equal(diagnostics.targetReactive, false);
assert.equal(diagnostics.keyboardExists, false);
assert.equal(diagnostics.modalCount, 0);
const failing = new Type();
let restored = 0;
failing._authKeyboard = {destroy() { restored++; }};
failing._syncAuthKeyboardState = () => { throw new Error('test API failure'); };
const oldError = console.error;
const errors = [];
console.error = message => errors.push(message);
try {
    failing._syncAuthKeyboard();
    failing._syncAuthKeyboard();
} finally {
    console.error = oldError;
}
assert.equal(restored, 1);
assert.equal(errors.length, 1);
assert(failing._keyboardFailed);
console.log('PASS: passive target, read-only diagnostics and keyboard failure isolation');

const typingKeys = [28, 30, 44, 57].reduce((n, code) => n | (1n << BigInt(code)), 0n).toString(16);
let devices = {
    event0: {name: 'Power key', 'id/vendor': '0000', 'id/product': '0000', 'capabilities/key': '10000000000000 0'},
    event4: {name: 'Tab Companion virtual keyboard', 'id/vendor': '04e8', 'id/product': 'a036', 'capabilities/key': typingKeys},
};
let closes = 0;
const fakeGio = {
    FileQueryInfoFlags: {NONE: 0},
    File: {new_for_path(path) {
        if (path === '/sys/class/input') return {enumerate_children() {
            const names = ['input0', ...Object.keys(devices)];
            return {next_file() {
                const name = names.shift();
                return name ? {get_name: () => name} : null;
            }, close() { closes++; }};
        }};
        return {load_contents() {
            const [, event, field] = /^\/sys\/class\/input\/(event\d+)\/device\/(.+)$/.exec(path);
            if (devices[event][field] === undefined) throw Error('Hotplug');
            return [true, new TextEncoder().encode(devices[event][field])];
        }};
    }},
};
const ScanType = new Function('Extension', 'Gio', 'isTypingKeyboard', source)(class {}, fakeGio, isTypingKeyboard);
const scanner = new ScanType();
assert.equal(scanner._scanPhysicalKeyboards(), false);
devices.event8 = {name: 'Book Cover', 'id/vendor': '04e8', 'id/product': 'a035', 'capabilities/key': typingKeys};
assert.equal(scanner._scanPhysicalKeyboards(), true); // Even if absent from Mutter's inventory.
delete devices.event8;
assert.equal(scanner._scanPhysicalKeyboards(), false);
devices.event9 = {name: 'Bluetooth keyboard', 'id/vendor': '0001', 'id/product': '0002', 'capabilities/key': typingKeys};
assert.equal(scanner._scanPhysicalKeyboards(), true);
delete devices.event9['capabilities/key'];
assert.equal(scanner._scanPhysicalKeyboards(), true); // Unknown: conservative until next scan.
assert.equal(closes, 5);
console.log('PASS: 5 actual sysfs inventory/hotplug paths with closed enumeration handles');
