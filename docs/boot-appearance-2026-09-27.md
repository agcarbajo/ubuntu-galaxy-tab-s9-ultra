# Visible boot on the SM-X910 (2026-09-27)

The current Ubuntu boot uses a BGRT-based Plymouth theme with Ubuntu artwork. The
`vendor_boot` command line requests `quiet splash`, kernel log level 3 and
hidden systemd status. The device package depends on `plymouth` and
`plymouth-theme-spinner`, and asks Plymouth to repaint once the panel is
physically reachable. GDM has no additional fixed startup delay.

## Measured cold boot

The ANA38407 returns `00 00 00` at about 1.5 and 2.7 seconds. It cannot
display Plymouth at that point. A `pm_test=platform` suspend/resume returns
`80 00 04`; `pm_test=devices` does not. Ftrace observed `mdss_gdsc` off and
back on during the platform cycle. This identifies a relevant transition,
but does not prove that the GDSC alone is sufficient to recover the panel.

The old service added a two-second fixed wait and the default five-second PM
test pause. Removing both was validated on a real cold boot. With device
package 2.72, the service entered platform suspend at 5.06 seconds, the DDIC
returned `80 00 04` at 6.58 seconds, and suspend exited at 6.91 seconds.
The `pm_test_delay` parameter was restored to its original value afterwards.
GDM and the recovery service were active, and the camera showed Plymouth
followed by the login screen without visible boot text in the sampled video.

An experimental board-only call to suspend the MDSS parent during KMS init
did not power the parent off (`suspended=0`), and both first panel reads stayed
`00 00 00`. The userspace recovery still worked. That kernel experiment was
removed and `boot` was restored and read back with SHA-256
`b82b66be360c12512768bf95e17c5c044a3b57900105e924bc19e67856a687b5`.

Package 2.72 was built from the complete current Noble package source,
including its signed TUN module; comparison with the installed 2.70 package
showed the intended panel changes and the ongoing package documentation
update. Its SHA-256 is
`07a0844d8dde2f2f5f63b81e3e7243b8343a9adbaa7e9234983f873adfcb50e1`.
APT simulation selected one upgrade and no removals. `dpkg --audit` and
`dpkg -V ubuntu-gts9u-device` were clean after installation.

## Remaining gap

The camera still shows several seconds of black between the Samsung logo and
the first Plymouth frame. Plymouth cannot render while the panel does not
respond to DCS reads. A seamless product handoff needs a coordinated
DPU/DSI/PHY/power-domain recovery during kernel initialization, or retention
of a working bootloader framebuffer until that recovery completes. The
postmarketOS port already ruled out simple rail/reset retries, a DSI
unbind/rebind, and an MDSS power cycle before child population. The kernel
experiment above ruled out a simple runtime suspend of the MDSS parent after
KMS init. The platform PM cycle remains the validated recovery path.

## Artwork and desktop controls (2026-09-28)

Package 2.76 installs a board-specific Plymouth theme based on BGRT. Its
Ubuntu wordmark is rendered from the official vector logo at 248 × 88 pixels,
matching the original 248 × 87 watermark, and the spinner frames remain
32 × 32 pixels. The default image locations and firmware background remain
unchanged; the artwork has smoother antialiased edges. The theme is selected
through the `default.plymouth` alternative at priority 120.

The compact `init_boot` image flashed for this theme has SHA-256
`2644ee8068aef62a82e1748dbdb17113f2f6d4968f29e56bc97687b17b43ec48`.
It was prepared from the previously validated compact initramfs with the new
theme added, the unused stock spinner/BGRT artwork removed, and the default
theme symlink changed. The full `update-initramfs` output does not fit the
8 MiB `init_boot` partition. This manually prepared image was superseded by
the normal generated Device 2.78 image described below.

The custom quick settings controls disappeared because the desktop account's
`org.gnome.shell disable-user-extensions` key was `true`. Setting it to
`false` reactivated the extensions; the value and enabled extension list
survived reboot. The package did not change this per-user preference.

## Dual-boot persistence and future builds (2026-09-28)

Returning from Android restored the old saved `init_boot` and `vendor_boot`,
including `loglevel=7`. Their active and saved hashes matched; the rootfs
package was already 2.76. Both images were replaced in the active partitions
and `/var/lib/gts9u-boot-sets/ubuntu`, with backups under
`/var/lib/gts9u-boot-backups/pre-visible-boot-sync-2026-09-28`.

Device 2.78 packages the initramfs pruning used by normal builds. It omits the
Pango font/X11 stack from the PNG-only early splash, unused theme assets,
early DHCP, snap desktop udev rules and source/preview graphics. The details
renderer and `e2fsck` remain. A generated initramfs measured 8,273,631 bytes;
its 72 ELF objects had no missing DT_NEEDED dependencies. The visible artwork
remains 248 × 88 and 32 × 32 pixels. `make-initramfs.sh` now checks the real
8,314,880-byte payload limit after the v4 header and AVB reservation, and
runs `check-visible-boot-initramfs.py` before packing an image.

Current image hashes:

- `init_boot`: `41aabac1788012ffc2f4a3945aa963da742e6cd64c90e236cf67f504ce3f7428`
- `vendor_boot`: `a1bdabe2cf5c954f9defae58f4c52bf7cc44a2b8d21017a7310e1ef1260ec7b3`
- Device 2.78 package: `b6b1b2891f533f388b96cb5460a5261b13a838c72f923034f690ca05a11226d3`

The tablet was switched to Android with Tab Companion, then back through the
Android Dualboot app. OBS showed the expected small Ubuntu artwork and GDM.
After that exact round trip, all four active partitions matched the saved
Ubuntu set, the cmdline retained `quiet splash loglevel=3`, Device 2.78 passed
`dpkg -V`/`dpkg --audit`, and the global extension-disable key remained false.
The updater's 36 regression tests and installer boot-set seeding tests passed.
No complete 1.3.0 release ZIP was built or published during this repair.

## 2026-09-30: deterministic ext4 checking in release initramfs

The fresh 1.3.0 build reached initramfs validation, which correctly rejected an
archive without e2fsck. Ubuntu's fsck hook defaults to FSTYPE=auto and probes the
root fstab device even when its type is specified. The label device does not
exist inside the WSL image-building chroot, so it emitted "Couldn't identify
type of root file system" and omitted the checker. The supported SD/UFS root
is always ext4. Device 2.79 therefore packages an initramfs-tools conf.d setting
FSTYPE=ext4, applying both to clean images and subsequent package updates.
The existing real-initramfs checker remains the required regression gate for
e2fsck, dependency closure, theme and the 8,314,880-byte budget. The regenerated
archive passes validation: e2fsck is present, all 72 ELF
dependency closures are complete, and the 8,273,061-byte payload fits the
8,314,880-byte budget. No tablet change was required for this fix.

## 2026-10-02: generated splash regression

After installing the published full 1.3.0 ZIP, the owner reported verbose boot
instead of the animation. Active and saved Ubuntu boot hashes match that ZIP,
and /proc/cmdline retains quiet splash loglevel=3 and hidden systemd status.
The panel recovery succeeds. Inspection of the actual release init_boot found
that scripts/init-premount/plymouth launches the daemon without --graphical-boot
or --ignore-serial-consoles. The retained, physically validated previous
init_boot includes both options. The live rootfs script still has that local
modification (dpkg -V identifies it), but regenerating the image from the clean
rootfs did not inherit it. This omission explains selection of verbose output
with the serial consoles appended by Samsung's bootloader; the boot cmdline and
saved-set synchronization are not missing.

Device 2.84 packages an initramfs hook which preserves the existing launcher
and adds the two options when absent. It accepts an already patched launcher,
is idempotent and rejects a missing launcher rather than building silently.
The real initramfs validator now requires those options as well as artwork,
ELF closure, fsck and the partition budget. Three focused hook tests pass,
including normal/partially patched launchers, duplicate prevention, prerequisite
query and missing-launcher failure. A generated image and physical deployment
remain pending. No partition was changed during diagnosis.

The normal rootfs/package pipeline generated Device 2.84 from committed source
f5794d751dc59bee14264339ce2322a526579df3. Package SHA-256:
4bd94aaa41cb72674de69f0d77b0f7b5343f8848fbe41e30f2ef1c19cbec53c7.
APT simulation selects only Device 2.84, zero removals. The normal initramfs
builder produced an 8,273,117-byte legacy-LZ4 stream, below the 8,314,880-byte
budget. All 72 ELF dependency closures, artwork, fsck and both graphical
launcher options pass. The strengthened validator rejects the previous release
initramfs specifically for its missing --graphical-boot option.

The normal Android bundle builder produced init_boot SHA-256
ce1ddfad3d33b5265d4cd1f5936c10b86b5263a72cae4f0a56358c848f8dc1da.
The other boot, vendor_boot and dtbo images are byte-identical to the published
release. Bundle validation passes. The staged tablet image/package hashes and
both signed board modules match the running release; no kernel replacement is
needed. Root-only active and saved init_boot backups are hash-verified under
/var/lib/gts9u-diagnostics/plymouth-20261002/backup, with other partition and
Android saved-set hashes recorded. Battery is 21% charging; preflight passes.
Deployment and reboot require the owner's explicit authorization, requested
before any active partition write or package installation. Physical animation
acceptance and any replacement full release artifact remain pending. The public
1.3.0 ZIP is unchanged at this checkpoint.

The owner explicitly authorized Device 2.84 installation, replacement of only
init_boot and its Ubuntu saved copy, and one reboot. Live APT installed one
upgrade with zero removals; audit/check pass. Verified both signed board modules
are byte-identical before and after package installation. Wrote only init_boot,
read its full hash back, refreshed the Ubuntu saved copy and matching filesystem
/boot initrd through atomic writes. Preserved the prior filesystem initrd in the
root-only backup as well. All other partition hashes and Android saved-set hashes
remain unchanged. Returned on boot f80f652c-c39d-44c1-a755-2570e8ce009d with Device
2.84, writable root, active GDM/NetworkManager and successful panel recovery.
The active/saved init_boot hash is the validated ce1ddfad candidate above.
Owner-visible animation confirmation has been requested; the published full ZIP
has not yet been replaced with this later fix.
