// SPDX-License-Identifier: MIT
import assert from 'node:assert/strict';
import {recoverClosedCancellation} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/authRecovery.js';

const closed = new Error('closed');
const other = new Error('unrelated failure');
const cleanupError = new Error('cleanup failed');
let cleared = 0;
let recovered = 0;
const receiver = {
    _userVerifier: {get_connection: () => ({is_closed: () => true})},
    clear() { cleared++; this._userVerifier = null; },
};
const wrap = original => recoverClosedCancellation(original, e => e === closed, () => recovered++);
assert.equal(wrap(function (value) { assert.equal(this, receiver); return value; }).call(receiver, 7), 7);
assert.equal(cleared, 0); assert.equal(recovered, 0);
wrap(() => { throw closed; }).call(receiver);
assert.equal(cleared, 1); assert.equal(recovered, 1);
assert.equal(receiver._userVerifier, null);
assert.throws(() => wrap(() => { throw other; }).call(receiver), e => e === other);
assert.throws(() => wrap(() => { throw closed; }).call(receiver), e => e === closed);
const connected = {...receiver, _userVerifier: {get_connection: () => ({is_closed: () => false})}};
assert.throws(() => wrap(() => { throw closed; }).call(connected), e => e === closed);
const noConnection = {...receiver, _userVerifier: {get_connection: () => null}};
assert.throws(() => wrap(() => { throw closed; }).call(noConnection), e => e === closed);
const badCleanup = {_userVerifier: {get_connection: () => ({is_closed: () => true})},
    clear() { throw cleanupError; }};
assert.throws(() => wrap(() => { throw closed; }).call(badCleanup), e => e === cleanupError);
assert.equal(cleared, 1); assert.equal(recovered, 1);
console.log('PASS 7 closed-connection cancellation cases (no authentication result emitted)');
