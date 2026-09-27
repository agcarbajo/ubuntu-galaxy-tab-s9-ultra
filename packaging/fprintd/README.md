# Matched-finger notification for Noble

`fprintd 1.94.3-1+gts9u2` keeps Noble's daemon and adds the newer
`VerifyFingerMatched(s finger_name)` D-Bus signal. The anatomical name comes
from `fp_print_get_finger(match)` in libfprint's real match callback, never a
secure slot, log, or requested candidate. The signal is sent **only to the
client holding the claim**, before the unchanged terminal `VerifyStatus` on
the same connection, and never on rejection, retry, cancellation or a repeated
terminal report. Companion requires both the name and `verify-match`.

This lets Companion use one `VerifyStart("any")`, like GNOME login. Existing
clients can ignore the extra signal. No authentication decisions, policy,
PAM configuration files, template storage, capture code or secure-owner lifecycle change.
The driver still searches its existing independent encrypted identities;
this is not a parallel-gallery or recognition-performance optimization.

Build with `scripts/build-fprintd-matched.sh` after creating the existing Noble
arm64 buildroot. It checks pinned source/runtime-package hashes, applies this
patch, compiles the daemon and PAM module, and reuses Ubuntu's runtime packaging (including
service, policy and upgrade scripts). It also builds the matching
`libpam-fprintd` package. Its module returns `PAM_IGNORE` before touching the
reader when `PAM_SERVICE` is `gdm-password`: the live GDM password stack
includes `common-auth`, which otherwise runs `pam_fprintd` for up to ten
seconds before `pam_unix`. GDM's separate `gdm-fingerprint` service and all
other PAM services retain the original biometric path. The PAM profile and
maintainer scripts are byte-for-byte unchanged from Ubuntu; the module,
documented patch, version, maintainer and exact dependency change. Both packages
must be installed as a pair. `packaging/fprintd/version` is their common source
of version information. Keep both original Ubuntu packages from the cache for
rollback, together with the previous Companion package. Upgrade only while the
reader is idle.

## Dependency regression and build protection

Noble's original `libpam-fprintd` requires `fprintd (= 1.94.3-1)`, not a minimum
version. Installing only `fprintd 1.94.3-1+gts9u1` left authentication working
but broke APT's dependency graph. Its automatic repair proposed removing both
`libpam-fprintd` and `ubuntu-gts9u-device`. Do not use that removal as a fix.

For an existing tablet with the patched daemon, build only the missing paired
PAM package with `scripts/build-fprintd-pam-package.sh`. Simulate a targeted
`apt-get --fix-broken --no-remove install /path/to/libpam-fprintd_1.94.3-1+gts9u1_arm64.deb`
first, verify it upgrades only that package, then install it. The explicit
local package supplies the correction; `--no-remove` forbids the destructive
repair suggested without that package. Preserve and
compare `/etc/pam.d`, the PAM module and fingerprint-store hashes. Do not edit
the dpkg database, drop the dependency, force dependencies, reset PAM defaults,
or run an unrelated full upgrade as part of this repair.

The normal builder now emits both packages and runs eight regression tests:
PAM payload limited to the module and documented patch, unchanged maintainer scripts,
matching versions/dependency, rejection
of the broken pair, and isolated APT checks for original, broken, corrected and
future-mismatched pairs. Rootfs builds invalidate the cache if either half is
missing, validate the pair, select both by the shared version (not independently
by mtime), install them in the same APT transaction, and run `apt-get check`.
Deployment must also run **`apt-get check` and an upgrade simulation against the
real tablet**, because `dpkg --audit` alone does not validate dependency edges.

The 2026-09-03 live repair upgraded only `libpam-fprintd`. Hashes of every
`/etc/pam.d` file, the module/profile, saved prints, daemon and libfprint stayed
unchanged. `apt-get check`, `apt --simulate upgrade` and the automatic-repair
simulation then passed without removals. The complete package builder also
finished with the corrected pair and all eight package tests passing.

Upstream source: <https://archive.ubuntu.com/ubuntu/pool/main/f/fprintd/fprintd_1.94.3.orig.tar.bz2>

Signal API: <https://fprint.freedesktop.org/fprintd-dev/Device.html>

The patch also extends upstream virtual-device tests for named single/any
matches, no match, cancellation, signal ordering and claim-private delivery.
Those tests use upstream synthetic prints, not the tablet's biometric data.
