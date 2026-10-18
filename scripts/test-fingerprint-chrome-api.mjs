// Exercise the upstream GNOME Shell dispatcher, not a permissive API mock.
// Usage: node --experimental-default-type=module scripts/test-fingerprint-chrome-api.mjs layout.js params.js
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fingerprintChromeOptions} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/chromeCompat.js';

assert.equal(process.argv.length, 4, 'Supply layout.js and params.js from the target Shell resource');
const layout = readFileSync(process.argv[2], 'utf8');
const parser = readFileSync(process.argv[3], 'utf8');
const defaults = layout.match(/const defaultParams = (\{[\s\S]*?\n\});/);
const method = layout.match(/    _trackActor\(actor, params\) \{([\s\S]*?)\n    \}\n/);
assert(defaults && method, 'Target Shell source must expose the actual chrome dispatcher');
const defaultParams = new Function(`return ${defaults[1]}`)();
const Params = new Function(parser.replace('export function parse', 'function parse') + '\nreturn {parse};')();
const trackActor = new Function('Params', 'defaultParams', `return function(actor, params) {${method[1]}\n}`)(Params, defaultParams);
const manager = {
    _trackedActors: [], _findActor() { return -1; },
    _queueUpdateRegions() {}, _untrackActor() {}, _updateActorVisibility() {},
};
const actor = {reactive: false, connectObject() {}};
assert.throws(() => trackActor.call(manager, actor,
    {trackFullscreen: true, affectsInputRegion: false}), /Unrecognized parameter/);
trackActor.call(manager, actor, fingerprintChromeOptions('50.1'));
assert.equal(manager._trackedActors.length, 1);
assert.equal(manager._trackedActors[0].trackFullscreen, true);
assert.equal(actor.reactive, false);
console.log('PASS: real GNOME 50 _trackActor rejects the old call and accepts the passive fingerprint overlay');
