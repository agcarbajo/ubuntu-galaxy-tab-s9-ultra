// SPDX-License-Identifier: MIT
import assert from 'node:assert/strict';
import {answerWithoutFingerprintMessages, beginPasswordImmediately,
    finishPasswordImmediately, PASSWORD, FINGERPRINT} from
    '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/authParallel.js';

const calls = [];
const cancelled = new Error('cancelled');
const verifier = {
    _messageQueue: [{serviceName: FINGERPRINT}],
    _userVerifier: {call_answer_query(...args) { calls.push(args); }},
    _cancellable: {},
};
const originalAnswer = function (...args) { calls.push(['original', ...args]); };
const answer = answerWithoutFingerprintMessages(originalAnswer,
    error => error === cancelled, error => { throw error; });
await answer.call(verifier, PASSWORD, 'test-only');
assert.deepEqual(calls[0], [PASSWORD, 'test-only', verifier._cancellable, null]);
await answer.call(verifier, FINGERPRINT, 'ignored');
assert.deepEqual(calls[1], ['original', FINGERPRINT, 'ignored']);
verifier._messageQueue = [];
await answer.call(verifier, PASSWORD, 'ordinary');
assert.deepEqual(calls[2], ['original', PASSWORD, 'ordinary']);

const prompt = {
    _userVerifier: {_userName: 'test', _getForegroundService: () => PASSWORD},
    updateSensitivity(value) { calls.push(['sensitive', value]); },
};
const begin = beginPasswordImmediately(function () { calls.push(['native-begin']); });
begin.call(prompt);
assert.deepEqual(calls.slice(-2), [['native-begin'], ['sensitive', true]]);
prompt._userVerifier._getForegroundService = () => FINGERPRINT;
begin.call(prompt);
assert.deepEqual(calls.at(-1), ['native-begin']);

let finished = 0;
const finish = finishPasswordImmediately(function (done) {
    assert.equal(this._userVerifier._messageQueue.length, 0);
    done();
});
const passwordPrompt = {
    _queryingService: PASSWORD,
    _userVerifier: {
        _messageQueue: [{serviceName: FINGERPRINT}],
        finishMessageQueue() { this._messageQueue = []; },
    },
};
finish.call(passwordPrompt, () => finished++);
assert.equal(finished, 1);
const fingerprintPrompt = {
    _queryingService: FINGERPRINT,
    _userVerifier: {
        _messageQueue: [{serviceName: FINGERPRINT}],
        finishMessageQueue() { throw new Error('must preserve fingerprint messages'); },
    },
};
finishPasswordImmediately(function () {
    assert.equal(this._userVerifier._messageQueue.length, 1);
}).call(fingerprintPrompt, () => {});
console.log('PASS password and fingerprint conversations remain independent');
