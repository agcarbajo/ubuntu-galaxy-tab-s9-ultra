// SPDX-License-Identifier: MIT
// GNOME 46 cancel() throws before clear() when GDM's private connection has
// closed. Recover only that exact condition. Never complete authentication,
// unlock the session, change PAM policy or swallow unrelated exceptions.
export function recoverClosedCancellation(original, isClosedError, recovered) {
    return function (...args) {
        try {
            return original.apply(this, args);
        } catch (error) {
            if (!isClosedError(error) ||
                !this._userVerifier?.get_connection()?.is_closed())
                throw error;
            this.clear();
            recovered();
            return undefined;
        }
    };
}
