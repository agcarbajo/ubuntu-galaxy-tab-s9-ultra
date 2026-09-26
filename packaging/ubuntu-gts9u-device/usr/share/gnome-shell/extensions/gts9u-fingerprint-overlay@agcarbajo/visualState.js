// SPDX-License-Identifier: MIT
// A short root-owned lease makes an abandoned waiting icon disappear. HBM
// remains authoritative for compensation, including older driver versions.
export function lightRequest(text, now) {
    const match = /^prepare ([0-9]+)\n?$/.exec(text ?? '');
    const token = match ? Number(match[1]) : 0;
    return Number.isSafeInteger(token) && token > 0 && token <= now &&
        now - token < 1_000_000 ? token : 0;
}

export function lightRelease(text, now) {
    const match = /^release ([0-9]+)\n?$/.exec(text ?? '');
    const token = match ? Number(match[1]) : 0;
    return Number.isSafeInteger(token) && token > 0 && token <= now &&
        now - token < 1_000_000 ? token : 0;
}

export function visualState(lease, now, hbm) {
    const match = /^active ([0-9]+)\n?$/.exec(lease ?? '');
    const expires = match ? Number(match[1]) : NaN;
    const waiting = Number.isSafeInteger(expires) && expires > now &&
        expires - now <= 3_000_000;
    return {active: Boolean(hbm) || waiting, illuminated: Boolean(hbm)};
}
