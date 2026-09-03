import assert from 'node:assert/strict';
import {KeyboardEventGuard} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/keyboardEvents.js';

let actor = null;
let lookups = 0;
let handled = 0;
const event = {};
const manager = {
    keyboardActor: {},
    maybeHandleEvent(received) {
        assert.equal(this, manager);
        assert.equal(received, event);
        handled++;
        if (!this.keyboardActor)
            return false;
        if (!actor)
            throw new Error('Argument descendant may not be null');
        if (actor.failure)
            throw actor.failure;
        return Boolean(actor.inKeyboard || actor.extendedKey);
    },
};
const original = manager.maybeHandleEvent;
assert.throws(() => original.call(manager, event), /descendant/); // Reproduce native failure.
handled = 0;
const guard = new KeyboardEventGuard(manager, received => {
    assert.equal(received, event);
    lookups++;
    return actor;
});
assert.equal(manager.maybeHandleEvent(event), false); // Propagate, don't consume or throw.
assert.equal(guard.targetlessEvents, 1);
assert.equal(handled, 0);
actor = undefined;
assert.equal(manager.maybeHandleEvent(event), false);
assert.equal(guard.targetlessEvents, 2);
actor = {inKeyboard: true};
assert.equal(manager.maybeHandleEvent(event), true);
actor = {extendedKey: true};
assert.equal(manager.maybeHandleEvent(event), true);
actor = {};
assert.equal(manager.maybeHandleEvent(event), false);
const unrelated = new Error('Unrelated native failure');
actor = {failure: unrelated};
assert.throws(() => manager.maybeHandleEvent(event), error => error === unrelated);
manager.keyboardActor = null;
const before = lookups;
assert.equal(manager.maybeHandleEvent(event), false);
assert.equal(lookups, before); // Preserve native no-keyboard early return.
guard.destroy();
assert.equal(manager.maybeHandleEvent, original);
const second = new KeyboardEventGuard(manager, () => null);
const otherWrapper = () => false;
manager.maybeHandleEvent = otherWrapper;
second.destroy();
assert.equal(manager.maybeHandleEvent, otherWrapper); // Don't clobber another owner.
assert.throws(() => new KeyboardEventGuard({}, () => null), /Unsupported/);
console.log('PASS: 10 native keyboard targetless-event/dispatch/restoration cases');
