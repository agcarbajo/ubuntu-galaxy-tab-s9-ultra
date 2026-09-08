# Consume the fingerprint contact through finger-up

The owner reported that touching the optical reader subsequently clicks the
content underneath it. The Goodix FOD code has a matching contact-lifetime
bug: `fod_enable_store(false)` clears `fod_suppressed_slots`, and the touch
filter exits immediately when FOD is disabled. If authentication finishes
while the finger is still down, subsequent coordinate MOVE/RELEASE packets
can therefore enter the ordinary input stream. An overlay which disappears
on authentication completion cannot reliably own this physical contact.

`retain-goodix-fod-contact-until-release.patch` fixes that lifetime:

- Disabling FOD preserves the already suppressed contact slots.
- MOVE packets for those contacts remain suppressed, even outside the reader.
- Their physical coordinate RELEASE is consumed and clears only that slot.
- Other fingers and subsequent ordinary taps continue normally.
- A fresh PRESS clears a stale slot if firmware omitted its earlier RELEASE.
- Closing FOD still resets its public state to idle; a later suppressed
  RELEASE does not publish an event to a closed FOD session.

Suspend clears retained slots with input IRQs disabled, even when the reader
has already been turned off. The patch does not add a global
touch grab, modify GNOME input picking, or alter fingerprint authentication.
The build script applies it to both clean and existing patched kernel trees.

## Validation and deployment status, 2026-09-08

Run `python3 scripts/test-goodix-fod-contact.py`. It extracts the production
functions from the existing FOD patch, applies the follow-up patch with zero
fuzz, and compiles the original and corrected C functions using `-Wall
-Werror`. The original reproduces the held-contact loss; the corrected code
passes tests of disable-while-held, movement outside the region, other fingers,
physical release, subsequent taps, missing-release slot reuse, FOD notification
semantics, repeated disable, hardware mode-write failure, and suspend with
the reader enabled or disabled. This is a
userspace driver-logic harness, not a full kernel build or a physical test.

**Not installed on the tablet yet.** The running build #7 has
`CONFIG_TOUCHSCREEN_GOODIX_BERLIN_CORE=y`, so this fix requires a new kernel
boot image. Its matching Galaxy/Gunyah runtime9 source/object tree and signing
material were not found on the tablet; they were subsequently located on
PC-ARTURO (see below). Do not rebuild from an unrelated baseline or replace the working
module/signature set just to apply this change.

Continue using an isolated copy of the validated build tree. Preserve its
config, signing certificate, Gunyah/fingerprint ABI and early Galaxy OPP
overlay. Validate and back up the candidate before changing boot, notify the
owner before rebooting, and physically test fingerprint authentication over a
clickable control: hold through success, move, release, then make a new tap.
Only the new tap should reach the underlying UI. Test another simultaneous
finger and ordinary touches outside the active reader too. Refresh the saved
Ubuntu boot image only after the new boot has passed validation.

## Existing-tree build audit on PC-ARTURO

The owner authorized an incremental build in place to avoid duplicating the
source/object trees. Administrative access uses the owner's Windows/WSL
integration; no password was collected and no sudo policy was changed.

- Source: `/root/ubuntu-gts9u/build/linux-src-performance-20260908`.
- Objects: `/root/ubuntu-gts9u/build/linux-performance-20260908`.
- Source HEAD: `5e34b887d2f39ed2c38673d4682b4d30b9112228`, a private snapshot
  of Gunyah runtime9, not a verified public upstream revision.
- Config SHA-256: `474a26a731694fb6838f463e21a057ff3e272fe27fc42b3d6b9d3b628070fcb3`,
  also verified against the tablet's `/proc/config.gz`. The file under `/boot`
  is stale and must not be used as the reference configuration.
- Public signing certificate SHA-256:
  `1735f50edfe85be64a1f76994451526249b153bc8f2e0f4835e68bd320c2f6fd`.
- Compiler: Ubuntu Clang/LLD 22.1.8 from `/usr/lib/llvm-22/bin`.
  The default `/usr/bin/clang` is version 14 and must not be used.

The three existing tracked modifications are the two Galaxy cpufreq fixes
and the Makefile integration of `gts9u-performance.o`, not new unfinished
Gunyah edits. The performance helper and generated overlay header are
untracked inputs and are preserved too, together with the pre-existing
`arch_topology.c.orig` file. No source cleanup or git reset was performed.

A reduced, root-private backup lives on the PC at
`/root/ubuntu-gts9u/build/pre-fod-contact.Pd4lPH`. It contains the original
affected sources, existing binary diff/status/HEAD, config, Image, vmlinux,
System.map, Module.symvers, version metadata and signing material. Private
keys stay on the PC and must never be committed or transferred to the tablet.
The backup also records hashes of Gunyah driver files and compilation logs.

After applying commit `5f4b85ac64c1eae585d29d4683e0e61b029c93bd`'s FOD patch
with zero fuzz, the incremental command is:

```sh
PATH=/usr/lib/llvm-22/bin:$PATH make \
  -C /root/ubuntu-gts9u/build/linux-src-performance-20260908 \
  O=/root/ubuntu-gts9u/build/linux-performance-20260908 \
  ARCH=arm64 LLVM=1 LOCALVERSION=-dirty KBUILD_BUILD_VERSION=8 -j4 Image
```

`LOCALVERSION=-dirty` is essential: the first compile without this explicit
argument generated `7.2.0-rc3+`, which is unsuitable for the installed module
directory. That intermediate Image was not deployed. This procedure records
how to repeat the incremental fix against the existing snapshot; it is not
yet a claim of a complete clean-room build from this public repository.

The corrected build completed as `#8 SMP PREEMPT Tue Sep 8 12:13:08 CEST 2026`
with release `7.2.0-rc3-dirty`. Image SHA-256:
`92ec07de1a34bb60f61d7ea05022a5ce4802de83908fe8305d261a50339e0a0d`.
Post-build comparisons verified that config, signing key and certificate,
Module.symvers, and the recorded Gunyah driver files did not change. The
original and fixed driver-logic tests were also rerun successfully locally.
This is build/logic validation, not physical fingerprint or VM validation.

## Candidate boot image prepared, not installed

After returning to the same LAN, Tailscale connected directly to PC-ARTURO
and the interrupted transfer completed. The full Image hash matched the
build host. No private signing material was transferred.

`scripts/prepare-fod-kernel8-boot.py` prepares the candidate from the audited
boot #7 image and kernel #8 Image. It pins both input hashes and the build
host's AOSP avbtool 1.2.0 hash, rejects existing output paths, preserves the
original boot-v4 header except for kernel size, and preserves the exact
appended DTB. The baseline has no boot ramdisk or boot signature. Its existing
unsigned AVB SHA-256 footer is regenerated using the same salt, partition
name/size, flags and rollback index; this does not add or remove AVB signing.

```sh
python3 scripts/prepare-fod-kernel8-boot.py \
  --baseline /home/agcar/performance-lab/runtime-boost-limit-boot.img \
  --image /home/agcar/performance-lab/fod-contact-kernel8.Image \
  --output /home/agcar/performance-lab/fod-contact-kernel8-boot.img \
  --avbtool /home/agcar/performance-lab/fod-avbtool.py
```

Candidate SHA-256:
`a48a7d1b81e27641683fc930b5f9c712990e3748121b09b1cc82bd33e5d9ac8f`.
Size: 100663296 bytes. AVB footer/hash verification, decompressed Image
identity, appended DTB identity, header preservation, and driver logic tests
passed. The tablet still runs #7: no partitions or saved boot sets have been
written. Physical fingerprint validation requires an owner-approved reboot.

## Owner-authorized trial deployment

The owner subsequently authorized installation and reboot. The narrow
`scripts/install-fod-kernel8.sh` installer verified the active boot hash
against #7, copied and verified it at
`/var/lib/gts9u-kernel-backups/pre-fod-kernel8-20260908/boot.img`, staged a
root-owned candidate, and wrote only the `boot` partition. Readback matched
the candidate hash above. `vendor_boot`, `init_boot`, modules and saved boot
sets were not changed. Physical validation is still pending.

`gts9u-fod-kernel8-rollback.service` is enabled for the next boot, not started
in the existing session. After ten minutes it restores #7 and reboots unless
validation has stopped/disabled it. It checks both the backup hash and active
candidate hash before restoring; it refuses to overwrite an unrelated boot.
This userspace safeguard cannot recover a failure before systemd starts.

After confirming the new kernel and basic device health, stop its countdown:

```sh
sudo systemctl disable --now gts9u-fod-kernel8-rollback.service
```

Then physically test the reader contact lifetime before refreshing the saved
Ubuntu boot set or calling the touch fix validated.

## Post-reboot acceptance, 2026-09-08

The owner reported that the tablet booted and the touch fix appears to work.
Checks confirmed kernel #8, the expected active boot hash and unchanged live
config hash. GDM, NetworkManager, Tailscale, fprintd, secure fingerprint
transport/UI, camera relays and the CPU boost service were active. No failed
system units were listed. `/dev/esfp0` and `/dev/gunyah` exist; the CPU prime
maximum remains 3360000 kHz and GPU maximum 719000000 Hz.

The rollback service was stopped and disabled after those checks. The saved
Ubuntu boot image was then synchronized to #8 using the validated helper,
with the previous saved image retained at
`/var/lib/gts9u-kernel-backups/pre-saved-ubuntu-boot-sync-6DwAm00u/saved-ubuntu-boot.img`.
The independent pre-install #7 backup remains available as documented above.
No vendor_boot, init_boot or module installation was performed.

This records successful boot, basic health checks and the owner's initial
fingerprint result, not an exhaustive regression pass. Multitouch and
suspend/resume have logic-harness coverage but were not physically retested
in this session; no VM workload or camera capture was run. The boot journal
contains platform/desktop errors; the previous boot journal is unavailable,
so this check does not establish that each message predates the change.
