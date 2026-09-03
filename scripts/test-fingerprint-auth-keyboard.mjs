import assert from 'node:assert/strict';
import {hasKey, isTypingKeyboard, needsAuthKeyboard, AuthKeyboard} from
    '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/authKeyboard.js';

let checks = 0;
const check = (actual, expected) => { assert.deepEqual(actual, expected); checks++; };
const keys = [28, 30, 44, 57].reduce((bits, code) => bits | (1n << BigInt(code)), 0n).toString(16);
check(hasKey(keys, 30), true);
check(hasKey(keys, 31), false);
check(hasKey(`1 ${keys}`, 64), true);
check(hasKey('1 0', 64), true);
check(hasKey('1 0', 0), false);
check(hasKey('1', 130), false);
for (const bad of ['', 'zz', '-1', '10000000000000000'])
    check(hasKey(bad, 30), null);
const physical = {name: 'Book Cover Keyboard', vendor: '04e8', product: 'a037', keys};
check(isTypingKeyboard(physical), true);
check(isTypingKeyboard({...physical, name: 'Bluetooth UHID keyboard'}), true);
check(isTypingKeyboard({...physical, keys: '100000000000000000000000000000000000'}), null);
check(isTypingKeyboard({...physical, name: 'Power Button', keys: '10000000000000 0'}), false);
check(isTypingKeyboard({...physical, name: 'Tab Companion virtual keyboard', product: 'a036'}), false);
check(isTypingKeyboard({...physical, name: 'Tab Companion virtual keyboard', vendor: 'ffff'}), true);
const tabletAuth = {active: true, authenticating: true, panelPresent: true, physicalKeyboard: false};
check(needsAuthKeyboard(tabletAuth), true);
for (const partial of [{active: false}, {authenticating: false}, {panelPresent: false},
    {physicalKeyboard: true}, {physicalKeyboard: null}])
    check(needsAuthKeyboard({...tabletAuth, ...partial}), false);

const jobs = new Map();
let nextId = 0;
let focusRefreshes = 0;
let syncs = 0;
let lastTouch = false;
let touchMode = false;
let a11y = false;
let textFocused = true;
let visible = false;
const manager = {
    _lastDeviceIsTouchscreen() { assert.equal(this, manager); return lastTouch; },
    _a11yApplicationsSettings: {get_boolean(key) {
        assert.equal(this, manager._a11yApplicationsSettings);
        return key === 'screen-keyboard-enabled' && a11y;
    }},
    _syncEnabled() {
        syncs++;
        this.keyboardActor = ((touchMode && this._lastDeviceIsTouchscreen()) ||
            this._a11yApplicationsSettings.get_boolean('screen-keyboard-enabled')) ? {} : null;
        if (!this.keyboardActor)
            visible = false;
    },
    keyboardActor: null,
};
const original = manager._a11yApplicationsSettings.get_boolean;
const reports = [];
const policy = new AuthKeyboard(manager, {
    schedule: job => { jobs.set(++nextId, job); return nextId; },
    cancel: id => jobs.delete(id),
    refreshFocus: actor => { if (actor && textFocused) { focusRefreshes++; visible = true; } },
    report: enabled => reports.push(enabled),
});
const flush = () => { for (const job of jobs.values()) job(); jobs.clear(); };
policy.sync({...tabletAuth, authenticating: false});
check(syncs, 0);
policy.sync(tabletAuth);
check(policy.fallback, true);
check(Boolean(manager.keyboardActor), true);
check(a11y, false); // Preference is not written, even with native touch mode false.
check(manager._a11yApplicationsSettings.get_boolean('unrelated-key'), false);
check(visible, false);
flush();
check(visible, true);
check(focusRefreshes, 1);
visible = false; // User deliberately dismisses the native keyboard.
for (let i = 0; i < 100; i++) policy.sync(tabletAuth);
flush();
check(visible, false);
check(focusRefreshes, 1);
check(syncs, 1);
policy.sync({...tabletAuth, physicalKeyboard: true});
check(policy.fallback, false);
check(manager.keyboardActor, null);
policy.sync(tabletAuth); // Unplug cover while password is focused.
flush();
check(visible, true);
policy.sync({...tabletAuth, authenticating: false}); // Login succeeded.
check(policy.fallback, false);
check(manager.keyboardActor, null);
lastTouch = true; // Native touch policy is preserved outside authentication.
touchMode = true;
manager._syncEnabled();
check(Boolean(manager.keyboardActor), true);
lastTouch = false;
a11y = true; // Accessibility preference stays authoritative.
manager._syncEnabled();
check(Boolean(manager.keyboardActor), true);
policy.sync(tabletAuth);
policy.sync({...tabletAuth, active: false}); // GDM seat handoff before idle.
flush();
check(policy.fallback, false);
check(focusRefreshes, 2);
textFocused = false;
policy.sync(tabletAuth);
flush();
check(focusRefreshes, 2); // Never steal focus from user selector or clock.
policy.sync({...tabletAuth, authenticating: false});
policy.sync(tabletAuth);
policy.destroy();
flush();
check(manager._a11yApplicationsSettings.get_boolean, original);
check(policy.fallback, false);
check(focusRefreshes, 2);
check(Boolean(manager.keyboardActor), true); // a11y untouched on disable.
check(jobs.size, 0);
assert(reports.includes(true) && reports.includes(false));
console.log(`PASS: ${checks} native authentication keyboard policy/lifecycle checks`);
