// SPDX-License-Identifier: MIT
// GNOME 50 removed the X11 input-region tracking option. Non-reactive actors
// retain their input transparency through Clutter on Wayland.
export function fingerprintChromeOptions(shellVersion) {
    const major = Number.parseInt(shellVersion, 10);
    if (!Number.isFinite(major))
        throw new Error('Unknown GNOME Shell version');
    const options = {trackFullscreen: true};
    if (major < 50)
        options.affectsInputRegion = false;
    return options;
}
