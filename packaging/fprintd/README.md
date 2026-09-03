# Matched-finger notification for Noble

`fprintd 1.94.3-1+gts9u1` keeps Noble's daemon and adds the newer
`VerifyFingerMatched(s finger_name)` D-Bus signal. The anatomical name comes
from `fp_print_get_finger(match)` in libfprint's real match callback, never a
secure slot, log, or requested candidate. The signal is sent **only to the
client holding the claim**, before the unchanged terminal `VerifyStatus` on
the same connection, and never on rejection, retry, cancellation or a repeated
terminal report. Companion requires both the name and `verify-match`.

This lets Companion use one `VerifyStart("any")`, like GNOME login. Existing
clients can ignore the extra signal. No authentication decisions, policy,
PAM files, template storage, capture code or secure-owner lifecycle change.
The driver still searches its existing independent encrypted identities;
this is not a parallel-gallery or recognition-performance optimization.

Build with `scripts/build-fprintd-matched.sh` after creating the existing Noble
arm64 buildroot. It checks pinned source/runtime-package hashes, applies this
patch, compiles only the daemon, and reuses Ubuntu's runtime packaging (including
service, policy and upgrade scripts). No `libpam-fprintd` is replaced. Keep the
original `fprintd_1.94.3-1_arm64.deb` from the cache for rollback, together with
the previous Companion package. Upgrade only while the reader is idle.

Upstream source: <https://archive.ubuntu.com/ubuntu/pool/main/f/fprintd/fprintd_1.94.3.orig.tar.bz2>

Signal API: <https://fprint.freedesktop.org/fprintd-dev/Device.html>

The patch also extends upstream virtual-device tests for named single/any
matches, no match, cancellation, signal ordering and claim-private delivery.
Those tests use upstream synthetic prints, not the tablet's biometric data.
