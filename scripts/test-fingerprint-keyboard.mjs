import assert from 'node:assert/strict';
import {keyboardCovers, intersects} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/keyboardGuard.js';
import {sensorGeometry} from '../packaging/ubuntu-gts9u-device/usr/share/gnome-shell/extensions/gts9u-fingerprint-overlay@agcarbajo/geometry.js';
let count = 0;
for (let transform = 0; transform < 8; transform++) {
    for (const scale of [1, 1.5, 2]) {
        const portrait = transform % 2 === 1;
        const monitor = {x: 37, y: 83, width: (portrait ? 1848 : 2960) / scale,
            height: (portrait ? 2960 : 1848) / scale};
        const target = sensorGeometry(monitor, transform);
        const box = {x: monitor.x, y: monitor.y + monitor.height,
            width: monitor.width, height: monitor.height * 0.38};
        const expected = target.y + target.height > box.y - box.height;
        assert.equal(keyboardCovers(target, box, true), expected);
        assert.equal(keyboardCovers(target, box, false), false);
        assert.equal(keyboardCovers(target, {...box, x: 10000}, true), false);
        count += 3;
    }
}
assert.equal(intersects({x: 0, y: 0, width: 5, height: 5}, {x: 5, y: 0, width: 5, height: 5}), false);
assert.equal(intersects(null, {}), false);
assert.equal(intersects({x: NaN, y: 0, width: 5, height: 5}, {}), false);
console.log(`PASS: ${count + 3} keyboard overlap cases`);
