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
[kernel]: https://www.kernel.org/

## Current installation and upgrade contract

Read-only SSH inspection after matching the previously saved ED25519 host-key
fingerprint identified `Samsung Galaxy Tab S9 Ultra Wi-Fi`, Ubuntu 24.04.5,
`7.2.0-rc3-dirty`, and updater state `complete` at v1.2.0. Nothing was
installed, updated, flashed, restarted or reconfigured on the tablet.

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

Rebuild the patched Mutter package from the exact pinned Resolute source;
re-evaluate whether its plane/CTL patch is still needed on Mutter 50. Rebase
the patched GNOME Settings Daemon ambient-brightness source package from 46
to 50, with a package version above the archive version. Rebuild the native
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
Check the tablet's actual cgroup hierarchy before attempting any userspace
transition; no read-only cgroup check has yet been recorded for this session.

### Non-destructive updater migration

Build a clean Resolute arm64 rootfs and exact matching local Debian packages
first. Test the Noble-to-Resolute APT transition on a **copy** of an installed
rootfs with representative local packages, conffile edits and user data. The
new updater needs an explicit source-suite transition and a complete dependency
plan, including legitimate obsolete-package removals reviewed by name. Reject
unexpected removals, unauthenticated archives and downgrades. Download and
verify the full dependency set before restart; freeze sources and package
versions in the offline plan. Snapshot `/etc`, APT sources, dpkg status and
local package inventory as well as images/modules; define recovery for an
interrupted or failing userspace migration. Check free space for both packages
and backups. The existing `--no-remove` path must remain for same-suite
updates; do not relax it globally to force a crossgrade.

After a simulated migration, verify accounts, UID/GID, `/home`, dconf,
fingerprint templates, NetworkManager profiles, SSH keys, boot sets and the
Android saved images are untouched. Verify `dpkg --audit`, `apt-get check`,
GNOME 50 login, updater status and a second same-suite update or repair. Keep
a known-good v1.2.0 boot set and matching module set for TWRP recovery.

## Distribution gate

Do not publish or present a ZIP as flashable until a clean, pinned 7.2.8 kernel
and modules, Resolute rootfs, rebuilt custom packages, GNOME 50 extensions,
offline migration simulation, complete Android v4 images and the updater ZIP
validator all pass. This branch does not yet meet those conditions. No ZIP was
built or flashed for this assessment.
