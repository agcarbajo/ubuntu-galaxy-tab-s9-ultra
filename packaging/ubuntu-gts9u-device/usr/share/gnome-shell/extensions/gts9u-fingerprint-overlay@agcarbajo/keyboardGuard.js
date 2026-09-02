// SPDX-License-Identifier: MIT
export function intersects(a, b) {
    if (!a || !b || ![a.x, a.y, a.width, a.height, b.x, b.y, b.width, b.height].every(Number.isFinite))
        return false;
    return a.width > 0 && a.height > 0 && b.width > 0 && b.height > 0 &&
        a.x < b.x + b.width && b.x < a.x + a.width &&
        a.y < b.y + b.height && b.y < a.y + a.height;
}

export function keyboardCovers(target, box, showing) {
    // GNOME anchors keyboardBox at the monitor's bottom. Its child translates
    // upward during animation. Reserve the entire final rectangle from the
    // first show/gesture frame, and until the hide animation has completed.
    return showing && intersects(target, {...box, y: box.y - box.height});
}
