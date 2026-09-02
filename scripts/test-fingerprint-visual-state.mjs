// Pure visual lease tests. No GNOME session or fingerprint device is accessed.
import assert from 'node:assert/strict';
import {visualState} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/visualState.js';
const cases = [
    ['', 1000, false, false, false],
    [null, 1000, false, false, false],
    ['active 3001000\n', 1000, false, true, false],
    ['active 3001000\n', 1000, true, true, true],
    ['active 3001000\n', 3001000, false, false, false],
    ['active 1000\n', 2000, false, false, false],
    ['active 900000000000000000\n', 1000, false, false, false],
    ['active 4001000\n', 1000, false, false, false],
    ['active NaN\n', 1000, false, false, false],
    ['active 3001000\nextra', 1000, false, false, false],
    ['active -5\n', 1000, false, false, false],
    ['', 1000, true, true, true], // Legacy driver: never drop HBM compensation.
    ['active 1000\n', 2000, true, true, true],
];
for (const [lease, now, hbm, active, illuminated] of cases)
    assert.deepEqual(visualState(lease, now, hbm), {active, illuminated});
console.log(`PASS: ${cases.length} visual lease states`);
