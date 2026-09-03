// SPDX-License-Identifier: MIT
// GNOME 46 normally requires the last non-keyboard device to be a touchscreen.
// Goodix consumes FOD contacts before Mutter, including the first GDM contact.
// Add a local enable predicate only during tablet authentication. Do not change
// a11y settings, focus, credentials, or GNOME's authentication state.

export function hasKey(bitmap, code) {
    const words = bitmap.trim().split(/\s+/);
    if (!words.length || words.some(word => !/^[\da-f]{1,16}$/i.test(word)))
        return null;
    // This package targets arm64; sysfs prints most-significant ulong first.
    const word = words.at(-1 - Math.floor(code / 64));
    return word ? (BigInt(`0x${word}`) & (1n << BigInt(code % 64))) !== 0n : false;
}

export function isTypingKeyboard({name, vendor, product, keys}) {
    // The companion's forwarding device exists even with the cover detached.
    // Do not ignore all virtual sysfs devices: Bluetooth keyboards use UHID.
    if (name === 'Tab Companion virtual keyboard' &&
        vendor === '04e8' && product === 'a036')
        return false;
    const capabilities = [28, 30, 44, 57].map(code => hasKey(keys, code));
    if (capabilities.includes(null))
        return null;
    return capabilities.every(Boolean); // Enter, A, Z, Space; not power/lid keys.
}

export function needsAuthKeyboard({active, authenticating, panelPresent, physicalKeyboard}) {
    return Boolean(active && authenticating && panelPresent && physicalKeyboard === false);
}

export class AuthKeyboard {
    constructor(manager, {schedule, cancel, refreshFocus, report}) {
        if (typeof manager?._a11yApplicationsSettings?.get_boolean !== 'function' ||
            typeof manager?._syncEnabled !== 'function')
            throw new Error('Unsupported native KeyboardManager');
        this._manager = manager;
        this._schedule = schedule;
        this._cancel = cancel;
        this._refreshFocus = refreshFocus;
        this._report = report;
        this._idle = 0;
        this.fallback = false;
        this._settings = manager._a11yApplicationsSettings;
        this._original = this._settings.get_boolean;
        const policy = this;
        this._wrapper = function (key) {
            const native = policy._original.call(this, key);
            return native || (key === 'screen-keyboard-enabled' && policy.fallback);
        };
        // This Settings instance is private to KeyboardManager. Supplement only
        // its enable predicate, not the shared Clutter seat or stored setting.
        // Native handlers already bound in its constructor see this predicate
        // too, so a last-device change cannot destroy a needed password OSK.
        this._settings.get_boolean = this._wrapper;
    }

    sync(state) {
        const next = needsAuthKeyboard(state);
        if (next === this.fallback)
            return;
        if (this._idle)
            this._cancel(this._idle);
        this._idle = 0;
        this.fallback = next;
        this._manager._syncEnabled();
        if (next) {
            // The password entry may already have focus when the keyboard is
            // constructed. Refresh once, not on every poll: a manual hide must
            // remain hidden until the next native focus/authentication change.
            this._idle = this._schedule(() => {
                this._idle = 0;
                if (this.fallback)
                    this._refreshFocus(this._manager.keyboardActor);
            });
        }
        this._report(next);
    }

    destroy() {
        if (this._idle)
            this._cancel(this._idle);
        this._idle = 0;
        this.fallback = false;
        if (this._settings.get_boolean === this._wrapper) {
            this._settings.get_boolean = this._original;
            this._manager._syncEnabled();
        }
    }
}
