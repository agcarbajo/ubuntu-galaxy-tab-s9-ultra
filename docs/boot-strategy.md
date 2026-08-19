# Boot chain, installation and recovery

Last revised: 2026-08-19. It inherits the chain physically proven by
postmarketOS v1.71; only the root filesystem and its initramfs differ.

Since v0.18 the root filesystem is installed on the **internal UFS** and a
release is a single flashable ZIP. Since v1.0.0 it can share that UFS with
Android — see [Two ways to install](#two-ways-to-install).

## The proven chain

- The SM-X910 has no A/B slots, and Samsung offers Download Mode and Odin, not
  a usable `fastboot boot`.
- The Android chain uses **boot header v4**.
- Samsung's ABL loads the kernel from `boot`, the generic initramfs from
  `init_boot`, and the DTB, cmdline and bootconfig from `vendor_boot`, all from
  the internal UFS.
- The Linux root is an **ext4 filesystem inside a partition** on that same UFS.
  ABL reads no filesystems: the kernel comes out of `boot`, and only the
  initramfs looks for the root, by label.
- The stock DTBO carries downstream interfaces and does not apply on top of a
  mainline DTB. The bundle writes a `dtbo` that deliberately is **not** an
  Android DT table, which makes ABL fall back to the DTB appended to the kernel.
- TWRP carries its own recovery DTB/DTBO and stays recoverable however the
  mainline images change.

Two invariants that cannot be touched:

- `APPEND_DTB_TO_KERNEL=1` and `DISABLE_RUNTIME_DTBO=1`. With the opposite
  values ABL returns to its `ufdt` fork, rejects the base DTB and drops into
  Odin before ever reaching Linux.
- **Changing the DTS means rewriting `vendor_boot`.** The X910's ABL applies the
  DTB from `vendor_boot`, not the one appended to `boot.img`. Rewriting only
  `boot` leaves the old DTS in use.

## Requirements

Three things have to be in place first, all flashed with Odin from Download
mode, into the `AP` slot:

1. **An unlocked bootloader.** Once it is, `ro.boot.verifiedbootstate` reads
   `orange`.
2. **TWRP.**
3. **A `vbmeta` with AVB verification disabled** — the one published alongside
   TWRP.

The third is the one that catches people out, because it is invisible until it
bites. Flashing stock firmware puts back a `vbmeta` with verification enabled,
and `vbmeta` lives on a read-only LUN — `sde15`, not the `sda` everything else
here is on — that only the bootloader can write. The installer therefore cannot
patch it from TWRP. It checks the flags instead and stops with:

```
ERROR: vbmeta is read-only and does not have AVB flags 2
```

That is the installer refusing to write a kernel the tablet would then decline
to boot. Flash the disabled `vbmeta` and run it again. Changing `vbmeta` makes
Android erase its own data on the next boot.

After flashing TWRP, reboot **straight into recovery**. Letting Android boot
once puts the stock recovery back over it.

## Partitions used

| Partition | Exact size | Contents |
|---|---:|---|
| `boot` | 100663296 | `Image.gz` with appended DTB, header v4, no ramdisk |
| `init_boot` | 8388608 | Ubuntu initramfs, legacy LZ4 |
| `vendor_boot` | 100663296 | X910 DTB, cmdline, bootconfig, and a vendor fragment with the early Bluetooth firmware |
| `dtbo` | 16777216 | a non-table image, which forces the appended-DTB fallback |
| `vbmeta` | 131072 | AVB with verification and verity disabled (`flags=2`) |
| `userdata` (34) | up to 1007985586176 | Android's data, or Ubuntu's root when the disk is not split |
| `linuxroot` (35) | the remainder | Ubuntu's ext4 root, labelled `UBTS9U_UFS`, when the disk is split |

The installation never touches `super`, the bootloader, the PIT, EFS, persist,
modem/modemst or the calibration partitions.

## Two ways to install

Both use the same ZIP. The difference is whether the UFS is split first, and
the installer's rule is one line: **`linuxroot` if it exists, otherwise
`userdata`**.

### Ubuntu on the whole tablet

Nothing is repartitioned. The ext4 image is written with `dd` into a partition
that already exists, and the filesystem grows to fill it on the first boot.

- **The GPT stays Samsung's, byte for byte.** Neither the build nor the
  installer runs `sgdisk`, `parted`, `sfdisk`, `mkfs` or `wipefs` against the
  device; `scripts/validate-bundle.sh` fails if any of those appears in the
  packaged installer.
- **`super` is untouched**, so Android's system image is still there.
- **Android's user data is lost**: it is exactly what occupies the partition
  being reused.

### Ubuntu beside Android

`gts9u-split.zip` shortens `userdata` and creates `linuxroot` next to it, then
recreates Android's data so it can make fresh encryption keys on its next boot.
Afterwards the installer finds `linuxroot`, installs there, and leaves
Android's `userdata` alone.

The split ships set to halve the disk. The share is one file inside the ZIP,
`ANDROID-PERCENT`, holding the percentage `userdata` keeps. Changing the split
means changing that number — open the ZIP in any archive manager and edit it:

```bash
printf '30\n' > ANDROID-PERCENT && zip gts9u-split.zip ANDROID-PERCENT
```

Nothing else needs touching: `SHA256SUMS` inside the ZIP covers the installer
script alone, so editing the number invalidates nothing. Anything from 5 to 95
is accepted, and the tablet checks the same bounds before it writes the table.

Flashed on a tablet that is already split it exits saying so and changes
nothing, so there is no harm in running it twice.

### Where the ZIP has to sit

When Ubuntu is going onto `userdata`, that partition *is* the internal storage:
reading the ZIP from there would destroy it half way through the write, so the
installer aborts if the ZIP's path is under `/data`, `/sdcard` or equivalent.
In order of convenience:

1. **`adb sideload`.** The ZIP is served from the PC and takes no room on the
   tablet. This is the proven route.
2. **USB-OTG**, if a stick is at hand.
3. **microSD**, with a warning: TWRP mounts the card's **first** partition at
   `/external_sd`, and on a card left over from the microSD releases that first
   partition is `UBTS9U_BOOT`, 256 MiB. A ~1 GiB ZIP does not fit there. Use a
   plain data card.

When Ubuntu goes onto `linuxroot`, the ZIPs may sit on internal storage,
because the partition being written is not the one they are on.

### Labels

| Label | Where | What it is |
|---|---|---|
| `UBTS9U_UFS` | `linuxroot`, or `userdata` | the installed root, since v0.18 |
| `UBTS9U_ROOT` | microSD | the root of releases up to v0.17 |

They differ on purpose. `root=LABEL=` resolves to the first match, and with the
same label in both places an old card forgotten in the slot would boot instead
of the new installation.

## The single installation step

Flash the ZIP from TWRP. It writes the root filesystem, verifies it by reading
it back and hashing it, and only then writes `boot`, `init_boot`, `vendor_boot`
and `dtbo`. That order is deliberate: if the long part fails, the device keeps
the boot images it already had and is still one retry from where it was.

Firmware for the GPU, ADSP, Wi-Fi and audio lives **inside** the root
filesystem image, not in an overlay applied afterwards.

The build tools **never** write to a partition. The owner flashes the ZIP.

### Update ZIPs

A ZIP with no `rootfs.img` but with an overlay updates an existing installation
in place: it mounts the root after checking it with `e2fsck -p`, replaces
firmware, modules and configuration, and leaves the data alone. This is how a
new kernel is tested without reinstalling. The two contents are mutually
exclusive and `make-twrp-zip.py` refuses to build a ZIP with both.

### Seeding the dual-boot sets

While the ZIP runs is the only moment both systems' boot images exist at once:
Android's are still on the partitions, and Ubuntu's are in the ZIP. So that is
where the sets the switchers read get saved, into
`/var/lib/gts9u-boot-sets/{android,ubuntu}` on the new root.

A set is the four boot images, 216 MiB, so both together need 432 MiB inside a
filesystem that has not grown yet. The installer refuses below 480 MiB rather
than seed half of them — Android's set is the one that cannot be rebuilt
afterwards. The image is therefore built with enough slack to clear that bar;
see `scripts/build-ufs-image.sh`.

This runs only when installing into `linuxroot`. On a whole-tablet install
there is no second system to switch to.

Because the set is copied off the live partitions, **install Android first and
Ubuntu second**, and root Android before that step if it is meant to be rooted:
switching systems from the Android side goes through `su`.

## Iterating on a running system

With Ubuntu up, kernel or DTS changes can be tested by writing only the image
strictly needed, always with explicit authorisation:

- `boot` for the kernel;
- `vendor_boot` for DTS, cmdline or bootconfig;
- both when the kernel and the ath12k modules form a newly signed set.

Before every write: a temporary backup, a size check, `dd conv=fsync` and a
SHA-256 comparison between source and destination. `sdaN` numbers are never
hardcoded; the stable links under `/dev/disk/by-partlabel/` are used instead.

Kernel lockdown requires that `boot` and the modules installed on the root —
ath12k and v4l2loopback — come from the **same** build. Recreating the `O=`
tree generates a new signing key and the old modules start being rejected with
"Operation not permitted": always ship the modules alongside their kernel.

## Boot quirks Ubuntu has to keep

- The ANA38407 panel is not reachable after Samsung's cold hand-off. Before the
  display manager starts, a single platform suspend/resume (`pm_test=platform`)
  is needed to recover the DDIC, the DPU and the graphics session. In Ubuntu
  this is ordered `Before=gdm3.service`.
- If a DisplayPort dock is already connected, its HPD must stay **deferred**
  until that recovery finishes. An early HPD also blocked the internal DSI in
  the baseline tests.
- An early visible console is not a requirement: ABL may add `console=null`.
  The persistent journal and TWRP are the reliable sources of diagnosis.
- Critical kernel providers are **built-in**. This port neither installs nor
  auto-loads a general module tree; it ships only the two ath12k modules,
  signed in isolation. A critical symbol left at `=m` usually makes the
  subsystem fail to appear at all.

## Exact installation procedure

The steps the owner performs. No tool in the project does them for them.

### Before starting

1. Check that the hashes in `MANIFEST-v<version>.txt` match the downloaded
   files.
2. Have the way back at hand.
3. Accept that **whatever Android keeps in the partition being written is
   lost**. `super`, the bootloader, EFS and the calibrations are untouched.
4. For a whole-tablet install, keep the ZIP off internal storage — see the
   media list above.

### Flashing

1. Boot TWRP. For sideload: `Advanced` → `ADB Sideload`, then `adb sideload
   <zip>` from the PC. From external media: `Install` → pick the ZIP.
2. Wait. Writing the root filesystem takes several minutes, shows no progress,
   and deliberately runs before the boot images.
3. Read the output. The installer aborts if the device is not an SM-X910, if a
   partition size does not match, if `vbmeta` lacks AVB flags 2, if the target
   is smaller than the image, if the ZIP sits on the destination, if the target
   is still mounted, or if what it reads back does not match the image's
   SHA-256.
4. The ZIP **does not reboot**. Reboot by hand when it finishes.
5. On the first boot the filesystem grows to fill its partition. Only the
   filesystem is resized: the partition was already that size.

### If something goes wrong

The installer does not format, does not repartition and does not reboot, so a
failure half way leaves the device in TWRP, still reachable. From there:

- retry the flash, or
- enter Download Mode and restore the official firmware with Odin.

A failure while writing the root filesystem leaves that partition half done but
the boot images intact: there is no state in which the device has a new kernel
and no system to boot.

## Recovery

In order:

1. **TWRP and `adb`**, to mount the root, pull the journal and restore images.
2. **Download Mode and Odin** with official firmware. On a tablet that was
   never split this is one step, because the GPT was never modified. On a split
   one, Odin's Re-Partition with the PIT from the firmware's CSC restores the
   factory table and returns `userdata` to the whole disk.

Backups are restored through `/dev/block/by-name/<partition>`, never with
hardcoded LUN numbers. EFS is only ever mounted `ro,noload`, when the Bluetooth
address has to be read; it is never written.
