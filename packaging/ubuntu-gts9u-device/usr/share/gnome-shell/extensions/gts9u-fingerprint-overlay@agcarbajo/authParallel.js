// SPDX-License-Identifier: MIT
// Keep GNOME's password conversation independent of the background fingerprint
// conversation. A successful password still goes through GDM/PAM unchanged.

export const PASSWORD = 'gdm-password';
export const FINGERPRINT = 'gdm-fingerprint';

export function answerWithoutFingerprintMessages(original, isCancelled, reportError) {
    return async function (serviceName, answer) {
        if (serviceName !== PASSWORD || !this._userVerifier ||
            !this._messageQueue?.some(message => message.serviceName === FINGERPRINT))
            return original.call(this, serviceName, answer);

        try {
            // The user has explicitly submitted the password. Waiting for a
            // background fingerprint hint/error here delays its PAM answer.
            this._userVerifier.call_answer_query(
                serviceName, answer, this._cancellable, null);
        } catch (error) {
            if (!isCancelled(error))
                reportError(error);
        }
    };
}

export function beginPasswordImmediately(original) {
    return function (...args) {
        const result = original.apply(this, args);
        const verifier = this._userVerifier;
        if (verifier?._userName && verifier._getForegroundService?.() === PASSWORD)
            this.updateSensitivity(true);
        return result;
    };
}

export function finishPasswordImmediately(original) {
    return function (onComplete) {
        const verifier = this._userVerifier;
        if (this._queryingService === PASSWORD &&
            verifier?._messageQueue?.some(message => message.serviceName === FINGERPRINT))
            verifier.finishMessageQueue();
        return original.call(this, onComplete);
    };
}
