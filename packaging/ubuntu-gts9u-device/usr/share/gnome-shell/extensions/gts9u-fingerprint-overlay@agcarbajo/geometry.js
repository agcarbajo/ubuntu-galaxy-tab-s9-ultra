// SPDX-License-Identifier: MIT
// Physical panel coordinates -> desktop coordinates, using Mutter's applied
// input transform (meta-monitor-manager.c), never accelerometer orientation.
export function sensorGeometry(monitor, transform) {
    if (!monitor || !Number.isInteger(transform) || transform < 0 || transform > 7 ||
        ![monitor.x, monitor.y, monitor.width, monitor.height].every(Number.isFinite) ||
        monitor.width <= 0 || monitor.height <= 0)
        return null;
    const shortAxis = Math.min(monitor.width, monitor.height);
    const longAxis = Math.max(monitor.width, monitor.height);
    const diameter = Math.round(shortAxis * 14.8 / 196);
    const inset = shortAxis * 16.7 / 196;
    const x = 1 - inset / longAxis;
    const y = 0.5;
    const points = [
        [x, y], [1 - y, x], [1 - x, 1 - y], [y, 1 - x],
        [1 - x, y], [y, x], [x, 1 - y], [1 - y, 1 - x],
    ];
    const [u, v] = points[transform];
    return {
        x: Math.round(monitor.x + u * monitor.width - diameter / 2),
        y: Math.round(monitor.y + v * monitor.height - diameter / 2),
        width: diameter,
        height: diameter,
    };
}

export function panelMonitor(logicalMonitors, shellMonitors) {
    const panel = logicalMonitors.find(logical =>
        logical[5].some(spec => spec[0] === 'DSI-1'));
    if (!panel)
        return null;
    const monitor = shellMonitors.find(item => item.x === panel[0] && item.y === panel[1]);
    return monitor ? {monitor, transform: panel[3]} : null;
}
