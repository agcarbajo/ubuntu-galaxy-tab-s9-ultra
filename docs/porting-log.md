# Ubuntu 24.04 porting log

One session per iteration, failures included. The current state is in
[`hardware-status.md`](hardware-status.md) and the durable conclusions in
[`development-notes.md`](development-notes.md).

---

## Session 1 — handover from postmarketOS v1.71 and the rollback build

Date: 2026-07-31. The physical tablet was not touched.

### Context

The handover of the `gts9uwifi` postmarketOS port is received at commit
`b1dcca0`, with the v1.71 baseline frozen and physically validated. The new
project's goal is to keep that hardware parity with an Ubuntu 24.04 LTS
userspace. The previous port's complete documentation was read before writing
any code: the README, `hardware-status.md`, `boot-strategy.md`,
`development-notes.md`, `panel-ana38407-bringup.md` and the relevant sessions
of its `porting-log.md`, plus the sources of the three device packages,
`configs/` and `scripts/`.

### The rollback build: the v1.71 TWRP ZIP

Before creating anything new, postmarketOS's last build was regenerated, so
that a way back would exist before Ubuntu touched the microSD.

The ZIP was rebuilt with `REUSE_BUILD_OUTPUTS=1` over v1.71's cached kernel
outputs (`out/kernel-gts9uwifi-v171`, kernel package r114). The result does
**not** match the release's recorded hash, and the cause was identified
precisely:

| Image | Result |
|---|---|
| `boot.img` | `cb13c0fa…` — **identical** to v1.71 |
| `init_boot.img` | `6fab6d38…` — **identical** to v1.71 |
| `dtbo.img` | `c17418be…` — **identical** to v1.71 |
| `vbmeta.img` | `b95e5ef9…` — **identical** to v1.71 |
| `vendor_boot.img` | `55d9d94a…` against the recorded `c4b93f02…` |

The regenerated `vendor_boot.img` was decomposed to narrow the difference down:

- packaged DTB: `952688174c…`, **identical** to the v1.71 build's DTB;
- `vendor_cmdline`: byte for byte identical to
  `configs/vendor_boot/cmdline.txt`;
- bootconfig: identical to `configs/vendor_boot/bootconfig.txt`;
- vendor fragment: contains exactly `usr/lib/firmware/qca/hmtbtfw20.tlv`
  (`b91f0af7…`) and `usr/lib/firmware/qca/hmtnv20.b21` (`864476ed…`), both
  identical to the repository's copies.

The only real difference is the CPIO headers' `mtime`s: `cpio --reproducible`
normalises device and inode but **not** the modification time, and the overlay
is copied with `install`, which stamps the build's time. It is a pre-existing
reproducibility gap in the pmOS pipeline, not a divergence of content. It is
recorded in `development-notes.md` and the Ubuntu pipeline will set `mtime=0`
across the overlay before packaging.

### The rollback build: the microSD image

The first attempt at regenerating the root filesystem image revealed a mismatch
that would have produced a misleading artefact: the WSL build base's
`pmaports` was at **kernel r103**, while the repository's frozen baseline is
**r114** (device r44, firmware r10). The resulting image was discarded and the
process repeated after running `scripts/sync-pmaports.sh`.

The second attempt failed in `apk add`:

```
breaks: device-samsung-gts9uwifi-1-r44[hexagonrpcd=0.4.0-r4]
```

The cause was not in the sources: the repository freezes `hexagonrpcd` at r4
and device package r44 pins it exactly. What was in the way was a
**locally built** `hexagonrpcd 0.4.0-r5` from a later experiment, still present
in `pmbootstrap-work/packages/edge`, which apk preferred for being newer. It
was quarantined, the local repository reindexed, and the build completed.

The resulting root filesystem installs exactly the baseline's set: kernel r114,
device r44, firmware r10, `hexagonrpcd` r4, `iio-sensor-proxy` r3 and Mutter
r6.

Two reusable conclusions:

1. the WSL build base is not a source of truth; the repository is, and
   `sync-pmaports.sh` has to be run before any deliverable build;
2. a locally built package can beat the pinned version even when the sources
   are correct. Faced with a `breaks:` of this kind, look at the local package
   repository before the APKBUILDs.

### Rollback artefacts delivered

They live in `PostmarketOS/artifacts/`, outside Git, with
`MANIFEST-v1.71-rollback.txt`:

| Artefact | SHA-256 |
|---|---|
| `postmarketos-edge-gnome-mainline-v1.71-dp-dock-coldboot-sm-x910-twrp.zip` | `3270afa0…` |
| `postmarketos-v1.71-rollback-sd-gts9uwifi.img.xz` | `05ccca69…` |

The uncompressed image is 5,941,231,616 bytes and its SHA-256 is `fb346a78…`.
The root filesystem image is a fresh build on current Alpine edge, not a
byte-for-byte clone of the userspace validated at the time; what is preserved
byte for byte is the boot part, which is where the hardware support lives.

### The Ubuntu repository

`Ubuntu-24.04/` was created alongside `PostmarketOS/`, with a local Git, no
public remote, and with `artifacts/`, `work/`, images, firmware and build
products ignored. The starting documentation was written: a short README, a
hardware matrix with explicit evidence levels, the inherited boot chain, the
root filesystem's architecture and this log.

### State at the close of the session

- A way back to postmarketOS v1.71 available outside Git, with a hash
  manifest.
- The Ubuntu repository initialised and documented.
- Kernel, DTS, five drivers, 17 patches, the configuration fragment, cmdline,
  bootconfig and the no-op DTBO imported with provenance and a source hash.
- The pipeline's dependencies installed in the WSL build base and checked with
  `scripts/check-build-deps.sh`.
- `scripts/build-ubuntu-rootfs.sh` written: `mmdebstrap` arm64 with `minimal`
  and `desktop` profiles, configuration applied within the invocation itself
  and no manual step afterwards.
- No partition, card or physical installation modified.

### Next step

Run the first `minimal` root filesystem, adapt the kernel build and the Android
v4 packaging to this repository, and generate the first microSD image and its
TWRP ZIP with a hash manifest.

---
## Session 2 — our own kernel, the image pipeline and the first release

Date: 2026-07-31. The physical tablet was not touched.

### The validated kernel is not the Alpine package's kernel

While porting the kernel build, a discrepancy appeared that would have produced
a kernel different from the validated one had the patch list been copied from
the wrong place:

| | direct build | APKBUILD |
|---|---|---|
| `ignore-console-null.patch` | **no** | yes |
| `set-mi2s-codec-dai-format.patch` | **yes** | no |

The `boot.img` that was flashed and validated comes from the direct build. That
is, the kernel that boots has the CS35L45 format/sysclk fix — which is why
audio works — and does **not** have the console patch. This port reproduces the
direct build's set and leaves `ignore-console-null` behind
`APPLY_IGNORE_CONSOLE_NULL=1`, as an explicit diagnostic build.

### Verification against the baseline

Built from this repository, with the checkout pinned at `a13c140c`:

| Output | Result |
|---|---|
| `sm8550-samsung-gts9uwifi.dtb` | `952688174c…` — **identical** to v1.71 |
| `config` | `2c1eaeee…` — **identical** to v1.71 |
| `Image.gz` | different |

The DTB and the config are exactly the validated ones, which is what fixes the
hardware description and the feature set. `Image.gz` does not match, and the
cause was measured rather than assumed: same uncompressed size (65,903,104
bytes), same release, same compiler and same banner, but 7,003,750 bytes
different. The trigger is `UTS_VERSION`: the baseline carried `#18` and ours
`#1`, and that one extra character shifts the linking. On top of that, each
build tree generates its own module signing key.

### Build identity: a privacy problem, not only a reproducibility one

The kernel's banner embedded `root@PC-ARTURO`, the owner's machine name, and
that literal would have travelled inside every published `boot.img`. The build
now fixes `KBUILD_BUILD_USER=ubuntu`, `KBUILD_BUILD_HOST=gts9uwifi` and a
`SOURCE_DATE_EPOCH` derived from the kernel commit's date, and resets
`.version` on every run. Verified on the resulting image: the banner is
`ubuntu@gts9uwifi` and no personal identifier remains.

### The image pipeline

The seven steps described in `ubuntu-userspace.md` were written. Three
decisions are worth recording:

- `build-sd-image.sh` **fails the build** if the initramfs is not legacy LZ4 or
  does not fit in `init_boot` minus its AVB footer. Both are failures the
  previous port discovered on the tablet; here they are discovered on the host.
- The TWRP installer locates the root filesystem **by label**, not by
  `mmcblk1p2`, and requires `ID=ubuntu`. It enables systemd units with real
  symlinks from a packaged manifest, because systemd ignores a regular file
  inside a `.wants` directory.
- The vendor fragment is normalised to `mtime=0` before packaging, closing the
  reproducibility gap found in session 1.

### Line endings

The scripts with no extension — the TWRP installer and those in `packaging/` —
fell outside any per-extension `.gitattributes` rule and would have been
written with CRLF in the Windows checkout, which stops `#!/sbin/sh` executing.
The repository now forces `eol=lf` for everything.

### The first release: v0.1-minimal

The complete pipeline produced its first installable artefact. Five defects
came to light while running it, all fixed in the scripts and none patched by
hand onto the artefact.

**1. Wi-Fi firmware mapped wrongly.** The overlay asked for `amss.bin` and
`board-2.bin`, names that do not exist. The real files are `official-amss.bin`
and, for the board data, `official-board-2.bin` as a container plus
`qrd-board.bin` as `board.bin`. The official container has no entry for the
X910, so ath12k deliberately falls back to the QRD ELF — and `board.bin` was
missing entirely. The overlay now validates every blob up front.

**2. `MODULES=dep` looks at the wrong host.** It makes `initramfs-tools`
inspect the root device of the machine doing the compiling, which here is WSL,
and it fails with "failed to determine device for /". `MODULES=most` is the
right choice and is still tiny: the only modules installed are the two ath12k
ones. `/boot/config-<release>` was also missing, without which
`initramfs-tools` cannot verify LZ4 support — precisely the only acceptable
compressor here.

**3. The initramfs did not fit.** 9.4 MiB against a budget of 8.0 MiB.
`build-sd-image.sh`'s guard stopped it on the host, which is its whole purpose.
It was measured before cutting anything: **zero modules** in the initramfs, and
12 MiB of the 29.6 MiB uncompressed were `udev/hwdb.bin`, a device property
database that is never read while looking for the root. The compressor was not
negotiable, so content was cut: 25,212 KiB → 13,204 KiB in staging and
**7,123,964 bytes compressed, with 1.2 MB to spare**. Discovered along the way:
`initramfs-tools` **silently skips** a hook that is not executable.

**4. The loop device's partition nodes do not appear on their own.** There is
no udev in this environment, so `losetup --partscan` does not guarantee
`/dev/loopNpM`. The script nudges the kernel, waits, and falls back to
`kpartx`.

**5. The validator was lying.** Without `unzip` installed, every ZIP check
failed except the negative one — "the installer never mentions forbidden
partitions" — which **passed** because `grep` found nothing in empty input. It
is the same silent-lie pattern that already cost a false dependency check. Now
a missing tool aborts the validation. The other two checks were also badly
framed: they identified the installer by its prose and grepped over the
comments that document precisely the partitions it promises not to touch. They
were replaced with an explicit contract line and with an analysis of the code
with comments stripped, plus a new check that it only writes with `dd` and
contains no formatting command.

The result, with all 21 static checks green:

| Artefact | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.1-minimal-sd.img.xz` | `c68f2bb9…` |
| `ubuntu-24.04-gts9uwifi-v0.1-minimal-sm-x910-twrp.zip` | `f534a5a5…` |
| `boot.img` | `4b99e90e…` |
| `init_boot.img` | `cbeb5716…` |
| `vendor_boot.img` | `678a5ebb…` |
| `dtbo.img` | `c17418be…` |
| `vbmeta.img` | `b95e5ef9…` |

`dtbo.img` and `vbmeta.img` match postmarketOS v1.71's byte for byte, as they
should: their content does not depend on the distribution.

microSD image: 2,367,684,608 bytes uncompressed (`f399d509…`), 110 MB
compressed, with a 256 MiB `UBTS9U_BOOT` and a 2 GiB `UBTS9U_ROOT`.

**Known gap:** `init_boot.img` changes hash between runs because
`update-initramfs` does not produce a reproducible CPIO. The rest of the bundle
is reproducible. Normalising it is still pending, as was done with the vendor
fragment.

### v0.1 desktop, and the failure that would have ruined the first test

The `desktop` profile builds 948 packages in 1.8 GiB. Checked inside the root
filesystem, not assumed: GDM3 46.2, GNOME Shell 46.0, Mutter 46.2, PipeWire
1.0.5, WirePlumber, Mesa 25.2.8 with `mesa-vulkan-drivers`, BlueZ 5.72,
NetworkManager, OpenSSH and the device package. The apt pin worked: **no**
`linux-image-*` from the distribution slipped in. `ssh`, `NetworkManager` and
`ubuntu-gts9u-grow-rootfs` are enabled; `/etc/fstab` mounts by label and the
`ubuntu` user is in `sudo`.

Before proposing a physical test, a failure appeared that would have made it
fail for a reason unrelated to the hardware: **the inherited cmdline has no
`root=`**. postmarketOS's initramfs locates its partition itself, so its
cmdline never needed one. `initramfs-tools` does not do that: it would have
waited for a device that never arrives and dropped to the emergency shell.

Ubuntu's cmdline adds `root=LABEL=UBTS9U_ROOT rootfstype=ext4` — by label,
because the enumeration order between microSD and UFS is not guaranteed — and
removes two parameters carried over that make no sense here: `pmos.nosplash`
and `ignore_console_null`, whose patch this build does not apply. The validator
now fails if `root=` is missing or if either of those two reappears.

The artefacts built with the old cmdline were deleted rather than kept: they do
not boot and their names do not distinguish them.

Release v0.1 (desktop), with every static check green:

| Artefact | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.1-sd.img.xz` | `5af2a7d2…` |
| `ubuntu-24.04-gts9uwifi-v0.1-sm-x910-twrp.zip` | `3a55399e…` |
| `boot.img` | `4b99e90e…` |
| `init_boot.img` | `a8252f1e…` |
| `vendor_boot.img` | `59a2e5c8…` |
| `dtbo.img` | `c17418be…` |
| `vbmeta.img` | `b95e5ef9…` |

Uncompressed image: 3,588,227,072 bytes, `27a4f469…`.

`boot.img` is identical to the minimal profile's, as it should be: same kernel
and same DTS. `dtbo.img` and `vbmeta.img` match postmarketOS v1.71's byte for
byte.

### v0.2: the panel recovery and writing the microSD through TWRP

The ANA38407's cold-boot recovery was ported before proposing the first
physical test, so that there is some chance of an image on the first attempt.
The mechanism does not change from the reference port because it is a property
of the hardware: the DDIC is unreachable after Samsung's hand-off and only the
`pm_test=platform` cycle recovers it. It was verified that `CONFIG_PM_DEBUG=y`
is in the built kernel, so `/sys/power/pm_test` will exist.

One deliberate difference: the unit is enabled in `multi-user.target`, not
`graphical.target`. That port always reached a display manager; here this cycle
is also what makes the text console visible, so if GDM fails it is worth having
the panel alive to see why.

Checked in the built root filesystem, not assumed: package `ubuntu-gts9u-device`
0.2 installed, script executable, unit present and the **enabling symlink** in
`/etc/systemd/system/multi-user.target.wants/`.

The owner noted that this PC has no card reader, but that the tablet can be
left in TWRP with the microSD in place. `scripts/twrp-write-sd.sh` writes the
card over ADB: by default it only inspects, and writing requires `--write` plus
an explicit `--device` after five guards — a whole mmc device, `removable=1`,
type `SD`, sufficient capacity and nothing mounted — as well as confirming the
device is an SM-X910 **in recovery**. When it finishes it reads the card back
and compares SHA-256 against the image.

Release v0.2 (desktop), every static check green:

| Artefact | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.2-sd.img.xz` | `aebe0193…` |
| `ubuntu-24.04-gts9uwifi-v0.2-sm-x910-twrp.zip` | `8a1c37bf…` |
| `boot.img` | `4b99e90e…` |
| `init_boot.img` | `fa787e86…` |
| `vendor_boot.img` | `59a2e5c8…` |
| `dtbo.img` | `c17418be…` |
| `vbmeta.img` | `b95e5ef9…` |

Uncompressed image: 3,588,227,072 bytes, `6e14f383…`. The v0.1 artefacts were
withdrawn so there is no ambiguity about which one to flash.

### Next step

The first physical test. The goal is milestone 2: systemd through to
`multi-user.target`, a persistent journal, Wi-Fi and SSH. The image and the
panel are not yet validated under Ubuntu and will not be declared working until
they are observed.

---
## Session 3 — the first physical boot: milestones 2 and 3 met

Date: 2026-07-31. Ubuntu's first run on the tablet.

### Writing the microSD without a card reader

The owner's PC has no reader, but the tablet can be left in TWRP with the card
in place. `scripts/twrp-write-sd.sh` writes it over ADB. Four defects appeared
only against real hardware, and deserve writing down:

1. **CRLF.** Windows's `adb.exe` ends every line with CRLF, so the
   end-of-line-anchored device detection never matched and the script reported
   there was no device while one was connected.
2. **32-bit overflow.** The sizes were computed on the tablet, whose busybox
   does 32-bit arithmetic: `sectors*512` wrapped around and a 29.7 GiB card
   showed as 1.72 GiB.
3. **`removable=0`.** This board's SD host marks the card as non-removable. My
   guard required `removable=1` and would have rejected the only valid
   destination. The decisive signal is `device/type == SD`, plus checking that
   the internal UFS exists separately as `sda`.
4. **`dd` reading from a pipe lost 42,688 bytes.** The card was deceptively
   convincing — correct GPT, correct partition names, an identical first MiB —
   but everything after the point of loss had landed 42,688 bytes early. It was
   located by searching for a signature from the image inside the card. Only
   the read-back verification caught it.

The easy hypotheses were ruled out with tests: `adb exec-in` and `exec-out`
turned out to be **binary-safe** (4 MiB with 16,507 LF bytes arrived
identical), so the transport was clean. The write now stages the image as a
file on the tablet's RAM disk, verifies that copy against the source hash, and
only then runs `dd` from a regular file.

### The TWRP installer, twice

The ZIP aborted with "could not find `UBTS9U_ROOT`" on a card that had it. Two
independent causes:

- this TWRP **has neither `blkid` nor `findfs`**, nor `/dev/disk/by-label`. It
  does have `tune2fs`, which reads the ext4 volume name directly;
- the kernel was still holding the previous partition table, so the `pN` nodes
  pointed at postmarketOS's offsets and any filesystem over them looked
  corrupt.

Fixing that introduced a third failure, subtler: the installer re-read the
table and searched **immediately afterwards**. Re-reading deletes and recreates
the partition nodes, so the search fell into that window and found nothing,
while the error message printed moments later listed the partition it had just
failed to find. Identical code, opposite results, only the timing changed. It
now searches first and re-reads only if it has to.

Since then, the rebuild script **extracts the real functions from the packaged
ZIP and runs them on the tablet** before asking for a flash.

### The first boot

It worked. Confirmed by the owner: display, GPU, touch, buttons, battery,
suspend with the cover, USB host and USB-C video output, with and without
external power.

**The panel recovery was validated under Ubuntu**, with the reference port's
exact signature in the journal:

```
ana38407 panel id: 00 00 00
  -> pm_test=platform cycle ->
ana38407 panel id: 80 00 04
```

Not working: sound, Bluetooth and auto-rotation.

### A single root cause for sound and sensors

The ADSP was `offline`. `qcom_q6v5_pas` has `auto_boot=true` and asks for
`qcom/sm8550/adsp.mdt` at around 3 s, when the microSD containing it is not
mounted yet: it fails with `-ENOENT` and stays off forever.

Starting it after `local-fs.target` works, PAS accepts Samsung's signed image,
and two things appear at once: the ALSA card and `/dev/fastrpc-adsp`, which is
the sensors' prerequisite.

Ubuntu already packages pd-mapper as **`protection-domain-mapper`**, so nothing
had to be compiled; it only had to be ordered after the DSP's late start, or it
finds no remoteproc and systemd gives up.

With the reference port's UCM profile, **PipeWire exposes "Built-in speakers
(4x CS35L45)" and the digital microphones natively, with no PulseAudio**. That
answers one of the userspace design's open questions. The owner confirmed
audible audio after a reboot, with no intervention.

### Bluetooth: my service hung the boot

The WCN7850's NVM address is null, so `hci0` comes up as
`00:00:00:00:5A:AD` and stays `DOWN`. Reading it from EFS (`ro,noload`) and
applying it with `btmgmt` brings it up — verified live, the controller went to
`UP RUNNING`.

But as a boot service it failed, and the failure was mine: **BlueZ 5.72's
`btmgmt` blocks indefinitely if it runs before the controller is registered
with the management interface**, which is exactly when this service runs. It
was measured: `btmgmt info` sat there for over four minutes and, with the
service ordered before `bluetooth.service`, it took the whole stack down with
it. The same command answers in under a second once the controller is
registered. `hciconfig`, by contrast, is an ioctl and answers in 3 ms.

The service now bounds every call with `timeout` and polls with `hciconfig`.
But retrying it revealed a different and deeper problem.

### Bluetooth: the firmware is not downloaded after a warm reboot

```
QCA Product ID   :0x00000019
QCA SOC Version  :0x40170200
QCA ROM Version  :0x00000200
QCA Patch Version:0x000043fb
QCA controller version 0x02000200
QCA Downloading qca/hmtbtfw20.tlv
command 0xfc00 tx timeout
QCA Failed to send TLV segment (-110)
```

The controller **answers every version query correctly** and only gets stuck on
the firmware's bulk download. That is: the UART works, the file is found, and
the TLV still does not go through. The driver retries three times and gives up.

What distinguishes the boots observed:

| Boot | Type | Result |
|---|---|---|
| 1st | cold, after flashing from TWRP | firmware loaded, `hci0` reached `5A:AD` and came up |
| 2nd–4th | warm `systemctl reboot` | `tx timeout` at 3.6 s, three retries, gives up |

Software recovery is ruled out with evidence: `rfkill` block/unblock changes
nothing, and an unbind/rebind of the serdev leaves the controller worse still —
after it, even the version read fails.

Current hypothesis, pending confirmation with a complete power-off: the
Bluetooth side of the shared WCN7850 needs a real power cycle, which a warm
reboot does not provide. Nothing is declared until it is measured.

### State at the close of the session

These come up on their own from a cold boot, verified without touching
anything: the panel recovery, the ADSP, pd-mapper and audio. Bluetooth is
intermittent and auto-rotation untouched, because it needs `hexagonrpcd` and
`libssc`, which do not exist in Ubuntu.

---

## Session 4 — Bluetooth closed, rotation packaged, and a desktop kernel

Date: 2026-08-01.

### Bluetooth: two `btmgmt` behaviours, neither documented

The service worked by hand and failed as a service. It was two chained BlueZ
5.72 traps, both measured:

1. **Ordered before `bluetoothd`, `btmgmt` blocks in `epoll_wait`** for
   minutes. Since the unit was `Before=bluetooth.service` — copying the
   reference port — it took the whole stack down: 90 s of timeout per boot.
   With the daemon already up, the same call takes 0 s. This port orders the
   service **after**, the opposite of the reference.
2. **With stdin on `/dev/null`, `btmgmt` prints nothing and exits 0.** That is
   what systemd gives a service by default. It does not fail: it lies. The
   `grep` over its empty output never matched and the wait loop timed out. With
   an empty pipe it behaves normally.

A third detail: the service reported failure when it had worked. Applying the
address reinitialises the controller, so re-reading it a second later showed
the old one. It now polls.

Result verified from a cold boot: `48:BC:…`, `UP RUNNING`, `Powered: yes`,
service completed in 1.3 s. A 10 s scan: 20 devices. A2DP still untested.

The power-cycle hypothesis was also **refuted**: a complete power-off changes
nothing. The `command 0xfc00 tx timeout` on the first firmware download attempt
is intermittent and the driver itself recovers on the retry. That was not the
problem.

### `apt install firefox`, `chromium` and `fastfetch`

Three symptoms, two causes.

The big one is systemic: **this port installs no module tree**, so anything
left at `=m` is absent. `CONFIG_SQUASHFS=m` means no snap can be mounted, and
in Ubuntu `chromium` and `firefox` are transitional packages whose only job is
to install a snap. The same explained `systemd-binfmt.service` and
`proc-sys-fs-binfmt_misc.mount` failing on every boot and leaving the system
`degraded`: `CONFIG_BINFMT_MISC=m`.

A configuration fragment of our own was added, separate from the inherited one
so that it stays comparable with its origin: `SQUASHFS` and its five
decompressors, `OVERLAY_FS`, `FUSE_FS`, `BINFMT_MISC`, exFAT, NTFS3, and
AppArmor with `apparmor` in `CONFIG_LSM` while **keeping `lockdown`**, on which
the kernel/signed-module pairing depends.

The build's guard rejected three errors before compiling:
`SQUASHFS_DECOMP_MULTI_PERCPU` lives inside a `choice` and is not set directly;
`NTFS3_FS` can only be a module while the old NTFS driver is enabled; and the
fragment list was a space-separated string in a repository whose path
**contains spaces**.

`fastfetch` is different: it simply **does not exist in Ubuntu 24.04's
archive**. That is not a configuration failure.

### Rotation: three packages Ubuntu does not have

The sensors live inside the ADSP and are reached over FastRPC, so Ubuntu's
`iio-sensor-proxy` has nothing to read. `libssc` 0.4.4, `hexagonrpcd` 0.4.0 and
`iio-sensor-proxy` 3.9 are compiled with `-Dssc-support`.

Two things Ubuntu imposed that Alpine's dependency list did not anticipate:
`libssc` requires meson ≥ 1.4 and noble ships 1.3.2, and `qmi-glib`'s
`pkg-config` drags in `mbim-glib` and `protoc`.

A design error corrected in time: the first version compiled **inside the root
filesystem that gets shipped**, which would have put `build-essential`, meson
and the development headers on the tablet. It now uses a disposable arm64
chroot.

And a gap that only appeared on inspecting the `.deb`: **upstream hexagonrpc
ships no systemd unit** — Alpine adds them with a distribution patch — so the
port's drop-in pointed at a service that did not exist. The unit is written
here, with `Conflicts=suspend.target` and the `fastrpc` user its own udev rule
needs.

### A false negative of my own

Checking whether `snapd` was in the root filesystem, I used a variable in an
inline command. This environment eats them, so I was inspecting the **build
host, not the root filesystem**, and wrongly concluded it was there. The check
from a script file confirmed the opposite. `snapd` and AppArmor's userspace are
now declared explicitly rather than left to `Recommends`.

### Release v0.6

Verified on the built root filesystem, not assumed: the four local packages
installed, **`iio-sensor-proxy` linking against `libssc.so.2`** according to
`ldd`, the `fastrpc` user created, the six units with their enabling symlinks,
and `snapd`, `squashfs-tools` and AppArmor 4.0.1 present.

| Artefact | SHA-256 |
|---|---|
| `ubuntu-24.04-gts9uwifi-v0.6-sd.img.xz` | `f3c8a6c5…` |
| `ubuntu-24.04-gts9uwifi-v0.6-sm-x910-twrp.zip` | `d061a856…` |
| `boot.img` | `744aab41…` |
| `init_boot.img` | `a27a5370…` |
| `vendor_boot.img` | `59a2e5c8…` |

Uncompressed image: 3,721,396,224 bytes, `3f92ddda…`.

**This ZIP has to be flashed**: the kernel changed, and `boot` and the ath12k
modules form a signed set under lockdown.

### Still to be checked on hardware

That the chain compiles and installs does not prove rotation works. What
remains is seeing whether Ubuntu's Mutter 46 suffers the two rotation-lock
races the reference port fixed with a patch of its own; it was deliberately
left out, to be ported only with evidence.

---

## Session 5 — the sensor chain, link by link

Date: 2026-08-01. `apt install chromium` and `firefox` were confirmed by the
owner: the `CONFIG_SQUASHFS=y` fix was the cause.

Rotation was walked through by measuring every link — ADSP →
`/dev/fastrpc-adsp` → `hexagonrpcd` → SSC → `libssc` → `iio-sensor-proxy` →
Mutter — instead of guessing where it failed. Four distinct problems appeared.

### 1. A runtime dependency is missing

`ssccli` and `iio-sensor-proxy` died with `error while loading shared
libraries: libqmi-glib.so.5`. The `libssc` package did not declare
`libqmi-glib5`. Added, every symbol resolves.

### 2. The HexagonFS tree ended up one level too deep

The tarball nests everything under `sensor-hexagonfs/` and the reference port
extracts it with `--strip-components=1`. This port omitted it, and
`hexagonrpcd` reported `Could not open /../sns_reg_version: No such file`.

It also matters because Samsung's patch remaps `/sensors/registry/` to
`/sensors/`, so the tree must have `dsp`, `sensors` and `socinfo` at its root.

### 3. `apps_std_fwrite`'s declared arity does not match this firmware

On making the tree writable, this appeared:

```
Invalid number of input numbers: 8 (expected 12)
```

The listener requires `4 * (in_nums + in_bufs + out_bufs)`. The patch declares
`fwrite` as `(2, 1, 2, 0)` → 12 bytes; the firmware sends 8, which are two
words: `in_nums=1` plus the size word contributed by the single input buffer.
That also matches the handler, which reads
`struct { uint32_t fd; uint32_t buf_size; }`, because with `in_bufs=1` the word
after `fd` **is** that buffer's size.

Corrected to `(1, 1, 2, 0)` in `packaging/sensors/fix-fwrite-arity.patch`.
Verified on hardware: both the arity error and the permission ones disappear,
and `sns_reg_version` **is written** — its date moves from 1970 to the current
time while keeping its 10 bytes. The write path works.

### 4. An open front: the DSP asks for an interface that does not exist

With all of the above corrected, the daemon lives **104 ms** and exits with
status 0. The complete exchange is:

```
Starting hexagonrpcd (INIT_ATTACH_SNS) on /dev/fastrpc-adsp
Could not find local interface sns_registry
Unsupported handle: 4294967295
```

The sensor firmware asks the AP for a local interface called `sns_registry`.
`hexagonrpcd` offers only three — `apps_mem`, `apps_std` and `remotectl` — and
the word `sns_registry` appears nowhere in its code, not even with Samsung's
patch. Failing to find it, the DSP invokes on the error handle `0xFFFFFFFF` and
closes the session.

Facts established, so the work is not repeated:

- **It is not a permissions problem.** Run as root the `Permission denied`
  messages disappear and the final behaviour is identical.
- **It is not fatal in itself.** Both `Unsupported handle` and `Could not find
  local interface` return an error to the DSP and the listener carries on; what
  ends the session is the DSP closing it.
- **The ADSP and audio survive.** The attempt causes no SSR: the ALSA card is
  still present afterwards.
- The correct tree makes the DSP get **further**, not less far: with the badly
  extracted tree the daemon lived indefinitely because it never reached this
  point.

### A warning

During diagnosis the daemon was run as root and truncated `sns_reg_version` to
0 bytes on opening it for writing. It was caught and the tree restored from the
build overlay's clean copy, verifying that it recovers its 10 bytes. Do not run
that daemon as root over a tree that matters.

### State

Rotation: still not working. Three real defects fixed and the fourth precisely
characterised. Everything else on the device is unchanged.

## Auto-rotation: solved

The full FastRPC trace closed the case. A diagnostic `hexagonrpcd` was built
with the meson option `hexagonrpcd_verbose`, which logs every call the sensor
firmware makes against the filesystem. The binary is not installed: it is for
debugging only.

### What was seen

With the HexagonFS tree correctly extracted, writable by the `fastrpc` user and
with `fwrite`'s arity corrected, the trace went from 3 lines to **757**:

```
openat($ADSP_LIBRARY_PATH, /vendor/etc/sensors/sns_reg_config) -> 2
read(2, 512) -> 329
...
openat(..., /mnt/vendor/persist/sensors/registry/registry/../sns_reg_version) -> 3
write(3, 10) -> 10
opendir(/mnt/vendor/persist/sensors/registry/registry) -> 3
readdir(3) -> lsm6dso_0_platform.ff.config
readdir(3) -> lsm6dso_0.gyro
...
```

The `write(3, 10) -> 10` is direct proof that the arity patch works: the DSP
finally manages to update the registry's version, and from there walks the
whole sensor configuration directory. The `sns_registry` request that closed
the session does not appear again: it was a consequence of the DSP never
completing the registry load, not an interface that needed implementing.

`ssccli --sensor accelerometer` then returns real measurements:

```
Accelerometer sensor measurement: X=0.440279 Y=-0.062213 Z=9.757931 m/s²
```

9.76 m/s² on Z with the tablet flat: that is gravity.

### The fourth obstacle: a udev tag upstream does not set

With the accelerometer being read, `iio-sensor-proxy` still said `No
accelerometer` while recognising the compass and the ambient light sensor. The
cause is in the rule `iio-sensor-proxy` itself ships:

```
SUBSYSTEM=="misc", KERNEL=="fastrpc-adsp*", ENV{IIO_SENSOR_PROXY_TYPE}+="ssc-light ssc-compass"
```

All four SSC drivers (`ssc-accel`, `ssc-light`, `ssc-compass`,
`ssc-proximity`) are compiled, but each only looks at devices carrying its own
tag. `ssc-accel` appears in no rule, so `drv-ssc-accel` never receives a device
to examine. It is a problem neither of the X910 nor of Ubuntu: it happens to
any device whose accelerometer lives behind the DSP.

The fix goes in `61-gts9u-sensor-mount-matrix.rules`, next to the mount matrix
that already touched that same node. `IIO_SENSOR_PROXY_TYPE` is a
space-separated list built with `+=`, so the order relative to upstream's `80-`
rule does not matter.

After applying it:

```
IIO_SENSOR_PROXY_TYPE=ssc-accel ssc-light ssc-compass
Found SSC accelerometer at /sys/devices/virtual/misc/fastrpc-adsp
=== Has accelerometer (orientation: undefined, tilt: undefined)
{'HasAccelerometer': <true>, ...}
```

The orientation comes out `undefined` with the tablet flat, which is the
correct answer: with gravity on Z there is no screen orientation to deduce.

### Verification from a cold boot

With the tablet rebooted and no manual intervention:

| | |
|---|---|
| `pd-mapper` | active |
| `hexagonrpcd-adsp-sensorspd` | active, 1 process alive |
| `iio-sensor-proxy` | active |
| udev tag | `ssc-accel ssc-light ssc-compass` |
| accelerometer | 9.76 m/s² on Z |
| ALSA card | present |

The daemon no longer dies at 104 ms: it stays up serving the tree.

### The four obstacles, in order

1. **HexagonFS tree extracted one level too deep** — `--strip-components=1` was
   missing. The DSP found nothing.
2. **A read-only tree for the daemon** — the firmware needs to write the
   registry's cache; without that it gives up.
3. **`apps_std_fwrite`'s arity declared wrongly** — `(2,1,2,0)` requires 12
   input bytes and this firmware sends 8. Corrected to `(1,1,2,0)`.
4. **A non-existent `ssc-accel` udev tag** — `iio-sensor-proxy` never
   considered the FastRPC node an accelerometer.

None was specific to Ubuntu; all four are real defects of the generic path, and
all four fixes live in the repository.

### A side effect worth knowing

Restarting the ADSP through `remoteproc` with the system running leaves the
system **with no sound card**: the audio services do not re-register
themselves. A system reboot recovers it. During diagnosis the ADSP was
restarted several times; it was checked after the reboot that the
`Samsung-Galaxy-Tab-S9-Ultra` card is present again.

## Auto-rotation: the root cause, and why the reference port did not suffer it

The `rename` and listener-buffer patches are correct and necessary for the DSP
to *be able* to rebuild the registry. But the better question was a different
one: why does it rebuild it at all, when postmarketOS uses the same
`hexagonrpcd` 0.4.0 with a single patch and rotation works there.

The answer was written in the reference port's own tree generator,
`stage-stock-sensor-hexagonfs.sh`:

> Samsung's registry service uses this zero-length file as the completion
> marker and the companion JSON as a per-input timestamp cache. Omitting either
> makes the DSP rebuild the registry through a temp.json + rename sequence.

Two files govern everything:

- `sensors/registry/sensors_registry`, of zero length, marks the registry as
  complete;
- `sensors/registry/sns_reg_config` is a cache holding, for each JSON in
  `sensors/config`, the date it had when the registry was generated.

The tree is built with **every date normalised to the epoch**, so the cache
stores `"data": "0"`. The DSP compares that value against each JSON's `stat()`:
if they disagree, it rebuilds.

Our overlay was correct — both files present, dates at zero — but the TWRP
installer writes each file with `unzip -p > destination`, which preserves no
dates at all. On the tablet the JSONs ended up with the recovery's clock,
July 2025, while the cache said zero. Hence the rebuild on every boot, and with
it the `sns_registry` request that closed the session.

### The fix

`ubuntu-gts9u-sensor-registry.service`, a `oneshot` ordered before
`hexagonrpcd`, normalises the tree's dates to the epoch and returns ownership
to the `fastrpc` user. It is done on the Ubuntu side rather than in the
installer on purpose: here there is GNU `coreutils` and `touch -d @0` behaves
the same every time, while TWRP's `busybox` varies; and it also repairs a tree
left half-rebuilt by an earlier attempt.

### Verification from a cold boot

| | |
|---|---|
| `hexagonrpcd-adsp-sensorspd` | active, 1 process |
| accelerometer | X=8.55 Y=0.00 Z=4.84 m/s², magnitude 9.82 with the tablet tilted |
| `AccelerometerOrientation` | `normal` |
| `AccelerometerTilt` | `tilted-up` |
| ALSA card | present |

With no manual intervention and without rebuilding the registry.

### What remains of the two patches

They stay in the repository and remain correct: without them, any rebuild of
the registry — from a freshly generated tree, from a date that slips, from a
new JSON — dies on the first entry. With them, the rebuild completes in full.
What they do not fix is the next stage, `sns_registry`, which is why it is
better never to need it.

---
## Session 6 — the EF-DX920 cover's STM32 answers once powered

Date: 2026-08-02.

### Correcting an earlier conclusion: it is not `i2c-gpio`

The first reading of the `stm32@2a` fragment saw the properties
`stm32,sda_gpio = <&tlmm 72 ...>` and `stm32,scl_gpio = <&tlmm 106 ...>` and
deduced the MCU used a bit-banged bus. That was wrong. The same DTBO's
`__fixups__` table contains the decisive association:

```
qupv3_se15_i2c = "/fragment@70:target:0";
```

Fragment 70 is `stm32@2a`. In mainline the controller is `i2c15`, and its
upstream pinctrl already assigns exactly GPIO72/106 to `qup2_se7`. Creating an
`i2c-gpio` as well would have made two masters compete for the same lines.

The stock DT also separates the booster: `kbd_boost@18` is on
`qupv3_hub_i2c4`, not on SE15, and `stm32,booster_power_models` contains only
`0xf9` and `0xd3`. The EF-DX920 appears as model `0xd6`, so the first bring-up
can skip the MAX77816 with documentary backing.

### A reversible physical power test

The booted kernel exposes the GPIO chardev v2, even though Ubuntu 24.04's tools
speak only v1. A temporary probe was written that uses the v2 ioctls directly,
modifying neither the root filesystem nor any partition. On the main TLMM it
applied the Samsung DT's sequence:

- GPIO10=1: VDDO;
- GPIO12=0: BOOT0/SWCLK;
- GPIO13=1: reset released.

After 100 ms, GPIO62 (`irq_conn`) began showing periodic activity and GPIO75
(`irq_gpio`) also produced a transition. On closing the descriptors the GPIOs
were released. The earlier test with three dead pins did not refute the wiring:
the MCU was unpowered. This measurement confirms VDDO and the control lines,
but does not yet confirm keys; that requires SE15.

### GPL sources and the first mainline driver

Nineteen files of the V3 implementation were imported from the official
`SM-X910_EUR_16_Opensource.zip` release, verifying the archive's SHA-256 first.
They stay untouched under `kernel/vendor/samsung-stm32-pogo/` with a
`SHA256SUMS`. No binary firmware was imported.

Porting the downstream's 11,652 lines unchanged would drag in `sec_class`, the
MUIC, Android notifiers, `msm-bus` and the FOTA path. For the real model a
small mainline subset was written that keeps the protocol observed in Samsung's
sources:

- a three-byte header and events on an active-low IRQ;
- model `0xd6` / EF-DX920;
- 16-bit keyboard events: the Linux keycode in bits 0..14 and press in bit 15;
- the Caps Lock LED's state in the following header;
- the MCU's Hall event translated to `SW_LID` (`2` open, any other value
  closed).

The new DTS enables QUPv3 SE15 at 400 kHz, the regulator with GPIO10 and the
four exact control/IRQ lines. The controller stays built in, like every
provider in this port. `CONFIG_GPIO_CDEV_V1=y` is also added so Noble's
libgpiod 1.6 tools stop giving false `Invalid argument` errors.

### State at the end of this entry

The kernel compiled correctly with the driver built in and the resulting DTB
contains `keyboard@2a` under `i2c15`, the VDDO regulator and the four expected
GPIOs. `llvm-nm` also confirmed the driver's static registration.

While packaging v0.8 an environment regression appeared: `sgdisk --zap-all`
wrote the file and then blocked forever inside `sync(2)`, in `super_lock`. It
was reproduced with a fresh image of only 16 MiB and the exact syscall located
with `strace`; it was not a layout fault. Creating the GPT on the freshly
recreated file was switched to `sfdisk`, keeping the offsets, types and labels.
The rule of cleaning a physical microSD with `sgdisk --zap-all` before writing
it stays intact.

Release v0.8 finished with every static validation passing:

- TWRP ZIP: SHA-256
  `35a48756961bb5c72eb207af6a3a5981a868add3c49108fe74a98b936ba17652`;
- compressed SD image: SHA-256
  `a24ce5f3fbc1b246311af046ad4e8876f9d87ffe34ffb4ab72a26a6febe1e093`.

Nothing has been flashed and the driver cannot yet be marked working. The next
evidence required is that `i2c15` probes `0x2a`, that the input device appears,
and that physical presses generate correct events with no regressions in audio,
Wi-Fi, rotation or suspend.

As a pre-installation baseline, v0.7 was queried over SSH: kernel
`7.2.0-rc3-dirty`, GDM active, no failed unit and, as expected in that version,
neither `i2c-15` nor `15-002a` present in sysfs.

---

## Session 7 — v0.8 on hardware: root filesystem recovery and pogo diagnosis

Date: 2026-08-02.

### The black screen was not a boot regression

The v0.8 ZIP was installed from TWRP with all its hashes correct, but the first
reboot left the panel black and the network down. A USB gadget called
`postmarketos` was expressly ruled out: it belonged to another device connected
to the PC, not to the X910 running Ubuntu.

`/proc/last_kmsg` only reached `ExitBootServices`; it contained no panic. The
microSD's persistent journal gave the exact cause: `systemd-fsck-root` ended
with code 4 due to an unexpected inconsistency and several unlinked inodes, and
systemd entered `emergency.target`. The black panel hid the prompt and
simulated a failure earlier than the kernel.

From TWRP an explicit repair was run on the Ubuntu partition: `e2fsck -f -y`
recovered three small inodes into `lost+found` and corrected the bitmaps and
counters. A second `e2fsck -f -n` pass ended with code 0. After rebooting, the
tablet came up on v0.8 with GNOME and Wi-Fi active. The root filesystem is
mounted from the microSD as ext4 `rw,noatime,errors=remount-ro`.

So that a dirty root filesystem does not present itself as a kernel regression
again, the TWRP installer now runs `e2fsck -p` **before** mounting it read-write.
It continues only if the filesystem was clean or safe errors were corrected
automatically; any more serious code aborts before writing the partitions and
asks for a manual repair. The ZIP's static validation checks this guard is
still packaged.

### What v0.8 proves and what it does not

The driver probes on the dynamic controller `i2c-5` (`89c000.i2c`; the number
is not the hardware alias), registers `Book Cover Keyboard Slim (EF-DX920)` as
an I²C input device and announces `connected=0, data-ready=0`. That proves the
driver bound, not working keys. An `evtest` capture received no events and the
GPIO75 data IRQ's counter stayed at zero.

A reversible probe, with the driver and regulator released and restored on
exit, applied VDDO=1, BOOT0=0 and NRST=1. GPIO62 began detecting the cover and
oscillating on retries of roughly two seconds; GPIO75 stayed high. The MCU sees
the physical connection but never announces a packet.

A complete re-read of Samsung's GPL driver found two omissions in v0.8. First,
the stock uses GPIO62 on both edges as a state machine: it powers VDDO on
connection, waits 50 ms, enables the active-low GPIO75 and reverses everything
on disconnection. Second, `qupv3_hub_i2c4`'s MAX77816 is needed after all: the
model list controls only a subsequent adjustment, while the output's power-on
routine always runs. It writes `0x03 = 0x70` and `0x02 = 0x8e`. In v0.8 that
bus is disabled, so the STM32's logic starts but the cover's boosted supply
does not.

### The next iteration

v0.9 must implement the connection IRQ and the stock's power sequence, enable
`i2c_hub_4` and program the MAX77816 with a built-in driver. It will be
considered working only after observing real presses in `evtest`; the input
device merely appearing is not enough.

---

## Session 8 — v0.9: the STM32 starts and the EF-DX920's real input appears

Date: 2026-08-02.

### A first real regression and its correction

The first v0.9 enabled `i2c_hub_4` in PIO. That controller claimed TLMM4/5 and
the ADSP stopped probing, because `6800000.remoteproc` uses the same lines in
its pinctrl. The v0.8 `boot` was restored immediately and SE4 was redone with
GPI DMA, like the SE3 already validated for the SM5440. The pinctrl property a
bus delegated to GPI must not own was also removed from the ADSP node. On the
next boot the ADSP was back to `running` and the GPIO conflict was gone.

SSC did not appear on that boot. So as not to attribute it to the keyboard, two
negative controls were run. First both `6-002a` and `990000.i2c` were
deregistered live, the ADSP restarted and SSC probed twelve times: it kept
returning `SSC QMI Service not found`. Then the clean v0.8 `boot` was started
again and the service's full window waited out: neither sensorspd nor the
accelerometer appeared there either. It is therefore SSC's already-known
intermittency, not an SE4 regression; v0.9 was restored at the end.

### Correct power, mute application

The driver moved to handling GPIO62 on both edges with 250 ms of debounce,
GPIO75 as level-low, VDDO and the MAX77816. Its registers were read live:
`CONFIG1=0x8e`, `CONFIG2=0x70` and the default voltage `0x23`; the writes were
arriving. Even so, the application address `0x2a` kept NACKing and GPIO75
generated no IRQ. The input stopped being registered in `probe`: it is now
created only after receiving the exact model `0xd6`, preventing GNOME from
disabling auto-rotation because of a phantom keyboard.

Samsung's code supplied the next decisive test. Before using the application it
always enters the STM32's I²C bootloader, validates the firmware and returns to
the main flash. Only the reading part was reproduced:

- ROM bootloader at `0x51`: reachable;
- product ID: `0x0460`, the one Samsung expects;
- version at `0x08000200`: `00 34 00 34`;
- official image `keyboard_stm/stm32_gts9family.bin`: `00 37 00 37`, 52,132
  bytes, SHA-256
  `1b48d88c23523ae205cd960e6d42725268638a15a47d8a5e52854eb01108caa3`.

An explicit updater was added, reachable only by root. It rejects any
unexpected size or version, erases only the 31 pages Samsung erases (keeping
the last), programs in 256-byte blocks and reads back and compares the whole
blob. With the tablet charging and at 89 %, the update finished without a
single differing byte. A reboot confirmed version `00 37 00 37`. The option
bytes read afterwards were `aa fe ff fe`: RDP level 0 and bit 24 already
cleared, so they did not need writing.

### The final cause of the silence

The new firmware was still mute because our driver did a second reset right
after enabling VDDO/MAX77816. That hypothesis came from an incomplete reading:
Samsung resets on leaving the bootloader, **before** the connection, but its
`stm32_keyboard_start()` only powers up, waits 50 ms and enables the IRQ; it
does not reset again. On removing that extra reset, the first boot produced:

```
STM32 bootloader reachable, product id 0x460, flash version 00 37 00 37
keyboard attached, model 0xd6 (EF-DX920)
EF-DX920 protocol confirmed; input enabled
```

`/proc/bus/input/devices` and `evtest` show the Samsung I²C device
`04e8:a035` with `EV_KEY`, `EV_LED/LED_CAPSL` and `EV_SW/SW_LID`.
Disconnecting the cover removes it and reconnecting registers it again. The
initial packet `0x7fff` falls outside the keycode range, as in Samsung's bypass
parser; it is ignored. The key had been left pressed before the keyboard was
powered and the firmware reports no earlier transitions, so a fresh physical
press is still needed to raise the row to full support.

### Reproducibility

The proprietary firmware does not go into Git.
`stage-stock-pogo-firmware.sh` takes it from the already-extracted official
vendor image and checks the pinned SHA-256; the overlay installs it under
`/lib/firmware/keyboard_stm/`. Package `ubuntu-gts9u-device` 1.2 adds a oneshot
unit that requests the update only with the exact blob, at least 50 % battery
and external power. If the version is already `00 37 00 37`, the driver writes
nothing. The live installed image was returned to v0.9 and Wi-Fi/SSH, audio,
GPU, touch and DSI were checked present.

The complete v0.9 release was also built from scratch: 985 packages, device
package 1.2 and the pogo unit enabled inside the SD image. The finished image
was mounted read-only to check those three facts. The ZIP passed every static
validation and contains the 52,132-byte STM32 firmware with the pinned hash.
Final artefacts:

- compressed SD image: SHA-256
  `fdeaf00cd5d64f9e0b16d39f9a9f1914a4e8a4fa59824e80fef680e6d1186eab`;
- TWRP ZIP: SHA-256
  `5477e23cd9c1884237b7171c6dafbd4271eca1e7c39ad06f150f7ab2a1187c16`;
- `boot.img` running on the tablet: SHA-256
  `f77de14e484b83bb31ead3e557e10d441b87e8c92e5f05c84d48600ba24e4ffe`.

---
## Session 9 — the application fully initialised, and polling withdrawn

Date: 2026-08-02.

### The application layer does get initialised

Fresh physical presses were observed simultaneously with `evtest`, the GPIO75
IRQ counter and the journal. No `EV_KEY` appeared and the counter stayed still.
This corrects the previous session's provisional conclusion: the input is real
and dynamic, but the keys still do not work.

Comparing with Samsung's `stm32_check_ic_work()` revealed the phase missing
after the `0xd6` announcement. Its version, mode, CRC and accessory-version
reads were ported, along with the stock's three I²C retries. On a clean boot
the hardware answered exactly:

```
application initialized: version 04 01 05 01, mode 1,
  CRC cd 0b f7 cf, accessory 09 00 ff 00 00 00
```

The `ff 00` value indicates there is no touchpad controller, as befits the Slim
cover. Even with this correct initialisation, new presses activated neither
GPIO75 nor delivered events. A manual query returned the keypad header with
payload `ff ff`, the marker for no key pending. Later queries competed with the
driver and caused NACK/`-EPROTO`; they must not be repeated with the client
bound.

### Periodic polling: a regression and immediate withdrawal

To separate an absent IRQ from a valid event queue, a 20 ms poll was built
inside the driver itself, protected by the same mutex. Only `boot` was written;
copy, backup and partition were verified by SHA-256. The new boot did reach the
real system, though Wi-Fi did not associate until it was rebooted once. The
subsequent journal gave the reason to withdraw the experiment: `i2c i2c-6:
Transfer while suspended`, with the stack pointing at the polling work. A 20 ms
task cannot touch SE15 while the system suspends.

It was withdrawn immediately and a kernel recompiled that keeps only the proven
initialisation. The resulting recovery `boot.img` has SHA-256
`17e7feaaca18cddbdd39c41bb2f477c0164482af26a40f0c86fdeb236d722f58`. After a
manual reboot, the tablet recovered Wi-Fi/SSH and only that `boot` was written
over UFS. TWRP was not needed.

As an external control, the same EF-DX920 cover was tested under One UI: the
keys worked correctly and closing the lid blanked the screen. The hardware and
the contacts are ruled out as a general cause; the blockage belongs to the
mainline sequence.

---

## Session 10 — the first real keys, and recovering from STM32 bounces

Date: 2026-08-02.

### Samsung's timing was functional, not cosmetic

A close comparison with `stm32_dev_int_proc()` and `stm32_check_ic_work()`
showed that Samsung does not keep the GPIO75 IRQ masked throughout
initialisation. It reads VERSION synchronously when it receives the `0xd6`
announcement, leaves the handler, and schedules the rest 10 ms later. The first
reproduction, which left MODE, the 200 ms wait, CRC and accessory inside the
handler, jammed DATA and produced `-110` timeouts. On separating the two steps
as the stock does, GPIO75 returned to rest and the application answered
consistently.

Reproducing Samsung's disconnection edge as well — releasing state and cutting
VDDO when GPIO62 falls, restoring it if it rises again within 250 ms — finally
unblocked the keyboard. A physical `evtest` capture measured press and release
of `U`, `I`, `T`, `H`, `W`, `E`, `F`, space and backspace. GPIO75's counter rose
at the same time. That definitively rules out GNOME, evdev, the keymap and the
firmware as the cause of the earlier silence.

### Why a key would stay pressed and then the keyboard would die

The first build with working keys used `boot.img` SHA-256
`25e0b8f6a58f7104649f7eb16f0bede7de0b40aa3ebacbaf40a5105677702838`. During real
typing GPIO62 bounced in both directions and the STM32 restarted. If that
happened with a key down, the micro lost the state and never sent its release.
The driver also did VERSION/MODE/CRC only on the first announcement;
afterwards it kept the input but skipped the handshake on re-announcements. The
visible result was a stuck key followed by an unresponsive keyboard.

Iteration `f33516674b910b5853f9fc3a9aaa94ac67069242cdcbadb4af73c8ae0cfb2243`
released every key before cutting VDDO and repeated the handshake on each
`0xd6`. It eliminated the sticking, but a physical test ended with a spurious
model `0xff`, DATA asserted and an `-ETIMEDOUT` every ~4.4 s with no recovery.
The capture had previously used `evtest --grab`; while that was active GNOME
could not receive the keys. Later captures dropped `--grab`.

The currently installed kernel, `boot.img` SHA-256
`171d335e9609be33387c915e8c7997b4fb884f0842b34abcf7b888d4bb31da2e`, adds the
stock's error path: it ignores `0xff`, releases the whole bitmap and pulses
NRST for 3 ms after exhausting the I²C retries. On a clean boot it survived an
early bounce, repeated the `0xd6` announcement and ended with version
`04 01 05 01`, mode 1, CRC `cd 0b f7 cf`, DATA inactive and no new timeouts.
Two later windows of 40 and 90 seconds received no physical activity; the state
stayed stable, but the final validation under sustained typing is explicitly
still pending and it is not yet marked as full support.

### The joint trace revealed a spurious read of an empty queue

With a key physically held down, only I²C adapter 6's tracepoints and IRQs
186/187 were enabled. The sequence was deterministic: the `0xd6` announcement,
VERSION and several valid keypad packets; then another IRQ 186 arrived, writing
the header `[03 00 01]` succeeded, but reading the header timed out with `-110`
after some 0.9–1.0 s. The retries returned `-6`, GPIO62 generated IRQ 187 and
VDDO entered a power cycle. The pattern reappeared every 2–3 s.

The cause was the adaptation to `IRQF_TRIGGER_FALLING`: it solved the loss of
short pulses that level-low suffered, but the handler read without checking
whether DATA was still asserted. Samsung's ISR does return when the active-low
line has already risen. The falling edge was kept and that check added before
any transaction. The experimental 3 s watchdog was also withdrawn: a key
legitimately held down does not demonstrate a blocked stream and must not
restart the application.

Only `boot` was compiled and written, with a backup and SHA-256 verification.
The new `boot.img` is
`5e3d577d81c6a74f11b55476555c3d4e37e387e332f6d50a21075900cdcc755b`; the
previous one,
`4b1e3637781081fc5fae9e108422dbca8864713f48f97df577f3a26c45471640`, was kept as
a temporary rollback. Live, over six minutes of physical typing, the counters
stayed at `connection_high=0`, `connection_low=0`, `recoveries=0`; one
already-deasserted IRQ was recorded in `data_irq_deasserted=1` and produced no
timeout. That is strong evidence the power storm is fixed. The owner's final
test with varied typing is still missing, so the status stays amber.

---

## Session 11 — the stability at 400 kHz did not survive a reboot

Date: 2026-08-02.

The owner confirmed the keyboard had worked with several keys at once and also
after disconnecting and reconnecting it, but on rebooting it became erratic
again. It was exactly the same `boot.img`, so the boots were compared rather
than blaming the IRQ filter.

On the bad boot the driver received hundreds of real events, but accumulated
dozens of GPIO62 edges, NACK `-6`, `-71` errors, GENI timeouts and several
destructions and recreations of `event3`. A passive capture ended with `No such
device` just as GPIO62 stayed low for more than 250 ms. The empty-IRQ filter
was doing its job — the discards grew without causing resets — but there were
also failures in transactions with DATA genuinely active.

### Autosuspend ruled out

The `89c000.i2c` controller uses a 250 ms autosuspend and the failing phases
showed delays of the same order. `power/control=on` was forced temporarily, the
`active` state verified and only the pogo driver reinitialised. GPIO62 kept
pulsing and the keys stopped again. The test was reversible, the controller was
returned to `auto` and no userspace patch was kept.

### SE15 at 100 kHz

Only I2C15's `clock-frequency` was changed from 400 kHz to 100 kHz. The driver
and `boot` stayed identical. Only `vendor_boot` was built and written, with a
copy and SHA-256 verification:

- new: `1313836dd22c120f7c2bb82a7ec45fba0de1e057e2b6691cb2e453d1bbdef6ba`;
- previous: `fb31f91ebb9959400a5110607353148e63f7017f7ba03616e21dcbbe6dc653ba`.

The live tree confirmed `clock-frequency=100000`. On the first boot there was
one initial cycle, the handshake completed correctly and a physical `ESC`
reached the input. The following 36 samples over three minutes were identical,
with no timeout and no recovery. It was rebooted again with the keyboard
connected and the result repeated. Finally an unbind/bind of the driver alone
was done: it recreated `event3`, received the physical key again and stayed
another three minutes with no new GPIO62 events and no resets. The frequency
stands as v0.10's reproducible fix; the owner's validation with varied typing
is still needed on her return.

A third reboot test, now with the fix installed persistently, was cleaner
still: the firmware announced `0xd6`, completed VERSION/MODE/CRC on the first
attempt and created `event3` with `connection_high=0`, `connection_low=0` and
`recoveries=0`. Before that reboot, 57 samples over nine minutes had stayed
identical. An object resting on the keyboard produced a physical `ESC`, but
that does not substitute for the manual test of several keys and a reconnection
that remains pending.

The reproducible v0.10 release was generated from commit `5403cd7`. Its
artefacts are `ubuntu-24.04-gts9uwifi-v0.10-sd.img.xz` (SHA-256
`8380a22336e4a6b5c8a9e713e105fd1807fc3346930d87662d07f7753fb3aa40`) and
`ubuntu-24.04-gts9uwifi-v0.10-sm-x910-twrp.zip` (SHA-256
`895c2f8a526d0bc234490c917349f87d48f739367cc1e74ece634db7ade233fc`).

---

## Session 12 — DATA pulses have to be classified in the hard IRQ

Date: 2026-08-03.

The pending manual test invalidated the previous session's strong conclusion:
the keys were still sticking, even though connecting and disconnecting the
cover and auto-rotation appearing both worked correctly. Over nine minutes of
typing, the diagnostics measured 174 DATA IRQs, 104 key transitions, 17 IRQs
discarded for DATA being inactive, 18 GPIO62 low edges and four recovery
resets. The journal contained `-110` and `-6`. During a later 60-second passive
capture, with no physical activity, every counter stayed still. That separates
the fault from the attach/detach path and from userspace.

The guard added in session 10 ran inside the threaded handler. That moment is
too late for a GPIO that emits short pulses: a valid edge may have returned
high while the corresponding packet is still queued, so a transition was lost —
the release especially. At the same time, removing the guard entirely had
already shown that a stale pending IRQ polls the empty queue and causes a
timeout.

`IRQF_TRIGGER_FALLING | IRQF_ONESHOT` was kept, but a primary handler was added
that reads GPIO75 with `gpiod_get_value()` in hard-IRQ context. Only if the
active logical level is still present does it return `IRQ_WAKE_THREAD`;
already-inactive pendings are counted and finish without I²C. The kernel
compiled and was written to `boot` alone, with SHA-256
`93e39902057b515017bb705fc6076fc9a35d212eafb35960afd5c054387d0d23` and a
verified rollback of
`5e3d577d81c6a74f11b55476555c3d4e37e387e332f6d50a21075900cdcc755b`. The first
boot and an unbind/bind recreated `event3` with zero recoveries; sustained
physical transitions are still needed to confirm the fix.

### Physical confirmation and persistence

The sustained manual test confirmed the hypothesis. Over more than eight hours
the driver counted 2,046 real key transitions and ended with `keys_down=0`; the
owner could type normally, use several keys and physically disconnect and
reconnect the cover without leaving a key pressed or losing the keyboard. Of
2,099 DATA IRQs, 12 already-inactive pendings were discarded in the hard IRQ
without starting I²C. There were two recoveries during the initial settling and
one isolated SE15 recovery at 16 minutes, but the driver redid the handshake by
itself and the following reconnections were clean; no visible degradation
occurred over the hours that followed.

The tablet was rebooted with the cover connected to rule out the success
depending on the test session's rebind. The kernel created `Book Cover Keyboard
Slim (EF-DX920)` again from boot, completed VERSION/MODE/CRC and received
another 61 physical transitions with `keys_down=0`. An early `-110` recovery
automatically redid the application and did not prevent operation. The live
tree kept exposing SE15 at 100,000 Hz and the partitions' hashes matched the
reproducible payloads:

- `boot`: `93e39902057b515017bb705fc6076fc9a35d212eafb35960afd5c054387d0d23`;
- `vendor_boot`: `1313836dd22c120f7c2bb82a7ec45fba0de1e057e2b6691cb2e453d1bbdef6ba`.

At that moment the evidence looked sufficient to move the keyboard to full
support. The next session showed that conclusion was premature: v0.11 was not
published.

---

## Session 13 — the prolonged stability did not survive a reboot either

Date: 2026-08-03.

After the window of more than eight hours and one correct reboot, the owner
rebooted again and the keys stuck once more; afterwards the keyboard stopped
responding. The partitions and the live tree were compared: `boot`,
`vendor_boot` and `clock-frequency=100000` were identical. The stable boot had
rebound the driver at 272 s and settled around 363 s; the bad boot did it at
3 s and accumulated NACK `-6`, `-110` timeouts, resets and GPIO62 pulses. An
isolated rebind did not guarantee reproducing the good state. The difference is
in the STM32's or the transport's cold/timing state, not in a different image.

Samsung's real controller `drivers/i2c/busses/i2c-msm-geni.c` was reviewed, not
only the smaller common driver. Three differences are backed by the SM-X910's
official source:

- the DT uses DATA as level-low + ONESHOT;
- the 100 kHz GENI counter is `{7, 10, 11, 26}` and mainline used
  `{7, 10, 12, 26}`;
- on a timeout Samsung sends `M_CMD_CANCEL` and only aborts if cancelling
  fails.

The first test with level-low, without the other changes, received 109
transitions in 60 s but ended with four recoveries and `-6/-110` errors. Adding
only Samsung's counter improved another capture to 57 transitions and one
recovery, but the corrupt event `0x6767` appeared and two NACKs and a timeout
persisted. No variant was declared fixed.

A clean variant was then built adding cancel-before-abort. Its `boot` has
SHA-256 `f3c6a4235e7dcea8e82ce510861eae3eb145e04ff5594005a0e7a42d3ca158d8` and
booted correctly; at idle it completed the whole handshake, though it recorded
two early NACKs. A 60 s capture with no physical presses changed no counter and
therefore does not validate the keyboard.

Finally another difference in the official driver was noticed: every failed
read attempt notifies RESET to the consumers and releases the keys before
retrying. Our own driver released them only after exhausting all three
attempts, which explained a press staying visible for several seconds. The
immediate release was added, keeping the physical reset only after the retries
are exhausted. That last variant is compiling and awaits sustained typing, a
reboot and a reconnection; the current release remains v0.10 and the keyboard
stays amber.

---

## Session 14 — the late recovery was also an SSC/GNOME race

Date: 2026-08-03.

The previous session's final variant compiled correctly. Its `boot.img`,
SHA-256 `df98bc12b74b84db65b2cb2c4bd669fb10d28b498773692e2e2db336be6f03fa`,
adds the immediate release after each failed read on top of the level-low,
Samsung timing and cancel-before-abort already described. Only `boot` was
written, with the copy and remote hash verified; the rollback is
`f3c6a4235e7dcea8e82ce510861eae3eb145e04ff5594005a0e7a42d3ca158d8`.

Before writing it, a second, independent anomaly was found. The bad boot had
`iio-sensor-proxy` near 100 % CPU and `irq/16-smp2p-adsp` near 90 %, while the
kernel repeated `Handover signaled, but it already happened` every ~233 ms.
Stopping the proxy needed the full 90 s timeout and SIGKILL. After a safe
rebind of the pogo, a physical capture delivered 432 transitions in 60 s,
combinations included, with `keys_down=0`, zero recoveries and zero errors.

The first interpretation — that the storm was the keyboard's root cause — was
too strong. The earlier boot that worked for eight hours had also accumulated
139,497 handovers. It is a real regression: it occupies two cores and coincides
with DPU and GENI timeouts, but it can only be considered an aggravating factor
for the pogo transport.

The chronology located the race. The helper started before LightDM/GDM, queried
SSC and created a proxy before GNOME was a consumer. The tests of not
restarting `hexagonrpcd`, waiting 75 s and observing fixed 4 s windows all
failed: the client's silent period varied and the storm appeared only after the
display manager was unlocked. Do not repeat those blind delays.

The reproducible solution orders `ubuntu-gts9u-sensors-resume.service` after
the display manager. Once it has a real accelerometer measurement it starts a
clean client and watches the handover IRQ every two seconds for 30 s. On the
clean boot `55a9406e-d2e8-4d54-9a87-f75ecb7066b5` it detected 3 IRQs in 2 s,
killed only the first proxy and opened another. The second passed the whole
watch; a later 10 s measurement gave a delta of 0, `iio-sensor-proxy` consumed
45 ms of CPU and the load fell to 0.74. The ADSP was not restarted and no audio
was lost.

On that same boot the pogo initialised from cold with no manual rebind, no
errors and no recoveries, and ended at `keys_down=0`. That validates
reproducing the boot state, not typing: the owner was away and still has to
test several keys, a physical reconnection and sustained use. The public
release remains v0.10 until that validation on the v0.11 candidate is complete.

---

## Session 15 — the black screen was emergency mode, not the screen

Date: 2026-08-03.

The owner reported that, after a reboot, the tablet went black and never
finished booting. She handed it over in TWRP.

### The diagnosis, and a misreading along the way

With the root mounted read-only, the active journal showed a boot that reached
`time-set`, `network` and `nss-lookup` and then fell silent for sixteen
minutes. The conclusion drawn was that systemd hung before `basic.target`.
**That was false.** That file contained only the boot's final stretch; the
beginning was in a rotated journal, and the line `Startup finished in 12.706s
(kernel) + 15.085s (userspace)` itself contradicted it.

With every `system*.journal` downloaded and read with `journalctl -D`, the real
sequence appeared:

```
systemd-fsck-root.service: Failed with result 'exit-code'
Failed to start systemd-fsck-root.service
Reached target emergency.target - Emergency Mode
```

The system booted fine and stopped in emergency mode because the root's `fsck`
found errors it could not correct unsupervised. Neither `multi-user` nor
`graphical` was ever reached, hence no GDM and no image.

Lesson: do not diagnose a boot with a single journal file.

### The repair

`e2fsck -fn` showed routine damage — two orphan inodes, bitmap differences and
free counters — with passes 2 and 3 clean, that is, the directory structure
intact. `e2fsck -fy` corrected it: `Filesystem state: clean` and a normal boot.
Five files ended up in `lost+found`; all five turned out to be text and GVariant
cache databases, nothing belonging to the port.

### The root cause, in the repository

`build-sd-image.sh` created the root with `-O ^has_journal`. Without a journal,
every dirty shutdown leaves damage, and with `Errors behavior: Continue` ext4
carries on instead of remounting read-only, so the damage accumulates
invisibly. The image is now created with a journal and `-e remount-ro`; on the
live card `tune2fs -e remount-ro` was applied.

### The keyboard, after the repair

The owner reported that the keyboard had stopped working. The obvious and wrong
hypothesis was ruled out first: `e2fsck` did not take the firmware, which is
still in `/lib/firmware/keyboard_stm/stm32_gts9family.bin` with its 52,132
bytes.

The real state:

```
attached=1 model=0x00 connected=1 data_ready=0
connection_high=129 connection_low=130
cannot restore keyboard power: -108
```

The protocol ID does not arrive — `model=0x00` where it used to be `0xd6` —
the connection line has bounced 259 times and the booster is re-enabled every
2.1 s indefinitely. The driver bound at 3.7 s.

This **matches the pattern already described in sessions 11 and 13**: the bad
boots bind early and accumulate GPIO62 pulses, the good ones bind late. It is
neither a new failure nor a consequence of the repair.

As an aggravating factor, the battery was at 10 % and 3,716 mV, and the
MAX77816 that powers the keyboard hangs off it; the firmware service itself
deferred for exactly that reason. Repeating the measurement with sufficient
charge, before touching the driver, is still pending.

### Driver defects recorded, not fixed

- The power retry has no brake: it re-enables the booster every 2 s forever,
  with no spacing and no surrender.
- `samsung_pogo_enable_power` emits a kernel backtrace on failure. A
  foreseeable power failure should not generate a WARN.

### A loose end: v0.11 has no artefacts

The tablet boots a `boot.img` `df98bc12…` built in session 14 that corresponds
to no packaged release: `artifacts/` goes up to v0.10. There is a kernel on the
device that is not reproducible from a release. Before continuing with the
keyboard it is worth closing v0.11 or going back to v0.10.

## Session 16 — what changed since the keyboard worked: nothing of ours

Date: 2026-08-04.

The owner reported the keyboard had stopped working and asked for a comparison
with the good state. Three hypotheses were ruled out with evidence, not
opinion.

**The battery, no.** It had been noted that 10 % and 3,716 mV might stop the
MAX77816 sustaining the MCU. The owner recalled it had worked at 15–20 %, and a
clean boot at 39 % reproduced the identical failure. Ruled out.

**The MCU's firmware, no.** `ubuntu-gts9u-pogo-firmware.service` deferred on
**every** recorded boot, including one at 91 %. It never wrote to the STM32, so
it cannot have corrupted it.

**This session's changes, no.** The filesystem repair touched nothing of the
pogo's — the firmware is still in place with its 52,132 bytes — and the power
button handler only reads `event0` of the `pmic_pwrkey`.

### What it is

The pattern matches what sessions 11 and 13 described: the bad boots bind the
driver early — here at 3.7 s — and accumulate GPIO62 pulses without the
protocol ID ever arriving. `model=0x00` where the good state gives `0xd6`.

New since session 14: **the rebind no longer recovers the good state**. A
complete unbind, 8 s wait and bind cycle again left 12 booster activations in
25 s and no input device. The recovery that worked there is not reliable.

### One measured difference, open to interpretation

The driver reads four bytes of the STM32's flash through the bootloader's read
command. On the boot that worked they were `00 37 00 37`; on every failing one,
`00 34 00 34`, consistently and reproducibly.

It is not claimed to be the cause. It is a memory read over the same I²C link
that is suspected of being marginal, and they differ by a single nibble, which
fits a corrupt read as well as it fits different content. It is recorded as the
only hard discriminator found between the two states, and it deserves checking
by reading several times in a row before anything is built on top of it.

### Confirmed and pending defects

The booster's retry still has no brake: on one boot it reached 788 activations.
It was stopped with a reversible unbind. The fix — a growing wait with a cap,
the counter reset on latching or disconnecting — is specified and **not
applied**, because touching the driver means compiling, writing `boot` and
rebooting, and the v0.11 loose end has to be closed first.

## Session 17 — v0.11 closed, and the keyboard points at the MCU's flash

Date: 2026-08-04. An unattended session, with the owner's explicit
authorisation to write `boot`, `init_boot`, `vendor_boot`, `dtbo` and `vbmeta`.

### v0.11 closed

Built with `KERNEL_CLEAN=1`. Before overwriting anything, the five partitions
were backed up into `artifacts/backup-preV011/`, including session 14's
`boot.img` `df98bc12…`, which existed in no release and is the kernel with
which the owner saw the keyboard work best.

They were written with `dd` rather than through the ZIP: `twrp install` takes
adb down and it did not come back the previous time, which in an unattended
session would leave the device with no way to reboot. Four partitions verified
by reading back. `vbmeta` copied zero bytes — it is read-only in this TWRP,
already documented — and stayed intact; the one there is the one that has
always been booting.

The microSD was not rewritten: the owner has data and installed snaps, and
v0.11 needed no new root filesystem. The two signed `ath12k` modules, which
live on the card and not in the ZIP, did have to be replaced by hand; without
that, a new kernel with old modules leaves Wi-Fi out and with it SSH access.

Boot verified: system `running`, zero failed units, Wi-Fi with the new modules,
and audio, sensors and the button handler all active.

An honesty note: that the clean build is **reproducible** is not demonstrated.
That would need a second identical clean build. What is demonstrated is that
the incremental one was not.

### The keyboard: the bootloader answers, the application does not

`event_poll`, the driver's own diagnostic hook, produced
`read_retry_releases=9` over `manual_polls=3`: three retries per poll, and no
answer at all. The MCU does not answer the keyboard protocol even when asked
directly.

Its bootloader, by contrast, answers perfectly on every boot, reading the
product id `0x460` and the option bytes without a single error.

That separates the two halves: **bootloader alive, application mute**, and
reframes the flash difference already observed. Where the good boot read
`00 37 00 37`, every bad one reads `00 34 00 34`, consistently. If those bytes
are real content and not a corrupt read, the keyboard's application is damaged
in the STM32's flash.

It fits everything observed: the bootloader answers, the application does not;
no reboot or rebind recovers it; and the owner describes it as previously
**latching** and only half failing with stuck keys, whereas now it does not
latch at all. They are different failures, not the same one worsened.

### What has not been done, and why

The driver exposes `firmware_update` and Samsung's blob is on the card with its
52,132 bytes, so reprogramming the MCU is possible. **It has not been done.**
The owner's authorisation covered the tablet's boot partitions, enumerated one
by one; rewriting an accessory's flash is a different thing, potentially
irreversible, and the firmware service itself is written to defer unless
conditions are safe. It stands as the recommended action, pending her
authorisation.

Before reprogramming, it is worth confirming the four version bytes are stable:
read them several times in a row and check they always give `00 34 00 34`. If
they wobble, they are corrupt reads and the hypothesis falls.

## Session 18 — stable auto-rotation and a complete audit of V34

Date: 2026-08-04.

### Sensors: two different races

The fix the owner physically confirmed for auto-rotation was made
reproducible. `iio-sensor-proxy` no longer claims SSC too early and the
`hexagonrpcd` service is ordered after the panel's cold-boot recovery. On top
of that, the `qcom_q6v5` patch masks the handover IRQ once it has completed: a
ten-second measurement stayed at `1 -> 1`, without the storm that used to
occupy CPU and contend with the display and I2C. The broken SSC light sensor is
excluded from the proxy; it is not presented as working automatic brightness.

### We went back to exactly the last known good pogo driver

The later sessions' experiments were withdrawn and
`kernel/drivers/samsung_stm32_pogo.c` was left identical to commit `504ff29`.
The historical good state `df98bc12…` could not be compared cleanly live
because it brought up none of the control channels; that absence of networking
was not turned into a conclusion about the keyboard.

Samsung's downstream journal showed that its own driver also observes the cycle
CONN high, VDD/MAX active for about two seconds, CONN low and power off. The
~2.126 s period therefore does not come from mainline's debounce: it is the
failure state the accessory's application communicates.

### The ROM jump was not the missing initialisation

Without writing the flash, the STM32 ROM command `GO 0x08000000` was added
temporarily. The bootloader accepted it. It was repeated with VDDO and the
MAX77816 already active and 100 ms of settling; it accepted that too. In both
cases the application kept `model=0x00`, DATA low and the same CONN pulse. The
experiment was removed completely and is not part of the final source.

### A read-only dump: V34 is a real application

A temporary tool exclusively claimed BOOT0/NRST, entered the ROM and used only
`READ MEMORY` over I2C6. It read the 64 KiB and restored normal boot without
sending ERASE, WRITE or UNPROTECT. Result:

```
bytes=65536
sha256=8937281d2efa08400390f9a2b02e40ca914b634e646d6dd544980c38464533ef
version_0x200=00 34 00 34
0037_offsets=
```

The image has coherent ARM vectors and strings that say
`TabS9(STM32G0) Series -> V34`. There is no second, hidden V37. Session 17's
conclusion — possibly damaged flash — is refuted: One UI uses V34, and Ubuntu
still does not reproduce some part of its cold initialisation.

As an additional defence, the updater now requires the explicit guard
`GTS9U_ALLOW_POGO_FLASH=YES`. The MCU has not been written and will not be
without specific authorisation.

This iteration's final `boot.img`, with the pogo driver returned to `504ff29`
and the q6v5 fix, has SHA-256
`9c4590600d410ca4e68f68a0f51abb9177df438c46ee42dded6bb651b7be956e`. The write
to `boot` was verified by reading back. After rebooting, Ubuntu did not
reappear in two complete LAN sweeps and the USB gadget stayed in Code 43, so
that boot has no remote validation yet. The next physical test must be done
with no key held down, disconnecting and connecting the cover once, because V34
contains stuck-key protection paths.

## Session 19 — the keyboard returns: the STM32 had gone back to V34

Date: 2026-08-06.

### The discriminator was already measured; what was missing was reading it the right way round

Since session 16 the same hard difference had been on record, boot after boot:
the good state read `flash version 00 37 00 37` and **every** bad one read
`00 34 00 34`. Session 18 dumped the 64 KiB read-only, checked that V34 is a
coherent ARM application, and from that deduced One UI uses V34 and that the
gap was in our cold initialisation.

That deduction contained a leap. V34 being a valid image says nothing about who
put it there. The only blob that exists in this project — the official X910
firmware `X910XXS5CYG1`'s, the same one pmOS packages in
`firmware-samsung-gts9uwifi` — is V37, 52,132 bytes, SHA-256
`1b48d88c23523ae205cd960e6d42725268638a15a47d8a5e52854eb01108caa3`. Session 8
programmed it into the MCU and **that** was the boot on which the first real
presses appeared. The MCU had gone back to V34 by itself; it was never
demonstrated that the mainline driver spoke V34.

### The repair

With the tablet at 64 % and charging — the two conditions the updater itself
requires — the driver's updater was invoked. The log is complete:

```
erasing STM32 application pages
STM32 programmed 256/52132 bytes
...
STM32 firmware programmed and fully verified (52132 bytes, version 00 37 00 37)
keyboard attached, model 0xd6 (EF-DX920)
EF-DX920 protocol confirmed; input enabled
application initialized: version 04 01 05 01, mode 1,
  CRC cd 0b f7 cf, accessory 09 00 ff 00 00 00
```

`Book Cover Keyboard Slim (EF-DX920)` returned to
`/proc/bus/input/devices` instantly. The CONN storm stopped dead:
`connection_high` stayed frozen through the following 30 s, where it used to
accumulate one booster activation every two seconds.

### Verified from a cold boot and with the owner typing

A complete reboot confirmed it without touching anything else. The driver read
`00 37 00 37` at 3.8 s, announced `0xd6` at 4.5 s and completed the application
initialisation at 7.6 s. In a 20 s window of real use the counter went from
1,063 to 1,174 presses, with `keys_down=1` in the middle of a key and
`last_key=0x0017`. `recoveries=0`, `read_retry_releases=3` and five error lines
in the whole boot. The cover was also physically disconnected and reconnected:
the driver let it go and latched it again with the full initialisation. The
owner declared it working.

### What is still unknown

**Who returned the MCU to V34.** There is no V34 in this tree, so it did not
come from here. The two plausible sources are One UI and the Ubuntu Touch port,
which load Samsung's `stm32_pogo_v3.ko` with their own vendor's blobs. It fits
the chronology — the failure appeared after booting other systems — and the
fact that the cover works on both: Samsung's driver does speak V34. Until it is
measured, **booting One UI or Ubuntu Touch may degrade the MCU again**.

Recovery is a single command, and is designed for exactly that:

```
sudo env GTS9U_ALLOW_POGO_FLASH=YES \
  /usr/libexec/ubuntu-gts9u-pogo-firmware-update
```

The updater with that guard was installed on the tablet (SHA-256
`854599b3bb89142fdaae6f6af4e4849f1485554540dd6d9c4790498618d96e53`), and
`ubuntu-gts9u-pogo-firmware.service` remains **masked**: no accessory write
happens at boot, which is precisely the scenario in which a forced reboot could
interrupt one.

### Two loose ends this session deliberately did not touch

The `boot` running on the tablet is `8fb31817…`, which appears in no manifest
in `artifacts/` and does **not** carry `qcom_q6v5`'s handover IRQ patch: the
journal repeats `Handover signaled, but it already happened` several times a
second. Rewriting `boot` to fix it would have risked the just-recovered good
state, so it was left for a session with the owner present.

The tree's uncommitted changes — `samsung,restore-output-on-resume` in the DTS
with its `i2c-qcom-geni` patch, the `KERNEL_CLEAN` that also recreates the
worktree, and `twrp-write-sd.sh`'s `sgdisk --zap-all` — are from the previous
session and **never reached the tablet**: `/proc/device-tree` does not have the
property. They stay in the tree unvalidated. The cause they were chasing no
longer stands, so they are worth revalidating on their own merits before being
adopted.

## Session 20 — v0.16: a release that installs a working keyboard

Date: 2026-08-06.

### The GENI experiment was discarded before anything was built

`samsung,restore-output-on-resume` and its `i2c-qcom-geni` patch pursued the
hypothesis that the MCU needed the serial engine's output drivers restored
after every runtime resume. It was first checked that they never reached the
tablet — `/proc/device-tree` did not have the property — and then they were
withdrawn, along with the `GTS9U_DISABLE_Q6_HANDOVER_PATCH` A/B switch that
existed only for that comparison, and with `twrp-write-sd.sh`'s untested
`sgdisk --zap-all`, which also aborts if the recovery does not ship `sgdisk`
and sits right on the path of reinstalling from scratch.

One thing from that batch was kept, because a release needs it:
`KERNEL_CLEAN=1` also recreates the source worktree. `apply_unless()` leaves
the tree accumulating every patch ever tried, so deleting only the objects does
not give a clean build.

### The guard was the wrong way round

Restoring V37 required `GTS9U_ALLOW_POGO_FLASH=YES`. On a fresh installation
that means a newly set-up system with a mute keyboard and no clue why: exactly
the problem just diagnosed, served from the factory. The guard becomes opt-out.

What makes the write safe is not choosing the moment, but where it can land.
The STM32's ROM bootloader lives in system memory, cannot be erased and answers
on every boot; the driver reads the 52 KiB back before accepting it. An
interrupted write completes on the next boot, so the service is self-repairing.
The only thing that must not happen is writing something other than Samsung's
blob, and the pinned hash still takes care of that.

The external power requirement was also removed. Programming and verifying
takes about sixteen seconds; half a tank is plenty, and demanding the charger
as well was exactly what stopped the restoration ever running.

`flash_version` now appears in `diagnostics`, alongside `bootloader`. It is the
field that separates a controller you can talk to from one you cannot, and
until now it had to be rescued from a `dmesg` line at boot.

### Static verification of the release, before touching the tablet

The finished SD image was mounted read-only: device package **1.5**,
`ubuntu-gts9u-pogo-firmware.service` linked into `multi-user.target.wants` and
not masked, the helper byte for byte identical to the repository's, and
`pogo-keyboard.md` installed. Samsung's blob does not live in the image but in
the ZIP's overlay; it was extracted from the ZIP and checked: 52,132 bytes and
the pinned hash. The source tree that compiled this release carries
`flash_version`.

### On hardware

`boot`, `init_boot`, `vendor_boot` and `dtbo` were written with `dd`, all four
backed up first and each read back. The two `ath12k` modules were replaced
**before** the kernel: they live on the card, not in the ZIP, and a new kernel
with old modules leaves Wi-Fi out and with it SSH access.

After the reboot, with nobody running anything:

```
ubuntu-gts9u-pogo-firmware.service: controller already on V37   (status=0)
attached=1 model=0xd6 connected=1 connection_high=0 connection_low=0
  bootloader=1 flash_version=00370037
N: Name="Book Cover Keyboard Slim (EF-DX920)"
```

Zero CONN pulses since boot, where the bad state accumulated a booster
activation every two seconds. The service does not delay the boot:
`graphical.target` at 54.5 s and the unit does not appear in the `blame`.

v0.16's artefacts, built with `KERNEL_CLEAN=1`:

- TWRP ZIP: `aa945ae57694df0056d1f06fc492a85e3291a8b07793e4c98451a3fc7c220397`
- compressed SD image:
  `631c0f8be83b18fe50a771963fb8de0ba6212350e7e5d071a08c1350d5d02079`
- `boot.img`: `d57eb0994876a22aeaebfcc09e127a8b4a202f4ef9491209154caa9275374c31`

### What this session does not demonstrate

That the clean build is **reproducible** is still undemonstrated: that would
need a second identical clean build. And there has been no genuine reinstall
from scratch — the card carries the owner's data and snaps — so the keyboard's
guarantee on a fresh installation rests on the static verification of the image
and the ZIP, not on having run it. What was run, and worked on its own, is the
restoration service on a real boot.

### A postscript: what could be checked with no finger present

In v0.16 a real press went unobserved: a five-minute watcher on `key_events`
recorded nothing because nobody was typing. That is not a failure, it is an
absence of data, and the two should not be confused.

The half of the link that needs no finger was exercised. Toggling the cover's
caps lock LED — `/sys/class/leds/input3::capslock` — sends a real I²C command
to the STM32's application: all four toggles arrived, the value the driver
publishes in `caps=` followed each one, and the pogo's error counter stayed at
**zero** through the whole boot. The read direction, which needs a physical
key, is still pending.

### Closing the postscript: v0.16 does type

Date: 2026-08-07.

The gap in the previous postscript was not a keyboard problem: the owner was
away and had left nothing on top of it. With real use it was measured on the
same boot, by then over seven hours old:

```
key_events=306 last_key=0x0042 keys_down=0
data_irq=318 connection_high=4 connection_low=4
recoveries=0 read_retry_releases=0 bootloader=1 flash_version=00370037
```

Four CONN transitions in seven hours, no recoveries and no read retries. It is
the longest stable window recorded in this port, and it contrasts with the
dozens of booster activations per minute of the bad state.

It was also checked that what is running is the release and not a loose `boot`:
the tablet's four boot partitions match v0.16's manifest byte for byte, and the
installed device package is 1.5.

## Session 21 — the keyboard stops asking for things, and the commercial names

Date: 2026-08-07.

### The cover requirement was an assumption, and it was false

The updater refused to write if the connection line was low. The assumed
justification — that the controller hung off the same rail as the accessory —
had never been measured. The owner asked the obvious question: if what is being
programmed is in the tablet, what is the cover for?

It was measured. With the cover off, `connected=0` and `pogo_vddo` `disabled`:

```
STM32 bootloader reachable, product id 0x460, flash version 00 37 00 37
STM32 pogo controller ready (connected=0, data-ready=0)
```

The ROM answers just the same with no cover and no rail. What is cut on
disconnection powers the keyboard; the microcontroller runs off the tablet's
I2C6 and is independent. The check is withdrawn: writing with no cover is
calmer still, because there are no connection pulses competing.

The battery threshold drops from 50 % to 15 %. It does not defend the flash —
an interrupted write completes on the next boot because the ROM bootloader
cannot be erased — it merely avoids starting on a tablet about to switch off.
The charger requirement had already been removed, and it was exactly what
stopped the restoration ever running.

With that, the README section explaining what the user had to do disappears:
they have to do nothing.

### The commercial names: two sources, one per layer

Each tool asked a different place and none gave a name.

**CPU.** `/proc/cpuinfo`'s `model name` line is the universal convention on
Linux, and arm64 only emits it for compat tasks. Filling it from a table
indexed by the machine's compatible — not by a new DTS property, which would
force rewriting `vendor_boot` — makes GNOME and everything that reads that file
receive "Qualcomm Snapdragon 8 Gen 2". `QCOM_SOCINFO` is also enabled; it was
at `=m` and therefore did not exist. Now `soc0` publishes family `Snapdragon`
and machine `SM8550`.

**GPU.** `force_gl_renderer` is a supported Mesa option — its factory
configuration uses it with other Adrenos — so no custom Mesa was needed. OpenGL
goes from `FD740` to `Adreno (TM) 740`, which is what Minecraft's F3 shows. One
trap that cost a session: a `--` inside an XML comment is illegal, and Mesa
discards the whole file without saying anything.

Vulkan still says `Turnip Adreno (TM) 740`: that string comes from a fixed
format inside the driver, with no configuration option.

**fastfetch** read neither of the two. An `strace` showed it opening
`/sys/firmware/devicetree/base/compatible` and never `/proc/cpuinfo`: on ARM it
fills the name from the device tree and, once set, skips the read entirely.
Since this port already compiles fastfetch from source, the precedence order is
patched, which is also the correct order. The package moves to
`2.66.0-gts9u1` so that an archive update does not take the patch with it.

### The clean build is not reproducible, and we now know why

Two clean builds of the same tree give the same DTB, `vendor_boot`,
`init_boot` and `dtbo`, but a different `Image.gz`. With the difference
isolated in a 1 MB module, **everything before `.BTF` matches byte for byte**:
the compiled code is already deterministic and what varies is the parallel BTF
encoder that `scripts/Makefile.btf` invokes with `-j$(JOBS)`. The detail and
the fix — unapplied, because it would change the kernel in exchange for nothing
needed today — are in the development notes.

### A race of our own, which ate the whole service

On deploying the kernel without the cover requirement, the restoration service
never ran: `ConditionResult=no` and not one line in the journal.

The cause is a change from session 20. The unit carried
`After=multi-user.target` **and** `WantedBy=multi-user.target`, on the idea that
it would run late so it could wait for the cover without delaying the boot.
systemd cannot order a unit after the very target that pulls it in: it ignores
that ordering without warning and launches it with the rest, at around three
seconds. The driver binds at 3.9 s, so
`ConditionPathExists=/sys/bus/i2c/devices/6-002a/firmware_update` lost the race
and the unit was marked not applicable. Silently: a failed condition is not an
error.

In v0.16 and v0.17 it did run, but by luck of the race, not by design. The
safety net had spent a day existing only intermittently.

The repair has two parts. The ordering returns to `After=local-fs.target`,
which now costs nothing either: with the cover requirement gone, the helper has
nothing to wait for. And the wait for the device moves down into the helper,
bounded to 15 s and with a message, instead of living as a systemd condition,
where losing a race leaves no trace.

Verified from a cold boot: `ConditionResult=yes`, the unit starts at 04:57:16
and finishes a second later with "controller already on V37".

## Session 22 — the S Pen's digitizer answers, but does not talk yet

Date: 2026-08-07.

### Where it was hidden

`vendor_boot` does not mention the digitizer once, which is why it was recorded
as "no mainline driver" with no further detail. It is in **Samsung's `dtbo`**,
which nobody had opened: it is extracted from the official firmware's AP
package and contains two overlays, both with the node.

```
wacom@56   compatible = "wacom,w90xx"   bus: qupv3_se3_i2c
  irq = gpio154   pdct = gpio137   fwe = gpio179
  avdd = pm_humu_l13              firmware = wez01_gts9u.bin
```

The bus is our `i2c3`: Samsung numbers the SEs the same as mainline, as the
pogo already demonstrated with `qupv3_se15_i2c` = `i2c15`. `gpio40/41` (the
bus's pins) and `gpio154/137` were free, and `gpi_dma1` already enabled.

### The chip is alive

With `i2c3` enabled and the node in place, `i2cdetect` sees **0x56** answering.
The HID-style query returns a stable register, and decoding it confirms it is
the right device: the register starts at offset **17** and is **big-endian**.

| Field | Read | Samsung's DT |
|---|---|---|
| x_max | `0x4c85` = 19589 | — |
| y_max | `0x7a90` = 31376 | — |
| pressure | `0x0fff` = 4095 | `max_pressure = 0xfff` |
| tilt | `0x3f 0x3f` | `max_tilt = <0x3f 0x3f>` |
| height | `0xff` | `max_height = 0xff` |
| module | `0x02` | `module_ver = 0x02` |
| boot addr | `0x09` | `boot_addr = 0x09` |

The ratio 19589/31376 is 0.6243, exactly the panel's 1848/2960. The decoding is
no coincidence.

### Why mainline's driver does not work, and why it was silent

`wacom_i2c` reads **19 bytes in little-endian** from offsets 3, 5 and 11. This
chip puts its register at 17 and in big-endian, so the query fails. And it
fails **silently**: the probe does `error = wacom_query_device(); if (error)
return error;` without a single `dev_err`. Hence not one line in dmesg, which at
first made it look as though it had not even matched.

Samsung's driver for this part is `wez01.ko`, with `alias:
i2c:wacom_w90xx`. Its strings give two requirements mainline does not meet:

- `fwe gpio is high, change low and reset device` — the flash-enable line has
  to be low.
- `failed to send wacom i2c mode` — there is a **mode command** that starts
  reporting.

Its notifiers enumerate exactly the scope asked for: `PEN_HOVER_IN/OUT`,
`PEN_INSERT/REMOVE`, `PEN_CHARGING_STARTED/FINISHED`.

### What did not work, recorded so it is not repeated

Samsung-style single-byte commands (`0x2a`, `0x31`, `0x32`, `0x33`) **make the
chip stop acknowledging its address**: for a while every transfer returned
`ENXIO`. It recovers on its own, but that is not its protocol. The six-byte
query with a register and an opcode does work, so the interface is
HID-over-I2C style, not the loose-byte one.

It was suspected that suspend cut the panel's rail, which is what powers the
digitizer. **False**: `vreg_l13b_3p0` stayed enabled, the panel was on, and the
only suspend was the boot's recovery one.

### State: it answers, it does not report

With the pen resting on the tablet no event arrives; the reads give a fixed
`0d 03 11` header that never changes. There are three explanations and they
cannot be separated without moving the pen: that an EMR lying **flat** couples
badly with its coil parallel to the grid, that the mode command is missing, or
that FWE is high.

A read-only recorder is left running on the tablet (`/tmp/spen-record.sh` to
`/tmp/spen-capture.log`) which logs any change with a timestamp. As soon as the
owner picks the pen up and holds it perpendicular, the report format is
captured without anyone having to be present.

Nothing that already worked has been touched: zero I²C error lines through the
whole boot, and display, GPU, sensors and the pogo controller all intact.

## Session 23 — the S Pen writes: our own driver, and three defects the owner found

Date: 2026-08-07.

### The report format, decoded from 5,200 frames

With the bus up and a read-only recorder running, moving the pen was enough to
capture the protocol. The fixed `0d 03 11` header seen at rest was not the
report: reports appear only with the pen in range.

```
[0]    state: 0x80 in range · 0x20 side button · 0x10 tip · 0x01 always
[1:2]  X          big endian        [7]   tilt X (signed)
[3:4]  Y          big endian        [8]   tilt Y (signed)
[5:6]  pressure   big endian        [9]   distance
       bit15 marks the field        [10]  sequence counter
```

What makes the decoding safe is not that it fits, but that every field is
validated against something independent: pressure is non-zero **exactly** in
the frames with bit4 and zero in the other 5,059; tilt Y sweeps −63…21, which is
Samsung's tree's ±63; and not one bit is left unexplained.

The side button needed a separate capture, because it was not pressed once in
the first. Two new states appeared, `0xa1` and `0xb1`: bit5.

### Our own driver, and why no mainline one would do

`wacom_i2c` reads 19 little-endian bytes from offsets 3, 5 and 11; this chip
answers big-endian from 17. And it fails **silently**: its probe returns the
query's error without printing anything, so a failure is indistinguishable from
not having matched, which misled us at first. `wacom_w9000` covers only the
W9002 and W9007A. Both are removed from the kernel: keeping them would only
make it ambiguous which one a future failure came from.

### Three defects, all found by using it

The owner tried it and described three symptoms. All three were real and none
was the one I would have looked at first.

**"Touches get ignored" and "it stops picking up the pen when I move fast."**
The same defect: my driver released the pen on any frame without the range bit,
and the chip interleaves status headers and broken reads among the good ones.
Measured: **75 losses in fifteen minutes**. Discarding what is not a pen report
and requiring three consecutive frames before believing a range exit, they
**dropped to zero**.

**"Hover lags, especially when moving fast."** That description was the clue:
it is the signature of a low sampling rate, not a slow driver. The interval
measured 25.0 ms to three figures, which is exactly 40 Hz, which is literally
Samsung's `COM_SAMPLERATE_40`. Sending `0x31` took it to ~440 Hz of **distinct**
positions — 5,385 new X values in 5,637 packets, so they are not repeats. And
the rate **reverts on its own**, which is what `wez01` calls "samplerate state
is %d, need to recovery", so the driver requests it on every entry into range
too.

**"When the screen rotates the pen stays turned 90°."** Here the instinct to
look at the orientation properties was the wrong one: if the base were wrong, it
would fail without rotating too. The comparison with the touchscreen closed it
at a glance: same tree, same properties, but `PROP=2` against `PROP=0`. Without
`INPUT_PROP_DIRECT`, libinput files the pen as an external graphics tablet,
which maps to the whole desktop and **deliberately** does not follow the
output's orientation.

### The probe

The first attempt would not latch: NACK at 3.887 s. The supply is PMIC B's
LDO13, shared with the panel's VCI, and I had decided not to declare it,
reasoning that "the panel keeps it on anyway". True in steady state, false
during boot, which is exactly when the driver probes. Declared and enabled from
the driver, with retries, it latches at 3.97 s with nobody doing anything.

### What remains

Parts 2 and 3 — the pen's docking and charging, and the BLE gestures.
Samsung's `wez01` depends on `stm32_pogo_v3`, `hall_ic_notifier` and
`usb_typec_manager`, and its notifiers name `PEN_INSERT`, `PEN_REMOVE`,
`PEN_CHARGING_STARTED` and `PEN_CHARGING_FINISHED`, so that part goes through
the same place as the cover.

### The pen's rotation was not in the kernel, and the finger gave the clue

With the driver working, the owner found the pen did not follow the screen's
rotation. It took three iterations because **I was looking in the wrong place**.

The methodological error: she described the failure **in portrait**, where what
you see is the driver's transform *plus* the compositor's. I attributed the
whole difference to the device tree, removed `touchscreen-inverted-x` and broke
landscape, which had been right from the start.

The measurement that should have been made from the first moment is in the
native orientation, where the compositor rotates nothing. Two opposite corners
with the pen:

```
top left        ABS_X   7 %   ABS_Y  97 %
bottom right    ABS_X  92 %   ABS_Y   6 %
```

`ABS_X` grows left to right; `ABS_Y` decreases top to bottom. So the original
configuration — invert X and then swap — was correct, and a single corner would
not have been enough to know: it distinguishes badly between "the axis is
inverted" and "I misread which corner that is".

The good clue came from her: **touch rotated correctly in every orientation**.
That rules out the compositor and points at the only thing finger and pen do
not share:

- a **touchscreen** is calibrated against its output, and GNOME applies the
  matrix to it without consulting anything else;
- a **tablet** is *assigned* to an output, and to know which — or whether it
  gets one at all — GNOME asks **libwacom**.

Our digitizer was not in its database. An unknown tablet is assumed external,
and an external tablet **deliberately** does not follow the screen's
orientation: that is right for an Intuos on the desk and exactly wrong when the
tablet *is* the screen.

The `samsung-gts9u-spen.tablet` entry says so in one line,
`IntegratedIn=Display;System`, and libwacom began returning `integration
flags=0x3`. Rebinding the driver was not enough: the compositor reads that
database at start-up, so a reboot was needed. With that, correct in all four
orientations.

Worth retaining that **this part is userspace**: it lives in the device
package, not the kernel, so iterating here costs a minute and forces no
reflash.

## Session 24 — the slow charging was three chained failures

Date: 2026-08-07.

The owner reported the tablet charging very slowly with the official 45 W
charger. Measured at the start: **4.7 W** entering the battery, and 1 % every
seven minutes. The charger advertised 5V/3A, 9V/3A, 15V/3A, 20V/2.25A and **PPS
up to 11 V at 5 A**; we were negotiating 9 V at 1.66 A.

### The SM5440 was there, and so was its driver

Neither the chip nor the driver was missing: `0-0063 -> sm5440`, "direct
charger device ID 0x21", and `sm5440_direct.c` already knew how to request PPS,
refresh it and fall back to the switched charger. The failure was not absence
but behaviour.

### First: I2C during suspend, which took down the whole port

```
i2c i2c-0: Transfer while suspended     ← the SM5440
i2c i2c-4: Transfer while suspended     ← and behind it the PD controller
```

The one-second polling loop ran during system suspend, and the failed transfers
**took the USB-PD contract with them**: the port fell to DCP's 5 V and stayed
there. It was not an exotic race — the panel's cold recovery suspends at ~21 s
of every boot, which is exactly when the charger is negotiating.

It is the same lesson as session 9's with the pogo. There the polling could be
removed; here it cannot, because direct charging needs its loop, so it is
stopped around suspend, returning the battery to the switched charger first.

### Second: there was no closed loop

With PD already stable the next one appeared: the driver computed the target
voltage **once at start-up** and then resent the same one forever. As the
battery rises, the margin over 2×Vbat narrows and the current dies on its own:

```
ibus: 970 → 1047 → 995 → 1050 → 775 → it lets go
```

It now recomputes the target before every refresh, in 20 mV steps, which is the
charger's own resolution.

### Third: REVBLK, and the chip said so itself

It still let go, with contradictory signatures — one stop with 1,085 mA flowing
and another with zero — and no fixed period. Instead of a third conjecture,
instrumentation was added: read the four interrupt latches at the moment of
failure, which is when they are useful because they clear on read.

```
int=0x0/0x0/0x2/0x0   →  INT3 bit 1
```

The bit order came from the strings in Samsung's `sm5440-charger.ko`, in the
binary's order, and **it validates itself**: `VBUSPOK` falls on bit 5, which is
exactly what our driver already defined. Bit 1 is **REVBLK**, reverse-current
blocking.

The cause: at 1.8 A the charger and the cable give up about 400 mV, so of the
nominal 700 mV of margin only ~290 mV were left at the chip — vbus 8291–8332
against a pack at 4003 — and any dip reversed the current. **Raising the current
is what exposed this**: at 1 A the drop was half and there was margin to spare.

Margin at 1,100 mV. Result: from stretches of 22–43 s to **more than 350 s at a
time**, and from 4.7 W to **~10 W** entering the battery, with the capacity
rising 2 % in six minutes.

### On method

Two hypotheses of my own fell along the way — the voltage margin and the
watchdog — both deduced from indirect data. The first was even reverted
deliberately, so as not to mix a demonstrated fix with an inference drawn from
readings that might have been corrupted by the suspend failure; it turned out to
be in the right direction but with the sign flipped, and it was only recovered
once the hardware named the cause.

Adding instrumentation instead of trying one more conjecture is what unstuck
this.

### What remains

The 45 W. The current ceilings are the driver's: a 2,200 mA PPS request and an
1,800 mA input limit. Raising them takes care, because **the cable's drop grows
with the current**, which is precisely what caused the REVBLK: every current
step eats more margin and approaches the edge again.

### The definitive loop: regulate on current, not on voltage

What remained was understanding what limited the current. It was no ceiling of
the driver's: it asked for 2,000 mA, the chip's limiter was at 1,800 and only
1,300 flowed.

The pattern comes out of the data itself. A 2:1 switched-capacitor converter
**behaves like a resistor**: the current is set by the difference between the
input and twice the pack.

| vbus | 2×vbat | ΔV | ibus | ΔV/I |
|---|---|---|---|---|
| 8623 | 8396 | 227 mV | 1321 mA | 0.172 Ω |
| 8455 | 8228 | 227 mV | 1325 mA | 0.171 Ω |
| 8291 | 8006 | 285 mV | 1720 mA | 0.166 Ω |
| 8332 | 8006 | 326 mV | 1805 mA | 0.181 Ω |

Four points, a constant 0.17 Ω. Raising the ceilings would have achieved
nothing because they were never reached; what was needed was to **push the
voltage until the current arrives**.

There is also an unexplained mismatch between what is asked of the charger and
what the chip measures at its input: ~900 mV, and it **grows as the current
falls**, which rules out cable drop. The cable is the original one and works
fine under One UI. It did not have to be solved: regulating on the measured
current, the voltage ADC's absolute accuracy stops mattering. It is recorded as
pending, not as a blocker.

Result with the battery at 28 %: **18.8 W** entering the pack, 4.76 A at
3.96 V, with not one cut-out in five minutes, the chip at 43 °C and the pack at
33.9 °C. The capacity rose from 28 % to 32 % in five minutes.

From 4.7 W to 18.8 W: **four times**, and the rate goes from 1 % every seven
minutes to 1 % every minute and a quarter.

## Session 25 — `iio-sensor-proxy`'s loop was a wait that did not wait

Date: 2026-08-08.

`iio-sensor-proxy` was burning **a whole core permanently**, from boot. The
baseline measured at the start, with 18 minutes of uptime: `cpu-time 00:17:27`
— that is, 96 % of the elapsed time — 199 ticks per 2 s, **94.7 °C** in the
hottest thermal zone with the tablet idle, and the charging current sunk.

The hard part was not finding it, it was that **the daemon doing the spinning
worked**: `AccelerometerOrientation = "normal"`, `HasAccelerometer = true`,
auto-rotation correct. And killing it was no use: the new instance loses the
sensor until the graphical session returns, and spins just the same. The
previous session had already crashed into that, building a recovery service
that neither cured the loop nor kept rotation, and which was withdrawn.

### The `strace` pointed at the caller, not at the event loop

The prior evidence said: 106,941 `ppoll`s in three seconds, 99.64 % of the
process's time, **all** with `{tv_sec=0, tv_nsec=0}` and **all** returning
`0 (Timeout)`. The natural reading is a `GSource` whose `prepare()` declares
itself ready on every pass. That is the wrong reading.

A zero timeout on every turn is not produced by a badly built source: it is
produced by `g_main_context_iteration (ctx, FALSE)`. With `may_block` at
`FALSE`, GLib **forces** the timeout to zero, whatever it is looking at. The
signature accused the caller.

### A `gdb` on the live process closed the case in one trace

There was no gdb on the tablet; installing it cost an `apt-get`. The main
thread:

```
#3 ssc_common_wait_sync_context (ctx=…) at ../src/libssc-common.c:56
#4 ssc_sensor_light_open_sync (…)      at ../src/libssc-sensor-light.c:225
#5 ssc_light_set_polling (…)           at ../src/drv-ssc-light.c:94
#6 handle_method_call (… method_name="ClaimLight" …)
#10 g_main_loop_run
```

Two things at once. First, that libssc 0.4.4 implements its synchronous waits
by spinning the default context without blocking:

```c
while (!ctx->finished) {
        g_main_context_iteration (g_main_context_default (), FALSE);
}
```

That is not waiting, it is spinning. Any request the SSC does not answer pins a
core for as long as the process lives.

Second, that the one not answering was the **light sensor**: Samsung's firmware
discovers the STK31610, accepts the `enable` and never sends the configuration
reply, so `ssc_sensor_light_open_sync()` never finishes. GNOME calls
`ClaimLight` when a session opens, and there it stayed.

And that finally explains the paradox: because the loop iterates the main
context, D-Bus and the accelerometer's flow **were dispatched from inside the
wait**. The daemon spun and worked because spinning was, literally, what made
it work.

### The fix, and why it changes nothing else

`packaging/sensors/fix-ssc-sync-wait-busy-loop.patch`: block in `poll()`. The
callback that ends the wait is dispatched from that same context, so what wakes
the poll is exactly what ends the wait, and the other sources are still
dispatched from the nested iteration as before. Only the thread driving the
context may block on it, hence the `g_main_context_acquire()` and the fallback
on the `GCond` the callback already signalled.

The specific trigger had had a patch since the previous session
(`disable-broken-ssc-light.patch`, which takes `ssc-light` out of the driver
table), but it **had never been installed on the tablet**: the binary running
was older. It was checked by comparing the built `.deb`'s sha256 with
`/usr/libexec/iio-sensor-proxy`'s on the device. The two go together: one
removes the request that is never answered, the other makes sure no unanswered
request ever costs a core again.

### Result, measured after a cold boot

| | before | after |
|---|---|---|
| ticks per 2 s | 199 | 1 |
| accumulated CPU / uptime | 00:17:27 in 1094 s | 00:00:01 in 222 s |
| hottest thermal zone | 94.7 °C | 46.9 °C |
| battery current | −908 mA | +1505 mA |
| `AccelerometerOrientation` | `"normal"` | `"normal"` |

The measurement is of rate, not of an accumulated counter on a freshly born
process: that was precisely the previous session's methodological error.

Retrying the charging current increase to 3,200 mA is still pending; it had
been measured with the bus contaminated by this loop.

## Session 26 — the pen stayed "present", and the pretty explanation was false

Date: 2026-08-08.

The owner reported a failure that predates all of this: while using the pen,
**part of the screen stops responding to the finger**. The detail that made it
interesting is that a drag started in the good area **does** cross the dead
zone; starting inside it does not. Intermittent, and it goes away on reboot.

### What was found, which is real

That detail describes libinput's touch arbitration precisely: with a tool in
proximity it discards **new** contacts inside a rectangle and does not cancel
those already in progress. And the two devices are paired: `udevadm info
/dev/input/event4` gives `LIBINPUT_DEVICE_GROUP=18/0/0:input/ts`, where
`18/0/0` is the bus and IDs of the **pen**.

With that in mind, the digitizer's real state was checked and it was stuck:
`BTN_TOOL_PEN` at 1 with no pen nearby. And it was not that the driver lost an
event: **0 interrupts in 5 s**, `ABS_DISTANCE` frozen, the last valid frame at
distance 235 of 255. The controller goes quiet when the pen leaves, and
`samsung_wacom_w90xx` only knew how to synthesise the exit by counting frames
that no longer arrive. It stays at 1 until the next reboot.

Fixed with a 250 ms `timer_list` that treats silence as a departure. Verified
after flashing: it rises to 1 while drawing and returns to 0 on its own when
the pen is moved away, and stays at 0 through 90 s of sampling.

### What it was not

The story fitted so well that it was nearly closed there. But before accepting
it, the physical check was requested, and with the flag stuck — stuck and
verified stuck — **the owner found no dead zone at all**.

So: the stuck proximity flag is a real defect and it is fixed, but it is **not
the cause of the touch failure**, or at least not sufficient. The failure is
still open.

The lesson is not new but it appeared again wearing another face: an
explanation that predicts the symptom in every detail is still a hypothesis
until it is tested. Here the cheap thing was to ask, and asking knocked it
down.

`work/catch-dead-zone.sh` is left for the next episode. It splits the problem
in two on a single measurement — whether the dead zone's touches reach the
kernel or not — and is validated against a real touch, so that a "0 contacts"
cannot be confused with a broken tool.

### Along the way: two scripts in `work/` that did nothing

`flash-boot-ssh.sh` could not work for two independent reasons. The tablet
**has no `authorized_keys`**, and the script forces key auth with
`BatchMode=yes`. And even if it authenticated, its payload would never run: in
`ssh host "echo PW | sudo -S bash -s" <<'EOF'`, `sudo`'s stdin is `echo`'s
pipe, which carries only the password; `sudo` eats it and `bash -s` gets EOF.
Reproduced with a harmless payload: empty output.

The dangerous part is the combination: it would print `pushed`, then nothing,
and exit with code 0 **without having written the partition**.
`work/restore-tree-and-test.sh` has the same pattern, so whatever was concluded
from running it was concluded from a no-op. Neither is in the published repo;
that was checked.

The replacement, `work/flash-boot-password.sh`, uses a password and runs the
payload from a file by path, keeping the checks that matter: the uploaded
image's sha, requiring the destination to resolve to `/dev/sd*`, and reading
the partition back to compare it.

## Session 27 — 25 W: the ceiling was in what we asked for, not in what we pushed

Date: 2026-08-08.

With the sensor loop gone, charging was worth retrying. Session 24 had left
18.8 W and a note saying that a 3,200 mA target collapsed the bus, that 2,200
was "prudence, not a measured limit", and that it was worth retrying with a low
battery and the charger freshly plugged in. All three conditions were met:
battery at 6 %, the official 45 W charger just connected, and nothing pinning a
core.

First result, for free: **19.4–20.9 W** without touching anything.
`iio-sensor-proxy`'s loop was worth almost two watts.

### The sweep that moved nothing

To avoid spending a compile-flash-reboot cycle per step,
`SM5440_TARGET_IBUS_MA` was exposed as a writable parameter. The sweep came out
flat: `ibus` 2,587, 2,596, 2,600 mA with the target at 2,200, 2,600 and 2,800. A
loop that does not react to its setpoint is saturated somewhere else.

Forcing it to 3,400, the request did rise — `in0_input` to 9,860 mV — but
**voltage and current fell together**, down to 1,867 mA. That is not a weak
loop: it is a source folding back because it is already at its limit.

An interpretation of my own had to be withdrawn here: the difference between
requested and measured looked like 0.55 Ω of series resistance, but it **grows
as the current falls**, which is the opposite of what a resistance does. The
driver itself already warned that the chip's `vbus` ADC drifts that way.

### What it actually was

```c
target_ma = min(target_ma, 3000);
```

The PPS contract's current, fixed. `dmesg` had been saying so since boot:
`direct charge started: PPS 8760 mV/3000 mA`. The adapter advertises 5 A, TCPM
adds no ceiling of its own, and the floor the loop was asking for already wanted
~4.1 A. We asked for 3 A and were given 2.9.

Two details were needed for the equivalent knob to be any use: the
`max(SM5440_INITIAL_PPS_MA, …)` in front of it would have left the result at
3,000 anyway, and the periodic refresh is the only place that resends the
current, so it has to be recomputed there for the change to take effect on the
live session.

### Result

| Contract | Pack | ibus | vbus | Die |
|---|---|---|---|---|
| 3000 mA | 21.4 W | 2601 mA | 8556 mV | 45.5 °C |
| 3200 mA | 22.8 W | 2864 mA | 8611 mV | 46.5 °C |
| **3400 mA** | **25.0 W** | 2960 mA | 8652 mV | 48.5 °C |
| 3600 mA | 24.2 W | 3141 mA | 8801 mV | 54.0 °C |
| 3800 mA | 24.2 W | 3128 mA | 8780 mV | 55.0 °C |
| 4000 mA | 24.2 W | 3167 mA | 8835 mV | 55.0 °C |

Above 3,400 `ibus` rises and the power does not: loss in the pump, paid for
with six degrees of die. A five-minute soak at 3,400: **25.2–25.5 W** flat, die
49.5 °C, pack 36.4 °C, from 45 % to 49 % battery.

From 18.8 to 25.2 W. Whether a lower battery gives more remains to be seen;
that condition was spent charging while compiling.

### On stopping in time

Half way through, the conclusion was reached that going above 3 A required
interrogating the cable over SOP', and that without `port0-cable` or VCONN that
was not legitimate. Half of that conclusion was wrong: as a *sink* and *UFP*,
it is the charger that interrogates the cable, not the tablet, so the absence
of those nodes is normal in this role and proves nothing about the cable.

What does stand is the substance, and that is why the knob keeps its bands and
the warning in its comment: the one rated 5 A is *this* cable, and above 3 A
what is at risk is the connector, not the silicon.

## Session 28 — four sensors, four photographs and real light

Date: 2026-08-08.

The criterion was set before starting: identifying over I²C or creating
`/dev/video0` closed nothing. Every lens had to deliver a recognisable physical
frame and the flash had to illuminate the scene, not merely accept a value in
sysfs.

### First, the flash

The stock block called `pm8350c-flash-led` is in SID 1's PM8550. In mainline it
corresponds to `qcom,spmi-flash-led`. Channels 0 and 1 are connected to the two
rear emitters and Samsung drives them together; the DT exposes them as a single
white LED with `led-sources = <1>, <2>` and conservative limits.

A held torch was tried first and then a strobe synchronised with the V4L2 flash
class. Both routes lit physically and changed the illumination and the
reflections on the desk:

- [capture with strobe](../work/resultado-flash.jpg);
- [capture with torch](../work/resultado-linterna.jpg).

### What sensors there actually were

The public stock DTS does not contain the modules: Samsung delivers them as
CamX Parameter Parser V3 blobs. The real inventory turned out to be three
HI1337s — main rear, main front and wide front — and one HI847, the wide rear.

Upstream's HI847 bound only through ACPI and assumed platform-managed power. DT
and its VDDIO/enable/reset/MCLK sequence were added. For the HI1337 a small
V4L2 driver specific to the X910 was written. A local extractor decoded from
the blobs the exact global table of 1,476 registers and the three exact modes;
the generated header lives in `kernel/drivers/` so the build is reproducible
without depending on the stock tree in `work/`.

The intermediate failures that changed the result were concrete:

- the main front's `slaveAddress = 0x40` was an eight-bit address; Linux needs
  `0x20`;
- CCI1 master 1 uses the AON GPIO208/209 pair, not the ordinary CCI pinmux;
- PM8550VS-C L1 and PM8550B L11 need the representable 1,104 V step;
- both front cameras share MCLK4/GPIO104, so only the main one can own its
  pinctrl;
- the module/reset GPIOs cannot stay claimed for the subdevice's whole life:
  they are taken on power-up and released on power-down.

In the end all four physical IDs answered:

```
rear-main       1-0021  model=0x1337 vendor=0x2000
front-main      3-0020  model=0x1337 vendor=0x2000
front-ultrawide 9-0021  model=0x1337 vendor=0x2000
rear-ultrawide  0-0021  HI847
```

### Four captures, not four enumerations

Each sensor was driven alone through `msm_csiphyN → msm_csid0 →
msm_vfe0_rdi0 → /dev/video0`. Five consecutive frames from each route arrived
at around 30 fps. The first frame saved and delivered gave:

| Lens | subdev / CSIPHY | Frame | RAW10 SHA-256 |
|---|---|---|---|
| main rear | `/dev/v4l-subdev32` / 1 | 4128×3096, 16,000,128 B | `104333e0d777448cb3857343a58bf6abbdcf1d4effefee70f7382f77d771ac43` |
| wide rear | `/dev/v4l-subdev33` / 2 | 3264×2448, 9,987,840 B | `c72f2fb32c1f21d541b62f85b5cacbc86f1738e5405010864979738987ac4997` |
| main front | `/dev/v4l-subdev31` / 4 | 3408×2556, 10,919,232 B | `876575b51473f80df986bb6b899a40b1bc93995f6de1baec09127f985fbd7a96` |
| wide front | `/dev/v4l-subdev30` / 5 | 4000×3000, 15,024,000 B | `4978876d3572e11855ee2fa9badc7f89f7cd3ba230d76e8a9d10554ec9c4176a` |

The tests were repeated after a later boot: all four gave five frames again,
with no errors and with new hashes — so they were not frozen buffers. Manual
Bayer development produced the evidence:

- [main rear](../work/resultado-trasera-principal.jpg);
- [wide rear](../work/resultado-trasera-angular.jpg);
- [main front](../work/resultado-frontal-principal.jpg);
- [wide front](../work/resultado-frontal-angular.jpg).

The desk/fan and the ceiling/lamp match the references and the wide lenses'
field is clearly larger. The main rear is out of focus: its actuator's driver
is missing. The colour is a manual Bayer conversion. It is delivered as such
because it is honest evidence of the layer that works; this is not being called
a finished desktop camera.

### An audio regression and an A/B comparison that came expensive

Two boots gave an enumerated but silent microphone. Both had the APM not
answering `APM_CMD_GET_SPF_STATE` and the LPASS pinctrl rejected with
`-EACCES`. To tell a regression from a race, an earlier `boot`/`vendor_boot`
was tried temporarily, with a backup, a write and a read-back. It was a bad
comparison: the old kernel did not match the installed ath12k modules and the
tablet was left with no Wi-Fi. The owner left it in TWRP; over ADB only
`/dev/sda21` and `/dev/sda24` were restored, verifying the hashes `579bf1ec…`
and `9293c93b…`. No other partition was touched.

A complete boot from TWRP settled the question: with the same camera image,
PipeWire recorded 729,285 non-zero samples before using CAMSS and 733,706 after
capturing with all four sensors. The cameras do not silence the DMICs; the
APM's failure is a pre-existing boot race that must be measured by its logs,
not inferred from a single zero WAV.

### The final clean build, the keyboard and a closed regression

The final build was made with `KERNEL_CLEAN=1` from the pinned 7.2-rc3
checkout. It produced `boot.img` SHA-256
`f24fce56c9cbb816f15c61f907369ccc5d0fdae516dcfd219e2f4fdb920503b6` and
`vendor_boot.img`
`9293c93b0ab1a1d0ad90353ec50969a120046aa2835aa2a05a28528c3ca3702d`. Both were
written and read back in full; the signed ath12k modules were installed from
that same compilation.

Booting from TWRP revealed a real side regression: the keyboard's STM32 had
gone back to V34 and the automatic restorer could not find it. CAMSS adds CCI
adapters and shifted the pogo's Linux numbering from `6-002a` to `11-002a`; the
helper assumed the first number. It now locates `*-002a` under the
`samsung-gts9u-stm32-pogo` driver, which is the stable identity. It restored
and read back the 52,132 official bytes, confirmed `00370037`, received model
`0xd6` and created `Book Cover Keyboard Slim (EF-DX920)` again. A later reboot
kept V37 and the service concluded without writing.

On the clean build, two passes of five frames per sensor were made, always at
around 30 fps and with different hashes. The twenty-frame strobe and the torch
at two intensities were also repeated, both ending switched off. The
consolidated regression left Wi-Fi with 3/3 replies, Bluetooth active, and the
keyboard, Wacom, Goodix, DSI, accelerometer, compass and audio all present. The
microphone gave 756,694 non-zero samples before CAMSS and 757,065 after the
four captures; a third consolidated take gave 455,636. Another boot of the same
image fell into the APM race again and produced zeros, confirming the problem
remains intermittent and predates any camera use. The only failed service was
the pre-existing `lxc-net`. The battery was at 98 %, so the 5 V/3 A PD contract
was verified, not a 25 W thermal session.

## Session 29 — processed colour, and cameras for applications

Date: 2026-08-09.

The next criterion was higher than the previous session's: the photographs
could no longer be a manual Bayer development. All four cameras had to converge
in exposure and white balance, open without root, and present themselves to the
desktop as repeatable sources.

`libcamera` was pinned at `62d4bfc` (0.7.2 + 53 commits) and only the `simple`
pipeline, its software ISP, `cam` and the GStreamer plugin were compiled. The
HI1337 and HI847 received helpers with the real gain `(code + 16) / 16` and
RAW10's pedestal of 64. The common tuning starts from red/blue gains `[1, 4]`,
uses grey-world AWB, AE and a conservative CCM. This removed the channel cast
of the first conversion and let walls, ceiling, metal, whites and the red
object keep coherent colour relationships.

Noble's PipeWire needed three bounded backports. The 1.0.5 mapper did not
understand libcamera 0.7's `string_view`, treated the `ColourGains` array as a
scalar and aborted, and confused DRM RGB names with in-memory byte order. That
last failure was the direct cause of the magenta image. The corrected SPA was
packaged without replacing the rest of PipeWire. A udev rule hands
`/dev/udmabuf` to the `video` group, so GStreamer and the software ISP run as
`ubuntu`, not as root.

The final physical tests were:

- 150/150 RGB frames from each of the four cameras, with final images
  [wide front](../work/resultado-frontal-angular.jpg),
  [main front](../work/resultado-frontal-principal.jpg),
  [main rear](../work/resultado-trasera-principal.jpg) and
  [wide rear](../work/resultado-trasera-angular.jpg);
- 99 frames through PipeWire and a [capture of that route](../work/resultado-pipewire-app.jpg);
- 30 frames negotiated on each PipeWire source and another 30 on reopening the
  wide front camera; PipeWire, `pipewire-pulse` and WirePlumber all stayed
  active;
- GNOME Camera (`Snapshot` 46.2) opened in a graphical session, with its stream
  shown by WirePlumber as `active`;
- the torch at levels 32 and 128, the strobe through a 20-frame sequence, and a
  final check of `strobe=0`, `torch=0`, with no latent fault.

The installed packages are `libcamera-gts9u 0.7.2+53.g62d4bfc-gts9u1`,
`libspa-0.2-libcamera-gts9u 1.0.5-gts9u1` and `ubuntu-gts9u-device 2.0`. The
final clean build produced `boot.img`
`d4323b9acd26a8b2179af1fda58536a1d8e622cde787a86406293e71d47b3eba` and
`vendor_boot.img`
`4441ae918f878a9592b2e5c863833d20dfefb44e50bb29645de97aa1f33eef5d`; both were
written and read back with those same hashes.

The last correction was metadata, not image: the DT value `2` means an external
camera, not a rear one. Both rear cameras moved to `orientation = <1>` and the
DTB had to arrive through `vendor_boot`. The live DT, the V4L2 controls, `cam
--list` and PipeWire now agree: two `Internal/Built-in Front Camera` and two
`Internal/Built-in Back Camera`.

After rebooting, Wi-Fi answered 3/3, the keyboard enumerated again as
`Book Cover Keyboard Slim (EF-DX920)` with firmware V37, Bluetooth was on,
Wacom/Goodix present, DSI connected, the accelerometer and compass delivering
data, and the microphone produced 438,846 non-zero samples. The only failed
service was still `lxc-net`, pre-existing and unrelated to cameras. The main
rear camera's focus actuator remains open; colour, exposure and the application
path are no longer the blocker.

## Session 30 — a desktop torch, a media restart and orientation

Date: 2026-08-09.

The flash already lit physically, but it was not yet an everyday feature.
Package `ubuntu-gts9u-device 2.1` adds a **Flashlight** tile to GNOME 46's
quick settings, an icon of its own and the `gts9u-flashlight` command. Udev
hands `video` only `brightness` with mode 0660; the strobe path stays reserved
for root. Level 32, level 128, toggle, rejecting 999 and switching off before
suspend were all tested as the `ubuntu` user. On every close the LED ended at
zero. The user confirmed the tile works in the UI.

The tablet was also rebooted because no application would play video and the
camera had stopped advancing. Before the reboot there were active services, but
also several historical instances and `spa.libcamera: can't add buffer ...:
File exists` errors. After booting with boot ID
`58ff3ce2-64c6-48f8-827a-ee52ccaa5e7c`, the video path processed 120 RAW frames
and encoded/decoded 60 VP9 frames. After cleaning the PipeWire session once,
the four camera sources gave 30 frames each and the front one reopened for
another 30; all three media services stayed active.

Orientation was checked against a known scene. Each source produced 150 JPEGs
through PipeWire and the last one was reviewed: both front cameras show the
person upright and the wall's line horizontal; the wide rear shows the 50 note
upright. The main rear was again too far out of focus at that distance to
extract an orientation from. The V4L2 controls agree with the mounting — fronts
270°, rears 90° — and PipeWire keeps two `front` and two `back` locations,
without publishing an additional transform. A correct rotation was not changed
on the basis of the single unevaluable image.

## Session 31 — stability across applications, and DW9808 autofocus

Date: 2026-08-09.

The closing criterion became real use of the four cameras in GNOME Camera, a
browser and OBS, with repeated switching and no black screens. PipeWire
received four further fixes: explicit buffer reuse in the requests, not closing
descriptors borrowed from PipeWire, processing completions on the data loop,
and suppressing a redundant transform. The regression alternated the four
sources in both directions: 16 captures of 45 frames, 720 frames in total, zero
failures, zero `EEXIST`, zero invalid descriptors and the same PipeWire PID at
the end.

GNOME Camera completed two cycles and saved eight photographs; the physical
images confirmed all four come out upright. Chrome enumerated four distinct
WebRTC identifiers — two front and two rear — and opened each at
1280×720/30 fps with no errors. OBS used four GStreamer/PipeWire scenes,
produced four correct captures and kept PipeWire stable. The plugin is pinned
at commit `a936d45` and packaged as `obs-gstreamer-gts9u`.

Focus was tackled next. The stock CamX module identified the `dw9808` and gave
its exact sequence; an I²C sweep from 0 to 1023 demonstrated movement and a
change of plane before any driver was written. The kernel now includes a V4L2
lens subdevice, shares GPIO15 safely with the HI1337's VIO, and links the lens
through `lens-focus`. The `focus_absolute` control answered live across its
whole range.

libcamera's software IPA received contrast statistics, a coarse sweep, local
refinement and continuous tracking. The first attempt mixed the sensor's and
the lens's V4L2 maps; WirePlumber correctly aborted because their identifiers
belong to different subdevices. It was replaced with a dedicated
`setLensPosition` IPC channel, the package reinstalled, and WirePlumber
published exactly four cameras again. A 41-frame capture with the flash
recorded the lens's real travel and ended with "Plano Esquemático de la Red"
legible. The later GNOME Camera photographs and OBS captures confirmed the
focus through the full application path.

The final installed packages are `libcamera-gts9u 0.7.2+53.g62d4bfc-gts9u2` and
`libspa-0.2-libcamera-gts9u 1.0.5-gts9u6`. The final installed artefacts'
SHA-256 are
`8078a33e33081568dee2406a26fe2b54b26047f9bc12a2bc4171748fab9c2f7e` and
`f8f938d4e38e4d5dfecdf7191854ab98990883d4b702602dadd8309f9088ea9a`.
`obs-gstreamer-gts9u 0.4.0+git20260809.a936d45-gts9u1` and
`ubuntu-gts9u-device 2.2` were also installed, with package SHA-256
`8b3ae0e64d5ce98aeaa83d92a51ec99c8537bf1a50516ffa1b69bbdba07267cc` and
`2131a585a22d93f9d26cc97571885dd07f2e4bebe2ce0c858661198e60095935`. On closing
the tests, Snapshot, Chrome and OBS were closed, the flash `off`,
PipeWire/PipeWire Pulse/WirePlumber active and the four libcamera sources
published. `lxc-net` was still the only failed service, pre-existing and
unrelated to this work.

## Session 32 — system V4L2 cameras, full field and a stable OBS

Date: 2026-08-09.

OBS's GStreamer scenes proved the pixels arrived, but did not solve the system
interface: browsers and the "Video Capture Device (V4L2)" source could not
discover the four cameras on a clean installation. That integration was
replaced with four `v4l2loopback` nodes, `/dev/video20`–`23`, with stable GTS9U
names. The module is pinned at `9ef83fb9`, receives two event/queue fixes, is
compiled against the exact kernel and signed with its build key. Four system
`v4l2-relayd` processes connect those nodes on demand to PipeWire's libcamera
sources.

CAMSS allows only one active physical input. The relay therefore serialises the
four inputs with a shared lock, groups negotiation closes over 500 ms and
destroys the input between real clients. A first 750 ms guard passed one round
but PipeWire ended in `SIGSEGV` as changes accumulated: the log showed two
almost simultaneous configurations and CAMSS callbacks still in flight. The
final two-second guard is applied to the error path as well. Two consecutive
rounds then completed 24 openings, ten frames each, with the same PipeWire and
service PIDs and four relays alive.

Chrome, without enabling any special camera backend, enumerated exactly
`GTS9U-Front-Ultra-Wide`, `GTS9U-Front-Main`, `GTS9U-Rear-Main` and
`GTS9U-Rear-Ultra-Wide`; it opened all four over WebRTC at 1280×720/30 fps. OBS
first reproduced the crash the owner reported. Its RAW CAMSS nodes appeared
before the processed cameras and, on top of that, Noble's plugin freed an
uninitialised pointer when the V4L `by-id`/`by-path` directories were missing.
`obs-v4l2-gts9u` fixes both cases and hides only the `Qualcomm Camera
Subsystem` cards. The standard dialog showed only the four GTS9U entries,
opened each and stayed stable; no OBS scene or configuration is installed.

The sensation of zoom had another reproducible cause. The software ISP scaled
to cover the destination and cropped the sides when the aspect ratio changed.
`libcamera-gts9u 0.7.2+53.g62d4bfc-gts9u3` now uses a *contain* fit, centred
and with a black background: the 1280×960 V4L2 output keeps the full 4:3 sensor
and 16:9 clients decide whether to add bars or crop. The physical captures
confirmed the much larger field of both ultra-wides; the main rear is still
optically narrower.

The clean integration lives in `v4l2-relayd-gts9u 0.1.2-gts9u3`,
`obs-v4l2-gts9u 30.0.2+dfsg-3build1-gts9u1` and `ubuntu-gts9u-device 2.5`.
`build-ubuntu-rootfs.sh` includes those three packages and their input
fingerprint, and no longer includes `obs-gstreamer-gts9u`. On closing the
validation, Chrome and OBS were closed, the flash was `off`, and PipeWire and
the four relays were still active.

## Session 33 — persistence after a reboot, and a colour review

Date: 2026-08-09.

The first cold-boot test uncovered a real failure hidden by the graphical
session. `ubuntu` had `Linger=no`: SSH raised a temporary PipeWire, but on
exiting it terminated `user@1000` and the system relays were left connected to
the dead server. All four names were still present even though the captures
were black. `ubuntu-gts9u-device 2.6` enables lingering both on existing
installations and when building a clean root filesystem. The launcher also
waits for PipeWire's live `MainPID` and restarts the four relays if it changes
or if one of them exits. The recovery was provoked twice; in both cases
PipeWire changed, the service was recreated and exactly four working relays
were left.

Three real reboots were made, with different `boot_id`s. The last one started
the exact 2.6 package, kept PipeWire stable between separate SSH connections,
published `/dev/video20`–`23` and their four aliases, kept Wi-Fi, Bluetooth,
the pogo keyboard and the Wacom, and left the flash off. A capture timed after
the boot produced real PNGs of 1.08–1.43 MB on all four nodes. From a normal
GNOME session, Chrome enumerated exactly the four cameras and opened each at
1280×720/30; OBS's standard selector showed only those four, started capture
from `/dev/video20` and stayed alive. The automatic login used only for that
test was removed and the original GDM configuration restored.

The unlit room did not allow a complete photometric calibration. On the front
cameras, lit only by the monitor, the RGB means were close to neutral; the rear
ones, tested with the torch, showed a moderate green bias over grey areas. As
the framing was dominated by a card and red/brown fabrics, grey-world AWB can
explain the bias and a global CCM would not be safe. The current tuning is kept
until a grey/colour chart under several lighting temperatures is available. On
closing, Chrome and OBS were closed, the flash `off`, the original graphical
configuration restored and the four relays active.

---

## Session 34 — the root moves to the internal UFS, in a single ZIP

Date: 2026-08-10. The physical tablet was not touched: this session produces
the artefact the owner will test.

### Context

Up to v0.17 the installation had two steps and two artefacts: writing a
two-partition image to a microSD by hand, and then flashing a ZIP that wrote
the boot images and applied the firmware overlay onto the card. The card was
also a single point of failure and the I/O bottleneck.

The brief was to install on the UFS **without creating, deleting or modifying
partitions**, and to deliver a single flashable `.zip`.

### What was reviewed before deciding

The reference Ubuntu Touch port (`../port`) solves the same thing by writing
the whole of `super`: it rebuilds its logical partitions with `lpmake` and puts
the root filesystem in there as `system`. That is exactly what was not wanted
here, and `super` is 11.2 GiB anyway, which is not enough for a desktop.

Inspecting the device (`port/device-inspection/partitions.txt`) gave the
answer: `sda34`, Android's `userdata`, is 984,360,924 KiB, that is 939 GiB. It
already exists. Reusing it touches no GPT.

### What was done

- `scripts/build-ufs-image.sh` builds the root as a **bare filesystem**, with
  no partition table: `/boot` inside, the firmware and module overlay already
  integrated, the `UBTS9U_UFS` label, a rewritten `fstab`, `-E resize=` so it
  can grow online to 1 TiB, and `e2fsck -fp` at the end so a dirty filesystem
  is never shipped.
- Generating the initramfs moves out into `scripts/make-initramfs.sh`, shared
  by both images; having two copies of that check was asking for them to
  diverge exactly where the symptom is a black screen.
- The TWRP installer writes the root into `userdata` and **verifies it by
  reading it back** and comparing SHA-256, before touching the boot images. It
  aborts if the ZIP is on the destination itself, if `userdata` is smaller than
  the image, or if the label read back does not match.
- `cmdline.txt` moves to `root=LABEL=UBTS9U_UFS`, which also disambiguates
  against an old microSD.
- `ubuntu-gts9u-grow-rootfs` tells the two cases apart: on microSD it extends
  the partition and the filesystem; on UFS, **only** `resize2fs`.
- `validate-bundle.sh` changes the guarantee it checks: `userdata` may now be
  named, but no `mkfs`, `parted`, `sgdisk`, `sfdisk`, `fdisk`, `partx` or
  `wipefs` may appear in the installer.
- `build-release.sh` stops producing the `.img.xz` image: the release is the
  ZIP.

### A failure the static validation caught

The first build failed in `validate-bundle.sh` with "installer code references
a partition it must never write". It was not a real write error: it was a
`ui_print` that said the word `super` while explaining what is **not** touched.
The check looks at code with comments stripped, and a visible string is not a
comment. The message was reworded. The check is correct and was left as it is:
it prefers a false positive to letting a `dd` to `super` through.

### The artefact's state

v0.18: a single ZIP of a 3.1 GiB root image plus the five boot images, with
every static check green. **Not yet booted on the tablet**; until it boots, the
README's storage row and `hardware-status.md`'s UFS row say pending.

### Cameras

The kernel was rebuilt to include the `v4l2loopback` patch 3 that was in the
working tree, and the root carries the current set of camera packages
(`libcamera-gts9u` gts9u5, SPA gts9u10, `v4l2-relayd` gts9u12, device 2.17).
The work on switching between cameras is ongoing and uncommitted; the
documentation now says what actually happens: each camera and the flash work,
and switching from one to another still fails.

---

## Session 35 — the first real flash of v0.18, and why it aborted

Date: 2026-08-10. Two attempts on the tablet, neither of which wrote anything.

### Attempt 1, from internal storage

`Installing zip file '/sdcard/ubuntu-24.04-gts9uwifi-v0.18-sm-x910-twrp.zip'` →
`ERROR: the ZIP is stored on the installation target`.

That is the protection working: `/sdcard` is `/data/media`, inside the
partition the installer is about to overwrite. There is nothing to fix here,
except that the README and `boot-strategy.md` already said so and it is worth
reading them first.
### Attempt 2, by sideload

`Installing zip file '/sideload/package.zip'` → `ERROR: malformed rootfs image
size`, with the ZIP intact and verified.

The cause is that TWRP runs `update-binary` with **mksh**, whose arithmetic is
32-bit even though the binary is 64-bit aarch64. The image is 3,271,557,120
bytes, which exceeds 2³¹ and is read as negative, so `[ "$ROOTFS_SIZE" -gt 0 ]`
came out false. The earlier checks passed because every previous size
(100,663,296 and smaller) fits in 32 bits.

It was confirmed by extracting `TWRP-gts9u-V2.img`'s ramdisk: `/sbin/sh` →
`/system/bin/sh`, an aarch64 ELF, and its strings include "Use 'exit' to leave
mksh". The same ramdisk confirmed that `wc`, `dd`, `unzip`, `sha256sum`,
`tune2fs`, `e2fsck`, `blockdev`, `cut` and `resize2fs` are all available.

### What was changed

- The `ROOTFS-IMAGE` manifest now publishes a third field with the size in MiB,
  and the installer reads that one. The bytes are kept for people and for
  `validate-bundle.sh`.
- The capacity check no longer compares `userdata`'s `blockdev --getsize64`
  (~1.008 × 10¹², impossible in that shell): it reads with `dd` the last MiB
  the image will occupy and checks it returns 1,048,576 bytes.
- `validate-bundle.sh` rejects any literal of ten digits or more in the
  installer's code.
- The loopback test bench moves to running under `mksh` instead of `bash`. That
  is the real methodological failure: the bench had gone green immediately
  before the flash, because `bash` counts in 64 bits.

### State

v0.18 repackaged. The root image does not change; only the installer and the
manifest. It still has not booted on the tablet.

---

## Session 36 — the third attempt, and the first session with the tablet reachable over adb

Date: 2026-08-10. The tablet was left in TWRP with `adb` available, so for the
first time the assumptions about the installer's environment could be checked
on the device instead of deduced.

### The failure

`ERROR: the ZIP carries both a rootfs image and an overlay`, on a ZIP that
carries no overlay.

Confirmed on the device: TWRP's `unzip` is `ziptool`, and `unzip -l ZIP MEMBER`
exits 0 even when the member does not exist. Every membership check in the
installer was always true. The previous session's failure had masked this one:
it aborted before reaching here.

They were replaced with a listing read once and queried with `awk` on the last
field. Verified against a real ZIP on the device itself.

### What did work

Session 35's unmount fix was seen working in the real log:

```
Unmounting /data before writing Ubuntu.
Unmounting /sdcard before writing Ubuntu.
```

`/data` and `/sdcard` are two mount points of the same `sda34`, and both were
unmounted. With the previous code neither would have been.

### Measured on the device

| Check | Result |
|---|---|
| `echo $KSH_VERSION` | `@(#)MIRBSD KSH R59 2020/05/16 Android` |
| `echo $((3271557120))` | `-1023410176`, confirming the 32-bit arithmetic |
| `readlink -f /dev/block/by-name/userdata` | `/dev/block/sda34` |
| `userdata`'s `blockdev --getsize64` | `1007985586176` |
| the `dd bs=1M skip=3119 count=1` probe on `userdata` | `1048576` bytes |
| the same probe on a small partition | 38 bytes, i.e. it rejects correctly |
| `unzip -l ZIP DOES-NOT-EXIST` | exits 0 |

### A correction to the documentation

`/external_sd` on this tablet is **224 MiB**: it is the microSD's
`UBTS9U_BOOT` partition from v0.17, because TWRP mounts the card's first
partition. A 992 MB ZIP does not fit there. Saying "copy it to a microSD" with
no further detail was bad advice: the practicable route is **sideload** or a
USB-OTG drive.

---

## Session 37 — it boots from the UFS

Date: 2026-08-10. The first real boot with the root on internal storage.

The ZIP with the three fixes (arithmetic in MiB, unmounting by resolved device,
and ZIP membership checked against the listing) was flashed by sideload and the
tablet booted from `userdata`. The README's storage row and
`hardware-status.md`'s two rows move to confirmed.

Before flashing, it was verified on the device itself, writing nothing, that
ziptool's `unzip -p` extracts the 3.1 GB member with the manifest's exact
SHA-256. That was the last link in the chain with no hardware proof.

### A pending item that appears on use: the whole of VLC in the image

`obs-v4l2-gts9u` — the patched V4L2 plugin the cameras were validated with —
declares `Depends: obs-studio`, and `obs-plugins` **recommends** `vlc`. The
base root filesystem is built with mmdebstrap without `Recommends`, which is
exactly why `snapd`, `yaru-theme-icon` and `gnome-keyring` had to be declared
by hand; but the hook that installs the local packages uses a plain `apt-get
install -y`, and there `Recommends` are honoured. Through that gap came 77 MiB
of VLC, of which 41 MiB is `vlc-l10n`.

OBS (21 MiB) is intentional in practice: it is our own plugin's dependency and
the tool the four cameras were checked with. VLC is not.

---

## Session 38 — the account stops shipping in the image

Date: 2026-08-10. A clean build with a first-boot wizard, to test on the
device.

### Why

The image carried an `ubuntu` user created at build time with `GTS9U_PW`'s
password. Beyond inheriting somebody else's account, that variable made a clean
build **impossible** for anyone who did not know it; v0.18 had to reuse
v0.17's root filesystem for exactly that reason.

### Checked before deciding

- `gnome-initial-setup` 46.3 is in noble arm64, drags in only `libsysmetrics1`,
  and keeps `gis-account-page.ui` and `gis-password-page.ui`: its
  account-creation page still exists.
- `ubuntu-desktop-bootstrap`, the Flutter wizard of the Raspberry Pi images, is
  **not** in noble's archive.
- `oem-config`/`ubiquity` are (24.04.5), but they are the heavy, X-based route;
  the native one for GNOME Wayland 46 is `gnome-initial-setup`.
- Nothing in the image sets `enabled-extensions`: Ubuntu's extensions come from
  gnome-shell's session mode, so an override can add ours without displacing
  any.

### What had to be unhooked from the name `ubuntu`

Four places in the build and two in the package. The one that nearly got away:
`ubuntu-gts9u-camera-relays.service` carried fixed `User=ubuntu`,
`Group=ubuntu` and `XDG_RUNTIME_DIR=/run/user/1000`. Without that account the
service does not even start, so the OOBE image would have shipped **with no
cameras**, which is precisely one of the things to verify. It was caught while
reviewing the rest of the package, not by testing it.

The solution: `ubuntu-gts9u-desktop-user.service` runs on every boot, applies
lingering to every UID between `UID_MIN` and `UID_MAX`, and writes a drop-in
into `/run` with the real owner's `User=`, `XDG_RUNTIME_DIR` and ordering
against their `user@UID.service`. The relay service depends on it and carries a
condition on that drop-in, so that a machine whose wizard has not been
completed does not enter a restart loop every two seconds.

The flashlight extension moves to a gschema override, and the SSH key, if
given, goes into `/etc/skel`.

### And along the way, VLC

The local-package hook's `apt-get install -y` was the only place in the build
that honours `Recommends`. VLC is purged after installing, rather than using
`--no-install-recommends`, which would also leave out `obs-plugins`.

---

## Session 39 — the torch, languages, and an upgrade that keeps the data

Date: 2026-08-10. v0.19 booted and the OOBE worked; the owner created her
account and reported two failures.

### The torch would not light

The tile appeared, but pressing it switched itself off and no light came out.

Mounting the root from TWRP showed the cause unambiguously: the account the
wizard created, `agcar`, is in `adm sudo plugdev users`. This port's udev rule
does `chgrp video` and `chmod 0660` on the LED's `brightness`, so it had no
write permission. The account the build used to create was in `video`, along
with `render`, `input`, `audio`, `dialout`, `cdrom` and `netdev`.

`ubuntu-gts9u-desktop-user` now applies them, and a `.path` unit on
`/etc/passwd` is added so it happens on the same boot in which the wizard
creates the account, not the next one.

Verified in the chroot against an account created with the wizard's exact
groups: it goes from `adm sudo plugdev users` to including all seven that were
missing.

### Only Spanish was offered

`/etc/locale.gen` had one line. The wizard offers the languages the system has
generated, so it offered one. With `locales-all` the available UTF-8 locales go
from 22 to 152, without running `locale-gen` under emulation.

### And what did work

v0.19's journal confirms the user service did its job: `no desktop user yet;
the first-boot wizard has not run` on the first boot, and afterwards `linger
enabled for agcar` and `camera relays bound to agcar (uid 1000)`.

### The upgrade without losing data

It was checked on the device that TWRP has no `rsync` and that its `tar` does
not support xattrs, so a file-by-file copy from recovery would lose the
binaries' capabilities. The upgrade moves to `gts9u-upgrade`, on the booted
system. Untested so far.

---

## Session 40 — the torch, again, and why the previous fix never arrived

Date: 2026-08-11.

### v0.20's fix was never applied

The account the wizard created, `arturo`, was still not in `video`, and the
journal had only `no desktop user yet`: the service did not run again after the
account was created.

The cause is the `.path` unit. `PathChanged=/etc/passwd` looked like the
obvious choice and does not work: `useradd` and accountsservice write a
temporary file and rename it over the top, so the inode systemd is watching is
**replaced**, not modified, and the event never arrives. It is changed to
`PathExistsGlob=/home/*`, which observes the same fact from where there is an
event.

### And even if it had arrived, it would not have been enough

A process's supplementary groups are fixed when the session starts, and the
wizard enters the session at the very moment it creates the account. Adding it
to `video` there is too late for that session.

That is why the real fix does not go through groups:
`ubuntu-gts9u-desktop-user` `chown`s the LED's `brightness` to its owner.
Ownership belongs to the file, not to the session, so there is no window. The
group is still applied for everything else, and the udev helper puts the owner
back if the LED is re-enumerated, reading it from
`/run/ubuntu-gts9u/desktop-user`.

Verified in the chroot: an account with the wizard's exact groups, the LED
going from `root:video 660` to `arturo:video 660`; and after returning it to
`root:video`, the udev helper restores it.

### Languages: a criterion corrected, not a failure

Including every language pack had been rejected for weighing close to 1 GiB.
Badly calibrated: the device has 256 GB in its smallest version. All 526
travel.

### GNOME Software

The system references it and it was not installed. It is added, along with its
snap plugin.

---

## Session 41 — why a reboot was needed: `RemainAfterExit`

Date: 2026-08-11. The cameras and the torch worked, but only after a first
reboot following the wizard.

### Confirmed with the journal, not deduced

`ubuntu-gts9u-desktop-user.service` appears **exactly twice as "Starting", once
per boot**, across both recorded boots. On the first, `no desktop user yet`; on
the second, all the work: groups, lingering, the LED and the relays. The
`.path` unit never achieved a third run.

The cause is `RemainAfterExit=yes`. The service runs at boot, finds no account,
finishes cleanly and stays `active (exited)`. When the `.path` unit fires and
does a `systemctl start`, systemd sees an already active unit and does nothing —
correctly. Everything was deferred to the next boot.

`RemainAfterExit` is removed. The service applies settings and exits; it has no
state to retain, and this makes it runnable again, which is the whole reason
the `.path` unit exists.

### And a second gap in the same place

`graphical.target` is reached long before the account exists, so the relay
service skipped itself by its own condition and nobody came back for it. Now,
after writing the drop-in, the helper does `systemctl start --no-block` on the
relays. `--no-block` is not optional: the relay unit carries `Requires=` on
this one, and waiting for its start job from inside would be waiting for
itself.

### Method

Three attempts at fixing the torch, and the first two were sent without being
able to test the real path. What closed it was reading the device's journal:
two runs, one per boot, which is an unmistakable signature. It is worth looking
at the journal before the code.

---

## Session 42 — the USB-C port misses connections, and a hub that will not give up

Date: 2026-08-11. A live debugging session on the booted tablet, over SSH, with
the hardware in hand.

### What gets fixed

**The port stops noticing connections.** Measured, not assumed: with a hub
plugged in and not enumerating, `CC_STATUS=0x22` (something is connected),
`INT1..INT5` at zero, correct masks and IRQ 166 frozen since the previous
unplug. The chip detects and does not report. An `unbind`/`bind` recovers it
instantly.

It is not deterministic — a later plug was detected on its own — so the fix is
a deferred watcher every 4 s that acts only when the hardware says something is
there **and** the interrupt has not announced it. The condition is deliberately
narrow: the driver already warned that re-arming the resynchronisation
unconditionally made TCPM oscillate between host and disconnected.

### What does not get fixed, and what is ruled out

The hub still does not enumerate. Ruled out with evidence: that it is broken
(it works on a PC), that the OTG path is no good (at t=369 a device was
enumerated with the tablet supplying VBUS), that the masks are wrong, and that
a suspend swallowed the event.

That leaves the advertised Rp, which the driver sets to the minimum on a
natural sink connection. `otg_rp` is added as a module parameter **with today's
value as the default**, so it can be tested live without risking what already
works: there is precedent for breaking it, because the Rp was lowered precisely
because `0x59` dropped a passive OTG dongle.

### Method

Three hypotheses of mine fell to measurement: a dead hub, a broken OTG path and
a low Rp. The one that survived came from reading the chip's registers over i2c
and counting interrupts in `/proc/interrupts`, not from reading code. And a
badly designed test — raising the Rp with the accessory already connected, when
a sink reads it on connecting — nearly discarded the only hypothesis still
alive.

---

## Session 43 — the first in-place upgrade, and what it broke

Date: 2026-08-11. `gts9u-upgrade` made its debut on the booted tablet, with
v0.23. It worked, and found three defects: two of its own and one much older.

### Own defect 1: rsync deleted its own working directory

`--delete` with the mounted image as source and `/` as destination went for
`/var/tmp/gts9u-upgrade.XXXX`, which does not exist in the source: it tried to
delete the mount point it was reading from, and **it did delete the ZIP** from
which the boot images had to be written afterwards. `/var/tmp` is excluded, and
it now explicitly checks the ZIP and the mount are still there before
continuing.

### Own defect 2: the "what to keep" list looked in the wrong place

Wi-Fi and brightness were lost. The network profile is **not** in
`/etc/NetworkManager/system-connections` — that directory was empty — but
generated by netplan in `/run`, with the original in `/etc/netplan`.
Brightness lives in `/var/lib/systemd/backlight`. The list moves to keeping
whole state directories.

### An old defect: the images have never carried capabilities

While verifying whether the upgrade preserved `security.capability`, a walk of
the image found **zero** files with any, and the source tree has three. They
were not being lost on upgrade: `tar --xattrs` copies only `user.*`, so **no
image from this port has ever carried them**, on microSD or UFS. Fixed with
`--xattrs-include='*'` in both image builders.

Ironic: the argument for doing the upgrade on the live system rather than in
TWRP was precisely not to lose the capabilities. It turned out they were
already being lost, somewhere nobody had looked.

### What did go well

The four boot images matched the manifest on being read back, and the account,
the `home` and the system all survived. The tablet booted with the new kernel.
The three capabilities were restored live.

---

## Session 44 — it was the current

Date: 2026-08-11. A clean installation of v0.24 and the closing of the hub
case.

### The hub works

With `otg_ma=3` (1500 mA) set **before** plugging in, the bus-powered hub
starts first time: `BSTCNTL1=0xc6`, and `lsusb` shows the Genesys Logic hub and
the RTL8153, which binds `r8152` and presents a network interface.

What they declare once enumerated: hub 100 mA, Ethernet 180 mA. What needed the
headroom was the inrush. With the ceiling at 900 mA the charger's protection
cut in before the hub could signal, and since the cut is the charger's and not
the host's, **no trace is left in any log**. That is why "it lacks current" and
"nothing is plugged in" looked identical from Linux.

The default is raised to 1500 mA. The Rp advertisement stays as it was: they
are independent settings, so headroom to start is given without telling anyone
they may draw 1.5 A continuously.

### The clean installation validated the rest

`ping` with `cap_net_raw` — a first for the port — the torch LED at
`agcar:video` and the seven groups applied without rebooting, 41 language
catalogues, five camera nodes.

### And it found a failure of mine

`ubuntu-gts9u-desktop-user.service` and its `.path` in a *failed* state. On
removing `RemainAfterExit` in session 41, the service becomes inactive when it
finishes, and `PathExistsGlob` fires **on level**: it relaunched in a loop up
to systemd's start limit. The work was applied on the first pass — which is why
the torch and the cameras worked — but the units were left marked as failed. It
is changed to `PathChanged=/home`, which is edge-triggered.

### And a language decision

The wizard preselected Spanish because the image fixed `locale.gen` at
`es_ES`, the keyboard at `es` and the zone at `Europe/Madrid`. It moves to
`en_US.UTF-8`, keyboard `us` and UTC: that is what somebody installing this
without knowing anyone on the project sees, and the wizard asks all three
questions anyway.

---

## Session 45 — switching the four cameras in normal applications

Date: 2026-08-11. v0.25 was picked up with four cameras that worked in GNOME
Camera but could go black or static when alternated from OBS or Chrome. Before
touching anything, all the pending libcamera, `v4l2-relayd`, `v4l2loopback`,
WirePlumber and build-script work was preserved in commit `bf6adb8`.

### The upgrade ran old code with a new file

The tablet still carried `ubuntu-gts9u-device 2.17`, but the package built
under that same number still contained `PathExistsGlob=/home/*`. APT does not
distinguish two contents with identical versions. The level condition
relaunched `ubuntu-gts9u-desktop-user` up to its limit and the camera service,
which depends on it, stayed stopped.

The package moves to 2.18. Its `postinst` reloads the units, clears the failed
states, restarts the corrected `PathChanged=/home` watcher and runs the
account's dynamic resolution. If the relays were active before the upgrade, it
restarts them at the end: a mere `start` would have kept the old binary's
process.

### Two different failures in the switching

The first failure was a race with pre-emption. A `SIGUSR1` arriving just after
the reader closed marked the previous relay as pre-empted forever. Now it is
marked only if a client is still active, and an input error schedules its
recreation if the reader is still open.

The second appeared under WebRTC stress. The lock file was truncated before
writing the PID, but the descriptor kept its offset. Successive PIDs ended up
behind NUL gaps; the reader read owner zero and could not signal the process
holding CAMSS. An `lseek(..., 0, SEEK_SET)` before the `dprintf()` closes the
failure. The result is packaged as `v4l2-relayd-gts9u 0.1.2-gts9u15`, and the
device package requires exactly that version.

### Evidence from applications, not only from drivers

OBS was started with an empty `XDG_CONFIG_HOME`. The scene really did start
empty and a normal "Video Capture Device (V4L2)" source was added from the
interface. The selector showed exactly the four GTS9U entries, with no RAW
nodes and no prebuilt scenes. That same source went through all four cameras;
two captures three seconds apart changed 31.12 %, 20.04 %, 22.98 % and 23.91 %
of the preview's pixels respectively. That rules out the static image that
prompted the session.

The WebRTC bench enumerates before opening anything, then selects each exact
`deviceId`, waits for a non-black image and compares samples two seconds apart.
Three consecutive rounds passed 4/4 at 1280×720, with 45.35–97.78 % changing
pixels depending on camera and scene.
GNOME Camera also saved four real JPEGs:
two front ones upright and two rear ones upright, with different fields of
view; the flash lit the rear ones.

Discord in the owner's Chrome session enumerated the same four names and
identifiers. Its preflight selector changed the label to the rear cameras but
kept `/dev/video20` open; the same Chrome's WebRTC page immediately opened each
rear camera when it asked for its exact `deviceId`. It is left as a peculiarity
of Discord's interface: no userscript, scene or per-profile preference that
would not exist on a clean installation is added.

### A second cold boot

The first reboot changed the IP over DHCP and left the tablet at GDM, as it
should with no autologin. The relays do not depend on that session: the marker
resolved `agcar`, enabled lingering and generated the drop-in in `/run`. An
attempt to measure with `v4l2-ctl` consumed the last buffer 75 times before the
debounce and produced a false "single frame"; that is not valid proof of
continuous video.

To exclude any manual recovery, a second complete reboot was made and Chrome
was the first consumer. With boot ID
`ea55e3d3-6104-4bc0-a8b1-c0c944764ee0`, four relays and no failed unit, all
four cameras passed first time: 1280×720, 2.030–2.034 s of progress and
98.76–100 % changing pixels. The root was still `UBTS9U_UFS`, the
`v4l2loopback` module matched `7.2.0-rc3-dirty` and was signed, and the flash
ended at zero.

Neither CCM nor AWB was changed. The available scenes contain no controlled
grey or colour chart; tuning a matrix for a wall and a flash-lit desk would
have been guesswork and could have made other lighting worse.

### v0.26's first clean build found another failure

The first complete build reached the local-package hook and stopped correctly:
purging `vlc-plugin-*` had also removed `obs-plugins`. That left `obs-studio`
and `obs-v4l2-gts9u` installed, but without the package that provides OBS's
sources. The check that already existed prevented an incomplete ZIP being
published.

The hook now reinstalls `obs-plugins` with `--no-install-recommends` after
removing VLC. The sequence was reproduced on that same failed ARM64 root: VLC
stayed absent, `obs-plugins 30.0.2+dfsg-3build1` came back and the active
`linux-v4l2.so`'s SHA-256 matched `obs-v4l2-gts9u`'s copy, while the original
binary stayed at the diverted path. The build now checks that equality, not
just dpkg's state.

### A clean release and the final state

The first complete build came from commit `978332d`; after finding and fixing
the audio race, the definitive release was regenerated from `9081233`. The root
filesystem contains 1,521 packages and keeps exactly
`ubuntu-gts9u-device 2.21`, `v4l2-relayd-gts9u 0.1.2-gts9u15`,
`libcamera-gts9u 0.7.2+53.g62d4bfc-gts9u5` and
`libspa-0.2-libcamera-gts9u 1.0.5-gts9u10`. There is no ordinary account, no
VLC and no `/tmp/local-debs`; the active V4L2 plugin and `obs-v4l2-gts9u`'s copy
have the same SHA-256.

The UFS image is 3,780,116,480 bytes and has SHA-256
`5fbd69982b10d297a8de5f6c1018b6c8a4ca3ee193165a222da0fc6143839386`. The TWRP
ZIP is 1,157,003,824 bytes and has SHA-256
`67a9710e2bfd15d86c631222e5ca866f7cd6d65c79f87cd5f3c0dcfec3976164`. The
independent validation again passed partition sizes, Android v4 headers, DTB,
LZ4, AVB flags, CRC and the installer's contract. Nothing was flashed.

The last reading from the hardware kept boot ID
`ea55e3d3-6104-4bc0-a8b1-c0c944764ee0`: the relay service active, four
processes, `/dev/video20–23`, `Linger=yes`, root `UBTS9U_UFS`, zero failed
units and the flash off. Building the release therefore did not alter the
tablet's already-validated state.

## Session 46 — the Dummy Input was a race with the panel's recovery

Date: 2026-08-11. After a reboot, GNOME offered only Dummy Input/Output. The
driver was not missing: `/proc/asound/cards` contained the X910, all five PCMs
existed and WirePlumber had created `alsa_card.platform-sound`. The object,
however, had only `off` and `pro-audio`; it had started at 19:17:02 and the
card did not finish registering until 19:17:14. Restarting WirePlumber alone
reloaded UCM, activated `HiFi` and brought back the speaker and the microphone.
A recording produced 352,871 non-zero samples.

The package's first fix waited for `controlC0` and refreshed WirePlumber once
per boot. The negative test left the profile explicitly at `off`; since
WirePlumber keeps a deliberate selection, the final version also selects and
checks `HiFi`. The package moves to `ubuntu-gts9u-device 2.21` and declares
`pulseaudio-utils`, which provides `pactl`.

The next reboot showed that fixed the enumeration but not the whole cause:
PipeWire opened the microphone and received nothing but zeros, as did ALSA
directly. The log captured the harmful order: the ADSP came up, the panel's
recovery entered its `platform` suspend, the APM timed out on opcode `1001021`
and `va_macro` resumed with `-EACCES`. It was the intermittent failure already
documented, but now tied to a concrete sequence.

The ADSP's unit now wants and waits for
`ubuntu-gts9u-panel-coldboot-recover`; the user resolution in turn waits for
the ADSP and only then refreshes HiFi and allows the relays to start. Two
consecutive reboots measured exactly that order. Boot IDs
`a4f0a3b9-0446-48a2-a915-b8c6995af27f` and
`7f3fbb28-c259-401f-8762-2807551d149a` produced 351,781 and 351,547 non-zero
microphone samples respectively, opened the output silently, and left four
relays, `/dev/video20–23` and zero failed units. The `-EACCES` did not return.
The isolated initial APM timeout still appears on one of the two boots, but it
prevents neither the later registration nor real capture.

v0.26 was rebuilt with that 2.21 inside the image, not only on the development
tablet. A second inspection mounted the UFS read-only and verified the exact
versions of the device package, libcamera, SPA, the relay and the OBS plugin,
the absence of an ordinary account and of temporary packages, and the installed
ordering of the units. The independent static validation passed the ZIP's full
contract again. The definitive hashes are the ones given in the release section
above; they replace the first v0.26 with 2.18.

## Session 47 — automatic brightness: both STK31610 routes stop at the DSP

Date: 2026-08-11. The starting point already had all of GNOME's integration:
`org.gnome.settings-daemon.plugins.power ambient-enabled=true`, the DCS
backlight at `/sys/class/backlight/ae94000.dsi.0` and `iio-sensor-proxy` with
SSC support. The light sensor was still hidden by design because claiming it
blocked the proxy.

The protocol difference that had not yet been tested was examined first. The
official Android/CHRE client includes in `sns_std_request` a batch
specification with a zero period and a three-second flush, and explicitly marks
the request as active. `libssc 0.4.4-gts9u1` (`4aa9c17c…`) and
`iio-sensor-proxy 3.9-gts9u1` (`b94af25e…`) were built for ARM64 with that
exact envelope and the light driver enabled. After restoring `is_dri=1` and
rebooting, GNOME detected `HasAmbientLight=true`; at 21:39:58 `gsd-power`
recorded `Claiming light sensor failed: timeout reached`. `LightLevel` stayed
at 0, brightness at 284/2047, and the proxy waited instead of consuming a core,
thanks to the earlier fix to the synchronous loop.

Explicitly enumerating `ambient_light_sub` produced the second instance the
default query does not show:

- `ambient_light`: `stk_stk31610`, SUID
  `5158289438331071126:3046173514946711665`;
- `ambient_light_sub`: `stk_stk31610_sub`, SUID
  `5230347032368999062:3046173514946711665`.

The secondary announces `available=yes`, 5 Hz and *on-change* mode. It accepted
the QMI transaction whose body ended in `0a:07:08:00:10:c0:8d:b7:01:18:00`,
exactly the earlier batch and active client, but over 20 s it emitted neither a
configuration nor any lux. This agrees with pmOS's exhaustive tests of both
instances, continuous, DRI, polling, the physical Samsung request, rails and
buses: the remaining boundary is the proprietary driver inside the DSP, not
GNOME and not the Linux client.

The diagnostic patches were not kept. The tablet returned to `libssc 0.4.4` and
`iio-sensor-proxy 3.9`, with `ssc-light` hidden, `is_dri=1` in both registry
files and the proxy active. The exit check left zero failed units,
`/dev/video20–23`, the speaker sink and the digital microphone. No false
solution is published, and no camera is opened periodically as an ALS: that
would be a substitute with battery, privacy and concurrency implications
requiring a separate decision.

## Session 48 — graphical artefacts: investigation abandoned

Date: 2026-08-12. Chromium showed Discord's background split into vertical
bands and tiles, and GNOME Settings deformed the background of disabled
switches after scrolling or after a few minutes. Games remained correct. A
temporary tool read the primary KMS framebuffer over PRIME: 2960×1848, `XR30`,
pitch 11904, linear modifier. The capture contained the same defects, ruling
out the panel, DSC and the photograph of the OLED.

Chrome with the GPU entirely disabled came out clean, but not with
`--disable-gpu-rasterization`, `FD_MESA_DEBUG=noubwc`, `notile`, `nofp16` or
ANGLE's vendor workaround. `--use-angle=vulkan` did fix the page without losing
the GPU process. In GTK4, Vulkan and NGL could look correct on opening, but the
failure reappeared with a delay; a temporary uinput device automated scrolling
and panel switching. The classic GL renderer stayed correct.

Zink was explored as a common fix. A global prototype initially fixed the
gradient, but after a reboot Mutter found no outputs and a blinking `_` was
left. It was recovered over SSH. Mesa was then patched to limit Zink to Wayland
clients and GBM render nodes: GDM survived, but Discord began turning `#` and
voice icons into blocks. That was discarded too; the test Mesa package was
uninstalled and its diversions restored Ubuntu's files.

A second round narrowed Chromium's defect to Ozone/Wayland: Xwayland and
ANGLE/Vulkan were clean, while `FD_MESA_DEBUG=flush` was the only Freedreno
control that fixed the OpenGL Wayland path. That mode drains the GPU after
every draw and was rejected for its potential cost. The compositor advertised
no explicit synchronisation; Chrome delivered dma-buf and received
`wl_buffer.release`, which leaves late implicit synchronisation as the clue.

The severity did not justify adding more complexity or risking good 3D
performance. At the user's request the work was cancelled and the previous
state restored: no alternative Mesa package, no diversions, no
`GSK_RENDERER`/`ANGLE_DEFAULT_PLATFORM` variables, no Chromium flags and no
Mutter changes. The artefacts are documented as a minor limitation, not as a
repaired feature.

## Session 48 — automatic brightness: the AP route is closed by measurement

Date: 2026-08-12. Session 47 had left the ALS as a "boundary in the DSP
driver". One claim that had been carried along remained unchecked: that the
STK31610 was physically where its own registry says.

### The registry and the stock tree agree; the silicon does not

`kailua_stk31610_0/1.json` (extracted from `vendor.img` and present in the
installed HexagonFS tree) place both chips at `bus_type=0` (I²C),
`bus_instance` 3 and 4, `slave_config=72` (**0x48**), 400 kHz and `dummy_vdd`
rails. The stock DTS resolves `qupv3_hub_i2c3 = i2c@98c000` and
`qupv3_hub_i2c4 = i2c@990000`, and its overlay hangs the SM5440 (0x63) and the
MAX77816 (0x18) off them **from the AP**: both engines are genuinely shared,
not exclusive to the SSC.

This branch already drives both in GPI-DMA. A complete `i2cdetect -y -r`
returns:

- SE3 (`/dev/i2c-4`): only `UU` at 0x63;
- SE4 (`/dev/i2c-5`): only 0x18.

And 0x48 NAKs on all sixteen AP buses. The neighbours answer on the same pair
of wires, with the sensors' rails measured alive (`vreg_l1b_1p8` and
`vreg_l16b_3p0`, both `enabled`, 1.8 V and 3.0 V, one consumer each). With the
bus vouched for by its neighbours, **the chip answers neither master**.

### A sweep of the engines that were missing, and its negative control

So as not to close the case falsely, `i2c_hub_2` (gpio20/21) and `i2c_hub_5`
(gpio6/7) were enabled in GPI-DMA — the only two left unmapped, because this
board uses SE0, SE1 and SE7's pins for camera enables, a regulator and the
pogo's rail. **Both boot and `vendor_boot`** had to be rewritten: with `boot`
alone the live tree was still the old one, exactly as `docs/boot-strategy.md`
already warns; a cycle was lost for not reading it first.

The packaging was validated by first reproducing the installed images byte for
byte with the old DTB (`boot` `0cf7c7c0…`, `vendor_boot` `e77aca73…`), so that
the diagnostic ones differed only in the DTB.

Result: SE2 shows only 0x18, SE3 0x63, SE4 0x18, SE5 empty. Neither 0x0c nor
0x48. The positive control **failed**: the AK0991x, which the registry places
at `bus_instance=2` at 0x0c, does not appear either. That is, the SSC's
`bus_instance` is not the hub's SE index, and the coincidence for 3/4 rests on
the stock DTS, not on arithmetic. (An honest caveat: SE2's adapter showed 0x18,
the same as SE4, which could indicate GPI channel aliasing; SE2/SE5's negative
result is therefore weaker than SE3/SE4's, which were measured in the
already-proven production configuration.)
### A mistake of my own, and the control that corrects it

It was first claimed that no SSC I²C sensor worked under Ubuntu, because
`gdbus introspect` on `net.hadess.SensorProxy` did not list `.Compass`. **That
was a methodological error**: that interface lives on the child object
`/net/hadess/SensorProxy/Compass`. Querying the correct object,
`HasCompass=true`, and after adding a temporary polkit rule — claiming sensors
over SSH gives `Not Authorized` because the session is not "active" —
`monitor-sensor` delivers a live heading between 127° and 134°. The compass
works.

That makes the failure more informative, not less. The AK0991x is on the SSC's
I²C (`bus_instance=2`, 0x0c) and, even while working, **also appears nowhere
when scanning from the AP**. A healthy SSC sensor is as invisible to the AP as
the ALS. So 0x48's NAK closes the AP route but does not license the conclusion
that the chip is missing or unpowered, as had been suggested; the earlier
conclusion is corrected in `docs/development-notes.md` and in the README.

With the compass as a control, what works can be compared field by field with
what does not, on the same transport and the same registry: the ALS is the only
one declaring `num_rail=2` with `vdd_rail`/`vddio_rail` at
`/pmic/client/dummy_vdd` and `dri_irq_num=0` with `irq_pull_type=0`, while the
compass uses the real rail `/pmic/client/sensor_vddio` and DRI 89 with pull 3.
The ADSP firmware contains the string `i2c_power_on failure`. The live
hypothesis becomes that the STK31610's registry entry is a reference-board
template that does not describe this board, not that the sensor is missing.

A measured asymmetry between branches: pmOS leaves `i2c_hub_4` disabled on the
AP and gives that pinctrl to the DSP (`pinctrl-0 = <&hub_i2c4_data_clk>`); this
branch enables it for the MAX77816 and deletes the ADSP's pinctrl.
`stk31610_1` is on that `bus_instance` 4. Even so, the ALS gave no lux under
pmOS either, so returning SE4 is not on its own the solution.

### Final state

No functional change survives: the DTS compiles the same DTB as the release
again (`22db3b18…`) and both partitions were restored from backup with a
read-back and SHA-256 comparison. The exit check on the tablet: zero failed
units, `boot` and `vendor_boot` with v0.26's hashes, 16 I²C buses,
`/dev/video20–23`, the speaker sink, the ADSP `running`, and the accelerometer
and orientation correct. Automatic brightness is not published: without lux
there is none, and the ALS is not replaced by the camera behind the owner's
back.

## Session 49 — the SSC's I²C route was not broken; the ALS is alone

Date: 2026-08-12, continued. It opened with the brief to "fix the SSC's I²C
route", the previous session's conclusion. **The premise was false and it was
mine: that route works.**

`ssccli`, which `libssc` itself installs, settles the diagnosis without
touching `iio-sensor-proxy`:

- `--sensor accelerometer`: 84 samples (SPI, `bus_instance=1`);
- `--sensor magnetometer`: 30 samples (I²C, `bus_instance=2`);
- `--sensor compass`: live heading 127–134°;
- `--sensor light`: **nothing**.

Two of the SSC's I²C sensors deliver data. There is nothing to fix on the bus;
the ALS is alone in its failure.

### What was ruled out, and with what rigour

With the compass as a control, the only two fields where the ALS's registry
departs from its own were attacked:

1. the `dummy_vdd` rails → `/pmic/client/sensor_vdd` and
   `/pmic/client/sensor_vddio`, the AK0991x's;
2. `is_dri=1` → `0` in `stk31610_{0,1}.ambient_light.config`, forcing polling.

Both at once, and verified **after a complete reboot** so the DSP would reread
the registry rather than only after restarting
`hexagonrpcd-adsp-sensorspd`. The accelerometer and magnetometer kept giving
samples; the light, zero. Both fields are ruled out and recorded so they are
not repeated.

`ssccli -v --sensor light` locates the boundary precisely: the enable request
goes out, the DSP answers `Control` with `Result = SUCCESS` and a Client ID,
and from then on **not one indication arrives**. The transport, the QMI client
and the permissions are all fine; what does not arrive is the sample.

Given that the SSC publishes the sensor as available — which implies its
start-up routine passed, and the firmware has an `STK3A6X HW absent` error path
it does not take — the most consistent reading is still that the chip exists
and answers on the DSP's private bus, and that the *streaming* configuration
inside the blob never completes.

### Unnecessary work, recorded so it is not repeated

`iio-sensor-proxy` was rebuilt without `disable-broken-ssc-light.patch` in
order to have an ALS client. It was not needed: `ssccli` already is one. The
build served to confirm that with `ssc_light` active `HasAmbientLight` becomes
`true` and `LightLevel` stays at 0, which is what session 47 already said.

### Final state

Everything reverted and verified: the registry `identical` to its copy, the
proxy binary with the release's SHA (`4c2a2a9c…`), `boot` `0cf7c7c0…` and
`vendor_boot` `e77aca73…`, zero failed units, 21 video nodes, the ADSP
`running`, the temporary polkit rule and the diagnostic files deleted. No
automatic brightness.

## Session 50 — the sheng reference exhausts the registry route

Date: 2026-08-12, continued. The owner supplied an excellent reference: the
Xiaomi Pad 6S Pro 12.4 (`xiaomi-sheng`), **same SM8550 SoC, same SEE, same
`libssc` + `adsprpcd-sensorspd`**, with automatic brightness working. It is not
the Xiaomi Pad 6 (`pipa`) that pmOS had already ruled out: that one is a
different SoC.

Its `sheng-sensors-20240917-r1.apk` package yields the complete registry. Its
ALS is a Sensortek **STK3BCX** on `bus_instance` **4**, slave **72** (0x48):
the same bus and the same address as our `stk31610_1`. The only configuration
differences were the four already suspected:

| Field | sheng (works) | X910 (does not) |
|---|---|---|
| `vdd_rail` / `vddio_rail` | `sensor_vdd` / `sensor_vddio` | `dummy_vdd` / `dummy_vdd` |
| `is_dri` | 0 (polling) | 1 |
| `dri_irq_num` | 16 | 0 |
| `irq_pull_type` | 2 | 0 |

sheng's exact shape was replicated on both STK31610 instances and checked
**after a complete reboot**: accelerometer 544 samples, magnetometer 19, light
none. (A methodological detail: the first attempt did not change `vddio_rail`
because `sed` without `/g` only substitutes the first occurrence and the JSON
is on one line; it was corrected and the whole cycle repeated.)

With that, the registry route is exhausted. What separates the two tablets is
not configurable: sheng boots Xiaomi's ADSP firmware, which carries a working
`sns_stk3bcx`, and the X910 boots Samsung's with `sns_stk31610`. The driver
lives inside the signed blob and cannot be replaced: Samsung's secure boot
rejects Qualcomm's reference `adsp.mbn`, as already documented in the
`&remoteproc_adsp` note.

Final state: the registry restored to its copy (`dummy_vdd`, `dri_irq_num=0`,
`is_dri=1`), the proxy at the release SHA `4c2a2a9c…`, `boot` `0cf7c7c0…`,
`vendor_boot` `e77aca73…`, zero failed units and the accelerometer giving
samples. Still no automatic brightness, and still no false solution published.

## Session 51 — the sensor is there, and the boundary is the blob's streaming

Date: 2026-08-12, continued. The owner insisted, rightly: the hardware exists
and works under Android. Samsung's official source was reviewed and the missing
test performed.

### A presence test: moving the bus gives a different answer

Until now it was known that on buses 3 and 4 the DSP accepts the enable and
sends nothing. The contrast was missing. Pointing both STK31610 instances at
`bus_instance` 2 — the compass's, where the ALS is not — and rebooting:

```
Unable to initialize light sensor: UNKNOWN
```

The DSP **does not publish the SUID**. With the original configuration it
publishes it again, `HasAmbientLight=true`, and the enable is accepted with
`Result = SUCCESS`.

That difference is the missing proof: **publishing implies the start-up routine
identified the chip**. So the STK31610 is present, powered and recognised by
the DSP on SSC buses 3 and 4 at 0x48. It is definitively ruled out that it is
missing, unpowered or on another bus — and session 48's contrary suggestion is
corrected. The only thing that fails is sample delivery inside the blob.

### Samsung's source: nothing is missing on the AP side

The official `Kernel.tar.gz`'s `kalama-gki_defconfig` compiles
`CONFIG_LIGHT_FACTORY=y`, `CONFIG_LIGHT_SUB_FACTORY=y`,
`CONFIG_SUPPORT_DUAL_OPTIC=y`, `CONFIG_SUPPORT_VIRTUAL_OPTIC=y`,
`CONFIG_TABLET_MODEL_CONCEPT=y` and `CONFIG_SUPPORT_LIGHT_SEAMLESS=y`. This
**corrects** pmOS session 108, which had `TABLET_MODEL_CONCEPT` down as absent.

But none of those options is a condition for the sensor to emit:

- `drivers/adsp_factory/` is the factory test driver. Android's HAL reads
  sensors without it, and this tree does not even carry `stk31610_light.c`: the
  X910 uses the generic `light_factory.c`.
- `SUPPORT_LIGHT_SEAMLESS` only sends `OPTION_TYPE_SSC_LIGHT_SEAMLESS` with
  four lux thresholds for switching main/secondary, and only if any of them is
  non-zero.
- `SUPPORT_PANEL_STATE_NOTIFY_FOR_LIGHT_SENSOR` is **not** enabled, which
  agrees with pmOS's negative panel-notification test.

There is no AP-side piece this port is omitting.

### State

The registry restored to its original form (`bus_instance` 3 and 4,
`dummy_vdd`, `dri_irq_num=0`, `is_dri=1`), with no copies and no diagnostic
files. `boot` `0cf7c7c0…`, `vendor_boot` `e77aca73…`, proxy `4c2a2a9c…`, zero
failed units, 21 video nodes, ADSP `running`, compass `HasCompass=true`.

What remains for a working ALS is one thing, and it is reverse-engineering
work: disassembling the blob's `sns_stk31610` path to see why, after an
accepted enable, it never programs the chip to sample.

## Session 52 — the client is ruled out; a basis for disassembling the blob

Date: 2026-08-12, continued. Before entering the blob, two suspects remained on
our side. Both fall.

### libssc loses nothing: the DSP does not transmit

`ambient_light` is an *on-change* sensor, and in SEE that requires message 514
with no payload rather than 513 with a `sample_rate`. `libssc` 0.4.4 was
reviewed and does it correctly (`libssc-sensor.c:230`). Its light handler only
accepts indications with `msg_id == 1025`, so it could be silently discarding
— but it is not. Counting QMI messages received **after** the enable with
`ssccli -v`:

| Sensor | total `rx` | `rx` after the enable |
|---|---|---|
| accelerometer | 180 | **171** |
| light | 8 | **0** |

Zero. The DSP accepts the enable and sends absolutely nothing. Not the client,
not the parser, not `iio-sensor-proxy`.

### Samsung's source: the panel route is not used in this product

Reviewing the four defconfigs one by one (`kalama-gki_defconfig`,
`kalama_sec_defconfig`, `kalama_sec_userdebug_defconfig`, `kalama_GKI.config`):
`SUPPORT_BRIGHTNESS_NOTIFY_FOR_LIGHT_SENSOR`,
`SUPPORT_PANEL_STATE_NOTIFY_FOR_LIGHT_SENSOR` and
`SUPPORT_DDI_COPR_FOR_LIGHT_SENSOR` are **enabled in none of them**. Android
does not send panel state or brightness to the ALS either. That explains why
pmOS's panel-notification test came out negative, and closes that hypothesis
for the right reason.

What do appear are driver strings that betray an under-display ALS:
`skip update bl = %d %d`, `stk3a6x_inst_notify_event: lcd %d->%d`,
`[TOP-ALGO] AC mode 0 ~ 73 code` and, most tellingly,
`[TOP-ALGO] all data was skipped`. Also the chip's ID in `light_factory.c`'s
table: `{0x66, "SensorTek", "STK31610"}`.
### A basis established for the reverse engineering

- The driver is in **`adsp.b18`**, loaded by `adsp.mdt` at **`0xb3200000`**
  (ELF32, 52 program headers, 1,935,448 B, R+X).
- A string's vaddr = `0xb3200000 + offset`. `[TOP-ALGO] all data was skipped`
  → `0xb33c8dd0`; `skip update bl` → `0xb33c8ca0`; `STK3A6X HW absent` →
  `0xb33ab5c8`.
- Tool: `rasm2 -a hexagon -b 32`. `llvm-objdump` lists `hexagon` as a target
  but accepts **neither** `-b binary` nor `--binary-architecture`; the segment
  has to be wrapped in an ELF32 with `e_machine = 164`.

And the warning to keep in mind: **the firmware is signed**. Even if the fault
is found, the blob cannot be patched. The only useful outcomes are finding a
non-obvious registry key or a message the AP should be sending. The live
candidate is `MSG_TYPE_OPTION_DEFINE` → **SSC message 615** (the
SSC = 600 + `MSG_TYPE` correspondence is verified with 9→609 and 12→612), with
`OPTION_TYPE_LCD_ONOFF` = 2. What is missing is the exact protobuf encoding of
the `int32` array `factory.ssc` uses.

State: no changes on the device. The original registry, `boot` `0cf7c7c0…`,
`vendor_boot` `e77aca73…`, proxy `4c2a2a9c…`, zero failed units, ADSP
`running`, the compass alive. Still no automatic brightness.

## Session 53 — there is no other light sensor to subscribe to

Date: 2026-08-12, continued. One well-founded idea remained: the blob contains
a **`light_seamless`** sensor (`light_seamless_sensor.c`,
`light_seamless_sensor_instance_island.c:send event curr_lux:%u`,
`Enable light rate %u`). On a *dual optic* product like this one it was
reasonable that Android's HAL subscribed to the fused sensor rather than to
each chip.

A variant of `ssccli` was built with the `data_type` selectable by environment
variable (`libssc-sensor-light.c:277`) and the candidates were swept:

| data_type | published | `rx` after enable |
|---|---|---|
| `ambient_light` | yes | **0** |
| `ambient_light_sub` | yes | **0** |
| `light_seamless` | **no** | — |
| `rgb`, `als`, `light`, `oem13`, `sns_oem13`, `ambient_light_v` | no | — |

The DSP publishes only the two physical sensors, and both accept the enable and
emit nothing. `light_seamless` exists in the firmware's code but is **not
instantiated** on this tablet: Samsung's X910 registry does not carry its
configuration (sheng's does carry an `sns_oem13.Light`). There is therefore no
alternative sensor to subscribe to.

The factory route was also located: `MSG_TYPE_FACTORY_ENABLE` is sent to
`MSG_SSC_CORE` with an empty payload (`ssc_core.c:672`), that is SSC message
**613**, and the driver has an `is factory` check. It stands as the only
untested actionable candidate, pending working out the `data_type` of Samsung's
SSC_CORE sensor, which does not appear among the segment's strings.

State: no changes on the device. Test binaries deleted, `boot` `0cf7c7c0…`,
`vendor_boot` `e77aca73…`, proxy `4c2a2a9c…`, zero failed units, ADSP
`running`, the accelerometer giving samples.

## Session 54 — `factory.ssc`: "factory mode" is our own message

Date: 2026-08-12, continued. One actionable candidate remained: sending
`MSG_TYPE_FACTORY_ENABLE` to the SSC_CORE sensor. That needed its `data_type`,
and that needed disassembling `factory.ssc`.

`vendor.img` is EROFS; `fsck.erofs --extract` opens it without ceremony and
leaves `bin/factory.ssc`, a 55 KB stripped **aarch64** ELF. It is ordinary
ARM64 reverse engineering, far cheaper than Hexagon's.

**First answer: there is no `data_type` for SSC_CORE.** The binary contains only
six: `ambient_light`, `ambient_light_sub`, `proximity`, `proximity_sub`,
`pressure` and `sensor_temperature`. `MSG_SSC_CORE` is not a SEE sensor with a
SUID, so the factory enable message has nobody to address.

**Second answer, the one that closes the matter:** the disassembly gives the
exact translation from `MSG_TYPE` to SSC message, identical at both places
where it is built (`0x9850` and `0xa330`):

```
9850: cmp  w22, #0xd        // FACTORY_ENABLE
9858: mov  w4,  #0x202      // -> 514
9860: add  w8,  w22, #0x258 // the rest -> 600 + msg_type
9868: cmp  w22, #0xe        // FACTORY_DISABLE -> 10
```

| `MSG_TYPE` | SSC message |
|---|---|
| 11 `SET_CAL_DATA` | 512 |
| 13 `FACTORY_ENABLE` | **514** |
| 14 `FACTORY_DISABLE` | 10 |
| the rest | **600 + `MSG_TYPE`** |

The 600+N rule pmOS had deduced (609 and 612) is confirmed along the way, and
therefore `OPTION_DEFINE` = **615**. But the decisive part is that
**`FACTORY_ENABLE` is message 514, which is exactly the standard
`ENABLE_REPORT_ON_CHANGE` `libssc` already sends**. Samsung's factory daemon
starts the ALS with the same request we do: there is no privileged mode, no
different sequence, and nothing we are omitting when enabling it.

With that, the last actionable candidate falls. Added to the fact that
Samsung's four defconfigs do not enable the panel/brightness notifiers — so
Android does not send `OPTION_DEFINE` to the ALS either — there is no known
request left that the AP should be sending and we are not.

State: no changes on the device (this session was static analysis only).

## Session 55 — swap: two tiers, 23 GiB, and the ALS closed

Date: 2026-08-12. With automatic brightness closed (see sessions 47–54), the
request was to enable swap now that the root lives on the UFS.

The starting point was **no swap at all**, with 14.2 GiB of usable RAM and
Steam and Chrome running: the OOM killer was the only backstop. Free space,
772 GiB.

What was installed, in device package v2.22:

| Tier | Size | Priority |
|---|---|---|
| zram `zstd` | 8 GiB | 100 |
| UFS swapfile | 16 GiB | 10 |

Three things that had to be checked before deciding, not assumed:

- **`zstd` is available for zram** even though `CONFIG_CRYPTO_ZSTD` is
  module-only and this port installs no generic tree: modern zram brings its
  own backend and `comp_algorithm` lists it. The opposite conclusion, drawn
  from reading only the `.config`, was corrected on the spot.
- **ext4 accepts a swapfile made with `fallocate`** on this kernel: `mkswap`
  and `swapon` take it without complaint. That avoids a 16 GiB `dd` and makes
  creation instant, so it adds no time to the first boot.
- The `90-gts9u-cs35l45-no-hibernate.rules` rule has **nothing** to do with
  system hibernation: it is the codec's *runtime suspend*.

Measurements on the tablet, not estimates: compression **4.53×** (0.65 GiB of
pages in 0.16 GiB of RAM), 11 GiB reserved at once **without a single OOM
kill**, and the swapfile untouched at 0 B throughout the test — which is
exactly what the priorities should do: zram absorbs, the UFS only overflows.

After an unattended reboot: both units active, `swappiness=100`,
`page-cluster=0`, zero failed units, GDM and the ADSP correct, and the swapfile
reused rather than recreated (`enabled the existing swapfile`, mtime
preserved).

## Session 56 — OBS gets off the image

Date: 2026-08-12. With the camera work closed, OBS is withdrawn from future
builds. The note "OBS was travelling along" had already recorded that this day
would come and what had to be undone.

What goes, in device package v2.23:

- `build-extra-packages.sh`'s `obs-v4l2` step (88 lines) and the
  `packaging/obs-v4l2/` directory;
- the device package's `obs-v4l2-gts9u` dependency, which was the only thing
  dragging `obs-studio` into the image: OBS was never in a package list, it
  only arrived through that dependency;
- `libobs-dev` from the build chroot's dependencies;
- and the whole **VLC dance**. It existed only because `obs-studio` recommends
  `obs-plugins` and that recommends `vlc`: 77 MiB, of which 41 MiB were
  translations. The `vlc-plugin-*` family had to be purged and `obs-plugins
  --no-install-recommends` reinstalled, because on Noble the purge took
  `obs-plugins` with it. Without OBS none of that remains.

In its place there is a three-line check that **can fail**: the build aborts if
`obs-studio`, `obs-plugins` or `vlc` turn up installed. It is not a decorative
check — all three arrived once as a `Recommends` of something else — and an
image swelling that way again would only show up in the size.

What does **not** change: the `/dev/video20–23` relays, `v4l2-relayd-gts9u`,
the camera udev rule and libcamera's software ISP all stay as they are. The
only visible consequence is that anyone installing OBS themselves will see the
internal CAMSS nodes in their V4L2 selector alongside the four processed
cameras: that was hidden by the patched plugin just withdrawn.

The owner's installation is left untouched at her request; this affects only
images built from now on.

## Session 57 — Tab Companion, phase 0: reconnaissance with no product code

Date: 2026-08-12. The S Pen and EF-DX920 special-key work was opened with a
prior remote snapshot. The tablet was at `192.168.1.171`, with the pen docked
and no possibility of physical interaction.

Initial health, measured before touching the product:

```text
0 loaded units listed.
/dev/video20
/dev/video21
/dev/video22
/dev/video23
/sys/class/remoteproc/remoteproc0/name=adsp
/sys/class/remoteproc/remoteproc0/state=running
44. Built-in Audio Built-in speakers (4x CS35L45)
36. Built-in Audio Built-in digital microphones
```

`evtest` confirmed the pen's current ABI on `event2`: `BTN_TOOL_PEN`,
`BTN_TOUCH`, `BTN_STYLUS`, pressure 0–4095, distance 0–255 and tilt ±63. For
five seconds there were no events because the pen stayed docked. The keyboard
was present as `event3`, V37 and model `0xd6`; another five-second window ended
with the counter unchanged:

```text
attached=1 model=0xd6 connected=1 data_ready=0 key_events=0
last_key=0x0000 keys_down=0 recoveries=0 flash_version=00370037
```

No codes have therefore been attributed to Galaxy AI, DeX, finder/settings or
`Fn+F1-F5`: without a real press, doing so would be inventing evidence. The
firmware delivers 15-bit Linux keycodes directly and the current driver
publishes them with no table, so the later physical capture will be
conclusive.

UPower saw only `sm5714-battery`, `sm5714-usb` and `tcpm-source-psy-8-0033`: no
pen device at all. Bluetooth came up soft-blocked; after removing the block it
was `Powered: yes` and a 25 s active scan discovered 22 devices. None
advertised an S Pen name and only a Pro Controller was paired. Since the pen
was neither removed nor put into pairing mode, this is recorded as a limited
negative test, not as an absence of BLE.

Reading Samsung's official source gave the route for phase 2: GPIO137 `PDCT` is
*pen in/out*, orientation is queried from the Wacom itself with `0xee`, and BLE
charging is also governed by the Wacom. That same source exposes no battery
percentage. These conclusions live in `development-notes.md` so the
investigation is not repeated.

## Session 58 — Tab Companion, phase 1: the app and package installed

Date: 2026-08-12. `ubuntu-gts9u-companion` 0.1.0 was created as an independent,
deterministic Debian package. It installs `tab-companion`, App ID
`io.github.agcarbajo.TabCompanion`, a launcher, AppStream metadata, scalable
and symbolic hicolor icons, a GSettings schema and Gio resources. The root
filesystem builds the package from the versioned sources and includes it in the
same APT transaction as the other local packages.

The interface is GTK4/libadwaita and separates hardware from presentation from
the first commit: `HardwareClient` knows only the D-Bus interface
`io.github.agcarbajo.TabCompanion.Hardware`; the window contains no sysfs paths
and no `eventN` names.
Gesture and key mappings share the
same action catalogue and are stored in GSettings.

The real `.deb` was installed on the tablet:

```text
ubuntu-gts9u-companion  0.1.0
```

With no unlocked graphical session, it was run there under Xvfb at 1200×900
with `GSK_RENDERER=cairo`. It stayed alive until the test finished, with no
traceback, and produced a 1200×900 PNG capture. The inspection confirms the
large horizontal pen, the state underneath, the status and Air actions cards,
and navigation to Cover keyboard. The state says literally "Hardware service
unavailable": that is deliberate until the backend exists, not a simulated
figure dressed up as real.

The `.desktop` passed `desktop-file-validate`, the metadata passed
`appstreamcli validate`, the schema compiled with `--strict` and every Python
module passed `compileall`. How it looks in a real GNOME/Wayland session awaits
the owner's confirmation; a headless capture does not substitute for that
observation.

## Session 59 — Tab Companion, phase 2: the S Pen's silo and discrete charging

Date: 2026-08-12. `pdct-gpios = <&tlmm 137 GPIO_ACTIVE_HIGH>` was added to the
digitizer and the Wacom driver extended with `SW_PEN_INSERTED`, the
`pen_docked`, `pen_orientation` and `pen_charging` attributes, and the
`gts9u-spen` power supply. Samsung's `0xee` command is serialised with the rate
adjustment and its silo reply separated from the EMR frames.

The available physical case was measured after booting the final kernel:

```text
Wacom EMR digitiser: 19589 x 31376, pressure 4095, tilt +/-63/63, module 2, docked=1
S Pen garage reply: docked=1 direction=2 charge-state=9
pen_docked:1
pen_orientation:downside
pen_charging:not-charging
SW_PEN_INSERTED_QUERY=10 (10 means set)
type=Battery
present=1
status=Not charging
scope=Device
model_name=Samsung S Pen
```

The owner left the pen with its tip pointing right, towards the USB-C. That
calibrates `direction=2` as `tip-right`. It could not be removed or reversed,
so the other edge and `tip-left` remain physically unvalidated. Nor does the
protocol contain a percentage: UPower does not enumerate `gts9u-spen` and the
application shows "percentage is not exposed".

`ubuntu-gts9u-companion` 0.2.0 adds the D-Bus-activatable user service and
keeps the separation: only the backend knows sysfs; the window sees only D-Bus
properties. The real query was:

```text
PenState = 'docked'
PenOrientation = 'tip-right'
PenBattery = -1
PenCharging = false
KeyboardPresent = true
BluetoothAvailable = true
GestureAvailable = false
```

The UI was captured again under Xvfb on the tablet itself. The SVG appears
physically inverted, tip to the right, state `Docked` and charging with no
percentage. How it looks in the locked GNOME session is not considered
validated.

A rollback of `boot`, `vendor_boot` and the modules was saved before writing.
The final images were statically validated and read back from the partitions:

```text
boot        417d279d472665f0f51b591b0a29c3050de2c29a39ea25c32037510dcca3fba3
vendor_boot bf312f08a6876194e3ce30d52a81f8da23dd88132c4660698eb5cde17a69e6bc
```

Final health: no failed unit; `/dev/video20`–`23` present; ADSP `running`;
`iio-sensor-proxy` active and `HasAccelerometer=true`; the PipeWire sink and
source present; `paplay` exited 0; the Wacom and the EF-DX920 enumerated, and
the pogo diagnostics kept `attached=1 connected=1`. Real writing with the S Pen
after this reboot could not be repeated without somebody to move it; the same
input ABI was checked, but that is not raised to physical proof.

## Session 60 — Tab Companion, phase 3: remapping the EF-DX920

Date: 2026-08-12. The X910's open source clarified that model `0xd6` uses the
bypass path: the STM32 delivers Linux codes directly. Only the attested values
were preloaded: Galaxy AI 760 (`0x2f8`), DeX 701 (`0x2bd`) and Search 217.
There is no table for `Fn+F1`–`Fn+F5`; they stay unset until the owner can
press them.

`ubuntu-gts9u-companion` 0.3.0 extends the service with a non-exclusive
EF-DX920 reader, learning of the next key, per-mapping targets and a `uinput`
virtual keyboard. The `70-tab-companion-uinput.rules` rule grants the node to
the `input` group. The application adds a learn button and an application-ID or
command editor to each row.

The output path was validated in software without attributing events to the
real keyboard. `key-galaxy-ai='volume-up'` was stored temporarily, the same
D-Bus route the engine uses was invoked, and the virtual device observed:

```text
(true,)
Input device name: "Tab Companion virtual keyboard"
Event: type 1 (EV_KEY), code 115 (KEY_VOLUMEUP), value 1
Event: -------------- SYN_REPORT ------------
Event: type 1 (EV_KEY), code 115 (KEY_VOLUMEUP), value 0
Event: -------------- SYN_REPORT ------------
```

The mapping was restored to `none`. `BeginKeyCapture key-fn-f1` returned `true`
and published `CapturingKey='key-fn-f1'`; it was then cancelled without
changing the dictionary, which stayed:

```text
{'key-galaxy-ai': 760, 'key-dex': 701, 'key-search-settings': 217}
```

The Cover keyboard section was captured under Xvfb on the tablet with
`Connected; remapping active`, the eight rows and their controls. The `Target
for Galaxy AI` dialog was also opened with no traceback. What remains without
physical proof is each special key's event and the Fn learning: there was
nobody to press them, and a `uinput` injection only validates the output, not
what the STM32 emits.

## Session 61 — Tab Companion, phase 4: the EMR button and the BLE boundary

Date: 2026-08-12. S Pen identifiers were looked for in the Samsung Kernel and
Platform trees of the X910 open package. They contain no service UUID, no GATT
protocol and no format for Air action notifications. Together with the earlier
scan with the pen docked, this does not allow building a pairer that identifies
the device safely. None was added blindly.

The part independent of BLE was closed, though. `ubuntu-gts9u-companion` 0.4.0
opens the existing Wacom EMR and turns `BTN_STYLUS` into a single, double or
long press, with 300 and 600 ms windows. The state machine was exercised
directly on the tablet and delivered:

```text
single: ['gesture-single-press']
double: ['gesture-double-press']
long: ['gesture-long-press']
```

The real service publishes `ButtonActionsAvailable=true` and
`GestureAvailable=false`: the first means the button's path exists, the second
that there is no motion transport yet. The final UI capture literally shows
"Button actions ready; air motion still needs S Pen BLE".

The button's physical test was not possible because the pen stayed docked. Also
unimplemented and unvalidated are the up, down, left and right swipes and the
clockwise/anticlockwise circles. Their next step requires the owner: undock,
enable pairing, inventory the GATT and produce one event of each gesture; any
code written before that capture would be guesswork.

## Session 62 — Tab Companion, phase 5: documentary closure

Date: 2026-08-12. `docs/tab-companion.md` was added with the architecture, the
use of the controls, the meaning of the unknown level and a concrete physical
script for undocking, the opposite orientation, the button, the special keys
and the GATT.

The final installed state is `ubuntu-gts9u-companion` 0.4.0. The last reading
from the service was:

```text
PenState='docked'
PenOrientation='tip-right'
KeyboardPresent=true
RemappingAvailable=true
ButtonActionsAvailable=true
GestureAvailable=false
```

The final check kept zero failed units, `/dev/video20`–`23`, ADSP `running`,
`iio-sensor-proxy` active, the PipeWire sink/source and the EF-DX920 at
`attached=1 connected=1`. The partitions still booted are:

```text
boot        417d279d472665f0f51b591b0a29c3050de2c29a39ea25c32037510dcca3fba3
vendor_boot bf312f08a6876194e3ce30d52a81f8da23dd88132c4660698eb5cde17a69e6bc
```

Removal/reinsertion, the left-hand tip, physical presses, the Fn codes, pairing
and BLE movements are not raised to "works". The prior backup of `boot`,
`vendor_boot` and the modules stays outside Git in
`artifacts/backup-pre-spen-phase2/` and also on the tablet for recovery.

## Session 63 — automatic charging and physical keycodes

Date: 2026-08-13. The owner confirmed that removal, reinsertion and both S Pen
orientations work. The physical EF-DX920 was then captured, with nothing about
the table inferred: Finder 710, Fn+Finder/Settings 709, DeX 701 and Fn+F1–F11
as 757, 758, 759, 705, 254, 172, 224, 225, 113, 114 and 115. Fn+F12 produced
neither a Linux event nor an increment of the STM32's raw counter. The observed
association of Alt 56 with Fn+F3 was a pending learn: Fn+F3 had not been
captured and the next press was stored.

`ubuntu-gts9u-companion` 0.5.0 migrates the corrupt codes, separates Finder and
Settings, shows Fn+F1–F12 and preserves F6–F11's default actions. Learning now
says "Learn", allows cancelling and expires after eight seconds. The
`Adw.ComboRow`s were replaced with a window using `Gtk.ListBox`: it does not
recycle rows and avoids a different option being activated after scrolling. So
that a remap replaces rather than adds to the original event, the service grabs
the keyboard and relays every non-remapped event through uinput, including
`SW_LID` and the Caps Lock LED.

The official Wacom source confirmed the charging commands 0xe9/0xeb/0xec
(enable/start/keep-on). The kernel sends them automatically on detecting the
pen and queries 0xee every 30 seconds. On a clean boot, with no manual bind:

```text
[    4.542848] S Pen charging started
[    5.884772] S Pen garage reply: docked=1 direction=1 charge-state=5
[   36.060489] S Pen garage reply: docked=1 direction=1 charge-state=8
pen_docked:1
pen_orientation:upside
pen_charging:charging
gts9u-spen/status:Charging
```

The silo's protocol contains no percentage: the official driver does not read
one either. `CAPACITY=100` exists only when it returns `BLE_C_FULL`; the
intermediate level is left unknown until the Battery service is read over BLE.
A first boot suffered a Wacom `ETIMEDOUT` and required a manual bind; the early
failure was changed to `-EPROBE_DEFER`. The final boot bound the Wacom at
4.48 s.

Writing `/dev/block/by-name/boot` was tried first; that path does not exist
under Ubuntu and `dd` aborted before opening the destination. `/dev/sda21` was
then vouched for through `PARTLABEL=boot` and the size 100663296, only that
partition was written, and it was read back in full. The final booted state is:

```text
boot        ff013634e1bd551cf2adcf0c94865ae5c511aee70cd12bce74c0f227585bd294
vendor_boot bf312f08a6876194e3ce30d52a81f8da23dd88132c4660698eb5cde17a69e6bc
```

The final regression kept zero failed units, four camera nodes and the ADSP
`running`.
 The cover was
reconnected and the service published `KeyboardPresent=true` and
`RemappingAvailable=true`. A capture on the virtual keyboard confirmed that the
chosen mappings produce, among others, `KEY_MUTE` and `KEY_SYSRQ`; the last
special source recorded was Galaxy AI 760. The owner afterwards confirmed that
Galaxy AI, DeX, Finder, Settings and Fn+F1–F11 all work; the only inoperative
combination is Fn+F12, consistent with the absence of an event from the
controller. Visually validating the scrolled selector in GNOME remains before
that interface fix can be considered closed.

## Session 64 — BLE pairing initiated from the silo

Date: 2026-08-13. One UI does not present the S Pen as an accessory the owner
pairs by hand: leaving it docked is enough. The official Wacom source explains
the physical part: `0xea` resets the pattern and gives a minute of charging.
The writable attribute `pen_ble_reset` was added, restricted to a docked pen;
the kernel cancels the charging work, sends the command and resumes the
maintenance sequence. The new booted and verified image is:

```text
boot        bbaaf263740850c4f50906b96ae621b70cf732176e4c1a7760ed83f73e0f2f31
vendor_boot bf312f08a6876194e3ce30d52a81f8da23dd88132c4660698eb5cde17a69e6bc
```

The pen advertised the Samsung FD6C and FEF5 services simultaneously. A classic
`Pair()` attempt fails with Authentication Failed because it inverts the flow.
Decompiling `AirCommand.apk` showed the real behaviour: it connects the GATT
with the pen still unbonded, registers a pairing receiver and accepts the
consent request the S Pen itself initiates. Doing the same with BlueZ, the
physical test produced `Connected`, `Bonded`, `Paired` and resolved services,
with no PIN and no on-screen intervention.

FD6C exposes Battery Level, Button State, Status, FW Version, Mode, Battery
Raw, the manufacturing date and test/sensor channels. Battery Level returned
`64 00`, that is 100 %, and Mode accepted `10`. Button State's format matches
Air Command's: 0/3 are button up/down; 14/15 and 142/143 carry incremental
`dx`, `dy` and a sequence number. An unbonded capture had fallen through
exactly as the pen was taken out; that is now understood as a consequence of
not having completed the authorisation, not as an absence of motion data.

`ubuntu-gts9u-companion` 0.6.0 installs
`tab-companion-spen-pairing.service`. It runs as root only to write the Wacom
reset and talk to the system bus. Its agent rejects any request unless
`pen_docked=1`, the name is SPEN and the candidate advertises FD6C and FEF5;
afterwards it marks only that pen as trusted. It occupies BlueZ's default agent
only during the 65-second window and releases it at the end, so it does not
block pairing other accessories. The user service reads Battery Level, writes
Mode 0x10, subscribes to Battery/Button and decodes the motion samples. Both
services were installed and active. To test the definitive flow, only the S
Pen's incomplete bond was removed and the service restarted with
`pen_docked=1`: it opened a single window, paired with no interaction, and Tab
Companion published `PenBattery=100` and `GestureAvailable=true`.

With the pen out, the six trajectories were captured. The first series was
classified exactly as up, down, left, right, clockwise and anticlockwise. After
integrating the classifier, a second live series produced the six corresponding
events; an isolated repeat of the clockwise circle confirmed the area's sign.
The swipes use the dominant axis and a signed sum; the circles require a wide
excursion on both axes and an oriented area. The start of movement cancels the
long press so actions are not duplicated. Still open are the visual test with
different targets and reconnection after a full reboot of the tablet.

## Session 65 — Tab Companion 0.7 and cover families

Date: 2026-08-13. "Learn" was withdrawn: the DX920's codes were already
measured and keeping learning in production allowed a correct table to be
corrupted by the next stray key. The new global restore resets actions, targets
and physical codes. The action picker moved to rows with icons; "Open an
application" enumerates the visible desktops with their icons and a search box,
and "Run a command" opens an explicit field. The touch test on the tablet
scrolled the list before opening both routes without reproducing the wrong
row's selection. A real press of Galaxy AI revealed that `gtk-launch` is not
installed in the image; it was replaced with `Gio.DesktopAppInfo.launch()` and
the existing mapping to Settings then returned `TriggerMapping=true` with no
error. The learning D-Bus methods and their capture state were also removed,
not merely their visual controls.

The keyboard page now has three states. With no history it shows a welcome that
does not allow configuring; connected it shows model and name; disconnected it
keeps the mappings editable and offers an X to forget the device. The
compatible list comes from the X910 DTS's `stm32,model_name` property and from
the commercial names Samsung publishes: EF-DX900, DX910, DX915, DX920 and
DX925. The controller uses the protocol model and VERSION to tell them apart.
Only the available DX920 is considered validated; no key or touchpad operation
is inferred for the others.

The S Pen page removed the textual orientation and the redundant Bluetooth
data. It keeps the oriented drawing and presents a battery bar. The BLE
percentage is stored so that 100 % does not turn into "unknown" when the GATT
sleeps. The stock Air Command flow contains a KeepConnected policy and a GATT
disconnection path. The most aggressive interpretation was tested:
disconnecting while docked and connecting on removal. The physical transition
showed it does not work: outside, no advertisement appeared, not even during an
active scan, and BlueZ returned `org.bluez.Error.Failed`. The forced
disconnection was withdrawn; docking it remains the reliable mechanism for
waking and reconnecting a sleeping pen.

The whole interface, "About" included, was translated into English, Spanish,
French, German, Italian and Portuguese. An AST audit compared the 97
translatable strings against the six tables and found no gaps. Package 0.7.0
passed pedantic schema, desktop and AppStream validation; its SHA-256 is:

```text
ubuntu-gts9u-companion_0.7.0_all.deb
313a71fb6ee8dc860ec6a08edf87d846f795b2b8ccda97a26b6581492c2e1b2c
```

The built kernel registered the real DX920 as `Book Cover Keyboard Slim with AI
Key (EF-DX920)`, protocol model `0xd6`, V37, remapping available and zero
recoveries. The Android v4 bundle was validated, `sda21` vouched for by
`PARTLABEL=boot` and 100663296 bytes, the previous image backed up, and only
that partition written. The booted hashes are:

```text
boot        8d102343c34288e38c4322a5d7503dfc52274c2267abf0cc3db727e6b11ee6cd
vendor_boot bf312f08a6876194e3ce30d52a81f8da23dd88132c4660698eb5cde17a69e6bc
```

The subsequent regression kept zero failed units, ADSP `running`, four-speaker
output and DMIC input in PipeWire, four V4L2 cameras and the four libcamera
relays. The sensor and pogo firmware `oneshot`s finished with `Result=success`;
Companion's service published the DX920 connected and kept the S Pen's real
battery at 100 %. Removal produced `PenState=paired` and the absence of
advertisement described above; reinsertion was used to recover the link with
the definitive policy.

## Session 66 — Tab Companion 0.8 and EMR policies

Date: 2026-08-13. The S Pen still had a bond in BlueZ that the pen no longer
recognised after the previous disconnection test. Only that bond was removed
and the silo's flow paired it again with no interaction. The service now
repairs that case automatically after four consecutive failures, and only if
the S Pen is still docked, and waits for the adapter during boot.

"Simulate a key" adds a graphical keyboard with F1–F12, alphanumerics,
navigation and modifiers. It also captures any physical keyboard while the
picker has focus. The backend validates the evdev codes and emits the
combination through uinput; the real interface correctly showed `Ctrl+Alt+T`.
"Toggle the flashlight" was verified with two D-Bus activations that produced
the physical states `on` and `off`.

Fn+F12 disappears because firmware V37 produces no event. The factory values
assign Galaxy AI to Tab Companion, Finder to search, Settings to Settings,
Fn+F1/F2/F3 to Files/browser/terminal, Fn+F4 to applications, Fn+F5 to the
overview and DeX to maximise/restore. Fn+F6–F11 keep the native home,
brightness and volume events.

The kernel shares Wacom proximity with the Goodix. When rejection is active,
the Goodix releases its slots and discards fingers from the first hover. The
second option disables the Wacom's coordinate IRQ with `pen_docked=1`, but
keeps PDCT, charging and BLE. The logs showed `digitiser disabled` on
insertion and `enabled` on removal; the owner physically confirmed both options
behave as expected. Udev lets the user write only these two boolean policies.

App 0.8.0 and the Android v4 bundle passed all their validations. The `boot`
partition was vouched for by label and size, a recoverable copy saved, and only
that partition written. The booted hashes are:

```text
boot        524a4ded657f1419640b051f580f8519f6fa79af1aac5e4f68a4505bb042ca02
vendor_boot bf312f08a6876194e3ce30d52a81f8da23dd88132c4660698eb5cde17a69e6bc
```

The package reproduced from the definitive tree passed `compileall`, strict
GSettings schema, Desktop Entry and pedantic AppStream:

```text
ubuntu-gts9u-companion_0.8.0_all.deb
b0eca63313975a28634bc367106bc42556aa939abb4baef788ec3137f6b75dd3
```

The first reboot after the final image stopped exactly at `PM: suspend entry
(deep)`, inside the pre-existing `pm_test=platform` that recovers the ANA38407
panel after a cold boot. Tab Companion's hardware service never started and
there were no Wacom or Goodix messages preceding the hang. After forcing a
reboot, the same cycle returned in about seven seconds (`PM: suspend exit`) and
the system booted normally. It is therefore an intermittent failure belonging
to the panel recovery, not a regression observed in the S Pen's two new
policies.

The recovered boot's regression left zero failed units, both Companion services
active and warning-free, the DX920 connected and remappable, the S Pen paired
at 100 % and charging, and both sysfs policies active. The owner had already
physically validated finger rejection during hover and the digitizer being
disabled and re-enabled.

## Session 67 — the real semantics of the default values

Date: 2026-08-13. The first implementation explicitly stored the utilities
chosen for Galaxy AI, DeX, Finder, Settings and Fn+F1–F5 as custom actions.
That made the picker show "Open an application", "Simulate a key" or
"Overview", when conceptually they should have been the behaviour of "Keep the
default action".

Tab Companion 0.8.1 now keeps every keyboard GSettings key at `none`. The
backend distinguishes two classes: Fn+F6–F11 already have a useful Linux event
and are relayed intact; the special keys with no native function are replaced
by the port's base utility only while they remain at `none`. A user's selection
takes priority, and returning to "Keep" recovers the base utility without
keeping a hidden mapping. Migration 4 converts only the exact combinations
0.8.0 had installed, respecting any different customisation.

The README was reduced to compatibility, installation and end-user-facing
features. The evidence, the port's decisions and the detailed limitations stay
in `docs/`.

Package 0.8.1 passed `compileall`, the strict schema, Desktop Entry and
pedantic AppStream, and was installed over 0.8.0:

```text
ubuntu-gts9u-companion_0.8.1_all.deb
648267df87b9ec5810613e9278e6dd7eafea83b348ce272b87c66c94119902ef
```

The migration on the tablet ended at version 4. Galaxy AI, DeX, Finder,
Settings and Fn+F1–F10 were left at `none`; a later customisation of Fn+F11
with its command target was preserved. `TriggerMapping` correctly ran Galaxy
AI's base utility and two DeX activations maximised and restored without
writing any mapping. Both services stayed active and warning-free.

## Session 68 — the S Pen's remote modes, pointer and haptics

Date: 2026-08-13. Tab Companion 0.9.0 separates EMR writing from the BLE remote
features. The `spen-remote-enabled` preference travels over D-Bus from the user
service to the root pairing service. Turning it off makes the latter cancel its
window, disconnect the S Pen alone and keep the BlueZ bond; it also persists
the state in `/var/lib/tab-companion` so it does not reconnect before login.
Turning it on allows connection and pairing again. The interface hides the
battery and the remote controls while it is off and keeps only docked/undocked,
but it does not touch the independent Goodix/Wacom policies.

Pointer mode takes PenMouseS as its conceptual reference, which integrates the
S Pen's gyroscope increments to move a cursor and uses the button for
click/drag. In GNOME it needs neither an overlay nor accessibility: the backend
creates `Tab Companion S Pen pointer`, a relative `uinput` device with `REL_X`,
`REL_Y` and `BTN_LEFT`. The same Button State packets that feed the gesture
classifier are routed to the pointer instead. Y is inverted, sub-pixel
remainders are kept, and configurable sensitivity, exponential filtering and
acceleration are applied. Gestures and pointer cannot be active at the same
time.

The orientation failure on inserting the pen the other way round came from
`disable_digitizer_when_docked`: it switched off the main I²C IRQ, but the
orientation/charge `GARAGE_STATUS` replies travel on that same line. The driver
now keeps the IRQ, consumes the garage replies first and only then discards the
coordinate packets if the policy is active. Every PDCT edge also clears the
previous orientation until a fresh reply arrives, so a stale direction is never
shown.

The downstream DTS identifies the actuator as `samsung,dc_vibrator`, type
`COINDC`, with its enable on TLMM GPIO18. Mainline is configured with
`CONFIG_INPUT_GPIO_VIBRA=y` and a `gpio-vibrator` node; its interface is evdev
`FF_RUMBLE`. The backend loads and reuses one effect and offers `Vibrate(uu)`
on the session D-Bus. The GPIO does not regulate amplitude, so the keyboard's
apparent intensity is represented by pulses of 8, 14 or 22 ms.

GNOME Shell 46 ships no native haptics option for its on-screen keyboard. The
`tab-companion-haptics@agcarbajo` extension listens only for `TOUCH_BEGIN`
inside the keyboard's visible actor and checks the `keyboard-key` class before
requesting the pulse. A helper adds its UUID to `enabled-extensions` without
replacing the owner's extensions. The app adds a third page with a switch, an
intensity setting and a momentary test button.

Before rebooting, the undocked pen's BLE connection was preserved. After
several hours Battery Level was still delivering 100 %, so no intermediate
value is invented or interpolated: that physical validation is still pending.

The first write updated only `boot`. The new kernel booted without failures,
but `/proc/device-tree` showed that Samsung's ABL was still taking the DTB from
`vendor_boot`: the `vibrator` node did not exist yet. Before updating that
partition, both v4 images were extracted and their sections compared. The
command line, the platform ramdisk, its table and the bootconfig were identical
byte for byte; the only difference was the DTB, 177,740 against 177,812 bytes.
The previous image was backed up and verified and the new one written to the
partition vouched for by label and size.

The booted hashes and the recoverable backups are:

```text
boot new             5f33dcd527bf0693ddf5b6ae1100912f82d0f055ab7f965cabb89053f1df5e0b
boot backup          524a4ded657f1419640b051f580f8519f6fa79af1aac5e4f68a4505bb042ca02
vendor_boot new      ded9ae5ddd3f86ab0ff0c77c410553f86c8d900f663751c95c9751efc5bfb98b
vendor_boot backup   bf312f08a6876194e3ce30d52a81f8da23dd88132c4660698eb5cde17a69e6bc
```

The second boot left zero failed system and user units. The live DT contained
`gpio-vibrator`, the driver published `event2` with `FF_RUMBLE` and
`HapticsAvailable=true`. `Vibrate(500, 65535)` returned success and the
`gpio:gpio_value` trace measured global GPIO 554 at 1 and, 500.741 ms later, at
0. That validates the whole software and electrical control path; what remains
is for the owner to confirm the physical sensation.

With the S Pen already asleep after the reboot, the remote cycle `true → false
→ true` was tested without losing a useful connection. The privileged state
changed 1/0/1, BlueZ kept the bond, and `ignore_finger_while_hovering` and
`disable_digitizer_when_docked` both stayed at 1. The final policy does not try
to connect a sleeping bond while the pen is out of the silo; it waits for an
insertion and avoids periodic errors in the journal.

The pointer's parser was exercised with a press, five signed samples and a
release: it produced `BTN_LEFT` down/up and coherent positive displacements
after inverting Y. The live device publishes `EV_KEY`, `REL_X` and `REL_Y`. The
app opened for eight seconds in the Wayland session with no exception. The
helper added the haptics extension while preserving the four existing ones; it
will load at the owner's next graphical login, which had not yet happened after
the reboot.

The definitive reproducible artefact passed `compileall`, the strict schema,
Desktop Entry, pedantic AppStream and syntactic validation of the extension:

```text
ubuntu-gts9u-companion_0.9.0_all.deb
18e7e34641184806e1c6ff8d1204f5851059cb2250a0a8fde543dd6996d2996a
```

## Session 69 — recovering the BLE bond after a reboot

Date: 2026-08-13. With the pen docked, the silo reported orientation and
charging at 90 %, but the previous BlueZ bond rejected `Connect`. The recovery
correctly reached four failures, removed only the stale SPEN and opened another
window with the reset command. The device reappeared as visible and unpaired,
but got no further: BlueZ recreated it before the `InterfacesAdded` receiver
could act, and afterwards emitted no other relevant property.

During the bounded 65 seconds of pairing, the service now also walks BlueZ's
current object set and applies the same strict validation of name, UUIDs, silo
and candidate. That closes the race without widening which devices it may
authorise and without repeating resets outside an active window.

Tab Companion 0.9.1 was installed with the S Pen still docked. The service
opened the window, found the already-visible object, completed
`Bonded/Paired/Trusted` and BlueZ left it connected with no additional physical
intervention. The backend published `GestureAvailable=true`; Battery Level went
from the initial 90 % reading to 80 %, also closing the pending validation of
intermediate percentages.

```text
ubuntu-gts9u-companion_0.9.1_all.deb
3cac7cb597659ab403810323bd54948e2262896a263b9d6f8a166cf3e8671471
```

## Session 70 — a raw-gyroscope pointer and notification haptics

Date: 2026-08-13. The pointer's first version created the `uinput` mouse
correctly, but left the S Pen in mode `0x10`: Button State only supplies
movement during gesture recognition and the cursor stayed still. Decompiling
the stock controller distinguishes `DEFAULT` (`0x10`) from `SENSOR_ON` (`0x04`)
and enables Raw Sensor Data separately. A physical capture in the latter mode
produced 430 samples in 18 seconds. The first guided test gave, for horizontal
movement, a gyro X deviation of 1,643 against 376 on Y, and for vertical
movement 1,455 on Y against 1,135 on X. The later visual test discovered that X
was in fact the pen's lengthwise roll: it moved the cursor when the pen was
rolled, and the Y axis changed sign when it was rotated 180°. The final
correction discards gyro X and uses the accelerometer's gravity in the local
Y/Z plane. It projects gyro Y/Z onto gravity for the horizontal axis and onto
its perpendicular for the vertical, keeping both invariant under any axial
roll. The dead zone is 120 counts.

The backend subscribes to Raw Sensor Data only in pointer mode and with the pen
out, integrates the samples at about 24 Hz, and returns to `0x10` when gestures
are selected or the pen is docked. That last condition fixes a physically
observed regression: `SENSOR_ON` during charging made the link drop before the
pairing and battery cycle finished. After installing the fix, BlueZ kept
`Paired/Bonded/Trusted/Connected` for more than 20 seconds with `pen_docked=1`
and charging active. On removal, raw mode returns with no intervention.

Sensitivity, smoothing and acceleration were recalibrated for the sensor's real
range. With the service installed, moving the pen generated 621 non-zero
relative events in 18 seconds, with both signs and both axes, through
`/dev/input/event9`. The subjective visual confirmation of direction and speed
remains.

The keyboard's three pulses go from 8/14/22 to 12/22/34 ms. The service also
translates the requests of whatever extension copy GNOME Shell may already have
in memory, so it does not require logging out after an update. For
notifications, depending on a JavaScript reload under Wayland was avoided: the
service itself watches the standard `org.freedesktop.Notifications.Notify`
calls, groups duplicates over 300 ms and applies a 60 ms pulse when the
preference, on by default, is enabled. A real notification traced GPIO554 high
for 64.456 ms.

Package 0.10.0 passed Python compilation, JavaScript syntax, the strict
GSettings schema, Desktop Entry and pedantic AppStream:

```text
ubuntu-gts9u-companion_0.10.0_all.deb
f5cccca41923c9230aae28ba8f9f08964c6614e6053749adfcf8e08d050b18ef
```

## Session 71 — detecting and recovering from a phantom GATT connection

Date: 2026-08-13. Although BlueZ published `Connected`, `Paired`, `Bonded`,
`Trusted` and `ServicesResolved` all at once, the gestures and the pointer
received no data and the app showed 0 %. Inspecting every characteristic
separated the surface state from the real link: every `ReadValue` and
`WriteValue` failed, Mode kept a cached `0x04` despite Gestures being selected,
and Battery Level reproduced the old `00 00`. That zero was therefore not a
physical measurement.

Restarting `bluetooth.service` alone made the S Pen's pending removal
effective. The silo's service authorised it again with no interaction; a real
GATT read returned Battery Level `[100, 0]`, Mode accepted `0x10` and Tab
Companion published 100 %, charging and gestures available.

Tab Companion 0.10.1 no longer accepts a stored battery notification until
`ReadValue` has answered on the current connection. It also requires a
successful GATT operation before announcing gestures as available. Three
consecutive GATT failures with the pen docked ask the privileged service to
replace that bond alone; if BlueZ does not answer `RemoveDevice`, it restarts
the Bluetooth daemon alone and continues the bounded pairing.

The new route was tested end to end by forcing its call on a healthy bond: it
went through unpaired, opened the silo's window and returned by itself to
`Paired/Bonded/Trusted/Connected`, Battery Level 100 % and
`GestureAvailable=true`. With the pen out, a final switch opened Raw Sensor
Data and received new samples in Pointer; returning to Gestures closed it, kept
Button State subscribed, and the direct reads returned Mode `[16]` (`0x10`) and
Battery Level `[100, 0]`.

```text
ubuntu-gts9u-companion_0.10.1_all.deb
a3aeabd722727df80c2d8ad2370d95643b46729fafbe10ec75c6400a7f8c0c75
```

## Session 72 — direction, horizontal travel, haptics and credits

Date: 2026-08-13. The visual test of 0.10.1 confirmed that the axial-roll
compensation was now stable, but both axes felt inverted and the horizontal
travel fell short of the panel's width. The final output inverts X and Y and
applies an additional 1.6× gain to X, close to the screen's 2960:1848 ratio.
Sensitivity, acceleration and smoothing still act before that geometric
correction.

The keyboard's haptic levels increase from 12/22/34 to 24/42/66 ms. The new
extension requests those values directly; the backend still translates 8/14/22,
the tokens of the copy GNOME Shell may keep loaded, so the improvement is
immediate without logging out. All three physical calls returned success with
the motor available.

"About", the README and the documentation now credit
[PenMouse S](https://github.com/jojczak/PenMouseS), by Jakub J (`@jojczak`), as
the conceptual inspiration for the air pointer and link to its GPL-3.0
repository. It is made clear that Tab Companion reuses none of its Android
code: the BLE + `uinput` route is an independent native Linux implementation.
The installed libadwaita API confirmed support for the additional link.

After installing 0.10.2, the S Pen stayed connected, published a new real
battery measurement of 70 % and kept gestures available. With Pointer left
selected, Raw Sensor Data stayed subscribed and delivered a fresh sample.

```text
ubuntu-gts9u-companion_0.10.2_all.deb
215450fcdff6a6ccf0f90da6dee95ac07064e5e62545122a09923dcf9ead7c7b
```

## Session 73 — a held left click in pointer mode

Date: 2026-08-13. Raw Sensor Data delivered 1,094 packets of 13 bytes over 45
seconds: a marker and six accelerometer/gyroscope integers, with no button
field. Button State did not notify during that capture in `SENSOR_ON`. PenMouse
S's code likewise confirms that its SDK registers movement and button as
independent units and keeps the `ACTION_DOWN`/`ACTION_UP` events to build the
held gesture.

Linux already delivers the side button through the digitizer as `BTN_STYLUS`,
but `_pen_button` always sent it to Gestures' single/double/long timer. In
Pointer it is now routed straight to the virtual mouse: down produces
`BTN_LEFT=1`, the raw movement continues without releasing it, and up produces
`BTN_LEFT=0`. That allows a normal click and a continuous drag. Changing mode,
disabling the remote features or losing the reader forces a release so the
button cannot get stuck.

An isolated backend test confirmed the exact sequence `[('BTN_LEFT', 1),
('BTN_LEFT', 0)]` and that duplicate events generate no additional edges.
0.10.3 was installed with Pointer active, a healthy GATT bond and a new real
battery reading of 40 %. Physical validation of the drag awaits the owner's
interactive test.

```text
ubuntu-gts9u-companion_0.10.3_all.deb
7a7c8398382eccbeda82af20d0a4f3e6c73f8a63291bab704d684b0b12fbeb6f
```

## Session 74 — fast recovery of the BLE bond after a reboot

Date: 2026-08-13. After a reboot, the S Pen stayed docked but the stored bond
would not reconnect. The service did detect the case and eventually recovered
it on its own, but too late: four failed `Connect` calls, each able to wait
some 30 seconds, delayed the new pairing to 91 seconds. At 15:01 it removed the
S Pen's bond alone, opened the silo's advertisement and returned to
`Paired/Bonded/Trusted/Connected`. A direct GATT read confirmed the recovered
state was real: Battery Level `[80, 0]` and Mode `[16]`, not properties stored
by BlueZ.

Tab Companion 0.10.4 now bounds each connection to 12 seconds and replaces the
bond after two failures, `NoReply` included. Both connection-driven recovery
and the one requested by the GATT backend use the same asynchronous removal;
the latter also accepts the `Paired` but disconnected state. If the
advertisement window expires, the service releases its repair state and reopens
it without requiring the pen to be removed. Also, the D-Bus object is no longer
exported until BlueZ and its adapter exist, avoiding the duplicate handler
observed across two boots.

The complete route was deliberately repeated with the pen docked after
installing 0.10.4. `RecoverStaleBond` removed the bond, enabled the
advertisement and left it paired and connected again with no interaction. The
final reads returned Battery Level `[100, 0]`, Mode `[16]` and Tab Companion
published `GestureAvailable=true`.

```text
ubuntu-gts9u-companion_0.10.4_all.deb
70e3d50715782081c1e0641178bced1505def8437487bed8cd6955b44619f5d9
```

## Session 75 — the order of the S Pen's controls, and a compact haptics page

Date: 2026-08-13. The S Pen page now presents Battery and Behaviour before
Remote features. That way the digitizer's two independent settings are read
before choosing whether Bluetooth is used for Gestures or Pointer. It changes
neither the logic, the stored values, nor each group's dynamic availability.

The Haptics page removes the `Adw.StatusPage` header with the phone icon.
On-screen keyboard and Notifications become the initial content, avoiding the
empty height and the unnecessary vertical scrolling observed at 960 × 760. The
package kept the strict GSettings, Desktop Entry and AppStream validations.

```text
ubuntu-gts9u-companion_0.10.5_all.deb
1b8455b62ce72db71d18300c5d1ff0313b4ef7366c2855f41c5bc8f28d81c0d9
```

## Session 76 — a haptic test faithful to the keyboard's intensity

Date: 2026-08-13. The Test vibration button used a fixed 100 ms pulse, so it
represented none of the three configurable levels. It now reads
`keyboard-haptics-strength` at the moment it is pressed and uses the same table
as the on-screen keyboard: Light 24 ms, Medium 42 ms and Strong 66 ms, at
magnitude 65535. Out-of-range values are clamped to the valid extreme, as in
the GNOME Shell extension. The subtitle makes clear that the test reproduces
the intensity chosen for the keyboard.

```text
ubuntu-gts9u-companion_0.10.6_all.deb
0dc708f72abc8fa95d77a7ac5a3a21ea6f56109d2940e98d8d81f8c3851a945c
```

## Session 77 — explicit text for the intensity test

Date: 2026-08-13. The Intensity selector now states that its value applies to
the on-screen keyboard and to the test button. The row is titled "Test the
selected intensity" and explains that it reproduces exactly the vibration of an
on-screen keyboard press. The button keeps the short label "Test". The
equivalent texts were updated in Spanish, French, German, Italian and
Portuguese; 0.10.6's 24/42/66 ms logic does not change.

```text
ubuntu-gts9u-companion_0.10.7_all.deb
dabd01e77dfca45e1d59e1699a17602352389551588787eca1927c5bf4e86c91
```

## Session 78 — remote features conditioned on Bluetooth

Date: 2026-08-13. `BluetoothAvailable` only checked for the existence of
`/sys/class/bluetooth/hci0`, which persists even when the user switches the
adapter off. The backend now queries `org.bluez.Adapter1.Powered` and listens
for its change over D-Bus. Effective availability is the conjunction of that
state and the `spen-remote-enabled` preference.

Switching Bluetooth off clears the GATT and the pointer, the privileged service
stops connecting, and the UI shows the same reduced state as with the remote
features disabled. The switch appears off and cannot be operated; a row
explains that Bluetooth has to be turned on. The GSettings value is not
overwritten. On receiving `Powered=true`, the backend and the window
immediately restore that stored value: off stays off, and on re-enables modes,
battery and actions. Late button or raw-sensor events are also blocked while
the effective state is false.

The physical test measured 0.23 s from the switch-off command to the false
D-Bus property. Powering the controller up fully took 1.8 s; the restoration
happened on that same `Powered=true` signal. Both stored values were verified
and the S Pen returned to `Connected`, Battery Level 70 % and gestures
available. An `UnknownObject` observed when `RemoveDevice` invalidated the bond
between reading and writing `Trusted` is treated as the expected race, with no
traceback and no interruption of the GLib loop. A second physical cycle with
that fix finished with no traceback, kept the preference active and published
Bluetooth available, Battery Level 90 % and gestures available again.

```text
ubuntu-gts9u-companion_0.10.8_all.deb
bf9e04819278947039d29d26710bce277ea8f8287aa0868722530637bc78781b
```

## Session 79 — the experimental base of the EL721/UDFPS reader

Date: 2026-08-13. The R03 overlay and Samsung's GPL driver identify the
under-display reader as a secure EgisTec EL721: PM8550B's LDO2 at 3.3 V,
enable/reset on GPIO155 and model `X916`. The SPI is assigned to TrustZone; it
is not correct to expose raw images or transactions from Linux.

Four independent layers are prepared: a minimal power/reset controller with
`/dev/esfp0`, QTEE integrated for future access to the signed `securefp`
application, the ANA38407 panel's optical/circle mode with brightness
restoration and a watchdog, and Goodix exclusion limited to the sensor's
rectangle. The intention is that a read should not press controls under the
finger without blocking the rest of the screen.

This infrastructure does not yet turn the reader into an authentication source.
`libfprint` does not support the EL721 and Samsung's stack depends on TrustZone
and Android components. Analysing the firmware fixes the chain
`fingerprint-service` → `libsfp_sensor` → `libsfp_teegw` → `libQSEEComAPI` by
objects → compatible AppLoader UID 122 → `lookupTA("securefp")`. `securefp` is
a preloaded TA, not a missing `.mbn`; the optional `fpta` path is empty and
`authnr.mbn` corresponds to a different authenticator.

Still pending are physically starting the four layers, checking
non-destructively that UID 122 returns `securefp`'s object, and creating a
secure backend for `fprintd`. Enrolment, verification, unlocking and GDM remain
marked unavailable until fully validated. The architecture, ABI and test
protocol live in `fingerprint-reader.md`.

The final implementation was rebuilt from scratch on Linux `7.2-rc3` with
Clang 22. The resulting kernel, DTB and configuration contain the EL721, QTEE,
panel FOD and Goodix FOD symbols:

```text
Image.gz  5057fcc1eba5d3b824fd4c6315f791df43ee5886e34fce577431403fb5f75ea5
DTB       b69f6d138e028ca507007e037d307c6ba859959d883a9be09999243d2520f3a9
config    16421292ef8d604803d44cbd202521004d42832ac230c4bc2d2caa6f9fb09a8c
```

The Android v4 bundle passed every static check: partition sizes, AVB, legacy
LZ4, the appended DTB, `vendor_boot`'s DTB, symbols and configuration. Its two
modified images were:

```text
boot.img        fe1f274af9d3ed524007093560bd3ab46158c2eb13717c19327407f341add041
vendor_boot.img 8599e133383e4e50227d9e2ac480bd3e0c53aa162dfad9bd83e1ee52b2ae63d9
```

Before the first write, `boot`, `init_boot`, `vendor_boot` and the modules were
saved off the device. An immediately preceding build, functionally equivalent
apart from code cleanup and powering the EL721 down on suspend, was written and
verified by reading back before rebooting. The tablet did not announce SSH
again after that reboot. There is still no console or USB to distinguish a
halted boot from the port's known problematic first reboot, so the incident is
not attributed to the reader and the boot is not considered validated. The
final bundle is not written again blindly: the machine will first be recovered
with a forced reboot and the documented non-destructive matrix run.

The probe `scripts/probe-qtee-securefp.c` was also pinned. Its source has
SHA-256 `06c664e0d322c8c6cbcb034274ad34c5ea9cdb6f8c68b1af0842c0e898bdf51e` and
the static AArch64 test binary
`44fc85bbb1547b9007e9adffc997e4662ac7bed3f3ce4fbd056a6e8d0260fba1`. It only
queries `lookupTA("securefp")`; it neither opens the application object nor
runs biometric operations.

## Session 80 — recovering from the bootloop, and experimental isolation

Date: 2026-08-13. After writing the first UDFPS infrastructure, ABL accepted
`boot`, `vendor_boot` and `init_boot`, decompressed the kernel and jumped to
it, but the tablet rebooted before mounting Ubuntu. `/proc/last_kmsg` kept
fourteen attempts with the same sequence and no `Linux version`, no panic and
no new journal: it was not an AVB rejection, a bad initramfs or root filesystem
corruption, but a regression earlier than having persistent logs.

A second image was tried with QCOMTEE converted from built-in to a signed
module, blocked from automatic loading. Its partitions were verified by hash
after writing and `init_boot` was left intact, but it did not reach SSH either.
That rules out QCOMTEE's probe as the sole cause; another experimental layer or
an interaction takes part in the reboot.

The strategy is corrected so that a normal build is conservative: it recovers
from `5046f92` the exact DT and panel of the last validated boot, does not
compile the EL721 and does not apply the Goodix FOD changes. QCOMTEE keeps the
base configuration's modular state and is packaged signed, but a modprobe rule
prevents automatic loading. Only `ENABLE_FINGERPRINT_EXPERIMENTAL=1` introduces
the DT, panel, EL721 and Goodix-FOD. That way the sensor, panel, touch and TEE
can be reintroduced one layer at a time from a known boot, instead of flashing
all four together again.

The second image was out of reach of ADB and SSH after four minutes. With no
remote key control and no bootloader channel, it cannot be returned to TWRP by
software. The prepared recovery uses byte-for-byte backups of the last
physically validated boot, not an approximate rebuild:

```text
boot        5f33dcd527bf0693ddf5b6ae1100912f82d0f055ab7f965cabb89053f1df5e0b
init_boot   8fab5f775748614ee7ff84e62e765d4f8bfeb0ed4f142ba0aaa89ae86be09d26
vendor_boot ded9ae5ddd3f86ab0ff0c77c410553f86c8d900f663751c95c9751efc5bfb98b
modules     ee5ef8855223d8229c764980bc10ba36aa4d8e6eb487dac4ed672f8fd3185f5f
```

With TWRP available again, `boot`, `vendor_boot` and the modules were restored
from those three backups. The transferred files were verified before writing
and both partitions read back in full afterwards; the hashes matched.
`init_boot` stayed intact and also kept the backup's hash. The failed module
tree was set aside with the suffix `.20260813-fingerprint-failed`, and the
active tree no longer contains `qcomtee.ko` or the temporary modprobe rule.

The first boot after that exact restoration published neither ADB nor SSH in
four minutes. Since the restored set is byte for byte the same one that booted
and was validated in session 74, it is treated as the known first-reboot hang
or as a persistent hardware state, not as evidence of another difference in the
images. A forced physical reboot is needed before continuing the A/B tests.

## Session 81 — isolating the panel, and secure transport of `fingerpr`

Date: 2026-08-14. The experimental selector was split into three independent
layers: panel FOD, Goodix-FOD and EL721. A from-scratch build with only the
panel enabled booted correctly, so that layer is ruled out as the cause of the
initial bootloop. On hardware, HBM, the 15-second watchdog and the exact
brightness restoration were validated. The DSI host returns `0` on a correct
generic write and the driver wrongly required the byte count; with that
contract corrected, `fod_circle=1` reaches the DDIC but produces no visible
image. The Samsung kernel first loads a Self Display image and validates its
checksum.
 Porting that graphics subsystem was
ruled out and a GNOME target added that follows rotation, blocks the touches
outside it and compensates the global HBM with the official 420/650 cd/m²
ratio. The circle is left out of the mask and receives the optical maximum,
while the background keeps its previous luminance. The owner physically
validated position, HBM and compensation.

QCOMTEE stays modular and blocked from automatic loading. Loaded by hand it
publishes `/dev/tee0`, reports QTEE 5.2.0 and passes Qualcomm Diagnostics. The
UID 122 AppLoader answers, but `lookupTA("securefp")` returns `2` even from the
kernel's internal privileged client. `NON-HLOS.bin` contains the signed image
`fingerpr.b00`–`b08`; it was reassembled with the Qualcomm driver's ELF
offsets, at 13,725,784 bytes. The upstream allocator cannot reserve that block
because of `MAX_ORDER`, so only messages larger than 4 MiB now go through
CMA/`qcom_tzmem`; normal control keeps the upstream path. The complete image
reaches `loadFromBuffer`, but TrustZone returns `1` for both the `securefp` and
`fingerpr` names, from user space and from the privileged client alike. Neither
the application object was obtained nor a biometric operation run.

The corrected panel image was verified by AVB and by reading the partition in
full after writing it:

```text
Image.gz  3f62bafce653866570c79ed7a829cc47c143cb0ff08e79d335040b7768cadded
DTB       613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4
boot.img  f08073bb6c1295775d3043c2ceb6ad0e72fa4c761fc96547240cc50e5a71bc2e
modules   b7976a8cd4eb4a2e4af01a4f63bce4c69298dc830401ae375cf65374664e6768
```

## Session 82 — real FOD events and regional isolation

Date: 2026-08-14. The Goodix-FOD layer was started independently alongside the
panel. The first version found a false address (`0x06015447`) because the
mainline structure omitted the 10 reserved bytes Samsung places at the end of
`IC_INFO.misc`. A raw read of the 181 bytes the GT6936 publishes confirmed the
real SEC extension: sponge `0x00029800`, length 1024.

The reserved field and the complete stock sequence were restored: before every
sponge access `0x9f` is sent with normal mode, and after writing it is
confirmed with `0xf2`. The order rectangle → FOD bit → `fast/strict` policy is
also respected, with `fod_property=3` by default and adjustable live.

On the physical tablet the central touch produced first `released 911 2808` and
then `released 945 2809`. A simultaneous listen on the Goodix device received
no tracking ID, no `BTN_TOUCH` and no normal coordinates, so the contact inside
the sensor is isolated from GNOME. The booted image was verified before and
after writing:

```text
Image.gz  861624962e12df39de7945430b83468736bf72286feedbbd46a159e5a9415e22
DTB       613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4
boot.img  8f260c5c74606886fd961cfdabfee7400c3430ec30210256ab1a560f77ebe0f3
modules   7528c67b18c6a0a842f069bc8aa54203f7adfd1f40a7980d8d909d2fa502521a
```

The next blockage is no longer the panel or touch: TrustZone still does not
publish the `securefp` logical object, so no working device is installed or
announced in `fprintd` yet.

## Session 83 — the `dualfp` TA accepted, and BAUTH transport

Date: 2026-08-14. It was first checked that there was no firmware mismatch: the
active `apnhlos` partition matches the analysed official `NON-HLOS.bin` byte for
byte (SHA-256 `1aa9de73…`) and the `tz` partition matches the official `tz.mbn`
(`865b32e1…`). An incompatible version and anti-rollback are ruled out as
explanations for the earlier rejection.

Analysing all of `NON-HLOS`'s split images identified two distinct pieces.
`fingerpr.b00`–`b08` assembles a generic Qualcomm QFP engine of 13,725,784
bytes. `dualfp.b00`–`b08` assembles 19,927,128 bytes and contains the
Samsung/Egis implementation of the EL721, BAUTH, matching and templates. The
name `securefp` used by `libsfp_teegw` is logical; it is not the name of the
image that had to be loaded.

QTEE's upstream 4 MiB message limit prevented testing `dualfp` with
`loadFromBuffer`. Instead of enlarging the message, a TEE memory object was
reserved, the signed image copied into it, and the UID 122 AppLoader's
`loadFromRegion` called. TrustZone accepted `dualfp`, returned its
QSEEComCompat handle and unloaded it cleanly. The tablet stayed stable, QCOMTEE
was unloaded again and `sensor_power` stayed at zero.

The `sendRequest` envelope and the two memory objects Samsung uses for
`BAuth_Type_Check` were also reconstructed. The transport returns success (`0`)
with both UID 0 and UID 1000. Later analysis of `SensorInfo` confirmed the
exact stock mapping `EL721 → name 21 → type 8`; repeating the request with the
correct identifier `21`, the TA keeps the result `29` while the physical sensor
is powered down. That rules out the wrong enum and leaves the same query after
the deferred power-up as the next test. No capture was run.

The stock overlay also clarifies that the X910 does not use the supposed LDO2
as a Linux regulator: `etspi-ldoPin` is TLMM GPIO91 and `etspi-sleepPin` is
GPIO155. The controller was corrected to map both lines through a platform GPIO
table created after boot. Their acquisition and switching remain deferred until
an explicit operation, so the DTB that caused early resets is not modified
again. The object compiles cleanly with Clang 22; this new sequence is not yet
flashed or enabled without a physical recovery route available.

The whole stack was rebuilt from scratch on Linux 7.2-rc3 with Clang 22. The
compilation took 575 seconds, confirmed `FINGERPRINT_EGIS_EL721=y`, `QCOMTEE=m`
and no longer contains the kernel-specific `securefp` probe/loader. The prepared
artefacts, still unflashed, are:

```text
Image.gz  d5021f8c99332149454a3c79fbfa7f648d10ae4abc9b8e1b15ffae5bc93e8e56
DTB       613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4
config    db2503329105ca65454354262958ea9515e2028961e4c3c02e18625bc81e0c78
```

`test-el721-type-check.sh` was also prepared for the new kernel's first
validation. It encapsulates power-up, loading QCOMTEE, `TypeCheck` and
unconditional cleanup, and refuses to operate if it finds the sensor or the TEE
already active. It is not run against the currently booted image.

## Session 84 — the EL721 powers up and the TA still rejects the request

Date: 2026-08-14. Session 83's kernel — the one that corresponds exactly to the
committed sources — was finally flashed. The booted partition was backed up
before writing and read back afterwards; the tablet booted first time:

```text
Image.gz  d5021f8c99332149454a3c79fbfa7f648d10ae4abc9b8e1b15ffae5bc93e8e56
DTB       613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4
boot.img  b4df747fda34b22b4258ecc7cfca646a389da0c42f9d341a81d47158da622f2d
previous  b8e7a938c9ac5f0a1a73c23cb5db2d677290bc158461ed2108791d0cccf6cad0
```

The image running was the experimental one from 04:00, not the corrected one:
it still asked for the `vdd` regulator and failed with `error -ENOENT: failed
to get enable GPIO`. With the new kernel, **the deferred power-up works on
hardware for the first time**: `sensor_power` rises to 1, the reset increments
`reset_count`, GPIO91 and GPIO155 go from input to output and return to zero at
the end. Before flashing it was checked that both lines were free and that
`gpiochip3` is called `f100000.pinctrl`, the name the lookup table assumes. The
tablet did not reboot at any point.

With the sensor powered, `TypeCheck` still returns `29`. Session 83's
hypothesis is therefore refuted. Analysing the gateway and the stock HAL also
clarified that `29` **is not a diagnosis**: it is the Samsung stack's generic
failure code; `readSensorType` returns it for a null pointer and
`BAuth_Get_Ta_Version` for any error. Disassembling required resolving the PLTs
against the GOT, because objdump labels them shifted: what looked like a
`BAuth_SessionOpen` before the command is really `memset`.

Every cause attributable to this port was ruled out experimentally on the
physical tablet:

- power: identical result with the sensor on and off;
- buffer size: reproducing the stock's complete dmabuf page changes nothing;
- name enum: a sweep from `0` to `40` in a single load, `29` in all 41 cases and
  the output buffer untouched, so the TA fails before reading the payload;
- load name: `dualfp` and `securefp` behave identically;
- the request's envelope: dumping the returned buffers shows QTEE does inject
  real embedded pointers (`0x921885000` and `0x924e64000`) at offsets 4 and 16
  with length 8, as `QSEECom_send_modified_cmd_64` does;
- a prior session: `BAuth_Type_Check` opens none, the HAL only retries;
- the kernel driver: in Samsung's secure build `el7xx_pin_control` is compiled
  out and `spi_clk_enable` is a no-op on Qualcomm, so the stock driver does no
  pinctrl and hands over no SPI clocks either.

`qcomtee` records no error during the transaction. The remaining hypothesis is
that the TA depends on services that on Android are provided by QSEECom's HLOS
side — `qseecomd`'s listeners — or on a state only that stack establishes. The
probe gained `--type-check=FIRST-LAST` and the transactional script a fifth
argument with that selector, because the expensive part is loading the 19 MB,
not repeating the query.

The tablet is left with the new kernel booted, `sensor_power=0`, QCOMTEE
unloaded and the system `running`.

## Session 85 — `29` solved: the TA requires shared buffers of 0x2a4000

Date: 2026-08-14. The `29` that had blocked the last three sessions came
neither from the sensor nor from the request's envelope. It was solved by
disassembling the TA itself: its assembled image is an **unencrypted** ELF, and
its strings and its code are readable.

The dispatcher (`0xb03c`) validates the request before looking at the `cmd_id`
and writes `29` into `rsp[4]` if that validation fails. The prior check
(`0x4420`) reconstructs the 64-bit pointers in `cmd[4]` and `cmd[16]` and calls
`0x4280` with a fixed size of `0x2a4000`:

```text
4280:  bl   0x1b0                 ; qsee_register_shared_buffer(ptr, 0x2a4000)
42b4:  cbz  w0, ok
42b8:  log  "FAIL_REGISTER_SB(%d)"
42cc:  log  "clean up shared buffer"
42dc:  mov  w0, #0x1d             ; 29
```

That is, the TA re-registers each embedded buffer as a 2,768,896-byte shared
buffer. The stock gateway declares 8 bytes of payload but backs those pointers
with much larger `dmabuf` allocations, so the registration works there.
Reserving both TEE memory objects at that exact size while keeping the declared
length at 8, the TA **accepts and runs** the command:

```text
TypeCheck name=21: invoke result 0; trustlet=0, payload=0, sensor=0.
```

The response envelope comes back zeroed, which is exactly what the stock host
interprets as success. Before getting here, power, the name enum (a `0`–`40`
sweep), the load name and the page size were all ruled out on the physical
tablet; and dumping the returned buffers demonstrated that QTEE does inject
real pointers at offsets 4 and 16.

The disassembly also clarified two things that had been assumed wrongly. The
`21` is not an enum that gets passed: it is the **ID the TA reads from the
sensor over SPI**. Its Egis-family `type_check` (`0x17dc`) performs up to three
4-byte transfers and requires `rx[42]==0x07` and `rx[46]==0x15` to declare
`ET721` and return type `8`; otherwise it logs `Type check Fail !!!` and
returns `0`. And the family selector (`0x1d64`) accepts only `sensor_name ==
21`, with up to 40 retries: any other value falls into `invalid sensor_name
parameter`.

What remains, then, is a new and well-bounded blockage: `TypeCheck` returns
type `0`, with identical results at `sensor_power=1` and with the sensor off,
so TrustZone's SPI is not reaching the chip. That bus is not Linux's — in the
stock tree `etspi,el7xx` hangs off `soc`, not off an SPI controller, and the TA
carries its own `sec_tzspi_*` and its own TLMM control — so the port has nowhere
to intervene blindly. The TA does record the reason (`gpio control tz_open
error : %d`, `Sensor is not ready!!`, the bytes read) in TrustZone's log, which
this kernel does not yet expose; instrumenting that is the next step.

The tablet is left with `sensor_power=0`, QCOMTEE unloaded and the system
stable.

## Session 86 — the reader's bus is QUP1_SE2 and TrustZone does not drive it

Date: 2026-08-14. With the transport solved, the `sensor=0` result was
attacked. The first thing was to rule out the TA not getting as far as running
the query: poisoning the output buffer with `0xa5` before the call, it comes
back with its first eight bytes zeroed and the rest untouched. The TA does run
`TypeCheck`, writes its result and declares type `0`.

The disassembly gave the exact bus. The TA resolves its pads by name —
`qup1_se2_l0` is MISO, `l1` MOSI, `l2` CLK and `l3` CS — that is, **QUP1_SE2**,
which on SM8550 is `gpio64`–`gpio67`. On the tablet those four pins are in
`func0`, input, unclaimed by Linux, and `spi10@888000` does not even exist as a
device: this port enables no SPI node.

`scripts/probe-fp-spi-pins.c` samples them through the GPIO chardev at some
445,000 reads a second, because `/dev/mem` is blocked and a shell loop over
debugfs is several orders of magnitude too slow. During a complete transaction,
with 13,357,820 samples in 30 seconds, **none of the four lines changes state**.
TrustZone never reaches the first transfer.

With the TA now running the command, these were also ruled out:

- `QSEECom_set_bandwidth` is not the missing piece: in `libQSEEComAPI.so`'s
  compat build it is literally `mov w0, wzr; ret`;
- the stock driver does nothing special: in the secure build it is a
  `platform_driver` hanging off `soc`, with `el7xx_pin_control` compiled out and
  `spi_clk_enable` a no-op on Qualcomm;
- it is not that Linux is holding the sensor's pins: unbinding `egis-el721`
  gives an identical result;
- nor is it power: identical with `sensor_power` at 1 and at 0.

The symbols the TA imports bound where it fails. It uses `qsee_spi_open`,
`qsee_spi_full_duplex`, `qsee_tlmm_get_gpio_id`, `qsee_tlmm_config_gpio_id` and
`qsee_tlmm_select_gpio_id_mode`, and has its own messages for each failure
(`qsee_tlmm_get_gpio_id: BLSP_CLK Failed`, `sec_tzspi_open failed : %d`, `gpio
control tz_open error : %d`). The failure is in that layer, inside TrustZone,
where the port has no lever at all.

The next step is therefore instrumental rather than speculative: porting a
reader for TrustZone's diagnostic log, `tzdbg`-style, which this kernel does not
expose. That log contains the exact reason. Without it, any change in the port
would be guesswork.

The tablet is left with `sensor_power=0`, QCOMTEE unloaded, GPIO91/155 at zero
and the system `running`.

## Session 87 — correcting the bus, and TrustZone still has no log

Date: 2026-08-14. The previous session claimed the reader's bus was
`gpio64`–`gpio67` and published a measurement of 13.4 million samples over them.
**That identification was wrong and the measurement is withdrawn.** The TA names
its pads `qup1_se2_l0..l3`, and `qup1_se2` is `gpio36`–`gpio39`;
`gpio64`–`gpio67` are `qup2_se2`. The numbering agrees between the stock tree
and mainline — `gpio26` is `qup1_se7` in both — so there is no ambiguity.

The real pins are out of Linux's reach **by design and in both trees**: this
port declares `gpio-reserved-ranges = <36 4>` and the stock one
`qcom,gpios-reserved = <0x20 … 0x27>`, because TrustZone governs them. The
kernel exposes them neither in `/sys/kernel/debug/gpio` nor through the chardev,
so there is no way to observe them from user space and **there is no valid
measurement of whether TrustZone drives that bus**. `probe-fp-spi-pins.c` is
kept as a generic sampler, with a selectable first line and its premise
corrected in the header.

It was verified, item by item, that the Linux layer already mirrors stock:

- `spi@a88000` (`qupv3_se2_spi`) is disabled in the stock tree too, and the
  X910's overlay — confirmed against `dtbo.img`, board-id 00, with
  `etspi-chipid = "EL721"` and `etspi-modelinfo = "X916"` — never references
  it;
- Samsung's controller in a secure build is a `platform_driver` hanging off
  `soc` (`el7xx_probe(struct platform_device *)`), not an `spi_driver`;
- the SE's clocks come up disabled from the bootloader and Linux does not
  disable them: the command line already includes `clk_ignore_unused`,
  `pd_ignore_unused` and `regulator_ignore_unused`. Holding
  `gcc_qupv3_wrap1_s2_clk` on from a module (`scripts/tzlog/gts9u-fpclk.c`) does
  not change `TypeCheck`'s result.

The attempt to read TrustZone's log did not prosper either, and its route is
documented so it is not repeated:

- the stock tree describes `tz-log@146AA720`, `reg = <0x146aa720 0x3000>`. That
  window can be mapped, but it is an area of pointers in IMEM: its first
  quadword is `0x14696000`, and mapping that address **reboots the tablet**
  because it is secure memory;
- the classic SIP call (owner 2, service 6, command 2) answers `-1`, "not
  supported", on this firmware. The SMC plumbing is correct: command 1
  (`is_svc_available`) returns 0. Commands 3 and 7 exist but reject the argument
  forms tried (`0x80000001`);
- QTEE's Diagnostics service (UID 143) answers: its operation 1 returns the
  list of loaded TAs (`keymaster64`, `featenabler`, `tz_hdm`, `tz_iccc` and two
  UUIDs), but no operation from 0 to 31 delivers the log.

`scripts/tzlog/` stays in the tree with the reader (`gts9u-tzlog.c`, which
accepts both mapping a window and requesting the dump over SMC) and the clock
module, plus `scripts/probe-qtee-diag.c`. A first reader that copied the 12 KB
in one go caused an oops and left the module in state `Unloading`, which blocked
shutdown; the committed version reads only the requested window and in aligned
32-bit accesses.

The blockage's real state is therefore: the TA runs `TypeCheck`, writes its
result and returns type `0`; everything the port controls matches stock; and
there is no visibility inside TrustZone to decide whether the failure is in its
SPI or in the sensor not answering. Without that visibility — or without
physically measuring the sensor's rails — any further change in the port would
be guesswork.

## Session 88 — the port's levers on the EL721 are exhausted

Date: 2026-08-14. A final round of attempts on `TypeCheck`, all negative and
recorded so they are not repeated:

- **A reset pulse beforehand.** The stock HAL, before asking for the type,
  makes sure the device is open (`EgisOptSensorControl::SensorType` checks a
  flag and calls its open method). The only physical thing on that route is the
  LDO/enable sequence plus a reset. Powering the sensor and giving two reset
  pulses before the query, `TypeCheck` still returns type `0`.
- **The SE's clocks held on.** No effect, and Linux never switched them off
  anyway: the command line already carries `clk_ignore_unused`; they came up
  disabled from the bootloader.
- **Boot state.** `/proc/cmdline` carries no secure-state parameter
  (`verifiedbootstate`, warranty, lock) that would allow checking from here
  whether TrustZone is degrading functions because of the unlocked bootloader.
  ABL does add its Samsung parameters (`hdm.status=NONE`,
  `sec_sysup.edtbo_ver`, etc.), but none indicates that state.

With this the port's levers are exhausted. The honest summary of the blockage
is: the TA loads, accepts the request, runs `TypeCheck`, writes its result and
declares "sensor not identified"; everything Linux controls matches stock; the
bus's pins are reserved for TrustZone in both trees and are not observable; and
there is no known route to read TrustZone's log on this firmware. No testable
hypothesis remains within the port.

What would settle the matter is a test that does not depend on the port:
confirming the reader answers on this same device under stock Android. If it
answers, the problem is in the environment we offer the TA and is worth
pursuing; if it does not, no amount of work in the port will fix it.

## Session 89 — the reader works under One UI: the failure is environmental

Date: 2026-08-14. The owner confirmed that **the reader works without problems
under One UI on this same device**. That fixes two things: the sensor and its
wiring are fine, and TrustZone knows how to drive its SPI here. It is ruled out
that the unlocked bootloader degrades the function. The failure is therefore in
the environment this port offers the TA, not in the hardware.

A misunderstanding is also worth clearing up: the finger detection documented in
session 82 (`released 911 2808`) came from the **Goodix touch controller**
through `fod_state`, that is, the screen noticing a finger inside the reader's
rectangle. It is the signal that triggers a read, but it is not the EL721
reading over SPI; it does not demonstrate that route works.

This round's attempts, all negative:

- **QUP interconnect votes.** The SE's clock is not enough: a QUP moves data
  with its wrapper's core clocks, and in mainline those come from the `qup-core`
  vote, not from a `clocks` property. On Android there are active SEs that hold
  that vote and here there are none. Reserving all three paths (`qup-core`,
  `qup-config`, `qup-memory`) was added to `gts9u-fpclk.c` by creating a device
  that borrows the SE's node. All three votes go in — the SE's clock even
  changes rate — but `TypeCheck` still returns type `0`.
- **`BAuth_SessionOpen` is not a command of the TA's.** It was disassembled in
  full: it never calls `QSEECom_send_modified_cmd_64`. It only reserves the two
  buffers — of `0x2a4000` bytes, which independently confirms the size we
  discovered — and starts the app with the name `securefp` or `dualfp`. There is
  no prior session in the TA to open.
- **A TrustZone diagnostic call.** The reader was extended to sweep owner and
  calling convention. With the SIP owner the answer is `-1`, "not supported".
  With owner 50 (trusted OS) it answers `0x80000001` for all twelve argument
  forms tried, which in that service space means the command is not that one.
  There is no known route to the log from this firmware.

The next step is no longer the port's but cross-instrumentation: the stock
kernel does include `tzdbg`. Running the failing query under Ubuntu and then
reading `/sys/kernel/debug/tzdbg/log` from the stock boot would give the exact
reason the TA records, provided the ring survives a warm reboot.

## Session 90 — TrustZone's log exists, but it is encrypted

Date: 2026-08-14. Where TrustZone's diagnostics live on this device was finally
located, and it turned out to be reachable without booting Android: Samsung does
not read it from live memory but from a **debug partition**. The
`sec_qc_hw_param.ko` module, present in TWRP, uses
`sec_qc_dbg_part_read(debug_index_reset_tzlog, …)`, and the X910's overlay gives
the location: `sec,bdev_path =
"PARTUUID=a17d0ddb-cec4-4a80-9e22-7d43fec26358"`, which on the tablet is
`/dev/sda8`, label `debug`, 10 MB.

Sweeping the partition, the magic `tzda` (`0x747a6461`, the same one our reader
already used) appears at offset **`0x90000`**. The table is readable:

```text
version    = 0x00090004
cpu_count  = 8
ring_off   = 0x11c0
ring_len   = 0x1e40   (7744 bytes)
ring_wrap  = 1
```

The ring, however, **is encrypted**: only 2,996 of its 7,744 bytes are
printable and the rest is high-entropy noise. The explanation is in Samsung's
own header: from `TZBSP_DIAG_VERSION_V9_2` onwards the log uses
`tzbsp_encr_info_t`, with AES-GCM, `nonce[12]`, `tag[16]` and a **256-byte key
that is itself wrapped** (`TZBSP_AES_256_ENCRYPTED_KEY_SIZE`). Their code does
not decrypt it: it dumps it in hexadecimal under the key `"TZDA"` for analysis
off the device. Our version is 9.4, above the threshold.

A firm conclusion: **there is no way to read TrustZone's log on this firmware**,
neither from Ubuntu nor by booting One UI, because the content comes out
encrypted in both cases. Instrumentation by that route is ruled out with
evidence rather than for want of trying, and it does not justify formatting the
tablet to get dual boot.

It is recorded as a useful fact that the owner confirmed **the reader works
without problems under One UI on this same device**: the sensor, its wiring and
TrustZone's ability to drive its SPI are beyond doubt.

## Session 91 — closing the fingerprint front

Date: 2026-08-14. One last check before parking the matter: whether the stock
HAL sends the TA any command before `TypeCheck` that we were not reproducing.
The candidate was `FPBAuthService::turnOnSensorPowerAndOpenSession(int, bool)`,
which by name is exactly the start-up step. Disassembled, it turns out to call
the **same virtual method** (slot 3 of the object at `this+80`) as
`readSensorType`, and that the "open session" is the host's
`BAuth_SessionOpen`, which was already shown to send no command to the TA: it
only reserves the buffers and starts the app.

**There is no missing prior command.** With this, the routes testable from the
port are exhausted:

- transport: solved, the TA runs the command and writes its result;
- parameters: enum, load name, sizes and envelope, all verified;
- the Linux layer: identical to stock in SPI node, driver type, reserved pins,
  clocks and command line;
- physical stimuli: power, reset and timing, with no effect;
- the QUP's clocks and interconnect forced, with no effect;
- TrustZone's log: it exists, it was located, and it is encrypted with a
  wrapped key.

All that remains is information obtainable only with the device working:
capturing under One UI the hardware's state while the reader operates — clocks,
interconnect votes, the configuration of pads `gpio36`–`39` and the state of
the PMIC's rails — and comparing it with ours. That requires being able to boot
Android, which becomes the next objective in its own right.

---

## Session 92 — why One UI does not boot after TWRP, and preparing the split

Date: 2026-08-15. Nothing was written to the tablet: this session resolves the
open problem that was constraining the test cycle and leaves the tooling ready.
### The open problem was the encryption, not the boot

Symptom: One UI is flashed, then TWRP, and One UI stops booting even when
restarting to system from the recovery. The cause is FBE. Once TWRP is in
`recovery`, Android can no longer decrypt `userdata` and goes to recovery in a
loop. The solution is one single thing, and it is the one the device's own
thread documents three times:

**In TWRP, `Wipe → Format Data`.** Not "Wipe", and above all not "Factory
reset".

- The port's maintainer, asked whether formatting data and flashing
  `repack.zip` is still needed after installing TWRP, answers "yep"; and his
  recipe for installing LineageOS begins with "Format data (**not wipe**) in
  twrp".
- A user with the exact symptom: "the solution is just that when you get into
  TWRP you go wipe → format data".
- Another (`flamadiddle`, Tab S9 Ultra) tried "factory reset" instead of
  "format data": he got `Failed to mount /data` and stayed in the loop. That
  error is exactly what distinguishes the two options: "factory reset" tries to
  empty `/data`'s contents, which requires decrypting it; "format data" remakes
  the partition and `metadata`, and Android regenerates the keys on the next
  boot.

It fits mine no. 1 already recorded for milestone 4 — `metadata` has to be
erased too — except it bites earlier than expected: in the first cycle, not in
the installer.

### Two of milestone 4's mines were false for this TWRP

`TWRP-gts9u-V2.img`'s ramdisk was unpacked (boot image v2, gzip+cpio) instead
of continuing to assume:

- **`sgdisk` is included**: `/system/bin/sgdisk`, an aarch64 ELF, 181,520
  bytes, from `external/gptfdisk`. No static binary has to be packaged. Mine
  no. 3 is withdrawn.
- **`bash` is included too**: `/system/bin/bash`, aarch64, a real GNU bash.
  `mksh`'s 32-bit arithmetic (session 35) is dodged by re-executing the
  installer's body under `bash`, rather than contorting the arithmetic.
  `/system/bin/sh` is still `mksh`, so the test bench's `mksh` check stays as it
  is.
- `make_f2fs`, `mke2fs`, `e2fsdroid`, `resize2fs` and `sload_f2fs` are also
  there.

### A danger in `twrp.flags`

That TWRP inherits this line from the Fold 5's tree:

```text
/usb-otg  vfat  /dev/block/sda1  /dev/block/sda  flags=...;storage;wipeingui;removable
```

On this tablet `/dev/block/sda` **is the internal UFS** — `userdata` is `sda34`,
checked over `adb` against `by-name` — so the menu's "USB-OTG" entry points at
the internal disk and is marked `wipeingui`. That entry is not touched, and it
is worth checking what it really resolves to once inside TWRP.

### What `repack.zip` does exactly

It is an **AnyKernel3** from the OrangeFox team (1,865,371 bytes, SHA-256
`262827a2…f06a`). Of the whole script only two lines are active, `split_boot`
and `flash_boot`, on `block=/dev/block/bootdevice/by-name/boot`, with
`patch_vbmeta_flag=auto`. That is: it **rewrites `boot`** and sets the
verification-disabled flag in `vbmeta`. Worth keeping in mind because milestone
3 is precisely about alternating `boot`, and because the `vbmeta` flag touches
milestone 2: the installer writes its own `vbmeta` if the recovery exposes it
writable, and only requires `flags=2` when it is read-only. Which of the two
cases applies is known from `blockdev --getro` as soon as TWRP is there.

### Things that turned out not to be what they looked like

- The boot images in `D:\gts9u-backup\` are **Ubuntu's**, not One UI's:
  `vendor_boot.img` carries `root=LABEL=UBTS9U_UFS` on its command line. They
  serve as one of milestone 3's two pairs; One UI's comes from DZA1's AP.
- In the GPT, `userdata` has **the same value as its type and as its unique
  GUID**, `1B81E7E6-F50D-419B-A739-2AEEF8DA3335`. It is a quirk of Samsung's
  PIT, and it is reproduced when recreating the entry.

### Tooling prepared

- `scripts/repartition-ufs.sh`: splits `userdata` into `userdata` +
  `linuxroot` by percentage, over ADB, with the tablet in TWRP. It inspects by
  default and requires `--write` and `--backup-dir`. All the arithmetic happens
  in `bash` on the PC and only literal sector numbers reach the tablet, which is
  the clean way not to step on the 32-bit arithmetic again.
- `TWRP-gts9u-V2-odin.tar`, generated from the project's `.img`. The internal
  file **must** be called `recovery.img` or Odin answers "unassigned file"; with
  a 512-byte block and no record padding it comes to 109,577,728 bytes, exactly
  the size of the `.tar` the maintainer publishes.

### State

The tablet intact, on One UI 8, unrooted (`uid=2000`), FBE active
(`ro.crypto.type=file`), bootloader unlocked. Nothing flashed yet.

---

## Session 93 — milestone 1: the UFS is split in two and One UI boots

Date: 2026-08-15. `userdata` becomes two partitions and Android boots again in
its own. Session 92's open problem is also confirmed on hardware: it was the
encryption, and `Format Data` resolves it.

### Flashing TWRP without graphical Odin

`usbipd-win` was already installed, so the "WSL cannot see USB" of the notes has
a fix: `usbipd bind --force` plus `usbipd attach --wsl` expose the tablet inside
WSL, and there `heimdall` 1.4.2 talks to it. Copying the key pair from Windows's
`~/.android` into WSL's `/root/.android` avoids having to authorise debugging by
hand on the screen.

Two things that cost time and are worth not repeating:

- **`--no-reboot` and `--resume` go together.** `print-pit --no-reboot` was run,
  which leaves the Odin session open, and then a `flash` without `--resume`.
  `heimdall help` itself warns about it. The result is not that the command
  fails: it leaves the device's protocol unable to reopen, and neither
  `--resume`, nor a new session, nor recycling the USB attachment recovers it.
  It has to be powered off and put back into Download with the buttons.
- **Download mode is only left with the buttons.** No heimdall or Odin command
  jumps to recovery. The only candidate software route was writing the
  *bootloader control block* in `misc` — which is flashable and is in the PIT at
  offset 25356 — but that is generic AOSP mechanism, unconfirmed on a Samsung
  ABL, and it would require a live Odin session anyway. It saves no reboot.

With the correct sequence — a single invocation, `heimdall flash --RECOVERY
TWRP-gts9u-V2.img --no-reboot` — the write was clean, and from Download one
enters TWRP with Volume Down + Power and immediately Volume Up + Power.

### The split

`scripts/repartition-ufs.sh` with `--android-percent 40`. It checked against the
device the disk's GUID, and entry 34's name, type and start sector, and that no
entry 35 already existed, before writing:

| Entry | Before | After |
|---|---|---|
| 34 `userdata` | 3,626,496 – 249,716,726, 938.8 GiB | 3,626,496 – 102,062,079, **375.5 GiB** |
| 35 `linuxroot` | did not exist | 102,062,080 – 249,716,726, **563.3 GiB** |

The script had a bug that **its own guard caught**: it runs in WSL but calls
Windows's `adb.exe`, to which it was passing the backup's destination path in
WSL format. The backup's `adb pull` failed and it aborted before touching the
table. A good outcome for the wrong reason; it now converts with `wslpath -w`.

Verified after rebooting to recovery so the kernel would reread the table:
`sda34` is 403,192,152,064 bytes and `sda35` 604,793,434,112, exactly as
calculated. `by-name/linuxroot` appears on its own, without touching any
`fstab`, and Android sees it too once booted.

`twrp format data` left `userdata` as f2fs (magic `10 20 f5 f2`) and **also
formatted `metadata`**, which is literally what was needed. `linuxroot` was
created with `mke2fs -t ext4 -m 0 -L UBTS9U_UFS`: it mounts, lists — only
`lost+found` — and unmounts without complaint.

### The success criterion, met

One UI 8 boots, sets itself up and sees its 376 GiB with 370 free. The
bootloader stays unlocked (`flash.locked=0`, `orange`) and the hybrid intact:
`abl` `X910XXS5CYG1` under system `X910XXS5DZA1`. `ro.crypto.state=encrypted`
and `ro.crypto.type=file`: Android regenerated its FBE keys, which was the real
proof. `super` was not touched, nor the bootloader chain, nor `efs`, `persist`
or `modem`.

The GPT was backed up twice: the previous `gpt-sda.bin` and the one the script
pulled live just before writing, `gpt-sda-20260815-044329.bin` (`3b71a2d0…`).

### Two measurements that condition milestone 2

- **`vbmeta` is read-only from TWRP** (`blockdev --getro` = 1) and its AVB
  flags, read at offset 120, are `00000000` with magic `AVB0`. Ubuntu's
  installer, when `vbmeta` is not writable, requires `flags=2` and aborts if it
  does not have them. So it **will abort** with the device as it stands.
  `repack.zip` sets that flag, and becomes a prerequisite for milestone 2, not
  a convenience for keeping TWRP.
- **The `twrp.flags` danger is confirmed live**: `/dev/block/sda` is the
  internal UFS — `userdata` is `sda34` — and `sda1` is `modemst1`. TWRP's menu
  entry "USB-OTG" points there and is marked `wipeingui`.

---

## Session 94 — `repack.zip` is a dead end, and the device is left asking for recovery

Date: 2026-08-15. A session with a negative balance: milestone 1 was still valid
at the start and by the end the tablet always boots into TWRP. Nothing has been
lost — the partitions, `super` and the backup are intact — but it is worth
writing down what was tried and, above all, in what order **not** to try it.

### Confirmed: One UI restores the stock recovery

After closing milestone 1, One UI was booted and then `adb reboot recovery`.
The **stock** recovery answered: it identifies itself as `product:gts9uwifixx`
against TWRP's `product:twrp_gts9u`, enumerates as `18d1:d001` instead of
`18d1:6860`, and its `adb shell` dies with `Could not set SELinux context for
subprocess` and SIGABRT. It is confirmed on this firmware.

### `repack.zip` is no use on this device

It was installed with TWRP, after backing up One UI's complete boot set with
the hash compared on both sides. Result:

- **It rewrote `boot`** (`bb7be3ce…` → `495aaeb2…`), as its `anykernel.sh`
  announced.
- **It could not touch `vbmeta`**, because that partition is read-only to the
  kernel: it lives on another LUN, `sde15`, and `blockdev --getro` returns 1.
- Since then the device always boots into recovery.

Doing only half the job is the worst thing that could have happened: it leaves a
`boot` that no longer matches a `vbmeta` still demanding verification.

### The chain of diagnostic errors, which is the useful part

The wrong symptom was chased for three cycles:

1. **Patching the signed `vbmeta` byte by byte was a mistake.** The tablet's own
   `vbmeta` was copied and `02` written at offset 123 to leave `flags=2`. That
   is what AnyKernel's `patch_vbmeta_flag` does, but it only works on devices
   whose ABL does not revalidate the vbmeta's own signature. Here the result is
   a signed image with a broken signature.
2. **Restoring `boot` did not fix anything either**, even ending up byte for
   byte identical to the state that used to boot.
3. **Nor did the port's `vbmeta`.** `port/sources/samsung-gts9u/vbmeta.img` is
   4096 bytes with magic `AVB0`, `flags=00000002` and authentication and
   auxiliary blocks **at zero**: an empty, unsigned vbmeta from `avbtool 1.3.0`.
   It is the correct shape, and the ABL accepts it — it says so itself — but the
   device kept going to recovery.

What should have been done first, and is now the lesson: **read the ABL's log
before flashing anything**. It is in `/proc/last_kmsg`, in the lines marked
`[ ABL ]`, and it tells the whole boot.

### What the ABL says, which is what is really happening

```text
[ ABL ] BootReason: 1
[ ABL ] Recovery Mode, Reset param!
[ ABL ] Booting Into Recovery Mode
[ ABL ] BootMode = 2
```

**The bootloader is not even trying to boot the system**: it is asked for
recovery and it goes to recovery. All that time was spent fixing a boot chain
nobody was rejecting. In fact, on the unsigned vbmeta the ABL itself says
`(Booting) AUTHENTICATE fail but allow Vbmeta binary: vbmeta`, and carries on.
The boots that did reach the system are distinguished by `BootReason: 14` with
`PARAM Flag is PARAM_BOOT_CHARGING` and `Booting Into Mission Mode`.

Byte 0 of the `param` partition is `0x02`, which is the same value the ABL calls
`BootMode = 2`; `1` is download and `0` is normal. The ABL says it resets it on
entering recovery, but **it is still 2 once inside**, so that reset does not
take and the loop feeds itself. `param` is writable (`blockdev --getro` = 0).

TWRP's official route was also tried: writing `reboot system` into
`/cache/recovery/openrecoveryscript`. TWRP **consumed** the file — it disappears
after being executed — and still returned to recovery. Rebooting from Download
mode does not break the loop either.

### The state it is left in

- Milestone 1's partitioning **intact**: `userdata` 375.5 GiB and `linuxroot`
  563.3 GiB with its `UBTS9U_UFS` ext4.
- `super` whole: all seven logical partitions mount, and `/system` gives
  `ro.build.display.id=BP2A.250605.031.A3.X910XXS5DZA1`.
- `boot`, `vendor_boot`, `init_boot` and `dtbo` byte for byte as the backup
  taken before `repack.zip`.
- `vbmeta` is now the port's, unsigned and with `flags=2`. It is left that way
  on purpose: it is what Ubuntu's installer requires, and the ABL accepts it.
- TWRP in `recovery`, reachable over adb as root.
- New backups in `D:\gts9u-backup\oneui-boot-set\`: stock `boot`,
  `vendor_boot`, `init_boot`, `dtbo` and `vbmeta`, hash-verified. It is also
  **the One UI pair that milestone 3 was missing**.

### Where to go next

1. **A cold boot**, which requires writing nothing: power off completely with
   Power and turn it on again. The good boots carry `BootReason: 14`, which
   smells like a cold boot as against the `1` of warm reboots.
2. If that is not enough, **zero byte 0 of `param`** (`dd if=/dev/zero
   of=/dev/block/by-name/param bs=1 count=1 conv=notrunc`) and reboot via
   `sysrq` so as not to go through TWRP's userspace.
3. As a last resort, Odin with the BL, which rewrites the whole `param.bin`.

And for milestone 2: `repack.zip` is discarded. Keeping TWRP will have to be
solved some other way, or a heimdall cycle accepted each time, which is cheap
enough already: `usbipd attach` plus `heimdall flash --RECOVERY … --no-reboot`.

---

## Session 95 — the recovery loop was Android's doing, and One UI coexists with `flags=2`

Date: 2026-08-15. Session 94's impasse is escaped and, along the way, the
requirement that was blocking milestone 2 falls.

### A cold boot did not fix it, and that was the good datum

Powering off completely and turning on with the button still entered TWRP. The
ABL's log explained why, naming the flag:

```text
[ ABL ] BootReason: 0                            ← no reboot reason
[ ABL ] PARAM Flag is PARAM_BOOT_RECOVERY_ENTER  ← the param partition asks for it
[ ABL ] PonReason.KPDPWR = 1                     ← powered on with the button
[ ABL ] BootMode = 2
```

Byte 0 of `param` was `0x02`, which is `PARAM_BOOT_RECOVERY_ENTER`, and **it
survives a complete power-off**. The good boots show `PARAM_BOOT_CHARGING`
there. Setting it to zero (`dd if=/dev/zero of=/dev/block/by-name/param bs=1
count=1 conv=notrunc`) and rebooting via `sysrq` so as not to go through TWRP's
userspace, the ABL did choose `Booting Into Mission Mode`.

### The one asking for recovery was Android

That boot reached the kernel and fell over mounting `/data`:

```text
init: [libfs_mgr] Failure while mounting metadata ... at /data: Invalid argument
init: fs_mgr_mount_all suggested recovery, so wiping data via recovery with prompt.
```

Android cannot open the metadata encryption, and **it is Android that writes
`PARAM_BOOT_RECOVERY_ENTER`** so the next boot goes to recovery to erase the
data. Hence `param` returning to `0x02` on its own. The loop was: Android does
not mount `/data` → asks for recovery → recovery erases nothing → repeat.

The underlying cause is that **`metadata`'s encryption key is tied to the
verified-boot state**. Changing `vbmeta` makes it underivable. That refines
session 92's conclusion: "One UI does not boot after TWRP" is not about the
recovery itself, it is about the verified-boot state having changed. The remedy
is the same, `Format Data`, and `init` itself asks for it in writing.

### What this unblocks

After `twrp format data`, **One UI boots and works with the unsigned `flags=2`
`vbmeta` in place**. It is the same one Ubuntu's installer requires, so:

- **The requirement blocking milestone 2 is now met**, and permanently as long
  as the firmware is not reflashed.
- **Dual boot will not need to change `vbmeta` between systems**, which was the
  serious risk on the horizon: every change invalidates Android's `/data`. It
  is worth not forgetting, because it means **touching `vbmeta` in future costs
  an erasure of Android's data**.

The correct `vbmeta` is `avbtool`'s empty, unsigned one
(`port/sources/samsung-gts9u/vbmeta.img`, 4096 bytes, authentication and
auxiliary blocks at zero). The ABL accepts it explicitly: `(Booting)
AUTHENTICATE fail but allow Vbmeta binary`. Patching Samsung's signed one byte
by byte does not work and fixed nothing anyway, because the problem was never in
the boot chain.

### State

One UI 8 `X910XXS5DZA1` booted and reconfigured, `abl` `X910XXS5CYG1`,
bootloader unlocked, FBE regenerated. `userdata` 376 GiB with 371 free and
`linuxroot` intact. TWRP has been lost again by booting One UI, as was already
known; recovering it is a `heimdall flash --RECOVERY` and the button
combination.

### A correction to session 94

There it was written that "the bootloader is not even trying to boot the
system". That was true only while `param` was asking for recovery. With the
flag cleared, the ABL does try; what was failing was one layer above.

---

## Session 96 — v0.27 installs into `linuxroot` and Android keeps its partition

Date: 2026-08-15. The first installation onto the split UFS. **Milestone 2's
hardware validation is pending**: this entry covers the installation only.

### The installer chooses its destination

`configs/twrp/ubuntu-update-binary` moves to writing the root into `linuxroot`
if that partition exists, and into `userdata` if not. The fallback is not a
leftover: it is what makes **the same installation ZIP work on its own** for
anyone who wants Linux across the whole UFS, with no need for the
repartitioning one. That leaves two independent artefacts, one to split and one
to install, and the second works alone too.

Associated changes: the "the ZIP is on the destination" guard applies only when
the destination is `userdata` — on a split tablet the ZIP can live in Android's
`/data` with no risk; the overlay update path falls back to `userdata` if
`linuxroot` exists but is not the installed root; and the contract line becomes
`writes boot init_boot vendor_boot dtbo vbmeta linuxroot userdata only`, with
`validate-bundle.sh` up to date.

The selection was tested **with `mksh`**, which is the shell TWRP runs
`update-binary` with, not with `bash`: all four cases — both, `userdata` only,
`linuxroot` only, neither — come out right. The bench also prints
`2147483647 + 1` and gets `-2147483648`, which confirms it is testing in the
32-bit shell and not a comfortable one. That was session 35's methodological
failure.

### The release

v0.27, reusing the kernel and root filesystem and regenerating the image, the
bundle and the ZIP. Every static check green, including the new contract's.
`ubuntu-24.04-gts9uwifi-v0.27-sm-x910-twrp.zip`, SHA-256 `281d9a9a…`.

### The installation, measured

Sent by `adb sideload` from TWRP. From the installer's log:

```text
Installing into linuxroot.
vbmeta is read-only but already has AVB flags 2; preserving it.
Ubuntu will be written into linuxroot (3605 MiB).
Writing the Ubuntu root filesystem. This takes several minutes.
Verifying the written root filesystem...
The root filesystem matches the image byte for byte.
Writing boot... init_boot... vendor_boot... dtbo...
Updater process ended with RC=0
```

Checked afterwards against the partitions: `linuxroot` labelled `UBTS9U_UFS`
and clean; `boot` gives `5f33dcd5…` and `vendor_boot` `ded9ae5d…`, identical to
the ones the build produced; `vbmeta` preserved.

**Android's `userdata` is still intact.** Read raw it no longer shows f2fs's
magic but ciphertext, which is correct: Android has it under metadata
encryption, so seeing it illegible from TWRP is proof that it is in place, not
that it has been broken.

A warning in the log that is not an installer failure: TWRP finishes with
`operation_end - status=1` because it then tries to mount `/data` for its own
interface and cannot decrypt it. The installer had already finished with
`RC=0`.

### State

Ubuntu installed on `linuxroot`; One UI does not boot because its four boot
images are now Ubuntu's, which is what was expected and what milestone 3
solves. The way back is a `dd` from TWRP with those in
`D:\gts9u-backup\oneui-boot-set\`, backed up with the hash verified on both
sides.

---

## Session 97 — swapping the boot set, and Android rooted to do it alone

Date: 2026-08-15. Milestone 2 is validated on hardware, the system swap is
written, and Android is rooted so the change does not depend on a PC.

### Milestone 2 validated

With v0.28 installed, checked over SSH: the root on `/dev/sda35` **grown to
555 GiB** with 513 free, `ubuntu-gts9u-companion` 0.10.8 and
`ubuntu-gts9u-device` 2.29 installed, `tab-companion-hardware` and
`tab-companion-spen-pairing` running, **not one failed service**, and no trace
of `obs-studio`, `obs-plugins`, `vlc` or `obs-v4l2-gts9u`. Among the input
devices are `Wacom EMR Digitizer`, `Tab Companion virtual keyboard` and `Book
Cover Keyboard Slim with AI Key (EF-DX920)`. The owner confirmed by hand the
display, brightness, touch, Wi-Fi, audio, camera, rotation, suspend, S Pen and
keyboard.

`ubuntu-gts9u-desktop-user.service` shows as `inactive (dead)` and **that is
correct**: it deliberately has no `RemainAfterExit`, so the `.path` can fire it
again. Its log shows it ran correctly and bound the camera relays to `agcar`.

### `scripts/swap-boot-set.sh`

It alternates the four partitions that separate the two systems — `boot`,
`init_boot`, `vendor_boot` and `dtbo` — from TWRP over ADB, verifying each image
by size before sending it, by hash after sending it, and reading the partition
back after writing.

**`vbmeta` is deliberately left off that list.** One UI works with the unsigned
`flags=2` vbmeta Ubuntu needs, so there is no need to alternate it; and since
changing it invalidates Android's `metadata` key, every change would cost a
complete erasure of its data. Leaving it alone is what makes switching systems
cheap.

Both sets are backed up with the hash compared on both sides, in
`D:\gts9u-backup\{ubuntu,oneui}-boot-set\`.

### Android rooted with Magisk

The file to patch is **`init_boot.img`**, not `boot.img`: this device has an
`init_boot` partition, so that is where the ramdisk with the first-stage init
lives. It was confirmed by extracting it from One UI 8's AP and comparing it
with the one pulled from the tablet itself: **identical**, `c5bff79e…`.

Magisk v30.7 — whose notes cite Android 16 QPR2 support — patches without
complaint: `Stock boot image detected`, `Patching ramdisk`, `Pre-init storage
partition: sda28`. The resulting image was written to `init_boot` with heimdall,
with no buttons, because Download mode is reached with `adb reboot download`
from One UI.

Root confirmed: `uid=0(root) context=u:r:magisk:s0`, and **all four boot
partitions are writable by root**. That is what makes the real idea viable: an
Android app that writes Ubuntu's set and reboots, with no PC and no Download
mode.

A trap that cost several attempts: **a superuser request that times out is
stored as denied**. The first `su` was left to expire its 10-second window, and
from then on Magisk refused flatly with `su: request rejected (2000)` without
asking again. It is fixed in the Superuser tab, by enabling the switch on the
`[SharedUID] Shell` entry.

It is also worth knowing that on this One UI `which su` and `which magisk`
return paths under `/product/bin`: those are the binaries Magisk injects through
its systemless mount, not Samsung's.

## Session 98 — repartitioning as a `.zip`, tested against a fake disk

Until now, splitting the UFS needed a PC: `scripts/repartition-ufs.sh` over ADB
from TWRP. The equivalent installer,
`configs/twrp/repartition-update-binary`, does the same from the device itself,
and `scripts/make-repartition-zip.py` packages it with the percentage inside.
The share is written into the ZIP and not asked for on the tablet, because TWRP
has no way of asking and a split is not something that should go wrong from one
tap too many.

Two things change on moving the logic to the device.

The first is the arithmetic. TWRP runs the script with mksh, whose `$(( ))` and
whose `test` are 32-bit signed. A 1 TB model has some 246 million sectors here,
and multiplying that by a percentage overflows before the division is reached.
Every number is computed by `awk`, which works in doubles and holds exactly
every integer in play.

The second is that there is no longer a PC to leave the GPT's backup on. It is
written next to the ZIP when the ZIP is on a microSD or an OTG drive, and to
`/tmp` if not, with a warning that this is a RAM disk. A first attempt aborted
the whole installation if that directory was not writable; it now falls back to
`/tmp`, which is the reasonable thing: a card mounted read-only is no reason to
refuse to partition.

The deletion and the creation go in **a single sgdisk invocation**. sgdisk
applies every option to the table it holds in memory and writes once at the
end, so the device never sees a table without entry 34. Split across two calls,
a failure in between would leave the disk with no `userdata`.

### Tested without touching the tablet

Since this tablet is already split, the guard would reject it, and testing the
good path would cost One UI's data. So a fake disk was assembled: a sparse file
of 249,720,832 sectors on a loop device with `-b 4096`, with the real disk GUID
and entry 34 in place, and the installer was run **with mksh**, the shell TWRP
uses, with `getprop` and `unzip` simulated.

The 40/60 comes out exact: `userdata` 375.5 GiB, `linuxroot` 563.3 GiB, the
second aligned to 512 sectors and both of `userdata`'s GUIDs reproduced. And
what matters most: loading the backup returns a table **byte for byte
identical** to the previous one. All four rejections were checked as well —
tablet already split, a device that is not an X910, an absurd percentage, and a
disk that is not the internal UFS — all before writing anything.

What the ZIP deliberately does **not** do is format. Shortening `userdata`
leaves inside it a filesystem describing a partition that no longer reaches that
far, so Android cannot mount it and it has to be remade; but that is TWRP's
Format Data, which asks for written confirmation. This ZIP should not be the
thing that erases a tablet silently.

---

## Session 99 — One UI 8 identifies the missing QTEE client context

Date: 2026-08-21. The rooted half of the dual boot gives a live reference for
the EL721 instead of another inference from blobs. The tablet is running
Android 16 / One UI 8 build `X910XXS5DZA1`; its fingerprint service is AIDL v2,
runs as `system` (UID 1000), opens `/dev/esfp0` and uses `/dev/smcinvoke`.
Nothing in the enrolled-template store was read or copied.

Stock reports `EGISTEC`, `EL721`, type `8`, `EL721-B`, a secure SPI clock of
20 MHz and the unchanged position string. A clean service restart also shows
the expected brief Linux-side sequence: sensor SPI control on, operation 22,
then control off. Current `dualfp.b00`–`b08` still assemble to 19,927,128 bytes;
their code keeps the same TypeCheck command, the `0x2a4000` shared-buffer
registration, QUP1_SE2 at 20 MHz and the enum `21` → type `8` mapping. The
dual-boot work has not introduced fingerprint protocol drift.

### The decisive live trace

`simpleperf` can record the stock kernel's `smcinvoke` tracepoints even though
SELinux correctly refuses direct tracefs writes. A system-wide recording of a
fresh fingerprint-service start produced 70 records with none lost. The
relevant calls are:

```text
AppLoader handle 1, op 2, counts 0x1100 -> result 0, controller 0x1a
controller 0x1a, op 0, counts 0x0424 -> result 0
```

The first line is `lookupTA("securefp")`: unlike the Ubuntu UID 0 probe, One UI
gets the preloaded controller. The second is BAUTH. `0x0424` means four input
buffers, two output buffers and four input objects, exactly the probe's current
packing. That independently confirms the reconstructed transport and removes
another possible cause of the type-zero result.

The best remaining difference is the client's credential. In Qualcomm's pinned
`quic-teec` commit `736419e…`, `qcomtee_object_credentials_init()` serialises
`getuid()` and the system time into CBOR, and that callback is passed to root
operation 2, `registerAsClient`. Every previous Ubuntu experiment registered
UID 0; Samsung registers UID 1000. TA visibility can therefore legitimately
differ even though both clients open AppLoader UID 122.

### A bounded UID test, not a service shortcut

Both QTEE probes now accept `--client-uid=UID`. They first open `/dev/tee0`,
then clear supplementary groups and irreversibly set real/effective/saved UID
and GID before creating the credential object. The probe cannot regain root;
the outer one-shot shell remains privileged only so its `trap` can power the
EL721 off and unload QCOMTEE. The split TA is read before the drop, and if UID
1000 finds `securefp`, TypeCheck runs on that returned controller without
loading or unloading a duplicate TA.

This is only a controlled hypothesis test. A final backend must have its own
unprivileged account and narrowly granted device access; it must not impersonate
Android's UID. The next physical Ubuntu invocation passes client UID 1000 as
the sixth argument to `test-el721-type-check.sh`. A result of type `8` would
close the secure hardware path. If it remains type `0`, the next branch is the
TrustZone log, not taking QUP1_SE2 away from secure firmware.

### Prepared without replacing the running Android set

The experimental kernel was rebuilt cleanly with
`ENABLE_FINGERPRINT_EXPERIMENTAL=1`, including EL721, Goodix FOD and panel FOD.
Because that clean build also regenerated the module signing key, its matching
QCOMTEE, ath12k, Wi-Fi 7 and v4l2loopback modules were packaged with it instead
of mixing two builds that happen to share `7.2.0-rc3-dirty` as their release.

The rooted Android side mounted `linuxroot` read-write only for staging. Before
changing it, it copied the normal Ubuntu `boot.img` and complete module tree to
`/var/lib/gts9u-fingerprint-backup-20260821`. The test bundle and probes live in
`/var/lib/gts9u-fingerprint-test-20260821`; the saved Ubuntu boot set now points
to the experimental image. Its SHA-256 is
`a624eeeab4f1d32ba8e95338205dfc896b5b8f0aa4f702ce2d4918139cfd9905`.

No live boot partition was written. The active `boot` hash remained
`bb7be3cea122f3ac60c710c7b6932d7f3bf98e46b086aa8e6dad4b9c113a68dc`,
identical to the stored Android set, and `linuxroot` was cleanly unmounted.
Selecting Ubuntu in Boot Switcher is therefore the explicit boundary that
writes the prepared four-image set and starts the physical test.

---

## Session 100 — UID, NULL credentials and `authnr` ruled out

Date: 2026-08-21. The hypothesis at the end of Session 99 was tested and is
false. The exact numeric Android identity (`--client-uid=1000`) sees no
preloaded `securefp` object and, after loading the signed `dualfp` image,
TypeCheck still returns sensor type zero. The process opened `/dev/tee0` while
privileged, discarded every supplementary group and irreversibly changed its
real, effective and saved UID/GID before `quic-teec` created the CBOR
credentials object.

The downstream smcinvoke client path was then reproduced more literally.
Samsung's in-kernel compatibility code calls root operation 5,
`registerWithCredentials`, with a NULL credentials object instead of using the
userspace CBOR callback. A diagnostic-only QCOMTEE patch permits that exact call
to a `CAP_SYS_ADMIN` process, and the probe's `--kernel-client-env` selector
uses it. The result is again type zero. The patch is gated behind
`QCOMTEE_ADMIN_NULL_CREDENTIALS=1`; ordinary and release builds do not apply
it.

Preloading `authnr.mbn` was negative as well. These three controlled failures
rule out the client identity, the kernel/client registration operation and the
extra authenticator as the missing prerequisite. Every one-shot test restored
GPIO91/GPIO155 to off and unloaded QCOMTEE.

## Session 101 — the live One UI path is explicit `dualfp`, not an alias

Date: 2026-08-21. A rooted Android 16 / One UI 8 reference was captured without
reading or copying any fingerprint template. The mounted
`com.samsung.android.biometrics.fingerprint` APEX contains only its manifest,
and `/data/apex/active` has no biometric or fingerprint update. There is no
hidden `fpta` payload to import.

A real fingerprint unlock was recorded system-wide with `simpleperf`: 3,839
samples, none lost. For the fingerprint-service process, every observed BAUTH
request used controller handle `0x14`, operation 0 and counts `0x0424`; all of
their result records returned zero. Fifteen such calls were present in that
unlock. GPIO activity and smcinvoke marshalling were included, but no biometric
payload or private template directory was recorded.

Restarting only init service `vendor.fingerprint-default` under a second trace
gave the missing start-up fact. The service logs this sequence literally:

```text
lookupTA(dualfp) returned 23
DMA heap qcom,qseecom-ta
DMA heap qcom,qseecom
Session is successfully opened
```

The new service process retained two dma-bufs of exactly 2,768,896 bytes
(`0x2a4000`), both exported by `qcom,qseecom`, plus its small command buffer.
The restart trace contained 80 samples with none lost and the service recovered
automatically. Thus Session 99's interpretation was wrong: One UI does not get
`securefp` from a UID-dependent preloaded alias. It explicitly loads the same
signed `dualfp` split Ubuntu already accepts.

This leaves a concrete transport difference. Stock's `qcom,qseecom` and
`qcom,qseecom-ta` heaps are CMA-backed reserved pools; the first is explicitly
allocated below 4 GiB. Upstream QCOMTEE's large-image extension already puts
the 19,927,128-byte image in DMA-coherent TZMEM, but its two `0x2a4000` memory
objects remained on `tee_dyn_shm_alloc_helper` because they were below the
previous 4 MiB cutoff. The next bounded kernel variant moves objects of 2 MiB
or larger to TZMEM while keeping ordinary invocation messages page-backed.
That reproduces the relevant contiguous-memory property without importing the
legacy downstream QSEECom driver.

`scripts/capture-oneui-fingerprint-reference.sh` records the build, public APEX
layout, signed-TA hashes and available tracepoints. It refuses every device
except `SM-X910`/`gts9u`, requires root, never writes a partition and never
walks Android's private biometric store.

## Session 102 — One UI power and secure-bus ownership measured

Date: 2026-08-21. The unlocked One UI 8 installation was used for one final
read-only reference before returning to Ubuntu. A controlled fingerprint
service restart produced 11,912 trace samples with none lost. On the Linux
side, startup enables only `VDD_BTP_3P3`, waits 2.856 ms, raises the EL721
enable GPIO155, loads `dualfp` and invokes TypeCheck. There is no reset pulse,
Linux QUP1_SE2 clock/interconnect transaction or claim of pins 36–39. The
service later lowers GPIO155 and disables the regulator normally.

This matches the Ubuntu one-shot sequence after making reset explicitly
opt-in. Trying another reset or driving the secure SPI controller from Linux
would diverge from stock rather than improve parity.

## Session 103 — exact One UI SHM bridge geometry

Date: 2026-08-21. Kprobes on stock's `qtee_shmbridge_register` measured the
addresses sent to secure firmware, not dma-buf metadata or userspace virtual
addresses:

```text
TA:      phys=0xf5400000 size=0x1302000
BAUTH 1: phys=0xfc300000 size=0x002a4000
BAUTH 2: phys=0xfc600000 size=0x002a4000
VMID=3, non-secure permission=6, secure permission=6, VM count=1
```

The reserved `qseecom_region` is 28 MiB and `qseecom_ta_region` is 48 MiB;
both are 4 MiB aligned and constrained below `0xffffffff`. SELinux was restored
to Enforcing and the fingerprint service was left healthy. This established a
specific upstream mistake: an earlier QCOMTEE experiment passed a device
DMA/IOVA where the Qualcomm TZMEM bridge API requires a physical address.

## Session 104 — physical DMA32 parity still returns type zero

Date: 2026-08-21. A clean Linux v7.2-rc3 build replaced that experiment with a
smaller QCOMTEE extension. Objects of at least 2 MiB use `qcom_tzmem` with
`GFP_DMA32`; `qcom_tzmem_to_phys()` supplies the bridge address and rejects any
range crossing 4 GiB. Ordinary messages retain upstream's page-backed path.
The build completed with LLVM 22. Its boot image SHA-256 is
`13d8eac81dfdcfbdcc32e5b22c0221303a61f1909b3748a8a2dfc487c1b866d3`.
The active partition and stored Ubuntu set were both reread and matched before
reboot; the preceding boot and complete module tree remain in
`/var/lib/gts9u-fingerprint-physaddr-backup-20260821`.

After Ubuntu booted, a kprobe on `qcom_scm_shm_bridge_create` proved the real
SCM arguments:

```text
TA:      phys=0xf1a00000 size=0x1302000
BAUTH 1: phys=0xf2e00000 size=0x002a4000
BAUTH 2: phys=0xf3100000 size=0x002a4000
VMID=3, permission bits=6
```

These have the same sizes, address width, VMID and permissions as One UI. The
TA loaded, controller operation 0 returned success and the BAUTH payload was
written, but TypeCheck again reported `sensor=0`; stock reports EL721 type 8.
Cleanup left the sensor powered off and QCOMTEE unloaded.

The host-visible transport, identity variants, TA source, memory geometry,
power sequence and reset behaviour are now ruled out. Work should resume at
the secure sensor boundary: obtain existing QSEE/TrustZone diagnostics or
identify the secure resource/ownership prerequisite that One UI establishes
outside the traced service path. Building `libfprint` integration before the
TA can see type 8 would only add an unusable frontend.

---

## Session 105 — One UI separates cached identification from `Prepare`

Date: 2026-08-22. A controlled restart of the One UI 8 fingerprint service and
a successful lock-screen authentication were captured without reading or
copying templates. The service starts with public driver type `8`, logs
`already sensor_type checked`, loads `dualfp` and makes command `1` (`Prepare`)
its first real TA operation. The gateway maps sensor-name enum `21` to EL721
type `8`.

Static analysis of stock `fingerprint.ko` completed the picture: a cold
`el7xx_probe` initialises its cached type to `-1`, while the service restart
observed a warm value already set to `8`. `FPBAuthService::checkSensorType()`
only sends command `16` (`TypeCheck`) when the driver value is unknown; a known
value is accepted and stored without repeating discovery. The X910 has one
soldered reader, so Ubuntu's platform driver can safely publish its fixed type
instead of making normal operation depend on a cold-discovery diagnostic.

The successful One UI unlock also records the actual authentication state
machine. It calls `Identify_Init` (`5`), repeats `Identify_Do` (`6`) while
servicing command-`12` control opcodes, and always closes with
`Identify_Final` (`7`). A bad-quality pass returned `39` and was finalised; the
next pass progressed through finger-down and capture-success to a match. This
provides the order needed for a future QTEE-backed `libfprint` driver without
exposing the biometric payload.

Android's generic `/proc/tzdbg/log` was found to be unsafe on this firmware: a
read rebooted the tablet. It is now explicitly excluded from further tests.
The specific `qsee_log` node returned no data without causing a reboot.

## Session 106 — Ubuntu securely initialises the physical EL721

Date: 2026-08-22. `scripts/probe-qtee-load-securefp.c` gained a bounded
`--prepare` operation reconstructed from `BAuth_Prepare`: command `1`, a
`0x80010` wire size over each `0x2a4000` TEE memory object, mode `2` and zero
calibration input. The selector is mutually exclusive with `--type-check` and
prints only status fields and the returned calibration length. It cannot
enrol, identify, capture an image or access a template.

The physical test ran on the DMA32/physical-address kernel from Session 104.
Its preflight found the EL721 powered off, QCOMTEE unloaded and no `/dev/tee0`.
The signed 19,927,128-byte `dualfp` image loaded and the TA returned:

```text
Prepare: invoke result 0; trustlet=0, payload=0,
         sensor_type=8, function_status=0, calibration_bytes=0
```

Cleanup was measured rather than assumed: `sensor_power=0`, `/dev/tee0`
absent, QCOMTEE unloaded and `reset_count=0`. This closes the secure sensor
communication boundary and supersedes Session 104's conclusion. Standalone
`TypeCheck` still returns zero in Ubuntu, but the stock steady-state path does
not require it once the platform identifies its fixed EL721, and `Prepare`
itself proves that the trusted SPI path works.

The remaining blocker is now userspace: implement the BAUTH enrolment,
identification, cancellation and lockout state machine behind `libfprint`, then
connect its transaction lifetime to the already-tested panel HBM, GNOME target
and Goodix regional touch suppression. Fingerprint support remains
experimental until the complete enrol/verify/GDM/reboot/crash matrix is
physically validated.

## Session 107 — isolate the EL721 early-rail bootloop

Date: 2026-08-25. A One UI cold trace measured the actual ordering as PMIC
`VDD_BTP_3P3`, GPIO155, then `smcinvoke`; stock neither claims GPIO91 nor asks
HLOS to touch the secure QUP engine. Three Ubuntu A/B kernels nevertheless
reset after ABL decompression and before the first persisted Linux message:
clean and incremental builds without GPIO91, followed by a rebuild with the
line restored. The identical failure with both variants rules GPIO91 out as
the boot regression.

The restored image
`9d4ace88d2d5e8c49f34945b8816bd468165d4562cf59282a9f64802b32bb899`
boots normally and predates the string `vreg_l2b_3p3`. The common failing
delta was the EL721 driver's `postcore_initcall`, which published a regulator
by modifying the live OF tree during core-provider initialisation. It has been
replaced with an on-demand path: the fallback EL721 device probes without any
rail node and the already-tested `regulators-el721` sibling is published only
when userspace explicitly requests sensor power.

The complete experimental kernel builds with no driver warnings and the
resulting `Image.gz` is
`1539dd48f6562a39edab3cad6dfe03e1b896d82102a6f1ae14e1453166c9be13`.
Loading the equivalent changeset as a signed module on the stable tablet with
power disabled registered the regulator, left the system responsive, and
reverted the tree cleanly on unload.

After a verified backup, the kernel was packed as boot image
`d315e4ffc751a6fb2e96ccb5b49fa623c0dfe760000882bcbd5e552574d7cbb4`
with the unchanged DTB and matching signed modules. It booted on the first
attempt. The supply node was absent at idle, appeared only on the first
`sensor_power=1`, registered at 3,296 mV with one consumer, and returned to
zero consumers on power-off. The active partition and stored Ubuntu boot image
were reread and matched; the previous set is in
`/var/lib/gts9u-fingerprint-on-demand-backup-20260825`.

The current QTEE self-test then loaded `dualfp` and issued calibrated
`Prepare`. Transport and function status succeeded, but the returned internal
sensor type remained zero. The boot and Linux-side rail regression are fixed;
the remaining blocker is still the secure initialisation needed for the EL721
to return identity bytes `07 15` to the TA.

## Session 108 — `Prepare` zero is success; matcher and `EnrollInit` work

Date: 2026-08-25. The last blocker was a response-decoding error, not secure
SPI. One UI obtains public sensor type `8` through command 16; its command-1
`Prepare` log reports zero for status, opcode, function result and function
status. Ubuntu's old unpowered word-zero value `8` was a reset/host-work status,
but the bridge had reinterpreted it as an EL721 type and consequently rejected
the correctly powered all-zero reply.

The final Linux-side parity test started from a reboot before the built-in
driver had acquired its GPIOs. A signed module held GPIO155 low, applied the
stock 100 mA regulator load, enabled `vreg_l2b_3p3` at 3,296 mV, waited 2.3 ms
and raised GPIO155. With QCOMTEE loaded afterwards, the signed TA returned an
all-zero `Prepare`, accepted control 76 and accepted the complete optical blob.
Every test unloaded QCOMTEE, lowered the line, disabled the rail and removed
the temporary live-tree node; `RAIL_AFTER=absent` was measured each time.

Operation 90 was then confirmed to leave the matcher absent: `EnrollInit`
returned 29. Selecting model `X916` with operation 88 constructs the matcher,
after which the same physical invocation returned zero from `EnrollInit` and
zero from `Cancel`. The corrected backend was rebuilt and repeated that result
with no parser or model override. Controls 45/46 are not an active-group key
exchange and the diagnostic no longer sends them by default.

One bounded `EnrollDo` without HBM or a finger returned status `-1`, opcode 0
and no template, then `EnrollFinal` and `Cancel` cleaned up normally. The next
boundary is therefore the real optical capture path — panel HBM, regional
touch handling, the interrupt loop and a user-present finger — rather than
sensor discovery or matcher construction.

The full pinned libfprint build then completed and produced package `gts9u4`.
After saving the `gts9u3` system library under
`/var/lib/gts9u-fingerprint-libfprint-backup-gts9u3-20260825`, the package was
installed on the tablet. The production library enumerated, prepared, opened
and closed the EL721 successfully; this was not an `LD_LIBRARY_PATH` test.
The imported `calib.dat` and `egoptbds.dat` had been missing from the production
firmware directory and were installed from the existing private test bundle.
Approximate implementation progress is now 80%: the real libfprint open path
works and enrolment can initialise/cancel, but no template has yet been
captured, persisted or verified through fprintd/GDM.

## Session 109 — physical FOD events reach production enrolment

The first end-to-end `fprintd-enroll` run found two API mismatches: fprintd
opens the device before claiming an operation, so repeating `Prepare` was
invalid in the same QTEE session; and its anatomical finger enum cannot be
used directly as BAUTH's four-slot template index. Operation setup now only
restores sensor power and uses a stable 1..4 slot mapping.

Long enrolment attempts revealed the panel's 15-second optical watchdog.
Package `gts9u9` rearms `fod_mode` every five seconds and leaves the desktop
visual to the unprivileged GNOME Shell extension. Extension version 7 polls
that panel state instead of depending on a root-to-session D-Bus call. This
also orders the shade after HBM: the temporary watcher sometimes darkened the
whole display before the panel brightened, an effect that must disappear when
the new version is loaded at the next GNOME session.

Finally, the Goodix sponge's monotonically increasing `fod_state` sequence is
used to recover press/release pairs shorter than the 45 ms libfprint poll.
Physical contacts at the stock coordinates now invoke BAUTH `EnrollDo` through
the installed system library. The measured replies were status/opcode
`-1/0`, `0/0`, `0/0`, exactly matching the older tokenless harness; no progress
or template was returned, and all rail, touch and panel states cleaned up to
zero afterwards.

The next boundary is secure capture rather than desktop plumbing. Stock issues
`Challenge` and a Gatekeeper-signed `Hat_OP` before enrolment and then services
the interactive opcode 4/5/87/6 sequence with controls 87 and 80. Ubuntu has
no Gatekeeper token source and the production driver has not yet implemented
that opcode loop. Approximate implementation progress is now 88%: fprintd,
power, panel HBM, overlay triggering, regional touch and BAUTH initialisation
are end-to-end, while template capture, persistence, verification and GDM
remain unproven.

## Session 110 — the HAT boundary is reproduced exactly

The old token probe only sent a zero-filled command-13 body and attributed its
code 62 to a bad signature. Disassembly of the stock gateway fixed the exact
wire layout: a packed 69-byte `hw_auth_token_t`, a selector, an optional
1024-byte payload and the 60-byte record returned by command 19 fill the
1165-byte input; the output is 1036 bytes. Typed `Challenge` and `Hat_OP` calls
now implement those measured offsets.

The bounded ARM64 harness generated a fresh BAUTH challenge, copied its ID into
an otherwise empty HAT and sent the matching challenge record. TrustZone then
returned 28, whereas the completely zeroed envelope still returns 62. The old
62 therefore meant that the challenge envelope itself was invalid. Reaching 28
with the correct envelope isolates the missing Gatekeeper/KeyMint HMAC without
copying an Android HAT, PIN, template or fingerprint image. Power and FOD state
were zero after both probes.

Progress remains approximately 88%: this removes ambiguity and prepares the
transport API, but it does not create the legitimate Ubuntu authentication
token required before the TA will enter opcode 4 and begin capture.

## Session 111 — TrustZone accepts Ubuntu's HAT and capture becomes recoverable

Date: 2026-08-26. Disassembly of dualfp and the stock gateway resolved the HAT
key path. `skeymast` command `0x203` encapsulates its current HMAC key for the
target `"dualfp"`; dualfp command 15 decapsulates that envelope, and control 49
installs the decoded metadata. The production bridge relays only those
target-bound secure-world objects. The raw key, Android PIN, Android HAT and
Android biometric data never enter Ubuntu.

Ubuntu maintains its own random, root-only Gatekeeper identity. It enrols the
same secret into each newly loaded `skeymast` session, verifies BAUTH's current
challenge and passes the resulting signed HAT to command 13. The ARM64 harness
then measured `Gatekeeper authorization probe: accepted`, `EnrollInit result=0`
and a clean cancel. The old code 28 came from the missing HMAC-key provisioning,
not from the challenge record or QTEE cache coherency.

The first physical run exposed two independent decoder/state-machine errors.
`BAuth_Enroll_Do` returns its opcode at word zero, not `+12`; with that fixed,
Ubuntu measures the same `4, 5, 87, 0` sequence as One UI. Result 39 is a normal
BAD_QUALITY capture result mirrored into the outer QSEECom response. Every
capture, including 39, must be closed with `EnrollFinal` and followed by a new
`EnrollInit`; otherwise dualfp remains in its `0x80000000` sentinel. Package
`gts9u14` implemented that recovery and repeatedly completed
`Init → Do → Final → Init` without wedging the trustlet.

Finally, One UI's `check_opcode` jump table supplied the missing control shape.
The first interpretation of opcode 5 treated one byte for control 87 and four
bytes for control 80 as output capacity. Later gateway analysis corrected
that interpretation; see Session 112. The negative dedicated-TZMEM kernel
experiment was removed from the branch because it changed neither HAT nor
capture behaviour.

Approximate implementation progress is 98.7%. HAT authorization, secure
sensor access, the desktop target, FOD touch events and a recoverable capture
protocol are in place. Still unproven are one accepted capture (`opcode 6`), a
complete stored template, verification, GDM integration and reboot/crash
recovery.

## Session 112 — physical progress and corrected control input framing

Date: 2026-09-02. After HwVault restoration, real fprintd enrolment reached
96% coverage with 16 accepted samples. Goodix emits a lone `released` sponge
event for most physical contacts, so FOD now discards the first isolated
release after enable as stale and accepts subsequent releases. The user
confirmed that the optical target appears correctly on repeated touches.

At high coverage, EnrollDo returned 70. Retrying it could advance one boundary
but eventually reset the TA's enrolment metrics to zero. Disassembly confirms
that Samsung maps 70 to return state 8 and invokes `enrollSystemFail`; it is
not a recoverable sample result. Only results 39 and 41 remain retries.

The underlying divergence was in the two controls issued for opcode 5.
`TeeProxy::ControlOp` forwards its third pointer and length to
`BAuth_Control_OP`, which copies them into the command-12 input payload.
Samsung supplies the active touch-status byte to control 87, then the signed
32-bit battery temperature in tenths of a degree to control 80. Ubuntu had
instead supplied empty inputs and advertised one/four output bytes, explaining
control 80's persistent result 51. Package `gts9u26` sends the stock input
shape, reads the temperature from `sm5714-battery/temp`, and removes the
result-70 retry.

That physical run reached 40% before result 70, proving that input length alone
was not the complete fix. Rechecking the captured One UI log showed
`tfd 2 0 1` at NOTIFY_DOWN and CAPTURE_STEP. Samsung therefore supplies the
pressed-state byte 2 to control 87, not zero. Ubuntu's zero-valued byte
described no active optical contact; it could accept some samples but poisoned
the session after enough quality retries. The driver and QTEE self-test now use
the measured value 2 for the next package and physical run. Implementation
remains approximately 99% until a template is saved and verified.

## Session 113 — press-time capture and repeatable Tab Companion diagnostics

Date: 2026-09-02. Package `gts9u27` supplied One UI's measured pressed-state
byte 2 to control 87. Physical enrolment reached 84% coverage and 13 accepted
samples in one run, but later runs could stall after several quality failures.
The missing timing boundary was in the touchscreen protocol: this Goodix
firmware publishes the dedicated Samsung FOD gesture on release, so userspace
was starting some captures after the finger had already left the glass.

The Goodix driver now synthesises `pressed` from the first ordinary coordinate
contact inside the fixed FOD rectangle and publishes its matching `released`
state when that suppressed slot ends. Kernel payload
`0469d300a33593bad813c6352620b380510590ed83d1a07f2789c49091f8c74b`
was packed as boot image
`55875b3c3dbd17cccd6ebc1e6caebb2701f976fcbc8009475edb4df06cf540d5`,
written to both the active Ubuntu boot partition and saved Ubuntu set, read
back identically and booted successfully. The preceding boot image and module
tree are retained in
`/var/lib/gts9u-fingerprint-goodix-press-backup-20260902`. Android was never
selected.

The first press-capable physical run proved that capture starts while the
finger is present and reached 26% coverage with four accepted samples. Its
precise log then exposed a second bug: after each real press capture, the old
release-only compatibility path could interpret a second firmware release as
a new contact and capture with no finger. Those phantom captures returned 39
until the TA exhausted its quality budget with result 70. Package `gts9u29`
disables release-only capture for the rest of an operation as soon as a real
press (or a complete press/release sequence delta) is observed. It also reports
17 enrolment stages, matching the accepted-sample count seen at 100% instead of
capping GNOME at 9/10, and emits one non-biometric aggregate log record per
sample. All 11 encrypted-template protocol tests and the complete ARM64 build
pass.

Tab Companion 1.1.3 adds a bounded test to its Info page. The user chooses the
duration and starts it locally; the view shows time remaining, coverage,
accepted samples, quality retries and secure result in real time. Escape or
Stop cancels the fprintd client and its partial transaction. Structured JSONL
is written below `~/.local/state/tab-companion/fingerprint-tests/`, with
`latest.jsonl` reserved for the most recent run, so a later diagnostic does not
depend on a simultaneous SSH window. The log contains no image, encrypted
template or credential bytes.

Approximate implementation remains **99%**. The duplicate-capture fix is
installed but still needs one user-started full run through Tab Companion,
followed by same-finger and wrong-finger verification. Lock-screen integration
and the requested icon-on-touch/rotation/keyboard-overlap polish remain after
that backend proof.

The first saved Tab Companion report lasted 73.7 seconds and retained all 15
quality retries even though the user cancelled it. It also exposed two
diagnostic defects: fprintd reported one stage before any physical contact,
while the secure aggregate remained at zero, and libfprint's INFO-level sample
records were filtered by the default daemon environment. Package `gts9u30`
now requires the paired press-capable kernel and never converts isolated legacy
RELEASE events into captures. Contact and sample aggregate records use MESSAGE
level so they reach the journal without globally enabling debug output. Tab
Companion 1.1.3 displays only the trustlet's accepted/coverage counters; the
generic fprintd callback remains in the raw report for correlation but can no
longer create a false `1/17` in the UI.

The next instrumented run produced 31 real press captures and no release
captures. Thirty returned secure result 39, one capture taken while the glass
was being cleaned advanced the trustlet to 2%/one accepted sample, and the
final attempt returned result 70 after the quality budget was exhausted.
Package `gts9u31` tested a cancelable 250 ms press-settle interval and recorded
the touch coordinates plus measured hold time for every capture. It installed
without a reboot; FOD and panel states were idle afterwards.

That test rejected every long contact despite 271–273 ms measured settling,
and the coordinates clustered correctly around the reader centre `(924,
2802)`. The difference from the earlier 84%-coverage run is instead the
capture boundary: Samsung's sensor acquires while covered and exposes the
buffered image at the paired RELEASE. Package `gts9u32` processes only the
first RELEASE that follows a real PRESS. This restores the proven timing while
still rejecting isolated startup releases and duplicate firmware releases.

## Session 114 — deterministic 62% failure and bounded opcode tracing

Date: 2026-09-02. The first `gts9u32` run accepted 10 of 11 contacts and
advanced secure coverage to 62%; its only quality retry was the first sample.
The following contact failed directly with result 70, proving that release-time
capture is correct but that a per-sample secure transition was still missing.

An initial reading associated Samsung's `CAPTURE_FINGER_LEAVE` message with
the following control 76 and `gts9u33` reproduced that call. The next physical
test disproved the hypothesis: it again failed at exactly 10 accepted samples
and 62% coverage. The two failures occurred at 53 and 64 seconds and used one
and two quality retries, so neither elapsed time nor the retry budget explains
the boundary. Static and trace review then established that control 76 fetches
the 1024-byte `adlg` diagnostic blob. A zero-capacity call merely receives the
known non-fatal shape status 51 and changes no enrolment state.

Tab Companion 1.1.4 delays final journal shutdown by 750 ms after fprintd
exits. This closes the observed race where the system journal retained result
70 but `latest.jsonl` missed that final aggregate line. The package and app
were upgraded and relaunched on the active Ubuntu desktop. Backend enrolment
is approximately **99%** complete pending one full physical save and verify;
the complete requested reader experience, including lock-screen integration
and icon/rotation/keyboard-overlap polish, is approximately **80%** complete.

Package `gts9u34` removes the ineffective control-76 probe and extends the
safe aggregate sample record with the complete EnrollDo path encoded as
`opcode:result:status`, plus EnrollFinal status. The report still contains no
image or template material. This instrumentation distinguishes a failure on
the initial wait, capture controls, acquired callback or terminal algorithm
reply without enabling noisy global GLib debugging. All 11 protocol tests and
the ARM64 build pass; package SHA-256 is
`b4c0dd699c9761793d7ef63e0a827807a86e39f5bb48077de98f4bce4547c239`.
It was installed live without restarting the tablet or selecting Android.

The `gts9u34` run failed deterministically after 10 accepted samples at 64%
coverage, with `4:0:0,5:0:0,87:0:0,63:0:0x80000000,0:70:0x80000000`.
Samsung's `check_opcode` jump-table case 63 constructs a legacy
`FINGERPRINT_TEMPLATE_ENROLLING` message from the current template id, group
and `100 - coverage`, invokes the notification callback, returns zero and
immediately re-enters EnrollDo. It performs no control transaction.

The earlier opcode-4 handling was the actual sequencing mismatch. One UI
receives opcode 4 before a touch, enables the sensor interrupt and blocks in
`BAuthDeviceWaitInt`; only the finger-down edge permits the next EnrollDo.
Ubuntu was consuming opcode 4 and the complete capture loop after RELEASE.
Package `gts9u35` now pre-arms opcode 4 after every EnrollInit and resumes the
remaining synchronous capture on PRESS. The sample trace retains the stored
opcode-4 status so the split transaction remains visible in Tab Companion.
The full ARM64 build and 11 wire tests pass; `gts9u35` was installed live with
SHA-256
`edf390dd414e83ab2d0159e91eaa0fdf8d1a893f476b176cf69fbe9957f61c23`.
