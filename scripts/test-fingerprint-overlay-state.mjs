// Exercise the actual extension methods with lightweight actors, without
// importing GNOME resources, authenticating, or accessing hardware.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
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
const Main = {panel: {statusArea: {}}, overview: {hide() {}}};
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
