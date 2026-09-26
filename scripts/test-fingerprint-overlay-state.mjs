// Exercise the actual extension methods with lightweight actors, without
// importing GNOME resources, authenticating, or accessing hardware.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isTypingKeyboard} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/authKeyboard.js';
import {visualState} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/visualState.js';
const source = readFileSync(new URL('../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/extension.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace('export default class', 'return class');
const timers = new Map();
const intervals = new Map();
let nextTimer = 1;
const GLib = {
    get_monotonic_time() { return 1000; },
    PRIORITY_DEFAULT: 0, SOURCE_CONTINUE: true, SOURCE_REMOVE: false,
    timeout_add(_priority, interval, callback) {
        timers.set(nextTimer, callback);
        intervals.set(nextTimer, interval);
        return nextTimer++;
    },
    timeout_add_seconds(...args) { return this.timeout_add(...args); },
    source_remove(id) { timers.delete(id); intervals.delete(id); },
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
overlay._refreshPanelFod = () => {};
overlay._syncAuthKeyboard = () => {};
overlay._updateFeedback = () => {};
overlay._position = () => {};
overlay._updateShade = () => {};
overlay._shadeOpacity = () => 135;
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
assert.equal(intervals.get(overlay._panelPollId), 50);
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
assert.equal(diagnostics.version, 22);
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

let paintCallback;
let presentations = 0;
let presentNow = 1000;
const watchers = [];
const Gts9uPresented = {PresentedWatcher: {new() {
    const watcher = {
        stopped: false,
        connect(name, callback) { assert.equal(name, 'presented'); this.callback = callback; return 1; },
        disconnect(id) { assert.equal(id, 1); this.callback = null; },
        stop() { this.stopped = true; },
        emit(view) { this.callback?.(this, view); },
    };
    watchers.push(watcher);
    return watcher;
}}};
const stage = {
    connect(name, callback) { assert.equal(name, 'after-paint'); paintCallback = callback; return 1; },
    disconnect(id) { assert.equal(id, 1); paintCallback = null; },
};
const presentationGio = {DBusCallFlags: {NONE: 0}, DBus: {system: {call(...args) {
    assert.equal(args[3], 'Presented');
    assert.deepEqual(args[4].value, ['c1', 1000]);
    presentations++;
}}}};
const presentationGLib = {...GLib, get_monotonic_time: () => presentNow, Variant: class {
    constructor(type, value) { assert.equal(type, '(st)'); this.value = value; }
}};
const Mtk = {Rectangle: class {}};
const view = x => ({get_layout(rectangle) {
    assert(rectangle instanceof Mtk.Rectangle, 'GNOME 46 requires a caller-allocated rectangle');
    Object.assign(rectangle, {x, y: 0});
}});
const PresentationType = new Function('Extension', 'GLib', 'Gio', 'global', 'Mtk', 'Gts9uPresented', source)(
    class {}, presentationGLib, presentationGio, {stage}, Mtk, Gts9uPresented);
const preparing = new PresentationType();
preparing._nativeGatesUsed = 0;
preparing._fallbackGatesUsed = 0;
preparing._panel = {monitor: {x: 0, y: 0}};
preparing._session = {Id: 'c1'};
preparing._canShowTarget = () => true;
preparing._lightRequest = () => 1000;
preparing._actor = {...actor(), visible: true, queue_redraw() {}};
preparing._shade = {...actor(), visible: true, queue_redraw() {}};
preparing._shadeReady = true;
preparing._requestLightPresentation(1000);
assert.equal(presentations, 0);
paintCallback(stage, view(2000));
assert(paintCallback);
paintCallback(stage, view(0));
assert.equal(presentations, 0);
const firstWatcher = watchers.at(-1);
firstWatcher.emit(view(0));
assert.equal(presentations, 0);
presentNow = 10_000;
firstWatcher.emit(view(0));
assert.equal(presentations, 1);
assert.equal(preparing._nativeGatesUsed, 1);
assert.equal(preparing._lastLightGateMs, 9);
assert(firstWatcher.stopped);
assert(!preparing._lightPresentId);
preparing._cancelLightPresentation();
preparing._requestLightPresentation(1000);
paintCallback(stage, view(0));
const stale = timers.get(preparing._lightPresentId);
preparing._cancelLightPresentation();
stale();
assert.equal(presentations, 1);
assert.equal(timers.size, 0);
preparing._requestLightPresentation(1000);
paintCallback(stage, view(0));
const fallbackTimer = timers.get(preparing._lightPresentId);
timers.delete(preparing._lightPresentId);
fallbackTimer();
assert.equal(presentations, 2);
assert.equal(preparing._fallbackGatesUsed, 1);
assert(watchers.at(-1).stopped);
preparing._cancelLightPresentation();
console.log('PASS: two native presentations acknowledge the painted shade; 35 ms fallback and cancellation remain');

let now = 1000;
let hbm = true;
const leaseGio = {File: {new_for_path: () => ({load_contents: () => [true, new Uint8Array()]})}};
const VisualType = new Function('Extension', 'GLib', 'Gio', 'visualState', source)(
    class {}, {...GLib, get_monotonic_time: () => now}, leaseGio, visualState);
const exitState = new VisualType();
exitState._panelFodActive = () => hbm;
exitState._lightRelease = () => 0;
exitState._canShowTarget = () => true;
exitState._lightRequest = () => 0;
assert.equal(exitState._visualState().illuminated, true);
hbm = false;
now = 2000;
assert.equal(exitState._visualState().illuminated, true);
now = 51999;
assert.equal(exitState._visualState().active, true);
now = 52000;
assert.equal(exitState._visualState().illuminated, false);
assert.equal(exitState._visualState().active, false);
console.log('PASS: compensation outlives HBM exit even after the active lease is removed');

// The panel holds its mode mutex through the 35 ms off settle. A pending
// sysfs read must not block Shell from consuming the separate release hint.
let finishModeRead;
let modeReads = 0;
let releaseFade;
let asyncSyncs = 0;
const asyncGio = {File: {new_for_path(path) {
    if (path.endsWith('/fod_mode')) return {
        load_contents_async(_cancellable, callback) {
            modeReads++;
            finishModeRead = () => callback(this, {});
        },
        load_contents_finish() { return [true, new TextEncoder().encode('0\n')]; },
    };
    return {load_contents() {
        const text = path.endsWith('/last-release') ? 'release 1000\n' : '';
        return [true, new TextEncoder().encode(text)];
    }};
}}};
const AsyncType = new Function('Extension', 'GLib', 'Gio', 'visualState', 'lightRelease', source)(
    class {}, {...GLib, get_monotonic_time: () => 2000}, asyncGio,
    visualState, (text, current) => {
        assert.equal(text, 'release 1000\n');
        assert.equal(current, 2000);
        return 1000;
    });
const asyncExit = new AsyncType();
asyncExit._displayCancellable = {};
asyncExit._hbmMode = true;
asyncExit._hbmWasActive = true;
asyncExit._releaseHintsSeen = 0;
asyncExit._shade = {visible: true};
asyncExit._fadeShade = (opacity, duration) => { releaseFade = [opacity, duration]; };
asyncExit._canShowTarget = () => false;
asyncExit._lightRequest = () => 0;
asyncExit._syncVisualState = () => { asyncSyncs++; };
asyncExit._refreshPanelFod();
asyncExit._refreshPanelFod();
assert.equal(modeReads, 1); // At most one worker blocked on the panel mutex.
asyncExit._visualState();
assert.equal(releaseFade, undefined); // Do not expose global HBM before DDIC-off.
assert.equal(asyncExit._releaseHintsSeen, 1);
assert.equal(asyncExit._lastReleaseHintDelayMs, 1);
finishModeRead();
assert.equal(asyncExit._hbmMode, false);
assert.equal(asyncSyncs, 1);
asyncExit._visualState();
assert.deepEqual(releaseFade, [0, 20]); // Fade only after mode zero.
console.log('PASS: release hint is processed while asynchronous panel read is pending');

let fadeNow = 1000;
let fadeHbm = false;
let fadedPresentations = 0;
let fadePaint;
const fadeStage = {
    connect(_name, callback) { fadePaint = callback; return 1; },
    disconnect() { fadePaint = null; },
};
const FadeType = new Function('Extension', 'GLib', 'Gio', 'global', 'Mtk', 'Clutter', 'visualState', 'Gts9uPresented', source)(
    class {}, {...presentationGLib, get_monotonic_time: () => fadeNow},
    {File: leaseGio.File, DBusCallFlags: {NONE: 0}, DBus: {system: {call() { fadedPresentations++; }}}},
    {stage: fadeStage}, Mtk, {AnimationMode: {EASE_IN_OUT_QUAD: 1}}, visualState,
    Gts9uPresented);
const fading = new FadeType();
fading._panel = {monitor: {x: 0, y: 0}};
fading._session = {Id: 'c1'};
fading._canShowTarget = () => true;
fading._lightRequest = () => 1000;
fading._panelFodActive = () => fadeHbm;
fading._lightRelease = () => 0;
fading._shadeOpacity = () => 135;
fading._actor = {...actor(), visible: true, queue_redraw() {}};
fading._icon = actor();
fading._shade = {...actor(), opacity: 0, queue_redraw() {},
    ease(options) { this.transition = options; },
    finish() { this.opacity = this.transition.opacity; this.transition.onComplete(); }};
fading._setIllumination(true);
assert.equal(fading._shade.opacity, 0);
assert.equal(fading._shade.transition.opacity, 135);
assert.equal(fading._shade.transition.duration, 20);
fading._updateShade();
assert.equal(fading._shade.opacity, 0);
fading._requestLightPresentation(1000);
fadePaint(fadeStage, view(0));
assert.equal(fading._lightPresentId, undefined);
fading._shade.finish();
assert.equal(fading._shadeReady, true);
fadePaint(fadeStage, view(0));
assert(fading._lightPresentId);
const fadePresent = timers.get(fading._lightPresentId);
timers.delete(fading._lightPresentId);
fadePresent();
assert.equal(fadedPresentations, 1);
fading._cancelLightPresentation();
fading._stopBrightnessPoll();
fadeHbm = true;
fading._visualState();
fading._lightRelease = () => 1500;
fadeNow = 1500;
fading._visualState();
assert.equal(fading._shade.opacity, 135);
assert.equal(fading._shade.transition.opacity, 135);
fading._lightRelease = () => 0;
fading._visualState();
assert.equal(fading._shade.opacity, 135);
fadeHbm = false;
fadeNow = 2000;
assert.equal(fading._visualState().illuminated, true);
assert.equal(fading._shade.transition.opacity, 0);
assert.equal(fading._shade.transition.duration, 20);
const obsoleteRelease = fading._shade.transition.onComplete;
fading._lightRequest = () => 2000;
fading._requestLightPresentation(2000);
assert.equal(fading._shade.transition.opacity, 135);
obsoleteRelease();
assert.equal(fading._shadeReady, false);
fading._shade.finish();
fadePaint(fadeStage, view(0));
assert(fading._lightPresentId);
fading._cancelLightPresentation();
fadeHbm = true;
fading._visualState();
fadeHbm = false;
fading._visualState();
const interruptedRelease = fading._shade.transition.onComplete;
fadeHbm = true;
fading._visualState();
assert.equal(fading._shade.opacity, 135);
interruptedRelease();
assert.equal(fading._shadeReady, true);
fadeHbm = false;
fading._visualState();
assert.equal(fading._shade.transition.opacity, 0);
fading._shade.finish();
assert.equal(fading._shade.opacity, 0);
fading._fadeShade(135);
const obsoletePrepare = fading._shade.transition.onComplete;
fading._finishHide();
obsoletePrepare();
assert.equal(fading._shadeReady, false);
assert.equal(timers.size, 0);
console.log('PASS: compensated fades gate presentation, release, rapid retry and cleanup');

let changed;
let canceled = false;
let refreshes = 0;
const WatchType = new Function('Extension', 'Gio', source)(class {}, {
    FileMonitorFlags: {NONE: 0},
    File: {new_for_path(path) {
        assert.equal(path, '/run/gts9u-fingerprint');
        return {monitor_directory(flags, cancellable) {
            assert.equal(flags, 0);
            assert.equal(cancellable, null);
            return {connect(name, callback) {
                assert.equal(name, 'changed');
                changed = callback;
            }, cancel() { canceled = true; }};
        }};
    }},
});
const watcher = new WatchType();
watcher._syncVisualState = () => { refreshes++; };
watcher._startVisualMonitor();
const path = name => ({get_basename: () => name});
changed(null, path('other'), null);
assert.equal(refreshes, 0);
changed(null, path('light'), null);
changed(null, path('light.new'), path('light'));
changed(null, path('active'), null);
assert.equal(refreshes, 3);
watcher._stopVisualMonitor();
assert(canceled);
changed(null, path('light'), null);
assert.equal(refreshes, 3);
const integration = new WatchType();
let watchedState = {active: true, illuminated: false, request: 0};
let requestSeen = 0;
integration._visualState = () => watchedState;
integration._active = false;
integration._illuminated = false;
integration._canShowTarget = () => true;
integration._actor = actor();
integration.Show = () => { integration._active = true; };
integration._finishHide = () => { integration._active = false; integration._stopVisualMonitor(); };
integration._setIllumination = lit => { integration._illuminated = lit; };
integration._requestLightPresentation = token => { requestSeen = token; };
integration._updateFeedback = () => {};
integration._syncVisualState();
assert(integration._visualMonitor);
watchedState = {active: true, illuminated: true, request: 3000};
changed(null, path('light'), null);
assert.equal(integration._illuminated, true);
assert.equal(requestSeen, 3000);
watchedState = {active: false, illuminated: false, request: 0};
integration._syncVisualState();
assert.equal(integration._visualMonitor, null);
const FailingWatchType = new Function('Extension', 'Gio', source)(class {}, {
    File: {new_for_path() { throw Error('runtime directory unavailable'); }},
});
const fallback = new FailingWatchType();
fallback._startVisualMonitor();
assert.equal(fallback._visualMonitorFailed, true);
console.log('PASS: active capture watches lease/request changes; idle and failures keep the poll fallback');
