# 2.0.0 release validation

Build date: 2026-10-19. Source revision:
`b39d227113cc8decffb795cba86250bfcb1c1955`; immutable source-tree SHA-256:
`06c4227245b78ec3e724953b0a39e3337fc8dbcf328df2fd49fd4a1db8f6262f`.
Galaxy Companion is pinned to `cbf80fd6b163e03a7b2fd998b0a2cd4d7f099ee5`.

The clean filesystem and update payload contain the same exact package
versions, including Device 2.91, Companion 1:1.0.0, the GNOME 50 hysteresis pair
and the matching hardware package 2.0.0-1. APT preparation reports three
upgrades, one new package, fifteen reinstalls and zero removals. Package audit
and dependency checks pass. The final filesystem contains no personal accounts,
fingerprints, network credentials, build SSH host keys or shared machine ID.
Chrome Beta is absent.

All 20 Companion test suites and nine selected port regression suites pass.
The combined ZIP passes CRC, manifest, boot layout, initramfs, root-image digest,
package ownership and frozen backend checks. The validator verifies 63 staged
modules and 68 packaged modules against the kernel release and certificate;
the separate alignment check uses the matching vmlinux and exported symbol CRCs.
All four boot images are byte-identical to the physically accepted set.

The published 1.3.0 ZIP was downloaded and authenticated before extracting the
offline migration fixture (SHA-256
`8f0e964f5627db1a6a31f80bf33844aecbfdf4bc037a1ea93244036fbf792f8d`).
Installing the README's Companion/transition pair into a copy succeeds with
zero removals; the real current migration entry imports correctly under Noble.
The original extracted fixture remains intact.

The full frozen transaction then passed against a second, disposable copy of
that prerequisite-updated fixture using the exact final combined ZIP. It
installed 1,571 packages from authenticated archives and removed 16 reviewed
obsolete or replaced packages. All 19 release packages remain protected. APT
dependency checks, dpkg audit, installed-version comparisons, original-root
integrity, shared-home preservation and protected identity checks pass. This
was an offline ARM64-emulated package transition, not a physical boot or
rollback test. Service-reload warnings in the chroot are expected because
services are deliberately prevented from starting there.

Artifacts:

| File | SHA-256 |
|---|---|
| ubuntu-26.04-sm-x910-v2.0.0.zip | `1a824ea3c2f33b38fad0ec15b755f0b492bfe2c5318d0794c03302cdd0840612` |
| galaxy-companion_1.0.0_all.deb | `061efd754b582afb1e5a3f73d20e598a5c5aa4d404eb51f3a8a1bbc6d5336d4e` |
| ubuntu-gts9u-companion_1.0.0_all.deb | `c0c662ef9e995924c5ad6d8f58bb3e8b4d15d9d66bef604741be8f6f9fa886a2` |
| galaxy-companion-dualboot_1.0.0.apk | `28ab85f46cf49c1bdba1b73aaef2b6158536f4138504aef16fdb0bd08ffac48f` |

The APK is the exact signed binary accepted on Android 16 / One UI 8, including
root authorization and return to the selected Ubuntu 26 installation. Source
comparison confirms no Android changes since that build.

Owner-confirmed hardware acceptance is recorded in the
[follow-up](resolute-followup-20261018.md). This publication does not perform a
destructive fresh installation, erase the retained system, or repeat physical
migration/rollback on the tablet. Second-unit fingerprint provisioning,
DualShock 4 physical input and the intermittent cover-repeat reproduction
remain outside the completed physical checks. The machine-readable validation
report preserves those limits rather than labelling static checks as boot
acceptance.
