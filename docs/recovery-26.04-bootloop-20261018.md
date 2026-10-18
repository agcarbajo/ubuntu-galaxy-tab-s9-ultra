# Ubuntu 26.04 migration boot recovery, 2026-10-18

The v1.4.0 migration finished its package transaction and retained the original
Noble root. Its first Resolute boot failed before the root-slot hook ran:
`selected`, `pending` and `ready` existed, but `tried` did not. The persistent
journal ended with the completed offline migration and its reboot.

## Reproduced cause and source correction

`build-compatible-migration-initramfs.py` injected the executable
`scripts/local-bottom/gts9u-root-slot` into a trusted bootstrap which had no
`local-bottom` stage. It did not create `scripts/local-bottom/ORDER`.
initramfs-tools' `run_scripts()` sources that file rather than enumerating
executables. Executing the actual arm64 bootstrap's dispatcher in a chroot
failed with `can't open '/scripts/local-bottom/ORDER'`. PID 1 exits on this
shell error before either root selection or boot rollback can run.

The generator now registers the hook in ORDER, preserving existing commands
and avoiding duplicate registration. The initramfs validator rejects missing
dispatch tables and executable hooks not listed in them. The focused test
reproduces the fatal missing-table path, executes the actual packaged selector
with no migration store, and checks preservation and idempotence of registration.

## First physical boot

Only `init_boot` was written from TWRP, with a verified backup and complete
readback hash. The matching image in the new root's Ubuntu Dualboot set was
updated. The old root, its boot backup, Android's saved images and `/home`
were retained.

- Corrected `init_boot.img` SHA-256:
  `91064d2edb82f70e1e0b78e789d6af6f7581cd2f50b2460c3eab632edda1e1f7`.
- Corrected legacy-LZ4 ramdisk: 7,929,987 bytes, SHA-256
  `c210eeaf01fcd043a939b6bef3fb81df5dea4e24c92473ecc1a35fa579924fb0`.
- Frozen Linux source snapshot SHA-256:
  `93299fe280179cc17ec4444d99ea3b548928f46b5189937a41078dbcebcdc3bf`.
- `boot`, `vendor_boot` and `dtbo` were byte-identical to the failed release.
- SSH with the previously trusted host key reported Ubuntu 26.04.1,
  `7.2.9-dirty` and GNOME Shell 50.1. The owner confirmed Ubuntu on screen.
- `/` was the new retained-root slot, mounted read/write; `/home` was a bind
  of the original home directory. `dpkg --audit` was empty and `apt-get check`
  passed. GDM, NetworkManager, SSH, camera relays, panel recovery and Bluetooth
  services were active; service status does not establish physical acceptance
  of the corresponding peripherals.
- The root acceptance timer completed with status 0 and logged that Resolute
  was accepted and the previous root and boot set remain retained.
- A second reboot through the active GNOME session returned with a different
  kernel boot ID, the same Resolute root mounted read/write, active GDM and
  NetworkManager, clean `dpkg --audit` and successful `apt-get check`.
- Fingerprint startup timed out waiting for SPSS applications. Proton VPN's
  split-tunnelling service also failed. These are separate from the initramfs
  dispatcher failure and remain outside the boot-fix validation.

The PC evidence is under `work/recovery-20261018/` (ignored by Git). The
tablet's failing init_boot backup is under
`/var/lib/gts9u-diagnostics/recovery-20261018/` in the retained Noble root;
the original bootable images remain under `.gts9u-root/slots/<id>/backup/`.

## Packaging and acceptance

The repaired combined installation/update ZIP also carries the corrected
ramdisk in `/boot/initrd.img-7.2.9-dirty`, through hardware package
`ubuntu-gts9u-hardware 1.4.0-4`. It retains the existing release version and
uses the final filename suffix `bootfix4` to distinguish the rebuilt artifact.
No kernel or hardware package functionality is removed to repair boot.

Checks run: 18 migration regressions, three Plymouth regressions, the new
dispatch regression, 73 ELF dependency checks, init_boot size and legacy-LZ4
checks, Android v4 bundle validation and AVB footer/hash verification.
The corrected hardware package was also simulated against the running tablet:
one upgrade, zero removals.

## Fingerprint recovery and GNOME 50

After the first successful boots the owner requested repair of the reader.
The SPU firmware loaded, but `spdaemon` timed out waiting for NVM readiness;
`sec_nvm` repeatedly reported the absent `/mnt/vendor/persist/secnvm/`.
The migration excluded all of `/mnt`, including this Ubuntu-local persistent
state. The new directories were empty while the retained Noble root still
contained the original backing files. No Android persist partition was used.

The original Ubuntu-local NVM was copied to Resolute with exact private modes,
ownership and content verification, entirely on the tablet. Its original
remains retained. The migration now explicitly includes the two local NVM
trees before the `/mnt` exclusion, rejects symlink/foreign-filesystem roots,
and verifies their preservation alongside accounts and encrypted templates.
The provisioning helper also creates the required `secnvm` subdirectory on
fresh installations without replacing existing state. Tests cover private
modes, idempotence, symlink refusal, actual rsync preservation and exclusion of
other mounted-media paths.

Device 2.90 restored SPSS readiness and fprintd enumeration after reboot.
The owner's lock-screen/Companion test then exposed a second, distinct failure:
the overlay's enable method passed `affectsInputRegion` to GNOME 50's
`LayoutManager.addTopChrome()`. Its strict `Params.parse()` rejected that
removed option, preventing target display and therefore correctly withholding
the touch-to-light authorization.

Device 2.91 / overlay 24 selects the accepted chrome parameters by Shell
version, retaining the GNOME 46 input-region behavior and non-reactive actors.
The new regression executes the actual GNOME 50 `_trackActor` and Params
parser extracted from the target's `libshell-18.so`: the previous call fails
and the corrected call succeeds. Existing waiting, capture, presentation,
keyboard and cleanup tests pass.

After installation with zero removals and a full reboot, SPSS and its secure
cache became ready, the overlay reported ACTIVE with no loading error, and
fprintd completed a successful physical capture. **The owner explicitly
confirmed both lock-screen fingerprint unlock and Galaxy Companion's test.**
`dpkg --audit` remains empty and `apt-get check` passes. Proton VPN split
tunnelling still reports a separate failed service.

The final combined ZIP carries Device 2.91, hardware 1.4.0-4 and the corrected
frozen migration backend in both installation paths. Its immutable source
snapshot SHA-256 (including Galaxy Companion 1.0.0) is
`c4e372c4ed316ac5cc1acfd1d8709bce3d7e80de22e70ba4ff421d5e476f7e37`.
Final focused checks include 20 migration tests, 25 provisioning tests, the
overlay state suite and the actual GNOME 50 chrome dispatcher test.

The local NVM repair backups and previous helper remain only on the tablet
under `/var/lib/gts9u-diagnostics/fingerprint-recovery-20261018/`; the previous
overlay is under `overlay-recovery-20261018/`. The repair did not copy the
tablet's restored NVM, templates, accounts or SSH identity into the build.

## Galaxy Companion 1.0.0 and draft releases

The owner requested the latest Companion source and then explicitly requested
draft releases pending further fixes. Remote commit `564f233` was reviewed and
fast-forwarded in its own repository. Companion commit `c27c006` prepares 1.0.0
and removes the obsolete input-region option from its S Pen popup; that popup
already uses GNOME 46's interactive default. All 17 Companion Python test
suites, package validation and Android unit tests passed in native WSL Ubuntu
24.04. Docker Desktop could not start because of a local service/socket error.
The APK certificate is identical to the previously published 0.9.0 APK.

This port now pins `c27c006a662fc50691473158c4cb7d42d7aa60d1`, builds through
its submodule wrapper and carries both `galaxy-companion` and the transitional
package at Debian version `1:1.0.0`. The ZIP's Companion package is byte-identical
to the Companion draft's asset (SHA-256
`2e5e466020083d4aab224fdb66234f7a08c583c1332a655ed18a74ca8d136a51`).
Companion 1.0.0 is a draft, not a public stable release. The tablet's fingerprint
physical acceptance above preceded this app update; this final app package was
validated through its own tests and in the clean build root.

A destructive clean installation and physical rollback are not established
by these repaired migration boots. Full peripheral acceptance remains separate
from the now owner-confirmed fingerprint path.
