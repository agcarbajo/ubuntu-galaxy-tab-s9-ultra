# Ubuntu 26.04 / GNOME 50 upgrade assessment

Status: **blocked for distribution**, 2026-09-26. No 26.04 ZIP is approved for
Tab Companion or TWRP. This assessment uses the `upgrade/ubuntu-26.04-gnome50`
branch; the virtualisation worktree and branch are independent.

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

[ubuntu]: https://documentation.ubuntu.com/release-notes/26.04/
[changes]: https://documentation.ubuntu.com/release-notes/26.04/changes-since-previous-interim/
[shell]: https://packages.ubuntu.com/resolute/arm64/gnome-shell
[mutter]: https://packages.ubuntu.com/resolute/arm64/mutter
[libfprint]: https://packages.ubuntu.com/resolute-updates/arm64/libfprint-2-2
[kernel]: https://www.kernel.org/

## Current installation and upgrade contract

Read-only SSH inspection after matching the previously saved ED25519 host-key
fingerprint identified `Samsung Galaxy Tab S9 Ultra Wi-Fi`, Ubuntu 24.04.5,
`7.2.0-rc3-dirty`, and updater state `complete` at v1.2.0. The cgroup mount is
`cgroup2fs`, the root is read/write with about 287 GiB available, and its
APT sources still point to Noble. Nothing was installed, updated, flashed,
restarted or reconfigured on the tablet.

An isolated arm64 Resolute mmdebstrap root was created in WSL. APT simulation
resolved all 98 packages in the current base/desktop input list with status 0;
this establishes archive availability only. It does not include the port's
local `.deb` packages or show that GNOME starts. The archive selected
`gnome-shell` 50.1-0ubuntu1.2, Mutter 50.1-0ubuntu2.4, GNOME Settings Daemon
50.0-1ubuntu1 and libfprint 1:1.95.1+tod1-0ubuntu2 during this check.

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
The five project Shell extensions (fingerprint overlay, flashlight, dualboot,
haptics and S Pen dock) currently list Shell 46 or at most 48 in their
metadata; validate each with GNOME 50 before extending that list. Also check
the extension recovery systemd drop-ins and lock-screen/OSK patches.

Port the pinned Noble libfprint, fprintd/PAM, camera, sensor, NPU and device
packages against Resolute's library ABIs. The device package explicitly
depends on `gir1.2-mutter-14` and a Noble-versioned libfprint, so it cannot
simply be copied into a 26.04 rootfs. Recheck camera PipeWire/GStreamer,
libcamera, sensor daemon and firmware dependency versions. Keep Tab Companion's
UI and hardware behaviour unchanged except for the updater compatibility
changes needed for the release transition and any GNOME 50 extension APIs.
Recheck the cgroup hierarchy during update preflight even though the current
installation was observed using v2; users can alter boot parameters.

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

Do not publish or present a ZIP as flashable until a clean, pinned 7.2.8 kernel
and modules, Resolute rootfs, rebuilt custom packages, GNOME 50 extensions,
offline migration simulation, complete Android v4 images and the updater ZIP
validator all pass. This branch does not yet meet those conditions. No ZIP was
built or flashed for this assessment.
