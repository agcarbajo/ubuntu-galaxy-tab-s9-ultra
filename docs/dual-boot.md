# Dual boot

Android and Ubuntu on the same internal UFS, switched from either side without
a PC, a bootloader menu or a second boot slot.

## What is actually shared

The two systems do not overlap anywhere except in the boot chain:

| Partition | Holds | Swapped? |
|---|---|---|
| `super` | Android's system, vendor, product | never |
| `userdata` (34) | Android's user data | never |
| `linuxroot` (35) | Ubuntu's root filesystem | never |
| `boot`, `init_boot`, `vendor_boot`, `dtbo` | the kernel, its ramdisks and the device tree | on every switch |
| `vbmeta` | verified-boot descriptors | never |

Switching means writing four images and restarting. Nothing is moved, resized
or reformatted, so a switch costs a few seconds and cannot lose data.

## Why `vbmeta` is never touched

Ubuntu needs a `vbmeta` with AVB flags 2, which disables verification. One UI
runs perfectly well with that same unsigned `vbmeta`, so it never has to change
— and it must not: Android derives the key for its metadata-encrypted
`userdata` from the verified-boot state, so rewriting `vbmeta` wipes Android's
user data every single time.

This was found the hard way. Changing `vbmeta` left One UI unable to mount
`/data`, at which point Android itself wrote `PARAM_BOOT_RECOVERY_ENTER` into
the `param` partition and the tablet booted to recovery on every cold start,
which looked exactly like a bootloader problem and was not. See
[porting-log.md](porting-log.md), sessions 94 and 95.

## Why One UI and LineageOS cannot coexist

They share `super`, and `super` is not swapped. Whichever Android is installed
occupies the Android half; the pairing that works is Ubuntu against that one.
Both apps discover the systems from the filesystem rather than assuming One UI,
so replacing Android with LineageOS needs no code change — only the boot images
in the set directory.

## Where the boot images live

Each system keeps its own copy, because neither can read the other's storage:
Android's `/sdcard` is metadata-encrypted, and Ubuntu's `linuxroot` is ext4
that Android has no driver for at that layer.

- Android: `/sdcard/BootSets/<id>/{boot,init_boot,vendor_boot,dtbo}.img`
- Ubuntu: `/var/lib/gts9u-boot-sets/<id>/` (same four names)

A directory name is an id; an optional `name.txt` beside the images is the
label shown in the UI.

## Names are read, never assumed

The label comes from whichever system is running, which is the only one that
can answer honestly:

- Android writes its own name from `ro.build.version.oneui` (`80000` is 8.0) or
  from LineageOS's own properties.
- Ubuntu writes `PRETTY_NAME` from `/etc/os-release`.
- Android additionally mounts `linuxroot` read-only and asks it, because it
  can; Ubuntu cannot return the favour.

The built-in fallbacks are deliberately version-free — "Android", "Ubuntu" —
because a hardcoded "One UI 8" is wrong on a tablet running One UI 7, and being
vague beats being confidently wrong.

## Switching

Both sides do the same thing: verify each image by size, write it, read the
partition back and compare hashes, and stop without restarting if anything
disagrees. A tablet with three of four partitions replaced still runs the
system it is on — but only until it is restarted, which is why a failure never
reboots and says so.

**From Android** — the `Dualboot` app, or its quick settings tile.

Writing and restarting are separate. *Switch on next restart* writes the four
partitions and stops; the tablet keeps running what it is running and boots the
other system whenever it next restarts. *Restart* does both. Once a switch is
staged, the first button greys out — repeating it would rewrite four identical
partitions — and *Undo* on the running system's row is the way back.

That staged state survives closing the app, because it is not kept in memory:
the partition hashes say what will boot, and a note in preferences says what
was running when the switch was staged. The note is only believed when the
partitions agree with it, so a restart, a switch made from Ubuntu, or a stale
note all resolve back to reality.

**From Ubuntu** — Tab Companion's Dualboot page, or its quick settings toggle.
The privileged half runs through polkit, split across two executables so that
reading the status is silent and writing asks for a password.

## If a switch goes wrong

Nothing here can leave the tablet without a working recovery: TWRP lives in its
own partition and is never written. From TWRP, `scripts/swap-boot-set.sh`
restores a set over ADB, and the installation ZIP reinstalls Ubuntu's boot
images without touching any filesystem.
