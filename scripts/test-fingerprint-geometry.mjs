// SPDX-License-Identifier: MIT
// Run with node scripts/test-fingerprint-geometry.mjs; no hardware required.
import assert from 'node:assert/strict';
import {sensorGeometry, panelMonitor} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/geometry.js';

let count = 0;
for (const scale of [1, 2, 3]) {
    for (let transform = 0; transform < 8; transform++) {
        const rotated = transform % 2;
        const monitor = {x: 120, y: 30, width: (rotated ? 1848 : 2960) / scale,
            height: (rotated ? 2960 : 1848) / scale};
        const target = sensorGeometry(monitor, transform);
        const cx = target.x + target.width / 2 - monitor.x;
        const cy = target.y + target.height / 2 - monitor.y;
        const inset = 1848 / scale * 16.7 / 196;
        const edge = ['right', 'bottom', 'left', 'top', 'left', 'bottom', 'right', 'top'][transform];
        const expectedX = edge === 'left' ? inset : edge === 'right' ? monitor.width - inset : monitor.width / 2;
        const expectedY = edge === 'top' ? inset : edge === 'bottom' ? monitor.height - inset : monitor.height / 2;
        assert.ok(Math.abs(cx - expectedX) <= 0.51);
        assert.ok(Math.abs(cy - expectedY) <= 0.51);
        assert.ok(target.x >= monitor.x && target.y >= monitor.y);
        assert.ok(target.x + target.width <= monitor.x + monitor.width);
        assert.ok(target.y + target.height <= monitor.y + monitor.height);
        count++;
    }
}
const monitor = {x: 0, y: 0, width: 1480, height: 924};
for (const bad of [-1, 8, null, NaN, 0.5]) {
    assert.equal(sensorGeometry(monitor, bad), null);
    count++;
}
assert.equal(sensorGeometry(null, 0), null); count++;
assert.equal(sensorGeometry({...monitor, width: 0}, 0), null); count++;
assert.equal(sensorGeometry({...monitor, x: NaN}, 0), null); count++;
const external = {x: 1480, y: 0, width: 1920, height: 1080};
const logical = [[1480, 0, 1, 0, true, [['HDMI-1']]], [0, 0, 2, 0, false, [['DSI-1']]]];
assert.deepEqual(panelMonitor(logical, [external, monitor]), {monitor, transform: 0}); count++;
assert.equal(panelMonitor([logical[0]], [external]), null); count++;
assert.equal(panelMonitor(logical, [external]), null); count++;
// Rotation lock: changing sensor orientation is deliberately not an input.
assert.deepEqual(sensorGeometry(monitor, 0), sensorGeometry({...monitor}, 0)); count++;
console.log(`PASS ${count} fingerprint geometry cases`);
