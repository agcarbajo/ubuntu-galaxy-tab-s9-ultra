# Ubuntu 26.04 / GNOME 50 upgrade assessment

Status: **combined clean-install/update trial ZIP built and exact-ZIP inactive-root
transaction passed**, 2026-10-04. Physical boot and hardware acceptance are
not established. This assessment uses `upgrade/ubuntu-26.04-gnome50`; the
virtualisation worktree and branch are independent.

> 2026-10-17: the migration backend now builds on Galaxy Companion (the
> `external/galaxy-companion` submodule) instead of Tab Companion, lives in
> `packaging/gts9u-migration/` and is frozen with the device profile; the
> v1.4.0 ZIP described below predates that change and would have to be
> rebuilt. "Companion 1.5.8" below corresponds to Galaxy Companion 0.9.0.

## Combined trial build and local ZIP support, 2026-10-04

The current combined file is `ubuntu-26.04-sm-x910-v1.4.0.zip`, SHA-256
`4d4fdd909aae9501b23039c63451b5ce96f7b5f7d5626f1d46b6c053d601fdbb`.
Unlike the earlier validation-only candidate, it includes the normal TWRP
installer and a clean ext4 `rootfs.img`, together with format-2 update packages
and the release-specific migration backend. The clean filesystem is
5,205,131,264 bytes (4,964 MiB), SHA-256
`33e87b9c4c4ed0b988ab87133fd83ea87ddae048b2d6a6fa5493468625779c4a`.
It was built with the repository's mmdebstrap customization hooks, 514 language
packages, Device 2.87, Companion 1.5.8 and the exact locked local package set.
The final ZIP is 1,624,800,564 bytes; its adjacent validation JSON binds the full
migration result to this exact SHA-256. The prerequisite Companion package is
SHA-256 `eb1e927b92bdc56305a125e9425480d875ca1f454bbd6453f6cbb38c57471559`.
No ordinary account, personal configuration or build SSH host keys enter the
shipping image.

The APT configuration-order simulation failure was reproduced independently.
An actual arm64 coreutils/sudo transaction in a new Noble fixture succeeds,
including clean dpkg/APT and protected-identity checks. The release engine now
freezes APT's bounded, versioned dependency selection separately from dpkg's
configuration-order simulation. Both preparation and offline application compare
the complete selected package/version/removal sets. Ubuntu archive signatures,
package checksums, downgrade rejection and the archive-kernel protection remain
active. Generated migration metapackages are placed in APT's canonical offline
cache too. The nine additional ABI/keybox replacements have named replacements
required in the same plan, not an unrestricted removal exception.

Two complete package transactions reached Resolute with 1,311 upgrades, 260 new
packages and 16 reviewed substitutions, but their preservation gate correctly
rejected activation: Resolute's tzdata removes `/etc/timezone` and rewrites
`/etc/localtime`. The engine restores the selected timezone representation and
the removed compatibility file before checking preservation. Rechecking the
inactive fixture then reports equal protected paths and account identities;
other changed protected state still aborts. The final exact-ZIP transaction was
repeated with this fix rather than treating the earlier rejected runs as
successful installations. The exact final ZIP's fresh full transaction then
passed: all 1,571 installed versions match the frozen plan, 1,577 cached archives
are hash-verified, all 16 reviewed substitutions are complete, dpkg/APT are clean,
protected identities/configuration match, and the original root/status database
and synthetic shared-home data remain unchanged. The result explicitly records
`physical_boot_validated: false`.

The real ext4 trial activation test was extended to start with a read-only
root. It failed writing the trial marker before the fix. Device 2.87's hook now
remounts the retained filesystem writable after checking its private store.
Trial activation, retained original root, shared-home inode identity and writable
home then pass. The actual early rollback script also restored all four boot
images with complete readback checks on newly created loop devices. These are
Linux filesystem/loop tests, not physical Samsung boot or power-loss evidence.

The compatible first-stage bootstrap retains the trusted published 1.3.0 early
runtime, removes every old module, and adds the current root-slot hook. It is
7,929,784 bytes, SHA-256
`c2d1c1aa3dc8410d1aae35529451d55f7206ccbcdb7b1ed3a59411bd14756e52`.
Its 73 unique ELF dependency closures, Plymouth and fsck pass, and it fits the
8 MiB init_boot budget in legacy LZ4. The full root is Resolute; this small
kernel-independent bootstrap avoids the oversized native Resolute initramfs.

Companion 1.5.8 extends the existing **Install from a ZIP** action. It hashes the
complete selected archive off the GTK thread, shows that digest and the release
migration warning, then sends the explicitly confirmed SHA-256 through polkit.
The privileged staging copy must still match. A private root-owned handoff record
binds origin, ZIP size/digest/tag and backend digest; the child rechecks it.
GitHub downloads still require the exact published stable tag, size and digest.
The same combined ZIP and migration engine support both origins. Old Companion
1.5.5/1.5.7 cannot learn this local authorization from a ZIP they already refuse;
install the supplied architecture-independent Companion 1.5.8 package first
for an unpublished local trial. No developer flag, fabricated Noble metadata,
publication or tablet change is needed to choose the ZIP afterward.

Readiness/authentication tests pass 20 cases, including locally confirmed handoff,
wrong digest/origin rejection and unchanged GitHub rejection. The GTK4/Adwaita
page test passes in WSLg with a memory GSettings backend and the built schemas;
its assertions never prepare an update. The complete trial build remains
experimental pending the final fixture result and physical cold boot, GNOME 50,
peripheral, clean-install and recovery acceptance.

## Earlier validation-only candidate, 2026-10-04 (superseded)


`artifacts/ubuntu-26.04-sm-x910-v1.4.0-candidate.zip` contains the Resolute
arm64 local packages, Linux `7.2.9-dirty`, four Android v4 boot images and the
release-specific migration backend. Its size is 185,205,284 bytes and SHA-256
is `4ac11bf93955b040c6f1febedbb315dfceb4bc104366ac6df1443a0f872df0d5`.
The adjacent `.validation.json` records build checks and explicitly says
`installation_approved: false` and `physical_validation: false`.

The new `scripts/build-migration-candidate.py` verifies the reused kernel
configuration, all 62 staged module releases/signing certificates and the
unchanged booted-reference DTB. It checks the Android v4 bundle, the compatible
legacy-LZ4 initramfs (73 ELF dependency closures, Plymouth, fsck and size),
dpkg/APT consistency in the isolated Resolute root, exact installed local
package versions, package-file ownership, every update-payload digest, ZIP
CRCs and the backend's read-only `--probe`. Export to Windows checks hashes
again and refuses to overwrite existing artifacts. `--verify-existing` also
checks every module extracted from the actual selected Debian packages; all
67 packaged modules passed the matching-release/certificate check.

`make-twrp-zip.py --update-only` omits `META-INF`, `vbmeta.img`, `rootfs.img`
and filesystem overlays. This candidate cannot accidentally execute the
clean-install TWRP route. It does not make the installed bridge accept an
unpublished migration: the official stable tag/size/digest gate is unchanged.
Do not publish this ZIP to bypass that gate before the transaction is fixed.

The actual native APT 2.8 resolver over the isolated arm64 package inventory
still exits 100 with `Conf Broken coreutils-from-uutils:arm64` and
`Conf Broken sudo-common:arm64`, including with deferred immediate
configuration. It proposes additional library/keybox removals outside the
existing reviewed list. No removals were authorized or applied. Two emulated
arm64 resolver runs were stopped after extended CPU-bound simulation; a
separate 180-second bounded run timed out. None constitutes a completed arm64
migration or a successful offline transaction. The new
`probe-migration-transaction.py` retains isolated simulation output, accepts
only fixture roots rather than `/`, and supports bounded native/emulated
comparisons. The production migration remains fail-closed.

Verification passed 44 updater cases (including the new update-only packaging
regression), 18 readiness/authenticated-handoff cases, 13 migration/root-retention
cases and the real ext4 root-slot mount test in a private namespace. The
update-only regression failed before implementing the builder option and passed
afterward. Root-slot and boot-error tests use synthetic data and file-backed
partition substitutes, not tablet partitions. Full root upgrade, physical
recovery, GNOME 50, new-kernel boot and peripheral acceptance remain pending.
No tablet access, installation, partition write, reboot, publication, commit
or push was performed in this continuation.

Read-only package validation from the repository on Linux/WSL:

```sh
python3 scripts/validate-update-zip.py artifacts/ubuntu-26.04-sm-x910-v1.4.0-candidate.zip
```

Candidate construction requires existing isolated, verified build inputs and
new output/workspace paths:

```sh
python3 scripts/build-migration-candidate.py --base "$build_base" \
  --rootfs "$resolute_root" --workspace "$new_workspace" \
  --output "$candidate_zip" --export-dir "$artifact_directory"
```

## Continuation from the published 1.3.0 bridge, 2026-10-03

The branch has been integrated with main at `916e2f13de00d0b5eba6c02c1a9d6e395e6b909e`,
with merge conflicts resolved but no commit or push, as the owner subsequently
requested. The Resolute recipes retain the later PAM/password, Caps Lock,
Plymouth, audio-session, TUN and Companion changes. Device 2.85 is newer than
the installed Noble 2.84; the Resolute fprintd/PAM pair and libfprint runtime
move to their respective `+gts9u2` revisions. These are build inputs, not
packages validated on hardware.

Read-only SSH inspection identified the SM-X910 on Ubuntu 24.04.5, port
1.3.0, Companion 1.5.5, Device 2.84 and `7.2.0-rc3-dirty`. Root was ext4 and
writable, with 233 GiB available; cgroups use v2. Package audit and a lock-free
APT dependency check passed. No tablet package, service, session, partition,
network configuration or boot image was changed.

The installed updater reports protocol 2, `distribution_migration: false`
and `release_backend_handoff: true`. It accepts the future release-specific
engine only after matching the complete local or downloaded ZIP to the exact
published stable GitHub tag, size and SHA-256. Being prepared for a backend is
not an implementation of the migration, and an unpublished local crossgrade
ZIP is not compatible with this bridge. That integrity gate remains intact.

Canonical's `meta-release-lts` now lists Resolute 26.04.1 with `Supported: 1`;
the earlier disabled LTS upgrade observation below is superseded. The proposed
migration must still freeze authenticated dependencies, review named obsolete
package removals, preserve third-party configuration and accounts, and recover
the old complete system root from an independent environment. No such backend
has been implemented or validated by this continuation.

The default kernel fetch now pins stable Linux 7.2.9 to official commit
`5fce161649b4d779d1b76d9fcd52dc77779774b8`, verified from the peeled upstream tag.
The per-board DTB gate remains unchanged. The prepared-CDSP 7.2.8 patch applies
with zero fuzz to the actual patched 7.2.9 FastRPC source; the NPU builder now
selects it for both exact stable releases. Kernel and arm64 userspace builds
are isolated in a newly installed WSL Ubuntu-24.04 under
`/root/ubuntu-gts9u-2604`, with the source snapshot under
`/root/ubuntu-gts9u-2604-source`. The kernel build completed with Clang 18.1.3.
All 62 staged modules, including compressed modules, match `7.2.9-dirty` and
the build certificate; the installed-output and object-tree configurations
match. `Image.gz` is SHA-256
`9d3d475f92cd920f2a7d6e640c0f5d8c2d74ae5ffe50d1210064057d5fd85480`,
the config is `8404b06a4404750171187caa32d2ef47a112f6ad22b632696094408a122c0eeb`,
and `Module.symvers` is
`9606ae924919ab4958ba8fbc2e6a45360134af4fc14b45e9940297a1d8e357dd`.
The final DTB passed the unchanged booted-reference hash gate
`613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4`.
The ABI change is intentional; none of the old tablet's signed modules may
be reused. This is compilation and signing evidence, not device validation.
The archive-root and libfprint arm64 builds remain in progress.

The rootfs pipeline now dispatches Resolute's camera ABI, libfprint/TOD and
fprintd/PAM versions, selects archive Mutter/GNOME Settings Daemon instead of
Noble binaries, explicitly requests Mutter 18 and the consolidated Ubuntu
extensions, and separates package-input caches by suite. Reusing a Noble
buildroot for Resolute is rejected before staging. The shipping release and
payload guards are deliberately still closed pending the migration backend.

The public 1.3.0 ZIP was downloaded and its complete SHA-256 matched
`8f0e964f5627db1a6a31f80bf33844aecbfdf4bc037a1ea93244036fbf792f8d`.
The bounded updater validator passed every payload hash. The new
`prepare-release-migration-fixture.py` extracts that trusted clean image into
a separate disposable Linux fixture; it never copies the owner's tablet data
or runs the TWRP installer. Fixture tests reject a wrong digest, wrong release
or existing output before extraction, and test provenance using simulated
debugfs. The real published rootfs fixture also extracted successfully and
contains Device 2.84 and Companion 1.5.5, matching the current bridge. A clean
installation need not have `ubuntu-gts9u-hardware` in dpkg; the updater adds
that package, whereas the clean image already has the corresponding files.
Migration preflight must support both inventories. A real dependency migration
and rollback remain outstanding.

Linux verification passed 44 system-update cases, 18 readiness/handoff cases,
2 release-suite guards, 10 upgrade-input/fixture cases and 2 PCIe-DTB-transform
cases, plus the fingerprint overlay and parallel-password JavaScript mocks.
The rootfs suite-dispatch regression failed before the fix and passed afterward.
Shell syntax, Python compilation and staged/unstaged diff whitespace checks
passed. These are isolated software tests; no GNOME 50 session, new kernel
boot, full-root recovery or Noble-to-Resolute transaction has been tested.

## Verified upstream versions

- Ubuntu 26.04 LTS is Resolute Raccoon, released 2026-04-23, with arm64
  packages. Its release notes specify GNOME 50. [Ubuntu release notes][ubuntu],
  [26.04 changes][changes].
- The Resolute arm64 archive contains `gnome-shell` 50.1 and Mutter 50 with
  `libmutter-18-0`; the current port packages target GNOME 46 and Mutter 14.
  Check the `resolute-updates` pocket at build time rather than assuming its
  package versions are fixed. [Ubuntu GNOME Shell package][shell],
  [Ubuntu Mutter package][mutter].
- The current Resolute archive has `libfprint-2-2` 1:1.95.1+tod1, with a
  separate `libfprint-2-tod1` runtime dependency. The port's Noble EL721
  package targets 1:1.94.7 and cannot be carried across unchanged.
  [Ubuntu libfprint package][libfprint].
- kernel.org lists 7.2.8, released 2026-09-25, as its latest stable kernel as
  of this assessment. 7.3-rc4 is a prerelease. The current physical tablet
  boots the project's `7.2.0-rc3-dirty` kernel, not 7.2.8. [kernel.org][kernel].
- Resolute's systemd 259 removes cgroup v1 support; an installation using
  legacy or hybrid cgroups cannot upgrade. Removable media now mount under
  `/run/media`, which requires an audit of any path assumptions in our helper
  scripts. [Ubuntu system changes][changes].
- On 2026-09-26, Canonical's live `meta-release-lts` index lists Resolute
  26.04.1 with `Supported: 0`. The normal LTS release-upgrader path is not
  enabled for Noble clients at this point. Recheck this live index before
  considering that path for distribution. [Ubuntu LTS upgrade index][meta].

[ubuntu]: https://documentation.ubuntu.com/release-notes/26.04/
[changes]: https://documentation.ubuntu.com/release-notes/26.04/changes-since-previous-interim/
[shell]: https://packages.ubuntu.com/resolute/arm64/gnome-shell
[mutter]: https://packages.ubuntu.com/resolute/arm64/mutter
[libfprint]: https://packages.ubuntu.com/resolute-updates/arm64/libfprint-2-2
[kernel]: https://www.kernel.org/
[meta]: https://changelogs.ubuntu.com/meta-release-lts

## Current installation and upgrade contract

Read-only SSH inspection after matching the previously saved ED25519 host-key
fingerprint identified `Samsung Galaxy Tab S9 Ultra Wi-Fi`, Ubuntu 24.04.5,
`7.2.0-rc3-dirty`, and updater state `complete` at v1.2.0. The cgroup mount is
`cgroup2fs`, the root is read/write with about 287 GiB available, and its
APT sources still point to Noble. Nothing was installed, updated, flashed,
restarted or reconfigured on the tablet.

An isolated arm64 Resolute mmdebstrap root was created in WSL. APT simulation
resolved all 98 packages in the current base/desktop input list with status 0.
An archive-only desktop root containing those 98 requests then built
successfully; `dpkg --audit` was empty, `apt-get check` passed and
`gnome-shell --version` reported 50.1. It does not include the port's local
`.deb` packages or show that GNOME starts on the tablet. The archive selected
`gnome-shell` 50.1-0ubuntu1.2, Mutter 50.1-0ubuntu2.4, GNOME Settings Daemon
50.0-1ubuntu1 and libfprint 1:1.95.1+tod1-0ubuntu2 during this check.

For a separate migration probe, the project's available Noble build rootfs
(24.04.4, device package 2.34) was copied to an isolated directory and its APT
sources switched to Resolute. A plain `dist-upgrade` simulation selected 1291
upgrades, 447 new packages and 17 removals. This is an **older reference
rootfs**, not the v1.2.0 tablet, and the plan is not an approved transaction.
The `apt-get -s dist-upgrade` command itself exited 1 after printing the
plan: it reported broken configuration steps for `sudo-common` and
`coreutils-from-uutils`. Ubuntu's 26.04 LTS notes document the `sudo-rs` and
Rust coreutils transitions behind these package changes. A staged transition
or Ubuntu's release-upgrader ordering must be tested; the plain APT command
is insufficient. The official LTS release-upgrader is currently disabled for
Resolute by the live index above, so it cannot yet supply a verified migration
path. [Ubuntu 26.04 LTS summary][lts-summary].
The removals include the old `ubuntu-gts9u-device`, Mutter 14 and camera SPA,
which need matching replacements in the same plan. Four separate Ubuntu GNOME
extensions (dock, appindicator, desktop icons and tiling assistant) are also
removed because Resolute consolidates them into
[`gnome-shell-ubuntu-extensions`][ubuntu-extensions]. That package must be an
explicit migration requirement so those desktop features survive.

[ubuntu-extensions]: https://packages.ubuntu.com/resolute/gnome-shell-ubuntu-extensions
[lts-summary]: https://documentation.ubuntu.com/release-notes/26.04/summary-for-lts-users/

The v1.2 updater preserves accounts, `/home`, app data and `/etc` by applying
packages to the existing filesystem. It stages matching boot images, backs up
the old images, modules and `/etc`, and writes boot images only after APT. This
contract is appropriate for same-suite releases. It does **not** currently
implement a distribution release upgrade:

1. `update_bundle.inspect()` only accepts `suite=noble` and release discovery
   only selects `ubuntu-24.04-sm-x910-*.zip`.
2. `update_core.device_check()` requires `VERSION_ID="24.04"` on every run,
   including the offline phase. `apt_args()` installs an explicit package list
   with `--no-remove`; it does not migrate APT sources or run a tested release
   upgrade transaction. The existing Noble sources cannot resolve GNOME 50.
3. `build-update-payload.py` previously hardcoded `suite=noble`. This branch
   now rejects mismatched rootfs and APT sources before replacing a staged
   payload. `build-release.sh` rejects non-Noble suite selection and a reused
   non-24.04 rootfs. These are temporary safety gates, not 26.04 support.
4. The ZIP also contains a destructive TWRP installer and `rootfs.img` for
   clean installation. The updater must select `UPDATE/manifest.json` and
   `UPDATE/debs/` exclusively. Never use that installer for an existing system.

## Work required before a 26.04 release

### Kernel and board

The candidate upstream base is **7.2.8** because it is stable and remains in
the same 7.2 line as the physically validated rc3. That is a lower porting
distance, not evidence that the hardware will still work. The kernel source
tag `v7.2.8` resolved to commit
`9a66fdc0d7fd55f54235524a73435af99051e46f` in the official stable tree.
The isolated build lives under `/root/ubuntu-gts9u-2604` in WSL and uses a
separate clone of this port; these are local diagnostic inputs, not shipped
files. The build completed successfully with no rejected patch hunks. Its
configuration selects the board panel, Goodix touch, SM5714 battery,
Qualcomm UFS, DRM/MSM, ath12k and EL721 fingerprint drivers. The generated
`Image.gz` is SHA-256 `c7e1d9799726e4a1fb5d1b9d48c6cca2400b4db539e89ce9e0af6097856b5b53`;
57 modules have `7.2.8-dirty` vermagic and a nonempty build-time signer. This
proves compilation and internal module version consistency, not hardware
compatibility or a matched release image.

The generated DTB is SHA-256
`12998b0a25fc763ab1dc6ea58a91ff488c5808440582cadc5c659ef530d5ab3c`,
177,828 bytes. The published v1.2.0 ZIP's `vendor_boot.img` contains a DTB
with SHA-256
`613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4`,
177,812 bytes (extracted using the Android v4 header offsets in
`validate-bundle.sh`). Decompilation showed **two changed `iommu-map`
properties** on SM8550 PCIe nodes: 7.2.8 added a zero cell to each mapping.
The board DTS was pinned, but its upstream include changed. Samsung ABL has
rejected even inert structural changes in this DTB before Linux can log a
failure. This branch now pins the four PCIe mapping entries to their booted
layout. Rebuilding just the 7.2.8 board DTB after that adjustment produced
SHA-256 `613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4`:
**byte-identical** to the published v1.2.0 DTB. The new kernel's ability to
use that old mapping, especially for PCIe Wi-Fi, still needs a physical test.
The kernel build now fails if its final board DTB differs from this booted
reference; a future DTB change requires an explicit review and device test.
The `Gts9uPresented` bridge also compiled successfully against Resolute's
Mutter 18 headers and libraries. Its ARM64 ELF depends on
`libmutter-clutter-18.so.0` and has the matching runtime search path. The
7.2.8 SPSS IRQ module built and signed with the same key and kernel release.
The kernel source
contains 59 project patch files and 42 driver files, plus DTS, config fragments,
signed modules and Android v4 boot packing. Build 7.2.8 in an isolated Linux
tree; keep the ABL-facing DTB and boot parameters fixed initially. Compare
config, signing certificate, symbol CRCs, module release, DTB and the generated
`boot`, `init_boot`, `vendor_boot`, `dtbo` sizes and hashes. The board-specific
Gunyah imports may overlap future upstream changes; coordinate that patch
stack with the virtualisation agent only through review, without merging or
overwriting their work. The upgrade must carry matched modules, including
ath12k, v4l2loopback and SPSS/secure fingerprint modules.

Required physical regression checks include cold boot, UFS root read/write and
deep resume, 120 Hz panel, touchscreen, S Pen and dock, cover keyboard, GPU,
external display, Wi-Fi/Bluetooth, audio, cameras, fingerprint, sensors,
battery and USB-PD/PPS. Of these, UFS resume, ABL DTB sensitivity and
fingerprint's secure module chain are especially high risk. A successful
cross-compile or module load cannot establish physical compatibility.

### GNOME and custom userspace

The exact Resolute Mutter 50.1 source rejected the existing plane patch's
second hunk. Inspection found that `find_unassigned_plane()` already reuses
the CRTC's assigned plane and avoids taking an active plane from another CRTC;
this appears to supersede the port's GNOME 46 patch. The exact GNOME Settings
Daemon 50.0 source also rejected the ambient patch because automatic
brightness now sends a rate-limited target to GNOME Shell instead of writing
the backlight directly. These are source-level reasons to use the archive
packages initially, subject to regression tests of external displays and
automatic brightness on GNOME 50. Do not reapply the Noble patches blindly.

Rebuild the native
`Gts9uPresented` bridge against Mutter 18 headers and runtime path, then
exercise the fingerprint overlay's private Shell/GDM APIs against GNOME 50.
The bridge now builds against Mutter 18. The exact Ubuntu GNOME Shell 50.1
source package was extracted offline: all imports used by the five project
extensions resolve, and the current keyboard, quick-settings, GDM verifier
and lock-dialog members they rely on are still present. All 11 project
extension JavaScript files parsed, and their metadata now allows Shell 50.
This is a static check, not a live Shell/GDM validation; a compositor session
must still exercise fingerprint, flashlight, dualboot, haptics and S Pen dock.
Also check the extension recovery systemd drop-ins and lock-screen/OSK patches.

Port the pinned Noble libfprint, fprintd/PAM, camera, sensor, NPU and device
packages against Resolute's library ABIs. The device package explicitly
depends on `gir1.2-mutter-14` and a Noble-versioned libfprint, so it cannot
simply be copied into a 26.04 rootfs. Recheck camera PipeWire/GStreamer,
libcamera, sensor daemon and firmware dependency versions. Keep Tab Companion's
UI and hardware behaviour unchanged except for the updater compatibility
changes needed for the release transition and any GNOME 50 extension APIs.
Recheck the cgroup hierarchy during update preflight even though the current
installation was observed using v2; users can alter boot parameters.

The EL721 patch now applies without fuzz to Ubuntu's Resolute libfprint
`1:1.95.1+tod1-0ubuntu2`. Its arm64 build produced both `libfprint-2-2` and
the required `libfprint-2-tod1`; the latter cannot be disabled because the
archive's libfprint references TOD symbols. The existing matched-finger patch
also applies to fprintd `1.94.5-4`; matching custom fprintd and PAM packages
built and passed the eight package compatibility tests. All four packages
installed together in a disposable Resolute arm64 desktop root. APT planned
zero removals, and `dpkg --audit` and `apt-get check` passed afterward. These
tests verify ABI/package consistency, not a real QTEE exchange, enrollment,
matching, GDM authentication or the secure kernel module on hardware.

The archive-only Resolute root has [PipeWire 1.6.2][pipewire],
[libcamera 0.7.0][libcamera] and [iio-sensor-proxy 3.8][iio]. The current
custom camera SPA package declares `pipewire (<< 1.1)` and therefore cannot
enter this root. The Resolute arm64 APT index does not list a separate
`libspa-0.2-libcamera` package; the port still needs its own plugin. PipeWire
1.6.2 has changed the plugin source layout, so the old patch series cannot be
reapplied verbatim. Its video-transform override has been rebased and applies
cleanly, while the other six fixes need upstream comparison. The camera
package also has file and ABI overlap with the archive's `libcamera0.7`.
Do not weaken its version bound merely to satisfy APT.

The pinned libcamera `0.7.2` tree with all seven SM-X910 patches compiled
against Resolute arm64. The exact Ubuntu PipeWire `1.6.2-1ubuntu1.2` source
compiled its libcamera SPA against that staged library with the rebased
video-transform patch. New reproducible package inputs use the real
`libcamera0.7` name to upgrade the archive library and provide the port's
`libcamera-gts9u` dependency. The matching SPA package requires PipeWire
`>= 1.6.2, << 1.7`. In the disposable desktop root, APT planned one reviewed
removal, `gstreamer1.0-libcamera`, because its direct physical-camera provider
duplicates the port's four V4L2 relay cameras. GNOME Snapshot remained
installed through the versioned virtual dependency. The package pair installed;
`dpkg --audit`, `apt-get check` and `ldd` on the SPA all passed. This does not
prove camera enumeration, frame delivery, autofocus or GPU ISP operation on the
tablet. The release-upgrade resolver must explicitly allow this one removal,
never arbitrary removals.

WirePlumber 0.5 no longer reads the port's `main.lua.d` camera rules. The
Resolute device package therefore carries a `wireplumber.conf.d` fragment
with the same four stable camera names, descriptions and `Video/Source` class;
the Noble package keeps its Lua fragment. `pw-config` in the isolated 26.04
root merged all four Resolute rules successfully. Live WirePlumber arbitration
and Snapshot enumeration remain device tests.

The Resolute device package 2.65 was assembled with the 7.2.8 signed SPSS
module, a freshly compiled secure fingerprint owner and the Mutter 18 bridge.
Its dependencies select the matched fingerprint stack, rebuilt camera and
sensor packages, V4L2 relay and Ubuntu's consolidated GNOME extensions.
The relay `0.1.2-gts9u16` compiled against Resolute and both packages installed
in the disposable desktop root without removals. Their maintainer scripts
completed; `dpkg --audit` and `apt-get check` passed. The chroot had no running
kernel or `/proc`, so depmod emitted expected missing-module-metadata warnings;
this does not verify the module load or boot-time service activation.

The five NPU session modules (`gts9u_cdsp`, `gts9u_dsp_stats`, `system_heap`,
`gts9u_fastrpc_prepared` and `gts9u_cdsp_intents_probe`) also compiled and
signed against the same 7.2.8 build. The FastRPC prepared-CDSP patch needed a
7.2.8-specific context rebase; the build script chooses it by kernel release
and requires zero-fuzz application. `modinfo` reports `7.2.8-dirty` and the
build signing key for all five. This is a build-time ABI check, not a live CDSP
or HTP inference test. Stock CDSP firmware staged from the owner's pinned
images verified all 43 file hashes. The assembled runtime's 88 manifest files
were checked without relaxing their pinned digests. Two stale Bionic staging
files were replaced with the matching FastRPC library build artifact and a
fresh diagnostic probe compiled from this repository's source with the pinned
NDK r26d and QAIRT headers; its SHA-256 matched the existing release manifest
exactly. `ubuntu-gts9u-npu_1.2.0_arm64.deb` then built successfully with the
new signed modules. `test-npu-package.py` passed, APT planned zero removals,
and installation in the disposable Resolute desktop root completed with empty
`dpkg --audit` and passing `apt-get check`. CDSP startup and HTP inference
still require a physical test. Do not reuse an old signed module in the update
payload.

The current `libssc 0.4.4-gts9u3`, `hexagonrpcd 0.4.0` and patched
`iio-sensor-proxy 3.9-gts9u3` packages were tested together in the isolated
Resolute desktop root. After refreshing the full APT indices, the resolver
installed their five archive dependencies with zero removals; `dpkg --audit`
and `apt-get check` passed. A Python import probe exposed a missing
`python3-protobuf` dependency and an absolute import emitted by `protoc` for
`ssc_server`. Adding that dependency and making the import package-relative
made `import ssc_server.ssc` succeed under Resolute's Python 3.14. The sensor
build recipe now packages those changes as `libssc ...-gts9u4` and gives the
new proxy package a matching dependency. A clean arm64 rebuild of all three
sensor packages completed on Resolute after setting the udev rules directory
explicitly for systemd 259 and extracting the upstream proxy archive with the
native host `tar` (the arm64 emulation returned ENOSYS). The new libssc
package upgraded in the disposable desktop root and its Python import passed.
The `iio-sensor-proxy ...-gts9u4` package then upgraded in the same root with
no removal; `dpkg --audit` and `apt-get check` passed. The DSP path and
automatic rotation still need a live device test.

[pipewire]: https://packages.ubuntu.com/resolute/arm64/pipewire
[libcamera]: https://packages.ubuntu.com/resolute/arm64/libcamera0.7
[iio]: https://packages.ubuntu.com/resolute/arm64/iio-sensor-proxy

### Non-destructive updater migration

Build a clean Resolute arm64 rootfs and exact matching local Debian packages
first. Test the Noble-to-Resolute APT transition on a **copy** of an installed
rootfs with representative local packages, conffile edits and user data. The
new updater needs an explicit source-suite transition and a complete dependency
plan, including legitimate obsolete-package removals reviewed by name. Reject
unexpected removals, unauthenticated archives and downgrades. Download and
verify the full dependency set before restart; freeze sources and package
versions in the offline plan. Snapshot `/etc`, APT sources, dpkg status and
local package inventory as well as images/modules. Those backups alone cannot
roll back a partially replaced `/usr` or `/var/lib/dpkg`; a tested full
system-root backup/restore path (while preserving user-owned data) or another
equivalent transactional mechanism is required before an unattended crossgrade.
Check free space for both packages and backups. The existing `--no-remove`
path must remain for same-suite
updates; do not relax it globally to force a crossgrade.

After a simulated migration, verify accounts, UID/GID, `/home`, dconf,
fingerprint templates, NetworkManager profiles, SSH keys, boot sets and the
Android saved images are untouched. Verify `dpkg --audit`, `apt-get check`,
GNOME 50 login, updater status and a second same-suite update or repair. Keep
a known-good v1.2.0 boot set and matching module set for TWRP recovery.
Boot images alone are not a valid rollback after userspace has crossed into
Resolute; the matching Noble system root must also be recoverable.

## Distribution gate

After refreshing the Noble fixture for the new release-suite guard, the
existing Linux-hosted updater tests pass: `test-system-update.py` (36 cases),
`test-release-suite-guard.py` (2 cases) and `test-update-launcher.py` (5 cases).
These exercise the current same-suite updater and its refusal of a mismatched
26.04 payload; they do not constitute a Noble-to-Resolute migration test.

Do not publish or present a ZIP as flashable until a clean, pinned 7.2.8 kernel
and modules, Resolute rootfs, rebuilt custom packages, GNOME 50 extensions,
offline migration simulation, complete Android v4 images and the updater ZIP
validator all pass. This branch does not yet meet those conditions. No ZIP was
built or flashed for this assessment.
