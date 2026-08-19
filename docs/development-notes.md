# Development notes

Durable conclusions from the Ubuntu port, and the list of things **not to
repeat**. The chronological history is in [`porting-log.md`](porting-log.md);
the current state is in [`hardware-status.md`](hardware-status.md).

This document starts by inheriting the postmarketOS port's knowledge. Entries
marked **[pmOS]** come from there and have already been paid for in debugging
time: repeating those experiments is time wasted.

## Goal and scope

An Ubuntu 24.04 LTS arm64 desktop on the same mainline kernel and the same
hardware postmarketOS v1.71 validated. The root lived on a microSD up to v0.17
and has lived on the internal UFS since v0.18. In the long run, compatibility
with ARM64 desktop software and, after that, Vulkan/Turnip, FEX, Box64 and
Proton/Steam **evaluated separately and with evidence**. Steam is not a
requirement for accepting the first working Ubuntu.

The postmarketOS repository is a stable, read-only reference. The Ubuntu port
does not intrude into it.

## Architecture decisions

- **The kernel is frozen for the first milestone.** The proven 7.2-rc3 and DTS
  are reused. A distribution change and a kernel jump at once makes regressions
  impossible to attribute.
- **Native userspace first.** Ubuntu's GDM3, Mutter, PipeWire and systemd are
  tried as they are. A pmOS patch is ported only when the specific regression
  it solved comes back, and with the evidence documented.
- **mmdebstrap, not a manual installation.** Every definitive change lives in
  the repository as configuration, a package, a driver, a patch or a script.
  Fixes applied only to the live installation are not accepted.
- **New partition labels** (`UBTS9U_BOOT`/`UBTS9U_ROOT`) so that a postmarketOS
  initramfs and an Ubuntu one do not compete for the same card.

## Working environment

- The Ubuntu build base is `wsl.exe -d Ubuntu-24.04 -u root`, directory
  `/root/ubuntu-gts9u`. The pmOS base is `/root/pmos-gts9u` and the two are not
  mixed.
- The WSL distribution called simply `Ubuntu` is a different environment and
  does **not** contain the right toolchain.
- Heavy builds run on a Linux filesystem and in a path without spaces. Versioned
  sources may live in the Windows folder.
- **[pmOS]** Do not pass complex Bash inline through PowerShell: the quoting is
  deformed. Write the script into `work/` and run it as a file.
- The same rule holds for Git Bash, and more treacherously: when invoking
  `wsl.exe ... bash -lc '...'` from Git Bash, **shell variables inside the
  inline script are lost**. A loop `for f in a b c; do echo "$f"; done` prints
  empty lines, which is how a dependency check came to report "OK" for tools
  that were not installed. It is not a loud failure: **it lies silently**. Any
  check that decides something must live in a script file.
- **[pmOS]** Do not use PowerShell's `Set-Content`/`Out-File` for Bash scripts:
  they write CRLF or a BOM and `set -euo pipefail` fails with `invalid option
  name`. Use the Write tool (LF) or `dos2unix`.
- With Git Bash on Windows, `wsl.exe` suffers MSYS path conversion; export
  `MSYS_NO_PATHCONV=1` before invoking it.

## Flashing without graphical Odin, and how to know what the device is booting

**The tablet's USB does reach WSL.** `usbipd-win` is installed on this machine;
the "WSL cannot see USB" of the old notes is solved with `usbipd bind --force
--busid 1-4` — which needs administrator — and `usbipd attach --wsl --busid
1-4`, which does not. A live WSL 2 session is required or `attach` fails.
Changing the device's mode changes its `VID:PID`, and the binding has to be
redone for the new identity.

Copying `~/.android/adbkey{,.pub}` from Windows into WSL's `/root/.android`
avoids having to authorise debugging by touching the screen.

**The USB identity says which mode it is in without looking at the screen:**

| `VID:PID` | Mode |
|---|---|
| `04e8:6860` | One UI booted (MTP + modem + ADB) |
| `04e8:685d` | Download mode |
| `18d1:6860` | TWRP (`product:twrp_gts9u`, `model:SM_X710`) |
| `18d1:d001` | Stock recovery (`product:gts9uwifixx`; its `adb shell` dies with SIGABRT) |

**heimdall 1.4.2 flashes this device correctly**, but `--no-reboot` and
`--resume` go together: after a command with `--no-reboot` the next one
**must** carry `--resume`. Skipping it does not merely fail that command, it
leaves the device's protocol unable to reopen, and neither a new session nor
recycling the USB attachment recovers it. The only way out is powering off and
entering Download again with the buttons. A single invocation that does
everything is best.

There is **no software way out of Download mode into recovery**. No heimdall or
Odin command does it: it is Volume Down + Power until it powers off and, right
after, Volume Up + Power.

**Before flashing anything to fix a boot, read the ABL's log.** It is in
`/proc/last_kmsg`, in the lines marked `[ ABL ]`, and it tells the whole boot:
which mode it chose, which partitions it loaded and whether it accepted each
binary. That is where the bootloader announces `BootReason`, `Booting Into
Mission Mode` or `Booting Into Recovery Mode`, and `BootMode = N`. Skipping
this cost three flashing cycles fixing a boot chain nobody was rejecting.

Two things that log makes clear, which save experiments:

- **The ABL accepts an unsigned `vbmeta`**: it says `(Booting) AUTHENTICATE
  fail but allow Vbmeta binary: vbmeta` and carries on. The correct vbmeta is
  an empty one made with `avbtool make_vbmeta_image --flags 2` — 4096 bytes,
  authentication and auxiliary blocks zeroed — like
  `port/sources/samsung-gts9u/vbmeta.img`.
- **Patching a signed `vbmeta` byte by byte does not work here.** Putting `02`
  at offset 120 of Samsung's image leaves a broken signature. That is what
  AnyKernel's `patch_vbmeta_flag` does, and it only works on ABLs that do not
  revalidate.

**`vbmeta` is read-only to the kernel** (`sde15`, a different LUN, `blockdev
--getro` = 1), so it is only ever written by Odin or heimdall, never from TWRP.

## `param` can leave the device stuck in recovery

Byte 0 of the `param` partition is the boot-mode flag the ABL reads: `0x02` is
`PARAM_BOOT_RECOVERY_ENTER`. **It survives a complete power-off**, so a cold
boot does not break the loop. It shows up in `/proc/last_kmsg` as `PARAM Flag
is PARAM_BOOT_RECOVERY_ENTER` followed by `BootMode = 2`; a normal boot shows
`PARAM_BOOT_CHARGING`.

It is cleared with `dd if=/dev/zero of=/dev/block/by-name/param bs=1 count=1
conv=notrunc`, and rebooting with `echo b > /proc/sysrq-trigger` is advisable
so as not to go through TWRP's userspace. Neither `adb reboot`, nor `reboot
system` via `/cache/recovery/openrecoveryscript` — which TWRP does consume —
nor rebooting from Download mode breaks the loop on its own.

But before clearing it, it is worth knowing **who set the flag**: normally
Android. When `fs_mgr` cannot mount the encrypted `/data` it writes
`fs_mgr_mount_all suggested recovery, so wiping data via recovery with prompt`
and leaves recovery requested. Clearing `param` without fixing the cause only
makes the cycle repeat once more.

## Changing `vbmeta` costs Android's `/data`

`metadata`'s encryption key is tied to the verified-boot state. When `vbmeta`
changes, Android can no longer derive it, does not mount `/data` and asks for
recovery. The only way out is `Format Data`, which erases `userdata` and
`metadata`.

The good part, verified: **One UI boots and works with the empty, unsigned
`flags=2` `vbmeta`** the Ubuntu installer requires. There is no need to
alternate `vbmeta` between systems, and milestone 2's requirement is met
permanently as long as the firmware is not reflashed.

## What not to repeat: the TWRP thread's `repack.zip`

It is an AnyKernel3 with two active lines, `split_boot` and `flash_boot` on
`boot`, plus `patch_vbmeta_flag=auto`. On this device it does **only half the
job**: it rewrites `boot` and cannot touch `vbmeta`, which is read-only. The
result is a `boot` that no longer matches a `vbmeta` still demanding
verification. It does not fix the stock recovery being restored — which on this
firmware does happen, verified — and leaves the device worse than it was.

## Packaging traps already known

- **[pmOS]** `init_boot`'s generic ramdisk must be **legacy LZ4**, not gzip.
  With gzip, ABL produces an initrd Linux rejects with "invalid magic at start
  of compressed archive" even though the Android image is valid.
- **[pmOS]** `APPEND_DTB_TO_KERNEL=1` and `DISABLE_RUNTIME_DTBO=1` are the only
  safe values. The opposites return ABL to its `ufdt` fork, which rejects the
  base DTB and enters Odin.
- **[pmOS]** The early overlay goes in `/usr/lib/firmware/...`. In the
  initramfs `lib` is a symlink to `usr/lib`; creating a `/lib` directory over it
  caused a reset before journald (pmOS v0.69).
- **[pmOS]** `unzip -p > destination` does not apply the ZIP's POSIX bits, and
  systemd ignores a regular file inside a `.wants` directory: a real symlink is
  needed. The manifest must carry the mode.
- **[pmOS]** Random AVB salts and CPIO timestamps broke reproducibility. The
  salts are derived from the image's SHA-256 and the ZIP uses a fixed epoch for
  all its members.
- **Reproducibility of the vendor fragment (found 2026-07-31).** `cpio
  --reproducible` normalises device and inode but **not** `mtime`. Since the
  initramfs overlay is copied with `install`, every build stamps the current
  time and `vendor_boot.img` changes hash even though its content is identical.
  When regenerating the v1.71 rollback ZIP, `boot`, `init_boot`, `dtbo` and
  `vbmeta` came out byte for byte identical and only `vendor_boot` differed for
  this reason. The Ubuntu pipeline must set `mtime` to 0 across the overlay tree
  before packaging it.
- **`sgdisk` can hang in WSL 2 while creating an image file.** With WSL kernel
  `6.6.87.2`, `sgdisk --zap-all` gets as far as writing the sectors and then
  stays indefinitely in its global `sync(2)` call (`super_lock`), even on a
  brand-new 16 MiB file. `build-sd-image.sh` uses `sfdisk` on the freshly
  recreated file and keeps the same GPT layout. The rule of running `sgdisk
  --zap-all` before writing a **physical microSD** does not change.

## Findings specific to this port

- **The validated kernel and the Alpine package's kernel are not the same
  thing.** In the reference port, the direct build — the one that produced the
  `boot.img` that was flashed and physically validated — applies 17 patches but
  **not** `ignore-console-null.patch`. The APKBUILD does the opposite: it
  applies that patch and instead **omits** `set-mi2s-codec-dai-format.patch`,
  the one that makes the CS35L45s sound. Since the kernel that boots is the
  direct build's, audio works; but copying the APKBUILD's patch list would have
  produced a kernel different from the validated one. This port reproduces the
  direct build's set and leaves the console patch behind
  `APPLY_IGNORE_CONSOLE_NULL=1`.
- **Line endings in files with no extension.** The TWRP installer and the
  scripts in `packaging/` have no extension, so a per-extension `.gitattributes`
  rule does not cover them. With CRLF, `#!/sbin/sh` simply does not execute. The
  repository forces `eol=lf` for everything.
- **A negative check passes on empty input.** A `grep` verifying that something
  does *not* appear returns "fine" when it cannot read anything at all. With
  `unzip` missing, the validator certified as safe an installer it had never
  even opened. Every check must first confirm it could read its input, and a
  missing tool has to abort, not degrade.
- **Do not identify a file by its prose.** The validator recognised the
  installer by a phrase in its comments and grepped for forbidden partitions
  across the whole file, flagging as dangerous the very documentation that makes
  it safe. An explicit contract line is used instead, and the code is analysed
  with comments stripped.
- **`initramfs-tools` silently skips a non-executable hook.** It neither fails
  nor warns. The `.deb` packaging forces the bit.
- **There is no udev in this environment.** `losetup --partscan` does not
  guarantee `/dev/loopNpM` appears; one has to wait and keep `kpartx` as an
  alternative.
- **`MODULES=dep` in `initramfs-tools` inspects the build host**, not the
  target, and fails with "failed to determine device for /". Building images
  requires `most` or an explicit list.

## Bluetooth on Ubuntu: two `btmgmt` traps

Both measured on this device with BlueZ 5.72, and both silently defeated
earlier versions of the service.

1. **`btmgmt` is useless with stdin on `/dev/null`**, which is exactly what
   systemd gives a service by default. It does not fail: **it exits 0 and
   prints nothing**. A `grep` over its output never matches and the caller
   concludes the controller is not there. With an empty pipe — `printf '' |
   btmgmt ...` — it behaves normally; a pty through `script(1)` works too.
2. **Run before `bluetoothd` it blocks in `epoll_wait` for minutes.** The
   service, ordered `Before=bluetooth.service`, took the whole stack down with
   it: 90 s of timeout on every boot and the controller unconfigured. With the
   daemon already up, the same call takes 0 s.

Hence this port orders the service **after** `bluetooth.service`, the opposite
of the reference port. Applying the address late costs nothing: a controller
with no address is unusable anyway, and `bluetoothd` adopts it immediately
without restarting.

To check whether the address is already set, `hciconfig` is used: it is an
ioctl, answers in ~3 ms and cannot block.

## A symbol at `=m` is absent, not degraded

This port installs no module tree: only the two signed ath12k ones. Therefore
**any `CONFIG_*=m` is equivalent to the feature not existing**. It is the
single cause of three failures that looked unrelated:

| Symbol | Visible symptom |
|---|---|
| `SQUASHFS=m` | `apt install firefox` and `chromium` fail: in Ubuntu they are transitional packages that install a snap, and a snap is a squashfs image |
| `BINFMT_MISC=m` | `systemd-binfmt.service` and `proc-sys-fs-binfmt_misc.mount` fail on every boot and the system stays `degraded` |
| `OVERLAY_FS=m`, `FUSE_FS=m` | snapd cannot overlay writable data on top of the snap |

Before accepting a desktop feature as working, check that its symbols are `=y`,
not `=m`.

## Do not trust `Recommends` for anything that matters

The v0.5 root filesystem shipped without `snapd` because it was left to
`ubuntu-desktop-minimal` to recommend it. What matters is declared explicitly.

## A compiled driver is not an offered driver

`iio-sensor-proxy` ships four compiled SSC drivers, but each one only looks at
devices udev has tagged with its name in `IIO_SENSOR_PROXY_TYPE`. Upstream's
`80-iio-sensor-proxy.rules` tags the FastRPC node with `ssc-light ssc-compass`
and nothing else, so `drv-ssc-accel` never receives a device even though it is
linked into the binary. The symptom is baffling: `ssccli` reads the
accelerometer perfectly and the daemon says `No accelerometer`.

When a capability exists in the code but the system does not see it, look at
the discovery mechanism first, not at the implementation.

## Restarting the ADSP hot leaves the system with no sound

`echo stop/start > /sys/class/remoteproc/remoteproc0/state` with the system
running destroys the ALSA card, and the audio services do not re-register
themselves. It recovers by rebooting. Useful for debugging sensors, but it has
to be said before leaving the tablet in anyone's hands.

## The first SSC client can leave the ADSP's handover asserted

On Ubuntu, the first `ssccli` query followed by the first `iio-sensor-proxy`
can leave the `q6v5 handover` IRQ firing about four times a second. The proxy
consumes almost a core, the `irq/16-smp2p-adsp` thread another, and DPU and
GENI I2C timeouts coincide. Restarting the whole ADSP is not acceptable because
it destroys audio; replacing only the `iio-sensor-proxy` client after SSC
answers removes the storm.

The recovery must run `After=display-manager.service`: GNOME is what actually
opens the accelerometer. If the unit carries `Before=display-manager`, the
health window closes before the failure appears and produces a false positive.
The helper measures the `q6v5 handover` counter every two seconds for 30
seconds, refreshes the proxy once only if it grows more than twice, and then
watches the second client. On the validated boot the first client produced 3
IRQs in 2 s; the second finished with an increment of 0, 45 ms of CPU and
auto-rotation working.

This storm worsens the global contention, but it does **not** on its own
explain the whole keyboard story: the boot that held 2,046 transitions over
eight hours also accumulated handovers. Do not turn that correlation into a
root cause of the pogo transport without the final physical proof.
## libssc's synchronous wait was not a wait, it was a loop

`ssc_common_wait_sync_context()` in libssc 0.4.4 spins the default GLib context
with `g_main_context_iteration (..., FALSE)`. With `may_block` at `FALSE`, GLib
forces the poll's timeout to zero, so that does not wait: it iterates as fast
as the CPU allows. Any request the SSC does not answer **pins a whole core for
the lifetime of the process**.

On the X910, the one not answering was the light sensor. With the `ssc-light`
driver still offered, GNOME called `ClaimLight` and `iio-sensor-proxy` stayed
inside `ssc_sensor_light_open_sync()` forever:

```
#3 ssc_common_wait_sync_context (ctx=…) at ../src/libssc-common.c:56
#4 ssc_sensor_light_open_sync (…)      at ../src/libssc-sensor-light.c:225
#5 ssc_light_set_polling (…)           at ../src/drv-ssc-light.c:94
#6 handle_method_call (… method_name="ClaimLight" …)
```

Measured cost, tablet idle: 199 ticks per 2 s (one core at 100 %) from boot,
~35,000 turns a second, 106,941 `ppoll`s in three seconds — 99.64 % of the
process's time — all with `{tv_sec=0, tv_nsec=0}` and all returning `0
(Timeout)`, **94.7 °C** in the hottest thermal zone, and the charging current
sunk.

The baffling part was that **the daemon doing the spinning worked**:
auto-rotation was fine while it burned the core. It makes sense now: because
the loop iterates the main context, D-Bus and the accelerometer's flow were
dispatched from inside the wait. And that is why killing it did not help
either — restarting it loses the sensor until the session returns, and the new
instance spins just the same.

The fix is to block in `poll()`
(`packaging/sensors/fix-ssc-sync-wait-busy-loop.patch`). It does not change
behaviour: the callback that ends the wait is dispatched from that same
context, so what wakes the poll is exactly what ends the wait, and the other
sources are still dispatched as before. Only the thread driving the context may
block on it, hence the `g_main_context_acquire()` and the fallback on the
`GCond` the callback already signalled.

With that, and with `ssc-light` out of the driver table
(`disable-broken-ssc-light.patch`), the same boot gives **1 tick per 2 s** and
48.9 °C with auto-rotation intact.

The absence of the SSC envelope's optional fields was not the cause either. The
official Android/CHRE client sends, for an *on-change* sensor, an
`sns_std_request` with `batch_period=0`, `flush_period=3000000` and
`is_passive=false`. That protobuf was reproduced literally in libssc and tested
after a full reboot: GNOME saw `HasAmbientLight=true`, but `ClaimLight` timed
out again and `LightLevel` stayed at 0 lux. Do not keep that patch: the
protocol itself says omitting `is_passive` is equivalent to an active request,
and the physical evidence did not change.

There are two routes, though the default search returns only one. An explicit
query also discovers `ambient_light_sub`, name `stk_stk31610_sub`, SUID
`5230347032368999062:3046173514946711665`, available and *on-change*. It too
accepts the QMI transaction with the exact Android envelope and publishes
neither the configuration event nor a sample. Both instances in the registry
(`stk31610_0` and `_1`) are therefore measured; selecting another entry of the
same `data_type` is pointless, because the firmware returns only one SUID for
`ambient_light`.

Do not implement automatic brightness from the camera as a silent substitute.
Opening an image sensor periodically would cost power, privacy and arbitration
with applications, and auto-exposure removes any stable relationship between
pixel luminance and lux. It is a different architecture that needs an explicit
decision, not a fix for the ALS.

**The AP route is closed by measurement, not by hypothesis.** Samsung's
registry places both STK31610s on I²C `bus_instance` 3 and 4, slave 72 (0x48),
with `dummy_vdd` rails (nobody switches them: they are expected to be powered
always). Those two `bus_instance`s are exactly `i2c_hub_3` (`i2c@98c000`) and
`i2c_hub_4` (`i2c@990000`) — the stock DTS calls them
`qupv3_hub_i2c3`/`_i2c4` and hangs the SM5440 and the MAX77816 off them **from
the AP**, so the AP and the SSC really do share those engines. A full
`i2cdetect -r` of both returns only 0x63 and 0x18, and 0x48 NAKs on all 16 AP
buses. The neighbours answer on the same pair of wires, so the bus is fine and
**the chip answers neither master**. Do not propose a mainline IIO driver for
the STK31610 again: it has nothing to bind to. Nor go looking for the
STK31610/STK3A6X register map: the missing datasheet was never the blocker.

**Invisibility from the AP does not prove absence, and the control proves it.**
The AK0991x compass works (live heading 127–134°) and sits on the SSC's I²C
(`bus_instance=2`, 0x0c); yet enabling `i2c_hub_2` on the AP makes 0x0c appear
nowhere. In other words: a perfectly functional SSC sensor is exactly as
invisible to the AP as the ALS is. The SSC's sensors hang off the DSP's own
I²C, and `bus_instance` is **not** the hub's SE index. Corollary: 0x48's NAK
closes the AP route, but does not license the conclusion that the chip is
unpopulated or unpowered. The ALS's failure is on the SSC side.

**How to check the compass without getting it wrong** (this was botched once):
the interface lives on the `/net/hadess/SensorProxy/Compass` object, not on
`/net/hadess/SensorProxy`; introspecting the parent object does not list it and
makes it look as though it does not exist. Also, claiming sensors over SSH
returns `Not Authorized` because the session is not "active" to polkit: a
temporary rule in `/etc/polkit-1/rules.d/` for
`net.hadess.SensorProxy.claim-sensor` is needed, and must be removed
afterwards.

**The useful comparison is compass (works) against ALS (does not)**, because
they share transport, registry and DRI:

| Field | `ak0991x_0` (works) | `stk31610_0/1` (does not) |
|---|---|---|
| `num_rail` | 1 | 2 |
| `vddio_rail` | `/pmic/client/sensor_vddio` | `/pmic/client/dummy_vdd` |
| `vdd_rail` | absent | `/pmic/client/dummy_vdd` |
| `dri_irq_num` | 89 | **0** |
| `irq_pull_type` | 3 | **0** |

The ALS is the only one asking for `dummy_vdd` rails and a DRI of 0 with pull
0, which looks very much like an unfilled reference-board template — and the
ADSP firmware contains precisely the error string `i2c_power_on failure`.

**That hypothesis was tested and was NOT it.** The installed registry in
`/usr/share/qcom/sm8550/Samsung/gts9uwifi/sensors/registry` was edited to give
the ALS exactly what the compass uses — `vdd_rail=/pmic/client/sensor_vdd` and
`vddio_rail=/pmic/client/sensor_vddio` — plus `is_dri=0` in
`stk31610_{0,1}.ambient_light.config` to force polling. It was checked **after
a complete reboot**, not merely after restarting
`hexagonrpcd-adsp-sensorspd`, so the DSP would reread the registry. Result:
accelerometer 84 samples, magnetometer 30, **light none**. Both suspect fields
are ruled out; do not repeat them.

**Use `ssccli`, not `iio-sensor-proxy`, to work on the ALS.** `libssc` already
installs `ssccli`, which accepts `--sensor light|accelerometer|magnetometer|
compass` and `-v` to dump the whole QMI. It works even when
`disable-broken-ssc-light.patch` has removed `ssc_light` from the proxy,
because it does not go through it. In this session the proxy was rebuilt
without that patch before this was realised: wasted work.

What `ssccli -v --sensor light` shows is that the transport is fine: the enable
request is sent, the DSP answers `Control` with `Result = SUCCESS` and a Client
ID, and then **not one indication arrives**. It is not a client failure, nor
permissions, nor QMI.

### The Xiaomi sheng reference closes the registry route

The Xiaomi Pad 6S Pro 12.4 (`xiaomi-sheng`) is the good contrast: **same SM8550
SoC, same SEE, same `libssc` plus `adsprpcd-sensorspd`**, and its automatic
brightness works. Its `sheng-sensors` package carries the full registry. Not to
be confused with the Xiaomi Pad 6 (`pipa`), which is a different SoC and was
already ruled out under pmOS.

Its ALS is a Sensortek **STK3BCX** on `bus_instance` **4**, slave **72**
(0x48) — the same bus and the same address as our `stk31610_1`. Configuration
differences: real `sensor_vdd`/`sensor_vddio` rails, `is_dri=0` (polling),
`dri_irq_num=16`, `irq_pull_type=2`.

That **exact** shape was replicated on both STK31610 instances and checked
after a complete reboot: accelerometer 544 samples, magnetometer 19, **light
none**. With that, the registry route is exhausted: it is not the
configuration.

The remaining difference cannot be touched from here: sheng runs Xiaomi's ADSP
firmware, which contains a working `sns_stk3bcx`, and this tablet runs
Samsung's with `sns_stk31610`. The driver lives inside the signed blob, and the
alternative — loading Qualcomm's reference `adsp.mbn` — is already ruled out
because Samsung's secure boot rejects it (see the `&remoteproc_adsp` note in
the DTS). **Do not try to fix the ALS through the registry, or by copying
another device's configuration, again.**

### The sensor IS there, and this proves it

Moving `bus_instance` to a bus where the chip is not gives a **different**
answer, and that difference is the proof. Pointing both instances at
`bus_instance` 2 (the compass's) and rebooting, `ssccli --sensor light`
answers:

```
Unable to initialize light sensor: UNKNOWN
```

that is, the DSP **does not publish the SUID**: its start-up routine found
nothing and abstained. With the original configuration (buses 3 and 4) the SUID
**is** published, `HasAmbientLight` becomes `true` and the enable is accepted
with `Result = SUCCESS`.

Publishing therefore implies the chip's identification worked. A firm
conclusion, and one that definitively corrects what was suggested earlier:
**the STK31610 is present, powered and correctly identified by the DSP on SSC
buses 3 and 4 at 0x48.** It is not a problem of presence, rail or bus. The only
thing that fails is sample delivery inside the blob: it probes fine, accepts
the enable, and emits not one indication.

### Reviewing Samsung's source: nothing is missing on the AP side

The X910's official `Kernel.tar.gz` confirms what Samsung compiles for this
tablet (`arch/arm64/configs/vendor/kalama-gki_defconfig`):
`CONFIG_LIGHT_FACTORY=y`, `CONFIG_LIGHT_SUB_FACTORY=y`,
`CONFIG_SUPPORT_DUAL_OPTIC=y`, `CONFIG_SUPPORT_VIRTUAL_OPTIC=y`,
`CONFIG_TABLET_MODEL_CONCEPT=y` and `CONFIG_SUPPORT_LIGHT_SEAMLESS=y`. This
**corrects** the note from pmOS session 108, which had `TABLET_MODEL_CONCEPT`
down as absent based on the config extracted from `boot.img`.

Even so, none of that is a requirement for the sensor to emit:

- `drivers/adsp_factory/` is the **factory test** driver; it exposes sysfs and
  requests self-tests. Android's sensor HAL works without it.
- `CONFIG_SUPPORT_LIGHT_SEAMLESS` only sends
  `OPTION_TYPE_SSC_LIGHT_SEAMLESS` to `MSG_SSC_CORE` with four lux thresholds
  for switching between the main and secondary sensors, and **only if any of
  them is non-zero**. It is not a start-up handshake.
- `CONFIG_SUPPORT_PANEL_STATE_NOTIFY_FOR_LIGHT_SENSOR` is **not** enabled,
  which agrees with pmOS's negative test of sending panel notifications.

Nor does this tree contain any `stk31610_light.c`: the X910 uses the generic
`light_factory.c`. There is therefore no AP-side piece this port is omitting.

Checked symbol by symbol across Samsung's four defconfigs
(`kalama-gki_defconfig`, `kalama_sec_defconfig`,
`kalama_sec_userdebug_defconfig` and `kalama_GKI.config`):
`SUPPORT_BRIGHTNESS_NOTIFY_FOR_LIGHT_SENSOR`,
`SUPPORT_PANEL_STATE_NOTIFY_FOR_LIGHT_SENSOR` and
`SUPPORT_DDI_COPR_FOR_LIGHT_SENSOR` are **enabled in none of them**. Android
does not feed the ALS panel state or brightness either, so the DSP has to emit
without them. This explains and confirms pmOS's negative panel-notification
test: nothing was missing, that route is simply not used in this product.

### It is not the client: the DSP transmits nothing

Measured with `ssccli -v`, counting QMI messages received **after** the enable,
within the same time window:

| Sensor | total `rx` | `rx` after the enable |
|---|---|---|
| accelerometer | 180 | **171** |
| light | 8 | **0** |

`libssc` handles the *on-change* case correctly (msg 514 with no payload, which
is right for `ambient_light`) and its parser would only discard indications
with a different `msg_id` — but none arrive at all. That rules out the failure
being in libssc, in `iio-sensor-proxy` or in the parsing.

### A basis for reverse-engineering the blob

All that remains is disassembling `sns_stk31610` inside the ADSP firmware. The
starting point is already established, so as not to repeat it:

- the segment with the driver is **`adsp.b18`**, which `adsp.mdt` loads at
  **`vaddr = 0xb3200000`** (ELF32, 52 program headers, `filesz = 1935448`,
  R+X);
- a string's virtual address = `0xb3200000 + offset_in_the_file`;
- key strings and their offsets: `[TOP-ALGO] all data was skipped` at 1867920
  (`0xb33c8dd0`), `skip update bl = %d %d` at 1867616 (`0xb33c8ca0`),
  `STK3A6X HW absent` at 1751368 (`0xb33ab5c8`);
- tool: `rasm2 -a hexagon -b 32` (radare2 ships the Hexagon backend).
  `llvm-objdump` **does** list `hexagon` as a target but its raw binary mode
  accepts neither `-b binary` nor `--binary-architecture`; the segment has to
  be wrapped in an ELF32 with `e_machine = 164` (EM_HEXAGON) before using it.

### `factory.ssc` disassembled: there is no privileged factory mode

`factory.ssc` is extracted from `vendor.img` with `fsck.erofs --extract` (the
image is EROFS) and lands in `bin/factory.ssc`: a 55 KB, stripped aarch64 ELF.
It is ordinary ARM64 reverse engineering, not Hexagon.

**There is no `data_type` for SSC_CORE.** The binary contains only six data-type
strings: `ambient_light`, `ambient_light_sub`, `proximity`, `proximity_sub`,
`pressure` and `sensor_temperature`. `MSG_SSC_CORE` is not a SEE sensor with a
SUID of its own, so the idea of "enabling factory mode by sending it message
613" has no recipient.

And the disassembly gives something better: the exact translation from
`MSG_TYPE` to SSC message, identical at both points where it is built
(`0x9850` and `0xa330`):

| `MSG_TYPE` | SSC message |
|---|---|
| 11 `SET_CAL_DATA` | 512 |
| 13 `FACTORY_ENABLE` | **514** |
| 14 `FACTORY_DISABLE` | 10 |
| the rest | **600 + `MSG_TYPE`** (hence 609, 612 and 615) |

```
9850: cmp  w22, #0xd        // FACTORY_ENABLE
9858: mov  w4,  #0x202      // -> 514
9860: add  w8,  w22, #0x258 // the rest -> 600 + msg_type
9868: cmp  w22, #0xe        // FACTORY_DISABLE -> 10
```

The important part: **`FACTORY_ENABLE` is message 514, which is exactly the
standard `ENABLE_REPORT_ON_CHANGE` `libssc` already sends.** Samsung's factory
daemon starts the ALS the same way we do; there is no privileged mode that
enables the sensor some other way. The last actionable candidate is ruled out.

A note on scope: the firmware is **signed** and Samsung's secure boot verifies
it, so even if the fault is found **the blob cannot be patched**. The only
actionable outcomes are discovering (a) a non-obvious registry key that changes
the behaviour, or (b) a message the AP should be sending and we are not. The
live candidate for (b) is `MSG_TYPE_OPTION_DEFINE`, which by the already
verified correspondence (`GET_DUMP_REGISTER`=9→SSC 609, `GET_DHR_INFO`=12→SSC
612, that is SSC = 600 + `MSG_TYPE`) is **SSC message 615**, with
`OPTION_TYPE_LCD_ONOFF` = 2 as the payload's first integer. What is missing is
deducing the exact protobuf encoding `factory.ssc` uses for that array of
`int32`.

One concrete difference from pmOS, should this be picked up again: pmOS leaves
`i2c_hub_4` **disabled** on the AP and gives that pinctrl to the DSP with
`pinctrl-0 = <&hub_i2c4_data_clk>` in `&remoteproc_adsp`, whereas this branch
enables `i2c_hub_4` for the keyboard's MAX77816 and deletes the ADSP's pinctrl
entirely. Even so, the ALS gave no lux under pmOS either, so returning SE4 is
not on its own the solution.

Two lessons beyond this particular failure:

- **A `ppoll` with a zero timeout that always returns `Timeout` is not a
  badly built `GSource`**: it is somebody iterating the context without
  blocking. The signature points at the caller, not at the event loop.
- **We compile the sensor stack ourselves**, so a loop like that is fixed where
  it is. Taming the process from outside — `renice`, cgroups, watched restarts
  — only hides the consumption, and in this case also broke rotation.
## The digitizer does not announce that it is leaving: it goes quiet

`samsung_wacom_w90xx` synthesises leaving range by counting valid frames with
the `IN_RANGE` bit clear, three in a row. That covers the case where the
controller keeps talking, but not the other one: **when you move the pen away,
the controller can simply fall silent**. Measured: 0 interrupts in 5 s with
`BTN_TOOL_PEN` still at 1 and `ABS_DISTANCE` frozen. The last valid frame
carried distance 235 of 255 — the pen right at the edge of range — and there
the conversation ended.

Without a timeout, `in_range` stays `true` **until the next reboot**.

It matters more than it looks, because libinput groups this digitizer with the
Goodix touchscreen: `udevadm info /dev/input/event4` shows
`LIBINPUT_DEVICE_GROUP=18/0/0:input/ts`, and that `18/0/0` is the bus and IDs
**of the pen**, not of the Goodix. With a tool it believes to be in proximity,
libinput arbitrates the touchscreen.

The fix is a 250 ms `timer_list` that treats silence as a departure (the frame
counter stays as the fast path). Idle reports arrive every 25 ms, so that is
ten missed frames: too many to fire with the pen present, few enough not to
notice when it is not. `exc3000.c` in mainline does exactly this, for the same
reason.

Verified on hardware after flashing: the flag rises to 1 while drawing, returns
to 0 on its own when the pen is moved away, and stays at 0 through 90 s of
continuous sampling.

**Beware the easy conclusion, which I nearly accepted.** All of this explained
the symptom the owner reported so well — an area of the screen that answers the
pen and not the finger, except when dragging in from outside, which is exactly
how the arbitration rectangle behaves — that I was about to call it the cause.
It is not, or not on its own: with the flag pinned and verified pinned, she
found no dead zone at all. The stuck proximity flag is a real defect and it is
fixed; **the touch fault is still open**.

For the next episode, the question that splits it in two is in
`work/catch-dead-zone.sh`: if touches in the dead zone reach the kernel, it is
userspace discarding them; if they do not, it is the Goodix and the pen has
nothing to do with it. The tool is validated against a real touch, so that "0
contacts" means something.

## The charging limit was not the loop, it was what we asked for in the contract

For two sessions the charging ceiling was hunted in the wrong place.
`SM5440_TARGET_IBUS_MA`'s comment said 3200 had collapsed the bus and that 2200
was "prudence, not a measured limit", so raising that target again was the
natural move. **It achieves nothing**, and now we know why.

With `TARGET_IBUS_MA` at 2200, 2600 and 2800, the measured `ibus` did not
budge: 2587, 2596, 2600 mA. Forcing it to 3400 did raise the request —
`in0_input` reached 9860 mV, nearly the ceiling — but voltage and current fell
**together**, which is the signature of a source folding back, not of a loop
that is not pushing.

The reason was two lines further on, in `sm5440_start()`:

```c
target_ma = min(target_ma, 3000);
```

The **PPS contract's** current was fixed at 3000 mA. `dmesg` had been saying so
all along: `direct charge started: PPS 8760 mV/3000 mA`. `ibus` topped out at
2895 because the adapter was in current limit, and the floor the loop itself
asked for — about 700 mV above `2×vbat`, which at 0.17 Ω is ~4.1 A — already
wanted more than we were entitled to take.

TCPM added no cap: `tcpm.c` clamps the request against what the source
advertises (`min(src_ma, req_op_curr)`), and this one advertises 5 A.

Swept on hardware, 41–44 % charge, 20 s per step:

| Contract | Pack | ibus | vbus | Die |
|---|---|---|---|---|
| 3000 mA | 21.4 W | 2601 mA | 8556 mV | 45.5 °C |
| 3200 mA | 22.8 W | 2864 mA | 8611 mV | 46.5 °C |
| **3400 mA** | **25.0 W** | 2960 mA | 8652 mV | 48.5 °C |
| 3600 mA | 24.2 W | 3141 mA | 8801 mV | 54.0 °C |
| 3800 mA | 24.2 W | 3128 mA | 8780 mV | 55.0 °C |
| 4000 mA | 24.2 W | 3167 mA | 8835 mV | 55.0 °C |

Above 3400 the input current keeps rising and the delivered power does not:
that is loss in the pump, paid for with six degrees of die in exchange for
nothing. 3400 held **25.2–25.5 W for five minutes** with the die flat at
49.5 °C and the pack at 36.4 °C.

Three things to take away:

- **A loop that does not react to its setpoint is saturated somewhere else.**
  The signal was that `ibus` did not move between 2200 and 2800; that alone
  said the target was not the limiter, before touching anything else.
- **Asking for more voltage from a source in current limit folds it back.** That
  is what was interpreted at the time as series resistance in the cable. The
  drop between requested and measured *grows as the current falls*, which is
  the exact opposite of what a resistance does — the driver itself already
  warned about this from the `vbus` ADC.
- **Ten minutes of compilation, not forty.** Measured: `.config` to `boot.img`
  in 10 min 38 s, 5,269 objects on 16 cores. Even so, it is worth exposing
  whatever is going to be swept as a parameter
  (`/sys/module/sm5440_direct/parameters/`): a step goes from eleven minutes
  plus a reboot to two seconds, and the reboot also stops charging and moves
  the measurement's conditions.

## GNOME cannot cover the S Pen's gestures, and Settings takes no panels

Written down before starting it, so as not to investigate it from scratch
again.

**What GNOME already gives for free.** It recognises the pen and stores
per-device settings for it: `dconf dump /org/gnome/desktop/peripherals/` shows
`[stylus/default-056a:0000]` with `button-action` and `pressure-curve`, and
`[tablets/056a:0000]` with `area`. So the "Wacom Tablet" panel works with our
digitizer untouched. It is worth defining a real stylus in the libwacom entry
instead of `@generic-no-eraser`, or the panel offers three buttons for a pen
that has one.

**Where it ends.** The actions a stylus button accepts are only `default,
middle, right, back, forward`. The `keybinding` value — the only one that would
allow "gesture → arbitrary action" — belongs to `GDesktopPadButtonAction`,
which is for the buttons on a Wacom tablet's body, not for the pen. There is no
way to map a gesture from GNOME.

**Settings takes no third-party sections.** Panels are registered in
`cc-panel-loader.c`, compiled into the binary; there is no external panel
directory and no plugin API in 46.7. Adding a section would mean forking
`gnome-control-center` and rebuilding it on every Ubuntu update, which would
also leave us behind on security. Ruled out for this port.

**The recommended shape, if it is picked up.** A session daemon (`systemd
--user`) that opens the GATT and writes to `/dev/uinput`, its own GSettings
schema in the device package, and a separate GTK4/libadwaita app. On Wayland a
normal application cannot synthesise key presses: uinput is the way out that
depends on neither portals nor per-session consent, and access to the node is
solved with a udev rule — the same pattern `10-fastrpc.rules` already uses for
the `fastrpc` user.

**And the order.** The side button is already visible as `BTN_STYLUS` on
`event2`, so click, double click and long press can be implemented **without
BLE**. That portion validates the whole path — daemon, uinput, GSettings, app —
against hardware that already works, before entering the GATT, which is the
part whose cost cannot be bounded. The UI is the last 10 %, and the gesture
list is dictated by the protocol: designing it before knowing the protocol is
inventing half of it.

### Docking and orientation already have an ABI in Samsung's driver

The X910's official source removes two unknowns before any code is written.
TLMM GPIO137's `PDCT` line is not proximity over the screen: the driver calls
it *garage*, configures it with an IRQ on both edges, and uses it as the `pen
in/out` signal. On this model, high means inside the silo. The input ABI
Samsung publishes is `SW_PEN_INSERT`; for the S9's bidirectional silo it adds
`SW_PEN_REVERSE_INSERT`.

Orientation must not be inferred from screen rotation either. When the pen is
put away, the host sends the Wacom command `0xee`
(`COM_REQUEST_GARAGEDIRECTION`) and the `REPLY_PACKET`, subtype 6, carries
`EPEN_GARAGE_UPSIDE=1` or `EPEN_GARAGE_DOWNSIDE=2` in byte 5. It is also the
same subtype the BLE charge-state reply uses, so the driver has to serialise
the request and remember which reply it is waiting for.

BLE charging is governed by the Wacom digitizer, not by BlueZ: the commands
Samsung documents are `0xe8`–`0xed`, `0xef` and `0xf3`, and the notifications
distinguish off, start, transit, reset, maintenance and charge complete. That
provides a **charge state**, but the driver's source exposes no battery
percentage for the pen; one must not be invented, nor charge time confused with
capacity.

## What not to repeat

Inherited from postmarketOS; every point cost at least one physical iteration.

### Kernel and configuration

- **[pmOS]** Do not leave a critical provider at `=m`. This port does not
  auto-load a general module tree: a symbol at `=m` usually makes the subsystem
  fail to appear. `HID_GENERIC`, `INPUT_EVDEV`, `QCOM_FASTRPC`,
  `POWER_RESET_QCOM_PON` and the LPASS-LPI pinctrls must be built in.
- **[pmOS]** `CONFIG_GPUCC_SM8550` does not exist; the real symbol is
  `CONFIG_SM_GPUCC_8550`. `DRM_MSM` will not go to `=y` with `QCOM_LLCC/OCMEM`
  at `=m`.
- **[pmOS]** `msm.separate_gpu_kms=1` on the cmdline is mandatory for Adreno to
  create its render node without an mdss component master.
- **[pmOS]** Do not re-enable `lpass_ag_noc`: it caused hangs and audio works
  without it.
- **[pmOS]** Do not add improvised MMIO/ioremap reads to diagnose probes, nor
  per-event `dev_info` in high-frequency paths such as DWC3.

### Wi-Fi and Bluetooth

- **[pmOS]** Do not use the Samsung HMT.2.0 BDF with the official HMT.1.1 amss:
  it crashes with MHI RDDM. The QRD BDF with its ELF wrapper is the definitive
  one, and must not be stripped of that wrapper.
- **[pmOS]** The generic Bluetooth NVM fails with `-52`; the valid one is
  `hmtnv20.b21`. Its address is null and EFS's, mounted `ro,noload`, has to be
  applied.

### Display and sensors

- **[pmOS]** The panel needs a `pm_test=platform` cycle before the display
  manager. `pm_test=devices` does **not** recover it. Do not repeat
  `unbind`/`bind` of `msm_dsi`.
- **[pmOS]** Do not use anonymous `systemd-run --on-active` timers to wake the
  display or to recover SSC: they are delayed by 7 to 16 s and overlap. One
  cancellable unit.
- **[pmOS]** The STK31610 ALS route is exhausted: registry, rails, streaming
  modes, the exact Samsung request and the comparison with `persist` produce no
  lux. Do not instantiate it as `sensortek,stk3310` and do not copy the Xiaomi
  Pad 6's configuration. Do not enable the AP's I²C controllers for SE3/SE4:
  those buses belong to the DSP.
- **[pmOS]** `ACCEL_MOUNT_MATRIX=0,1,0;-1,0,0;0,0,1` is a validated physical
  measurement; keep it even though the stock JSONs suggest otherwise.

### USB, charging and DisplayPort

- **[pmOS]** Do not treat USB host as solved because TCPM publishes a role and
  xHCI creates its root hubs. The valid proof is downstream enumeration with
  real `event*` or `hidraw*` nodes.
- **[pmOS]** The SM5714's MUIC must route D-/D+ **before** the OTG boost.
- **[pmOS]** Do not force `CC_CNTL1=0x49/0x59` or `CC_CNTL3=0x81` after a
  natural source/host connection: it produces an immediate `DETACH`.
- **[pmOS]** Do not resynchronise CC at 250 ms: TCPM is still in
  `PORT_RESET_WAIT_OFF`. The validated value is 1,500 ms.
- **[pmOS]** The `2d79:e001` hub declares `USB_COMM=false` without external
  power; stop poking VBUS, the PTN3222 and TCPM for that case, and try another
  adapter.
- **[pmOS]** The DisplayPort HPD of a dock present at boot must not activate the
  encoder before the panel's `pm_test=platform`. It has to be stored and
  replayed after `PM_POST_SUSPEND`.

### Method

- **[pmOS]** Do not declare a component working because its driver probed. Real
  proof or physical confirmation is required.
- **[pmOS]** Do not identify an SSH endpoint by its IP alone: several devices
  share the `172.16.42.0/24` USB subnet. Compare the host key.
- **[pmOS]** Do not compare only configs and DTS between builds: also verify
  the booted kernel's release against `/lib/modules/`.
- **[pmOS]** Do not leave the microSD's root mounted before flashing a ZIP with
  an overlay.

## Security

Non-negotiable rules, identical to the postmarketOS port's:

- The owner flashes manually; the build tools never write to the tablet or to a
  card.
- Keep TWRP, Download Mode and Odin.
- Do not touch the PIT, EFS, persist, modem/modemst or the calibration
  partitions. EFS only `ro,noload`, and only when unavoidable.
- Do not repartition `super`, and do not reuse it. Since v1.0.0 the UFS *is*
  repartitioned, but only by the split ZIP, only entries 34 and 35, and only
  when the owner flashes it deliberately; the installer itself still runs no
  partitioning tool at all, and `validate-bundle.sh` fails if one appears in
  it.
- Do not publish SSIDs, passwords, IPs, private keys, MAC/Bluetooth addresses
  or personal names in commits, logs or documentation.
- Do not publish proprietary firmware, or images that contain it.
## The EF-DX920 keyboard cover: how it is really wired

Recovered from Samsung's original DTBO (`port/firmware-extracted/ap/dtbo.img`,
entry `board-id,00`, decompiled with `dtc`). The first reading of the isolated
overlay confused the diagnostic GPIO properties with the bus. The `__fixups__`
section resolves the parent unambiguously:

```
qupv3_se15_i2c = "/fragment@70:target:0";
```

So `stm32@2a` lives on QUPv3 SE15, which mainline calls `i2c15`; its upstream
pinctrl already assigns SDA/SCL to TLMM72/106.

### The keyboard

```
stm32@2a {
        compatible = "stm,stm32_pogo";
        reg = <0x2a>;
        stm32,irq_gpio  = <&tlmm 75 0>;    /* data ready */
        stm32,irq_conn  = <&tlmm 62 0>;    /* cover connected */
        stm32,irq_type      = <0x2008>;
        stm32,irq_conn_type = <0x2003>;
        stm32,mcu_swclk = <&tlmm 12 0>;
        stm32,mcu_nrst  = <&tlmm 13 0>;
        stm32,sda_gpio  = <&tlmm 72 0>;
        stm32,scl_gpio  = <&tlmm 106 0>;
        stm32,fw_name   = "keyboard_stm/stm32_gts9family.bin";
        stm32,model_name = "EF-DX915","EF-DX910","EF-DX900","EF-DX925","EF-DX920";
        support_open_close;
};
```

The important part: **a second `i2c-gpio` bus must not be created**. `sda_gpio`
and `scl_gpio` repeat the GENI controller's pins for diagnostics and for the
MCU's recovery/bootloader path. An `i2c-gpio` over 72/106 would compete with
SE15 for the same lines.

Two function nodes hang off it:

- `pogo_kpd`, `compatible = "stm,keypad"`, with the name list that includes
  `Book Cover Keyboard Slim (EF-DX920)`;
- `pogo_touchpad`, `compatible = "stm,touchpad"`, with
  `touchpad,invert = <0 1 1>`.

Plus a separate boost regulator: `kbd_boost@18`, `max77816,kbd_boost`, on the
different bus `qupv3_hub_i2c4`. The `stm32,booster_power_models` list contains
`0xf9` and `0xd3`, while the EF-DX920 is `0xd6`, but that list **only** selects
the subsequent voltage adjustment. Samsung's driver always calls
`kbd_max77816_control_init()` when powering VDDO if the list is not empty; that
routine enables the output (`0x03 = 0x70`) and sets the limit to 3.1 A
(`0x02 = 0x8e`). The MAX77816 therefore cannot be skipped on the EF-DX920.

`stm,stm32_pogo` does not exist in mainline. It does exist in Samsung's source
release for the SM-X910, which is GPL, so the realistic route is porting it,
not reinventing the protocol.

### The connection sequence the driver requires

The stock implementation does not leave VDDO on from `probe`. It requests the
GPIO62 connection IRQ on both edges and keeps the GPIO75 data IRQ disabled.
When GPIO62 rises, it powers VDDO, waits 50 ms, enables GPIO75 and arms the
initialisation timeout; when it falls, it disables data, releases the state and
powers VDDO down. GPIO75 is active low and is requested as level-low plus
oneshot.

v0.8 does not yet reproduce this state machine: it keeps VDDO on and only
listens for GPIO75's falling edge. In the physical test, GPIO62 detected the
connection and retried roughly every two seconds, but GPIO75 stayed high
throughout. The next driver must implement both IRQs and also enable the
MAX77816 before waiting for data.

### The STM32 sequence validated in v0.9

The ROM bootloader is at `0x51`, answers with PID `0x0460` and allows reading
the flash even while the `0x2a` application is mute. The X910 tested contained
`00 34 00 34`; the official blob `stm32_gts9family.bin` is `00 37 00 37`,
measures 52,132 bytes and has SHA-256
`1b48d88c23523ae205cd960e6d42725268638a15a47d8a5e52854eb01108caa3`. After
programming it, the whole range was compared byte by byte. The option bytes
`aa fe ff fe` already have bit 24 — the one Samsung checks — cleared.

The working sequence is strict: enter the bootloader, validate/update, drive
BOOT0 low, pulse NRST and wait 150 ms; then, on detecting GPIO62, enable VDDO
and the MAX77816, wait 50 ms and enable GPIO75. **Do not reset the STM32 after
enabling VDDO**: that extra reset keeps the application mute even when
firmware, option bytes and power are all correct. Without it, the MCU announces
`0xd6` and creates the EF-DX920 input device.

The input must not exist from `probe`. It is registered only after the model
announcement and destroyed on disconnect; otherwise GNOME concludes there is a
permanent external keyboard and hides auto-rotation. The initial value `0x7fff`
is outside Linux's range and is ignored. A key held from before the cover was
powered produces no retrospective transition in `evtest`.

After the model announcement, Samsung still runs an application
initialisation: MCU version (`ID_MCU`, command `0x02`), mode (`0x01`), a 200 ms
wait, CRC (`0x03`) and accessory version (`ID_TOUCHPAD`, `0x18`). On the real
EF-DX920 it returns version `04 01 05 01`, mode 1, CRC `cd 0b f7 cf` and
accessory `09 00 ff 00 00 00`. The `ff 00` pair is the stock case with no touch
controller, normal for the Slim cover. This sequence already works and is not
the cause of missing keys.

The application initialisation cannot run entirely inside the data IRQ. Samsung
reads VERSION immediately, releases the IRQ and defers MODE, the 200 ms wait,
CRC and accessory by 10 ms. Keeping the 200 ms inside the handler leaves GPIO75
asserted and ends in `-ETIMEDOUT`. With the asynchronous split, `evtest`
received real presses and releases of letters, space and backspace.

GPIO62 can bounce while typing. Cutting VDDO during a key makes the STM32
forget its release, so Linux has to release every `keys_down` before powering
it off. After each `0xd6` re-announcement, VERSION plus initialisation is
repeated even if the input already exists. `0xff` is bus garbage during a
bounce and must never replace the valid model. If the I²C retries are exhausted
and DATA stays asserted, the keys are released and NRST is pulsed for 3 ms,
just as Samsung's driver does on its error path; without that recovery the IRQ
repeated a timeout every ~4.4 s forever.

A joint trace of `i2c_transfer` and the IRQ made clear that this recovery was
treating a symptom created by our own IRQ selection. With
`IRQF_TRIGGER_FALLING`, after delivering several valid packets there was a last
handler left with GPIO75 already deasserted. Sending the probe header
succeeded, but reading an empty queue timed out after ~1 s; right afterwards
the STM32 pulsed GPIO62 and the power cycle began. The stock checks GPIO75's
level on entering its ISR and returns if it is already high. Mainline has to
keep the falling edge — level-low lost short pulses — and combine it with that
guard: if the active-low descriptor returns 0, `data_irq_deasserted` is counted
and I²C is not touched. In the first six-minute test the result was one
discard, zero timeouts, zero GPIO62 pulses and zero resets.

That stable window at 400 kHz was not reproducible after rebooting. On the next
boot the reads suffered NACK `-6`, `-EPROTO`, GENI timeouts and dozens of
GPIO62 cycles again; `event3` was destroyed when the level stayed low for more
than 250 ms. Holding `89c000.i2c/power/control=on` and reinitialising the
client did not fix it, so do not attribute it to the 250 ms autosuspend. The
downstream uses 400 kHz, but its GENI generator and its timing patches are not
mainline's. On this board, 100 kHz gave three consecutive boots and a rebind
with no idle timeouts or resets, but sustained typing brought `-110`, NACKs and
GPIO62 back. For a keyboard the lost bandwidth is irrelevant, but 100 kHz is
not on its own the solution.

The DATA guard cannot run for the first time in the threaded handler either: a
valid short pulse may have returned high while its packet is still queued, and
discarding it loses releases above all. Moving it into TLMM's hard IRQ produced
more than 2,000 clean physical transitions and one reconnection, but that
stability did not survive the following reboot with identical images and DT. Do
not call that combination definitive, and do not attribute the regression to a
partition having changed.

The stock DT asks for `IRQF_TRIGGER_LOW | IRQF_ONESHOT`; that variant lets the
controller re-fire while several packets remain with DATA low. The downstream
GENI uses, at 100 kHz, the counters `{div=7, cycle=10, high=11, low=26}`
against mainline's `high=12`, and on a timeout it sends `M_CMD_CANCEL` before
resorting to `M_CMD_ABORT`. These are real product differences being tried
together, not results validated yet.

Samsung's driver also emits its RESET notifier — which releases every key — on
**every** failed read attempt, not only when three retries are exhausted.
Replicating that semantics avoids holding a press through several timeouts; the
STM32's physical reset stays reserved for retry exhaustion. This is different
from a watchdog based on key duration.

Do not use a watchdog based solely on how long a key stays pressed. A real key
can be held indefinitely; the experimental 3 s timer mistook it for a lost
release and reset a healthy STM32. Synthetic releases are kept on the objective
disconnection and transport-error paths.

Do not query `0x2a` with `i2ctransfer` while the driver is bound: it competes
with its two-phase transaction, causes NACK/`-EPROTO` and can force a false
disconnection cycle. A periodic poll inside the driver did reach the real
system, but Wi-Fi did not associate until a reboot and the journal also showed
`i2c i2c-6: Transfer while suspended` from the polling work. It was withdrawn:
no periodic query that can survive suspend should be reintroduced. A manual,
serialised `event_poll` control, run only on request while the system is awake,
is a different tool.

The same physical unit was later tested under One UI: the keys worked and
closing the cover blanked the screen. That rules out a keyboard, contact or
wiring defect as the general explanation for the silence under mainline.

The MAX77816 is on hub SE4, and that SE must use GPI DMA. PIO claims TLMM4/5
and blocks the ADSP's probe. Releasing SE4 hot did not recover SSC, and a
control run with v0.8 had no sensors on that boot either: do not attribute that
pre-existing intermittency to the keyboard without an A/B comparison.

### Blanking on close

Samsung's `hall_ic` node has **two** Hall-effect sensors, and our DTS only
wires the first:

| | GPIO | Samsung event | in our DTS |
|---|---|---|---|
| `hall` | TLMM 107, active low | `0x15` | yes, as `SW_LID` |
| `hall_wacom` | TLMM 203, active low | `0x1e` | **no** |

That the plain cover blanks the screen and the keyboard one does not fits with
each of them tripping a different magnet. Before touching the DTS this has to
be measured: read TLMM 203 with the keyboard cover open and closed.

### Measured: the pogo connector's pins are dead without power

Two recordings of 280 s each, with the owner working the EF-DX920 cover:
closing and opening it three times, latching it onto the pins, typing,
unlatching it and closing it again. TLMM 203 (`hall_wacom`), 62 (`irq_conn`)
and 75 (`irq_gpio`) **did not change once**, with pull-up or pull-down, and
`SW_LID` did not either.

Reading the pins from userspace cannot attribute the cover to any of them:
Samsung's node declares an `stm32_vddo-supply` and a `max77816,kbd_boost@18`
boost regulator, and without powering them the MCU does not start and the
presence detector does not conduct. The measurement does not say "there is no
signal", it says "there is no power".

A fact from the owner closes the reasoning: **this cover has to be unlatched
from the pins to close it**. With the cover closed the pogo link is dead by
definition, so the "closed" state cannot arrive that way. And since the magnet
moves neither the Hall we already use (TLMM 107, which does work with the plain
cover) nor the second one (TLMM 203), the most likely explanation is that this
cover has no magnet in that position and that in stock it is the keyboard's own
driver that blanks the screen on seeing the connector released.

Consequence for planning: automatic blanking with the keyboard cover is **not
independent of the keyboard**. Both halves are one job: port the
`stm,stm32_pogo` protocol from Samsung's GPL release, enable SE15 and VDDO, and
translate the Hall event the MCU sends into `SW_LID`. The booster is postponed
unless a measurement on the EF-DX920 proves it is needed too.

### Measured with the MCU powered

A transient test with the GPIO chardev v2 applied exactly the stock DT's
levels: TLMM10=1 (VDDO), TLMM12=0 (BOOT0) and TLMM13=1 (NRST). TLMM62 began
showing periodic activity and TLMM75 produced one transition. On closing the
descriptors every GPIO was released. This proves the power and control wiring
are correct; it does not yet prove the keyboard registers presses, which
requires starting the driver on SE15.

### `CONFIG_GPIO_CDEV_V1` is needed for Ubuntu's tools

Ubuntu 24.04 ships libgpiod 1.6, which speaks only the GPIO chardev's v1 ABI.
The mainline kernel ships it disabled, so `gpioget` returned `Invalid argument`
on **every** line, even those in use. The symptom looks like a reserved pin and
is not. Resolved: `CONFIG_GPIO_CDEV_V1=y` is in
`config-ubuntu-desktop.fragment`. It is recorded here because the failure is
silent and very easy to mistake for a hardware problem.

### Measured again on 2026-08-17, this time across all 207 pins

The earlier measurement looked at three hand-picked pins. This one sweeps
**every** pin `/sys/kernel/debug/gpio` exposes — 207 — sampling them every
0.4 s while the owner opened and closed the EF-DX920 several times. It confirms
the above and settles whether the magnet was moving something we were not
looking at:

- With the cover **closed**, `gpio107` reads `in high`. The line is active low,
  so "high" means *no magnet in front*. The sensor is neither broken nor stuck:
  it is saying it sees nothing.
- Its interrupt (`279:` … `107 Edge Book Cover`) is still at **0** after a whole
  boot. Careful reading `/proc/interrupts` here: the 107 on the right is the
  GPIO number, not a count, and confusing them makes it look as though the Hall
  is firing constantly.
- The only pins that moved — 73, 85, 86, 95 and 207 — are **pulses that return
  on their own in under a second**, pogo chatter from latching and unlatching.
  None holds a level while the cover is closed, which is what reading "closed"
  would require.
- `SW_LID` did not change, and neither logind nor upower saw anything:
  `lid-is-closed: no`.

From that it was concluded that there was no signal at all and that closure
could only be inferred from the connector coming loose. **That was wrong, and
the next section corrects it.** It stays written down because the mistake is
instructive: a whole route — the digitizer — was ruled out without having been
looked at, and all the evidence gathered was true but incomplete. The owner
insisted it works under One UI, and she was right.

### Solved: the cover is seen by the digitizer, not the Hall

Watching the stock with `getevent` (no root needed: the `shell` user is in the
`input` group), closing the keyboard cover emits this:

```
/dev/input/event13: EV_SW  SW_MACHINE_COVER  00000001   <- close
/dev/input/event13: EV_SW  SW_MACHINE_COVER  00000000   <- open
```

`event13` is `sec_e-pen`. **The Hall plays no part**: what notices is the
digitizer, whose grid covers the whole panel. That is why no GPIO moved.

The protocol is in Samsung's already-imported sources (`work/stock-wacom`,
`wacom_i2c.c:917` and `wacom_i2c_cover_handler`):

| | |
|---|---|
| packet | `(data[0] & 0x0F) == NOTI_PACKET` (13) |
| subtype | `data[1] == COVER_DETECT_PACKET` (10) |
| state | bit 7 of `data[3]`, 1 = closed |
| switch | `SW_FLIP` = `0x10`, which is `SW_MACHINE_COVER` |

And the controller **already sends them under Ubuntu**, without being asked for
any watch mode. Captured from the i2c tracepoints, which are what serve when
the driver has inlined its parser and there is no symbol to put a kprobe on:

```
i2c_reply: i2c-12 a=056 l=16 [0d-0a-10-80-13-...]   bit 7 set     -> closed
i2c_reply: i2c-12 a=056 l=16 [0d-0a-10-00-13-...]   bit 7 clear   -> open
```

All that was missing was reading them: the frame is not a pen report, so it
fell into `samsung_wacom_irq`'s general discard. The handling goes **before**
the `pen_irq_disabled` check, because the pen lives in its silo and that is
exactly where reporting is suppressed, so tested later it would be lost in the
normal case. `SW_MACHINE_COVER` is emitted — which is what the hardware means —
along with `SW_LID`, which is the one logind and GNOME attend to.

Checked on hardware with the new kernel: four closes and four opens, `book
cover closed`/`open` in the log and `systemd-logind: Lid closed`/`Lid opened`
in exact correspondence with each. The digitizer already came tagged
`power-switch` by udev, so no rule was needed.

A note for the trackpad covers, which do not unlatch when closed: they could
not be tested, but since the signal travels through the digitizer and not the
connector, there is no reason for them to behave differently.

### And why it appeared not to work on the lock screen

Symptom: with the session locked, closing the cover did nothing. It sounded
like permissions or a GNOME setting, and it was neither: **logind ignores the
lid for `HoldoffTimeoutSec` after every resume**, 30 s by default. The lock
screen is reached right on waking, so almost any close falls inside that
window.

There is no need to take this on faith: correlating every "Lid closed" in a
whole boot with the preceding resume gives **eleven out of eleven**.

```
13:05:53   136.0 s after the resume   suspended
13:06:03     7.0 s                    ignored
13:09:12   196.0 s                    suspended
13:09:17     2.0 s                    ignored
13:26:00     5.0 s                    ignored
```

Careful when diagnosing this: the driver **does** emit the event and logind
**does** write "Lid closed" into the journal. The only thing missing is the
"Suspending...", so looking only at whether the event arrives makes everything
seem fine.

And careful with `loginctl lock-session` as a way to reproduce it: in this
session (`Type=tty`) it locked nothing and `LockedHint` stayed at `no`, so the
first measurement was in fact the unlocked case all over again. It has to be
locked by hand and checked through GNOME's `ScreenSaver`, not through
`LockedHint`.

`11-gts9u-lid-holdoff.conf` lowers it to 5 s. The point of the holdoff is a lid
that re-announces itself on waking and puts the machine back to sleep; neither
of the reporters here does that — the digitizer sends a packet only when the
state changes, and gpio-keys is only read on a real edge — but 5 s rather than
0 leaves the resume a moment to settle. Verified: a close 9 s after a resume
now suspends, and it slept for 25 s until the cover was opened.

A `logind.conf.d` drop-in is not applied hot, so a reboot is needed (or
restarting logind **and** the session manager).
## The tablet was warm at idle for two independent reasons

Symptom: poor battery life and heat under light use. Measured at idle, screen
on and only a browser open: **32 % CPU busy** and thermal zones at
**57–63 °C** with nobody asking for anything.

### 1. There was no frequency scaling at all

No `/sys/devices/system/cpu/cpufreq`, no policies, no `schedutil`: eight cores
at whatever frequency the firmware left them. It all hangs off one dmesg line:

```
platform 17d91000.cpufreq: deferred probe pending:
    qcom-cpufreq-hw: Failed to find icc paths
```

`qcom-cpufreq-hw` resolves the interconnect paths the CPU nodes name before
registering anything. Decoding that property by phandle gives three providers:

| phandle | Provider | Driver |
|---|---|---|
| `0x7` | `gem-noc` | `qnoc-sm8550` |
| `0x8` | `mc-virt` | `qnoc-sm8550` |
| `0x9` | `epss-l3` | **none** |

The third is handled by `INTERCONNECT_QCOM_OSM_L3`, which the inherited config
left at `=m`. Since this port installs no module tree — there are only three
`.ko`s on the tablet — that module did not exist, `17d90000.interconnect` was
left with no driver, one path did not resolve, and the probe was deferred
forever. It is exactly the trap `config-ubuntu-desktop.fragment`'s own header
warns about, again.

With `=y`: three policies, one per cluster, `307–2016` / `499–2803` /
`595–2956 MHz`, `schedutil` governor, and the kernel building an energy model.

To diagnose it: `/sys/kernel/debug/devices_deferred` says who was deferred and
why, which is more direct than digging through dmesg.

### 2. The four camera relays were transmitting with nobody watching

`ubuntu-gts9u-camera-relays` keeps four GStreamer pipelines that take 640×480
out of libcamera, **rescale it to 1280×960 in software** and push it at 30 fps
into the v4l2loopback nodes. Stopping them and starting them again:

| | CPU busy | highest temperatures |
|---|---|---|
| with the relays | 32.30 % | 58.0 / 57.2 / 55.2 °C |
| without them | **1.76 %** | **40.2 / 40.2 / 40.2 °C** |

That is **2.4 cores out of 8 and about 17 °C** of fixed cost.

Careful measuring this with the charger connected: on stopping the relays the
current *rose* from 866 to 1450 mA, because with less CPU more current goes
into the battery. `current_now` does not measure the system's consumption while
charging; look at CPU and temperature, or unplug.

**A note on method, because it cost three bad measurements:** `v4l2-relayd`
forks. Launching it and measuring the returned pid always gives `0.0 %`,
because the one doing the work is the child. With that I got as far as
concluding the pipeline only ran on demand, and it was false: the CPU of
**every** process with that name has to be summed. A `0 %` that fits the
hypothesis is worth checking twice.

Measured properly, a single relay at idle with nobody reading the node:

| Output pipeline | CPU of one relay |
|---|---|
| 1280×960 @30, splash as it was | 106.8 % |
| 1280×960 @30, splash fixed | 60.6 % |
| **640×480 @30, splash fixed** | **2.2 %** |
| 640×480 @15, splash fixed | 1.1 % |

Two different things, then:

- **The rescaling contributed nothing.** `pipewiresrc` is asked for 640×480, so
  publishing 1280×960 only interpolated, and paid for the scaler, a conversion
  to YUY2 and about 73 MB/s of copying per camera, thirty times a second.
- **The idle pipeline converted every frame.** Patch 0002 left `imagefreeze
  is-live=true` *after* the `videoconvert`, so the black PNG was reconverted on
  every repeat. Putting the conversion before the freeze does it once. That was
  half the idle cost.

Result on the tablet, before and after, same session:

| | Relays' CPU | Global CPU | Temperatures |
|---|---|---|---|
| 1280×960 | 230.0 % | 31.07 % | 58.4 / 58.4 / 56.0 °C |
| 640×480 + splash | **8.1 %** | **2.48 %** | **39.8 / 39.8 / 39.0 °C** |

The four nodes still announce capture and PipeWire still sees them. That is
practically all the headroom there was: stopping the relays entirely gave
1.76 % and 40.2 °C, so the cameras now cost nothing appreciable for being
available.

## A tablet that will not turn on may be in emergency mode

On 2026-08-03 the tablet "would not boot": a black screen after rebooting. It
was neither the panel nor GDM. The system booted all the way and stopped here:

```
systemd-fsck-root.service: Failed with result 'exit-code'
Reached target emergency.target - Emergency Mode
```

`emergency.target` opens a root console on the tty. On a laptop that is
visible; here the panel stays dark until the cold-boot recovery restarts it,
and with no session manager there is nothing to draw. The result is
indistinguishable from a dead device.

How to diagnose it without a screen: mount the root from TWRP read-only, pull
**all** the `system*.journal` files — not just the active one — and read them
with `journalctl -D`. With a single file you see the boot's final stretch and
it is easy to conclude systemd hung half way, when what is actually missing is
the beginning. That is exactly what happened here, and it cost one wrong
hypothesis.

The repair is `e2fsck -fy` on the unmounted partition. Beforehand `e2fsck -fn`,
which writes nothing, is worth running to see the extent: if passes 2 and 3
come out clean the directory structure is intact and the repair is routine.

### The cause: the root was created without a journal

`build-sd-image.sh` formatted the root with `-O ^has_journal` to save writes to
the microSD. That is the wrong trade for the root of a tablet that gets powered
off abruptly: without a journal, every dirty shutdown can leave orphan inodes
and skewed bitmaps, and it accumulates. With `Errors behavior: Continue` — the
default — ext4 also keeps working after detecting corruption, so the damage
grows silently until the day `e2fsck` refuses and the boot falls into
emergency.

The root now carries a journal and `-e remount-ro`. The first real error leaves
the root read-only: annoying, but visible and repairable before it compounds.

## Do not restart `systemd-logind` with a live graphical session

While installing the power button handler, `systemctl restart systemd-logind`
was run so it would pick up its drop-in. With the desktop open, that breaks
GDM's session tracking: it opened two new greeters without closing the previous
one and, when the owner logged in, her `gnome-shell` and the zombie greeter
fought over DRM master. The loser repeated

```
[atomic] Failed to disable device '/dev/dri/card1': drmModeAtomicCommit: Permission denied
```

and the screen stayed black with the greeter's cursor blinking. It recovers by
terminating `seat0`'s sessions and restarting `gdm3`, until a single compositor
is left.

The restart was not needed at all: a `logind.conf.d` drop-in applies by itself
on the next boot, and that was enough. If it has to be applied hot, restart the
session manager too, not only logind.

## The power button needs a single owner

What was asked for — a short tap suspends, a long press brings up the
sixty-second session dialog — cannot be provided by either piece on its own:

- **logind** distinguishes the long press (`HandlePowerKeyLongPress`) but only
  runs fixed actions of its own, and "show GNOME's dialog" is not one of them;
- **gnome-settings-daemon** shows that dialog with
  `power-button-action='interactive'`, but treats every press the same.

Splitting the key between the two produces races, because both act on the same
press. `ubuntu-gts9u-powerkey.service` takes the `pmic_pwrkey` evdev and
decides by duration; the other two are explicitly stood down
(`HandlePowerKey=ignore` and `power-button-action='nothing'`).

The long press invokes `org.gnome.SessionManager.Shutdown` in the active
session, which is what `gnome-session-quit --power-off` does.

### The press that wakes is not a command

Without treating it separately, a single tap suspended, the waking press was
read as another tap and the tablet went back to sleep. `CLOCK_MONOTONIC` does
not advance during suspend, so that press arrives — by that clock — barely
seconds after the suspend was issued, however many hours the machine actually
slept. Discarding presses inside that window solves the case without having to
listen to `PrepareForSleep`.

### And the charging pen woke it a second later

Symptom: you tap the button, the screen goes off, and a few seconds later it
comes back; insisting changes nothing. It looks like the button, and it is not.

`power_supply_register()` marks **every** power supply as a system wakeup
source. The S Pen is a `power_supply`, so while it sits in its silo charging,
every `power_supply_changed()` from the driver counts as a wakeup event.
Measured at idle, cover closed and nothing touched: one every ~20 s. Suspend
entering at 11:46:21 and leaving at 11:46:22.

How it is attributed without guessing, which is what the keyboard cost at the
time:

- the difference in `/sys/kernel/debug/wakeup_sources` either side of a cycle:
  only `gts9u-spen` moved (39 → 40). `11-002a` stayed at 58, so it was not the
  pogo;
- the pen dock's IRQ (`gts9u-spen-dock`) did **not** move, so it is not that
  the pen was taken out: it is the charging notification;
- the `wakeup_count` protocol: reading `/sys/power/wakeup_count` and writing it
  back fails with `EBUSY` when events are pending. With the pen disabled as a
  source, 40 s at idle and the counter did not move once.

Fixed from userspace with `90-gts9u-spen-no-wakeup.rules`, which sets
`power/wakeup` to `disabled` on the pen's `power_supply`. It still reports
charging — the battery indicator is untouched — it merely stops being a reason
to leave suspend. Verified on hardware: **161 s asleep** until the owner
pressed the button, `wakeup_count` unmoved and `pm_wakeup_irq=21`.

The properly correct fix is `no_wakeup_source` in the driver's
`power_supply_desc`, but that needs a kernel; the rule needs a reboot at most.
Careful if this is ever revisited: the device's other `power_supply` objects
(`sm5714-battery`, `sm5714-usb`, `tcpm-source-psy-8-0033`) are wakeup sources
for the same reason, and in 40 s of idle they emitted nothing, so they are left
alone.

## The kernel build is incremental, and that is why the releases were not reproducible

`build-mainline-kernel.sh` reuses `$build_dir` between runs. That makes a
normal rebuild fast, but it also makes the image depend on whatever was in the
tree before.

It was discovered while closing v0.11. The tablet was booting a `boot.img`
`df98bc12…` built in session 14 that corresponded to no release. Building v0.11
from the repository — with **all** of sessions 13 and 14's code committed and
`kernel/` clean — produced `e7d65812…`. Identical sources, a different binary.

It was not `SOURCE_DATE_EPOCH`: that is derived from the kernel's commit, which
is pinned. It was the build directory's previous state.

`KERNEL_CLEAN=1` discards it before starting. It is slow, so it is optional,
but **a release must be built that way**: without it, comparing hashes between
two builds means nothing and there is no way to demonstrate that what the
device boots came from the tree the manifest names.

## The keyboard's V34 is real content, not a marginal read

The difference between `00 37 00 37` and `00 34 00 34` was first read as
possible read or flash corruption. A complete, repeatable, read-only dump of
the STM32's 64 KiB closed that hypothesis: SHA-256
`8937281d2efa08400390f9a2b02e40ca914b634e646d6dd544980c38464533ef`, version V34
at `0x200`, no copy of V37 and a coherent ARM vector table. The binary's
strings name `TabS9(STM32G0) Series -> V34` explicitly.

From that it was concluded that One UI uses V34 and that the fault was ours, in
the cold state. **The conclusion did not hold.** A valid image says nothing
about who wrote it, and no V34 exists in this project: the X910's official blob
— the same one pmOS uses — is V37, and it is what session 8 programmed to get
the first real keystrokes. The useful rule is simpler: *the mainline driver
speaks only V37*. With V34 the application pulses CONN and goes quiet;
returning V37 to the MCU recovered the keyboard instantly and through a cold
boot.

The ROM bootloader's reversible `GO 0x08000000` command was accepted both
without and with the rails already settled, but it changed neither the ~2.126 s
CONN loop nor produced DATA or a model. It was the V34 application starting
correctly and speaking a different protocol. Do not repeat that jump expecting
it to be, on its own, the missing initialisation.

What returns the MCU to V34 remains unmeasured. No blob in the tree does it, so
the suspect is Samsung's `stm32_pogo_v3.ko` with its own vendor blobs, under
One UI or under the Ubuntu Touch port. If the keyboard goes quiet again, the
first thing to look at is `flash version` in the pogo's `dmesg`.

The updater cannot write the accessory by accident: beyond its safety
conditions it requires `GTS9U_ALLOW_POGO_FLASH=YES`. That guard must not be
defined, and the STM32 must not be programmed, without explicit authorisation
separate from the boot partitions.

## The clean build is not reproducible, and we now know exactly why

Measured on 2026-08-07 with two clean builds of an identical tree (it was
verified beforehand that since `f078c39`, v0.16's `port_revision`, nothing had
changed in `kernel/`, `scripts/`, `configs/` or `packaging/`).

The DTB, `vendor_boot`, `init_boot` and `dtbo` all match. **`Image.gz` does
not, and by extension neither does `boot.img`.** There are two causes, and they
should not be confused:

**1. The module signing key.** `CONFIG_MODULE_SIG_KEY` points at
`certs/signing_key.pem`, *inside* the object directory. When it is missing,
kbuild manufactures it with `openssl req`, and the certificate is linked into
the image. `KERNEL_CLEAN=1` deletes that directory, so it mints a new key every
time.

**2. BTF, which is the real one.** With the key pinned outside the object
directory, `config` did start matching, but `Image.gz` still differed. The
difference was isolated in a 1 MB module rather than in a 67 MB image:

| Region | Bytes differing |
|---|---|
| Everything before `.BTF` | **0** |
| Inside `.BTF` | 184,688 |
| After `.BTF` | 255 |

The compiled code is already deterministic. The final 255 bytes are the
module's PKCS#7 signature, computed over content that changed: a consequence,
not a cause. The mechanism is in the kernel's own `scripts/Makefile.btf`,
which with pahole v1.25 passes `--btf_gen_floats -j$(JOBS)`; the parallel BTF
encoder produces different output on every run.

### What it would take, if it ever matters

A `pahole` wrapper that rewrites `-jN` to `-j1`, without touching the rest of
the compilation's parallelism. A wrapper and not an overridden `PAHOLE_FLAGS`:
the kernel chooses those flags according to pahole's version, and fixing the
set today would rot as soon as it is updated. It cannot go through the
environment either, because the root Makefile assigns `PAHOLE` with `=`, which
beats an exported variable; it has to go on each `make` line.

**None of this is applied.** It was tried and reverted: the tree stays
identical to the one that built v0.16, which is what works on the tablet.
Applying it changes the kernel, and therefore forces a new release and a
reflash, which is a price that buys nothing today — the keyboard and everything
else work. It is recorded here, measured, for the day it is worth paying.

If it is applied, reproducibility would still be **per machine**: the signing
key is private and cannot go into Git, and a published key would not be a
signature.
## The four cameras are not four independent pipelines

On the SM-X910, CAMSS exposes seventeen video nodes because every RDI of the
VFE is a possible destination. That does not mean `/dev/video0` is a particular
lens. The stable identification is the sensor's subdevice and its physical
link:

| Module | Bus | Observed subdevice | CSIPHY |
|---|---|---|---|
| HI1337 main rear | CCI0 master 1, `0x21` | `/dev/v4l-subdev32` | 1 |
| HI847 wide rear | CCI0 master 0, `0x21` | `/dev/v4l-subdev34` | 2 |
| HI1337 main front | CCI1 master 1, `0x20` | `/dev/v4l-subdev31` | 4 |
| HI1337 wide front | QUP I²C9, `0x21` | `/dev/v4l-subdev30` | 5 |

Every test disables the previous links and drives **one** sensor through
`csiphyN → csid0 → vfe0_rdi0 → /dev/video0`. Judging the lens by the
`/dev/video*` number is wrong, and leaving several links active means an
apparently valid capture may come from the previous sensor.

### CamX's `slaveAddress` values are eight-bit

The main front camera was the exception that exposed the rule. Its stock
descriptor gives `slaveAddress = 0x40`; using that literally as a Linux address
finds nothing. It is the eight-bit address: in the DT it corresponds to
`reg = <0x20>`. The other three modules declare `0x42`, which becomes `0x21`.

CCI1 master 1 does not use the ordinary CCI pins either: the stock routes it
through the AON GPIO208/209 pair. Without that pinmux the controller
enumerates, but every identity read fails; it is not a chip-register problem.

### The three HI1337s need different tables, not a generic initialisation

Samsung's blobs use Parameter Parser V3. Decoding them gave an exact global
table of 1,476 writes and an exact mode for each module: 4128×3096, 3408×2556
and 4000×3000. With an approximate sequence the sensor can answer over I²C and
still emit no CSI-2: reading `0x0716 = 0x1337` proves identity only, not
streaming.

The stock power sequences matter too. VIO and VDIG get their delays, then the
module is enabled, MCLK settles for 10 ms and only then does it leave reset.
PM8550VS-C L1 does not represent exactly 1,100 V; 1,104 V is the nearest NLDO
step. PM8550B L11 is the shared 1.1 V rail for the display and the front
cameras, also voted at 1,104 V, not the old 1.2 V name.

Both front cameras share MCLK4/GPIO104. The main one, which probes first, keeps
ownership of the pinctrl and the wide one reuses the clock; making both claim
the same group leaves the second blocked before it can read its ID. The
enable/reset GPIOs are requested only while the sensor is powered and released
when the stream ends.

### From RAW10 to a desktop camera: the six missing layers

RAW10 had closed sensor, clock, power, CSI-2, CSIPHY, CSID, VFE and DMA, but it
was not an application interface. The finished path adds six reproducible
layers:

1. the drivers export V4L2 selection, orientation and location so `libcamera`
   can tell front from rear and does not have to guess the crop;
2. `libcamera` 0.7.2 uses the `simple` pipeline and the software ISP with
   HI1337 and HI847 helpers. Both encode gain as `(code + 16) / 16` and have a
   pedestal of 64 in RAW10 (`4096` once normalised to 16 bits);
3. the tuning YAMLs enable AE, grey AWB, pedestal, adjustment and CCM. Start-up
   begins at gains `[1, 4]`; AWB converges on real statistics;
4. PipeWire 1.0.5's libcamera SPA carries the backports essential for libcamera
   0.7 and for the RGB byte order. Without skipping `ColourGains` (an array),
   WirePlumber aborts; with the old RGB map, the image comes out magenta;
5. a patched, signed `v4l2loopback` creates `/dev/video20`–`23`, while four
   on-demand relays translate the PipeWire sources into YUYV 1280×960;
6. OBS keeps its standard V4L2 source, but its list omits the `Qualcomm Camera
   Subsystem` RAW nodes, which are not application-ready cameras.

`/dev/udmabuf` must be `root:video 0660` and carry `uaccess`; otherwise the ISP
works as root and fails precisely in applications. The final validation
required two consecutive rounds of 12 openings across the four nodes, 240
frames in total, four WebRTC openings in Chrome, and all four selections of
OBS's standard V4L2 source. PipeWire and the relay service kept their PIDs and
the system maintained exactly four relays.

The software ISP no longer uses a *cover* scaling that cropped the sides when a
different ratio was requested. It computes the smaller factor, centres the
image and clears the rest to black; a 4:3 output therefore keeps the whole
sensor and a 16:9 output can show bars instead of faking a zoom. This does not
widen the main rear camera's optical field, which is physically narrower.

### V4L2 compatibility means serialising the single ISP

The four names do not represent four physical pipelines. They all end at the
same CAMSS/ISP, and opening two libcamera inputs during the asynchronous
release queue can bring PipeWire down. Every relay therefore takes a shared
`flock`, groups the brief negotiation closes over 500 ms, and holds the lock
for two seconds after taking its pipeline to `NULL`. The same guard applies to
the error path: releasing a failed input immediately left CAMSS callbacks in
flight and reproduced a `SIGSEGV` on the twelfth switch.

OBS added another, independent bug. On Noble, if `/dev/v4l/by-id` or
`/dev/v4l/by-path` do not exist, `v4l2-input.c` frees an uninitialised
`namelist`; the deduplication path also assumed a non-empty list. The patch
initialises the pointer to `NULL`, walks the list with a null check, and
filters by CAMSS's exact card name. The tested dialog contains only the four
GTS9U entries and still allows normal V4L2 resolutions, formats and controls.

### System relays need a persistent PipeWire

The `/dev/video20`–`23` nodes belong to a system service, but their sources
live in the PipeWire graph of the account OOBE created. There is no known user
or UID when the image is built. On a boot with no graphical session, an SSH
connection could temporarily start that user manager and PipeWire; closing SSH
made the server disappear while the four relays stayed alive, bound to the old
socket and delivering black frames.

`ubuntu-gts9u-desktop-user` finds human accounts by the `UID_MIN`–`UID_MAX`
range, enables lingering, and writes a drop-in into `/run` with the real name,
UID, runtime and bus. The relay unit only starts if that drop-in exists and
never contains `User=ubuntu` or `/run/user/1000`. The launcher does not
consider a socket ready on its own: it waits for a live `MainPID` from
`pipewire.service`, keeps that PID, and watches both PipeWire and each relay.
Any change restarts the whole set through systemd.

Image version 2.17 mistakenly still carried the variant built with
`PathExistsGlob=/home/*`. Being a level condition, it relaunched the oneshot up
to systemd's limit and could block the camera dependency. Fixing the file under
the same version number was not enough: apt had no reason to replace it. 2.18
raises the version and its `postinst` does a `daemon-reload`, clears the three
failed states, restarts the edge watcher and resolves the account again. If the
relays were active, it restarts them after the upgrade so the freshly installed
binary runs instead of the old inode.

### Two small races explained the black screen when switching

Pre-emption is requested with `SIGUSR1`. If the signal arrived just after the
previous consumer closed, always setting `input_preempted = TRUE` left that
relay on a black splash even though there was no client left to pre-empt. The
flag is now set only while `input_client_active` is still true; an input error
also recreates the pipeline as long as the consumer stays open.

The second race was in a seven-byte file. Each owner did `ftruncate()` and
`dprintf()` on the shared descriptor, but truncating does not return the offset
to zero. After several switches the PIDs ended up preceded by NUL gaps,
`g_ascii_strtoll()` read owner zero, and the next relay sent no signal. An
`lseek(..., SEEK_SET)` now precedes every write. It is a good demonstration of
why a visible name, an open node and a live process do not prove the handover
is happening.

When diagnosing a `v4l2loopback` with duplicated buffers, consume at video
rate. A `v4l2-ctl` with no pause can read the last buffer 75 times before even
the 250 ms debounce expires, and produce a false freeze. The WebRTC validation
keeps a single consumer, waits for a non-black image, compares samples two
seconds apart and requires media time, brightness and changing pixels. Three
consecutive rounds and the first consumer after a cold boot all got 4/4; OBS
was verified with two captures three seconds apart for each standard source.

The colour review did not justify changing the global CCM. The front cameras
came out close to neutral and the rear ones showed a moderate green bias under
flash in a heavily red/brown scene, precisely an adverse case for grey-world
AWB. A reproducible correction needs a grey/colour chart and several light
temperatures; until then the current tuning stands.

### The DW9808 needs a channel separate from the sensor's controls

The stock firmware identifies the main rear camera's actuator as a DW9808, on
CCI1 master 0 with Linux address `0x0c`. Its exact start-up sequence is
`02=01, 02=00, 06=60, 07=05`, Samsung's preparation positions and `02=02`; an
I²C test swept 0–1023 and confirmed that optics and motor respond. The DTS
shares GPIO15 through a fixed regulator between the HI1337's VIO and the lens's
VCC, and links the two with `lens-focus`.

The sensor's and the lens's V4L2 `ControlInfoMap`s cannot simply be merged:
each subdevice creates its own map of identifiers and libcamera aborts if a
control belongs to the other map. The reproducible solution adds a `hasFocus`
boolean and a `setLensPosition` IPC event to the software IPA; exposure and
gain still travel to the sensor, while the position reaches only `CameraLens`.

The ISP's statistics accumulate a horizontal second derivative of luminance.
The IPA normalises that measure by light, sweeps 128–896, refines around the
best point in steps of 48, and publishes `AfMode`, `AfTrigger`, `AfState` and
`FocusFoM`. Continuous mode re-scans if the figure of merit falls in a
sustained way, with a spaced safety check to avoid breathing in video. On
hardware, a 41-frame capture recorded the lens's real travel and ended with the
banknote's text legible; GNOME Camera and OBS then confirmed the same result
through the application path.

### The audio APM can fail on a boot without the camera causing it

During the regression, two boots showed `APM_CMD_GET_SPF_STATE` timing out, the
LPASS pinctrl at `-EACCES` and microphones with every sample at zero. The ADSP
was not restarted hot. After a full boot from TWRP, the same camera image
produced 729,285 non-zero samples before using CAMSS and 733,706 after
capturing with all four sensors. Taking a single silent buffer as a camera
regression would therefore have been another false positive; the APM's messages
have to be required as well, and the test repeated from a full boot.

The cause was measured afterwards: it was not a race between audio and camera
but between the ADSP's late start and the panel's cold recovery. The latter
runs a `pm_test=platform` cycle; if it suspends while the APM and the VA macro
are probing, the log contains `CMD timeout for [1001021]` followed by
`va_macro ... -EACCES`. The ALSA card may appear anyway, but the DMICs deliver
nothing but zeros.

The mandatory order is now panel → ADSP → desktop user → camera relays. On top
of that, WirePlumber may have started before the card exists: in that case it
keeps an object with `off`/`pro-audio` profiles and GNOME shows Dummy
Input/Output. `ubuntu-gts9u-desktop-user` waits for `controlC0`, restarts
WirePlumber alone, selects `HiFi`, and uses a stamp in `/run` to do it once per
boot. The ADSP is not restarted hot: ASoC does not re-register the card with
this kernel.

### I²C adapter numbers are not an ABI

On enabling the camera CCI controllers, the STM32 pogo remained the same
physical device at `0x2a`, but Linux began enumerating it as `11-002a` instead
of `6-002a`. The V37 restorer had the second path hardcoded and, after the MCU
returned to V34, correctly ended up saying there was no controller. The stable
path is the device's link under
`/sys/bus/i2c/drivers/samsung-gts9u-stm32-pogo/`, not the adapter number.
Services, diagnostics and documentation must look for `*-002a` there; adding a
bus cannot turn an existing accessory into an absent one.

### The desktop torch does not need to grant the flash to the whole system

The combined LED appears as `/sys/class/leds/white:flash`. GNOME's tile needs
only the continuous light, so udev changes `brightness` alone to `root:video
0660`; `flash_strobe`, strobe intensity, timeout and faults stay `root:root`.
The `gts9u-flashlight` command validates 0–255 and defaults to 128. No setuid
helper and no generic sudo rule was installed.

The `flashlight@ubuntu-gts9u` system extension uses GNOME 46's Quick Settings
API. It reads the physical state, runs the helper without blocking Shell, shows
an indicator while it is on, and forces it off when unloaded. The package
preserves the existing extension list when adding its UUID, and the root
filesystem builder does the same after creating the user. A `system-sleep` hook
writes zero before suspending.

That solves the torch and continuous light during a photo. An automatic
photographic flash is a different job: it needs libcamera to expose flash
controls and to coordinate the strobe with the request and the exposure. That
synchronisation must not be faked by giving Snapshot direct access to every
sysfs attribute.

Orientation checks must use physical content, not just
`camera_sensor_rotation`. The two front cameras with the monitor and the two
rear ones with a legible banknote all came out upright through GNOME Camera and
OBS. The main camera's autofocus now allows that lens to be used as a physical
reference too.
## Installing on the UFS did not require touching the partition table

Throughout the port it was assumed that moving the root onto the UFS meant
repartitioning or rebuilding `super`, which is why it was postponed. That was
not true. This device's `userdata` partition is 939 GiB, already exists, and
nothing else is needed: an ext4 filesystem is written inside it with `dd` and
resized with `resize2fs` on the first boot. Samsung's GPT stays intact, which
is exactly what keeps the way back to a single Odin flash.

What is lost is Android's user data, because it is literally what occupies that
partition. `super` stays intact, so Android's system image is still there.

> Since v1.0.0 there is a second way, and it does repartition: `gts9u-split.zip`
> shortens `userdata` and creates `linuxroot` beside it, which is what makes
> dual boot possible. The reasoning below still holds for the whole-tablet
> install, and the split remains a separate, deliberate act by the owner — the
> installer itself still runs no partitioning tool.

`super` was ruled out as a destination: 11.2 GiB is not enough for a desktop,
and using it would also mean rebuilding its logical partitions, which is
exactly the class of operation this design avoids.

Three details that are not obvious until it is implemented:

- **The ZIP cannot be read from the destination.** TWRP's "internal storage"
  *is* `userdata`. A ZIP kept there would destroy itself half way through the
  write. The installer aborts if its own path is under `/data` or `/sdcard`,
  and the installation is done from a microSD or USB-OTG.
- **The label has to change.** `root=LABEL=` resolves to the first match it
  finds. With `UBTS9U_ROOT` in both places, an old microSD in the slot would
  boot instead of the internal installation, and the symptom would be "the
  flash did nothing". The internal root is `UBTS9U_UFS`.
- **The write order matters.** The root first, the boot images after. The other
  way round, a failure half way leaves a new kernel with no system to boot;
  this way it leaves the device where it was, one retry away.

`validate-bundle.sh`'s check that forbade naming `userdata` in the installer
has become two: `userdata` may now be named, but no `mkfs`, `parted`, `sgdisk`,
`sfdisk` or `wipefs` may appear. The guarantee that mattered was never "do not
touch that partition", it was "do not touch the table".

## TWRP's shell does 32-bit arithmetic, and a 3 GiB image does not fit

The first v0.18 flash aborted with "malformed rootfs image size" on a perfectly
good ZIP. The image is 3,271,557,120 bytes; the installer checked
`[ "$ROOTFS_SIZE" -gt 0 ]` and that comparison was false.

TWRP runs `update-binary` with `/sbin/sh`, which is a link to
`/system/bin/sh`: **mksh**. The binary is a 64-bit aarch64 ELF — which
misleads — but mksh's arithmetic type is `int32_t`. 3,271,557,120 exceeds 2³¹,
so it is interpreted as −1,023,410,176 and any `-gt 0` fails. Every earlier
check had passed because the boot partitions' sizes (100,663,296 and smaller)
do fit in 32 bits: the first number over 2 GiB was the first one to fail.

The rules that follow:

- **No value the installer handles may exceed 2 GiB.** Sizes are counted in
  MiB. The `ROOTFS-IMAGE` manifest publishes the bytes for people and for this
  repository's checks, and **also** the MiB, which is the field the installer
  reads.
- **`blockdev --getsize64` on `userdata` cannot be compared in the shell**: it
  is ~1.008 × 10¹². Capacity is checked by reading with `dd` the last MiB the
  image will occupy and counting the bytes returned; a partition that falls
  short returns fewer, or none.
- **Testing the installer with `bash` is useless.** The first loopback-partition
  test bench passed green right before the real flash failed, because `bash`
  has 64-bit arithmetic. The bench now runs it with `mksh`, and
  `validate-bundle.sh` rejects any literal of ten digits or more in the
  installer.

This is not a problem with TWRP or with this device: it is what any recovery
with Android's shell has, and it will bite again on the first image that grows
past 2 GiB.

## In TWRP, `unzip -l ZIP MEMBER` never fails

TWRP's `unzip` is a link to **ziptool**, AOSP's. Asked about a member that does
not exist it prints "0 files" and **exits 0**:

```
$ unzip -l package.zip DOES-NOT-EXIST ; echo $?
0
```

`unzip -p` with an absent member does the same: it prints nothing and exits 0.

The installer used that idiom to decide what the ZIP carried. Every one of
those checks was always true, so a ZIP with no overlay was considered to carry
one and aborted with "the ZIP carries both a rootfs image and an overlay". The
checks that the five boot images were present were checking nothing either.

The correct way is to read the listing once and ask it questions:

```sh
unzip -l "$ZIPFILE" > "$ZIP_LISTING"
zip_has() {
    awk -v name="$1" '$NF == name { found = 1 } END { exit !found }' "$ZIP_LISTING"
}
```

Verified on the device against a real ZIP: it distinguishes `boot.img`,
`META-INF/com/google/android/update-binary` and a made-up name.

The general lesson, which has now cost two flashes: **a check that cannot fail
is worse than no check at all**, because it also gives confidence. And the test
bench in WSL uses Debian's `unzip`, which does return 11: for the bench to be
worth anything it has to imitate ziptool's behaviour, and it now does so with a
wrapper on the test `PATH`. `validate-bundle.sh` also requires the installer to
run `unzip -l` exactly once.

## The owner creates the account, not the build

Up to v0.18 the image carried an `ubuntu` user created in the
`--customize-hook`, with whatever password arrived in `GTS9U_PW`. Two problems,
and the second is the serious one:

1. Anyone installing it inherited somebody else's account.
2. **`GTS9U_PW` was mandatory and cannot live in the repository.** A clean
   build was literally impossible for anyone who did not know that password. It
   was discovered while building v0.18: the v0.17 root filesystem had to be
   reused with the packages installed on top, instead of rebuilding it.

Since v0.19 the image carries no account and GDM launches
`gnome-initial-setup`, which asks for name, password, language, keyboard and
time zone. GDM takes that path when **there is no ordinary account** — exactly
the state of a freshly built root filesystem — and `InitialSetupEnable=true` is
in `/etc/gdm3/custom.conf`. Ubuntu ships that file with every key commented
out, so the line has to be **written**, not uncommented.

Checked before adopting it, rather than assumed: noble arm64's
`gnome-initial-setup` 46.3 still contains `gis-account-page.ui` and
`gis-password-page.ui`, so its account-creation page is still there.
`ubuntu-desktop-bootstrap`, the Flutter wizard of the Raspberry Pi images, is
**not in noble's archive**; `oem-config`/`ubiquity` are, but they are the
heavy, X-based route.

What this forces to change: nothing in the port may name a user.

- The flashlight extension is enabled with a gschema override, not by writing
  into an account's `gsettings`. No other file in the image touches
  `enabled-extensions` — Ubuntu's extensions come from gnome-shell's session
  mode — so putting the default there adds ours without displacing theirs.
- Lingering is applied by `ubuntu-gts9u-user-linger.service` on every boot, for
  every UID between `UID_MIN` and `UID_MAX`, because the account does not exist
  when the image is built.
- The SSH key, if given, goes into `/etc/skel`, which is what gets copied into
  the account the wizard creates.

If the wizard ever failed to appear, the way back is TWRP: the root is ext4 and
can be mounted from there to create an account by hand, or it can be reflashed.
Worth keeping in mind because, with no account and no wizard, there is no way
in.

## What the wizard does not give the account it creates

`gnome-initial-setup` creates an administrator, and in Ubuntu that means
`sudo`, `adm`, `plugdev` and `users`. Nothing else. The account the build used
to create was also in `video`, `render`, `input`, `audio`, `dialout`, `cdrom`
and `netdev`, and that difference is not cosmetic: this port's udev rule does a
`chgrp video` on the flash LED's `brightness`, so without that group the torch
tile switches itself off when pressed and lights nothing. It was the first
failure of the first account-less image, and it looked exactly like that.

`ubuntu-gts9u-desktop-user` now applies it, along with the lingering and the
relays' drop-in. With two triggers, because one is not enough:

- the service, on every boot;
- a `.path` unit on `/etc/passwd`, for the boot in which the wizard creates the
  account. Without it, everything the account needs would arrive on the *next*
  boot: the owner would finish setting up and find no cameras and a torch that
  does nothing, with no hint that rebooting fixes it.

One known race remains: a process's groups are fixed at login, so if the wizard
enters the session before the `.path` unit finishes, that first session still
lacks the groups. A reboot resolves it. Moving the LED to an ACL-based
mechanism would avoid the race, but logind's `uaccess` acts only on nodes in
`/dev`, and an LED has attributes only in `/sys`.

## The wizard only offers the languages the system has generated

The image generated a single locale, `es_ES.UTF-8`, so the wizard offered
exactly one language. It is solved with `locales-all`, which brings the 327
pregenerated ones and incidentally avoids running `locale-gen` under emulation.

`locales-all` on its own allows **choosing** any language, with its formats,
its collation and its keyboard, but leaves the desktop in English: a translated
GNOME needs its `language-pack-XX`.

A wrong decision was taken here and then corrected: including them all was
rejected for weighing close to 1 GiB. The criterion was badly calibrated. This
device has 256 GB in its smallest version and the root occupies the whole
939 GiB partition; the gigabyte is not the scarce resource. What does grate is
a tablet that offers you Japanese in the wizard and then speaks to you in
English. Since v0.21 every language pack travels.

The general lesson: an image's size matters only for how long it takes to
download and flash, not for what it occupies once installed, and it is worth
saying which of the two is being optimised before cutting anything.

## Updating without losing data does not fit in the TWRP installer

Keeping the data means replacing the system file by file instead of writing the
image over the partition. TWRP has no `rsync`, and its `tar` is toybox's, with
no xattr or ACL support — verified on the device. Copying an Ubuntu root with
those tools **silently loses every file capability**: `ping`, `dumpcap` and
company would stop working with nothing to say so, and the symptom would appear
weeks later.

That is why the upgrade lives in `gts9u-upgrade`, which runs on the booted
system, where `rsync -aAX` does exist. It reads the release's ZIP, verifies the
image against its manifest, loop-mounts it and synchronises onto the live root,
excluding what belongs to the owner: `/home`, `/root`, the accounts and their
groups, the network connections, the host keys, the `machine-id`, the journal
and the language and keyboard configuration. Then it writes the four boot
images and reads them back to check them, because the kernel and modules it has
just installed have to be the same signed set.

It does not reboot. And it is **not tested yet**: it will make its debut on the
first real update where there is data worth keeping.

## OBS was travelling along, and has now been put down

`obs-studio` was in the image because `obs-v4l2-gts9u` — the patched V4L2
plugin the four cameras were validated with — depended on it. It was never
there because the port wanted to ship a streaming studio: it was 21 MiB and an
application most people will not use.

**Removed in v2.23 of the device package**, with the camera work closed. What
went with it:

- the `obs-v4l2` step of `build-extra-packages.sh` and `packaging/obs-v4l2/`;
- the device package's `obs-v4l2-gts9u` dependency;
- `libobs-dev` from the build dependencies;
- and above all **the VLC dance**. The root filesystem's hook installs local
  packages honouring `Recommends`: `obs-studio` recommends `obs-plugins` and
  that recommends `vlc`, so 77 MiB of VLC arrived, of which 41 MiB were
  translations. VLC had to be purged and `obs-plugins` reinstalled with
  `--no-install-recommends`, because on Noble purging the `vlc-plugin-*` family
  took `obs-plugins` with it. Without OBS none of that exists.

In its place there is a check that **can** fail: the build aborts if
`obs-studio`, `obs-plugins` or `vlc` turn up installed in the image. None
should be reachable any more, but all three arrived once as a `Recommends` of
something else, and an image swelling again with a streaming studio and a media
player would only show up in the size.

A consequence worth knowing: the patched plugin was also what hid the raw CAMSS
endpoints from OBS's V4L2 selector. Anyone installing OBS themselves will see
the internal nodes in that list alongside the four processed cameras. The
`/dev/video20`–`23` relays and every other application are unaffected: the udev
rule and `v4l2-relayd-gts9u` are unchanged.

## The USB-C port misses connections, and the chip does not always say so

Measured on the device, not deduced. With a hub plugged in and not enumerating:

| Measurement | Value |
|---|---|
| `CC_STATUS` (0x28) | `0x22` — `ATTACH=SINK`, something is connected |
| `INT1`…`INT5` | `00` — no interrupt pending |
| Masks (0x06…0x0a) | `e6 cf ff 08 ff`, the ones the driver programs |
| IRQ 166 (`8-0033`) | frozen since the previous unplug |

That is: **the chip detects the accessory in `CC_STATUS` and generates no
ATTACH**. TCPM stays disconnected indefinitely. An `unbind`/`bind` of the
driver recovers it instantly, because its reprobe programs the
resynchronisation.

It is not deterministic: in the same session, a later plug was detected on its
own. That is why the fix is a **safety net**, not a guessed register value: a
deferred work that every 4 s compares `CC_STATUS` with what the interrupt path
has reported, and calls `tcpm_cc_change()` only when the hardware says
something is there and the interrupt has **not** announced it.

That condition is deliberately narrow. There is already a comment in the driver
warning about the opposite: re-arming the resynchronisation unconditionally
made **TCPM oscillate between host and disconnected**, because poking it while
it is legitimately idle feeds `start_toggling()` back. The work is
*deferrable*, so an idle tablet with nothing plugged in is not woken by it.
## What we know and do not know about the hub that will not enumerate

A bus-powered USB-C hub with 3 USB ports and Ethernet does not enumerate on the
tablet. What is **ruled out with evidence**:

- **It is not broken**: the same hub, with a memory stick, works on a PC over
  USB-C.
- **It is not the OTG data path**: at t=369 the tablet had a device enumerated
  *while it was supplying VBUS*, before a PR_SWAP to sink.
- **It is not the interrupt mask**: Samsung writes `~ENABLED_INT`, that is 1 =
  masked, and our `0xe6` does enable VBUSPOK, ATTACH and DETACH.
- **It is not a suspend swallowing the event**: the boot's only suspend cycle is
  the panel's.

One hypothesis remains: **the Rp we advertise**. On a natural sink connection
the driver sets bits 5:4 of `CC_CNTL1` to zero, the minimum, and the port
reports `power_operation_mode = default`; a PC advertises 1.5 A or 3 A. Writing
that register with the hub already connected changed nothing, but that **proves
nothing**: a sink reads the Rp when it connects, and the driver also forces it
to the minimum at the exact moment of attach.

Hence `otg_rp` is added as a module parameter, **with the current behaviour by
default**. Raising it blindly is not safe: the port really does supply 900 mA,
and a device that believes otherwise can collapse the rail. And there is
precedent for breaking something by touching it: the driver itself lowered the
Rp because with `0x59` "a passive OTG dongle kept dropping".

## The images have always shipped without file capabilities

`tar --xattrs` copies **only the `user.*` namespace**. `security.capability` is
discarded silently, so every image from this port — microSD and UFS — has
shipped with `ping` lacking `cap_net_raw`, `snap-confine` lacking its capability
set and `gst-ptp-helper` lacking its own. `--xattrs-include='*'` is needed at
both ends of the `tar`.

It was found by accident, while looking for something else: checking whether
`gts9u-upgrade` preserved capabilities, a walk of the image found **zero** files
with any, while the tree it is built from has three. So they were not being
lost on upgrade; they had never arrived.

It is the worst kind of failure: silent and delayed. A binary without its
capability keeps working for root and stops working for everyone else, weeks
later, with nothing in any log.

`gts9u-upgrade` also reapplies the capabilities explicitly after the rsync. That
is not redundant: the kernel clears `security.capability` when a file's owner
changes, so keeping them depends on the order in which rsync does things.

## Where Ubuntu keeps the network configuration, which is not where it looks

The first in-place upgrade lost Wi-Fi despite protecting
`/etc/NetworkManager/system-connections`. That directory was empty: `nmcli -f
NAME,FILENAME` revealed the profile lives in
`/run/NetworkManager/system-connections/netplan-NM-<uuid>.nmconnection`, that
is, **generated by netplan**. The persistent store is `/etc/netplan`.

And brightness is kept by `systemd-backlight` in `/var/lib/systemd/backlight`.

The rule that follows: when preserving state, **keep whole state directories,
not the particular file you happen to remember**. `gts9u-upgrade`'s list now
includes `/etc/netplan`, `/var/lib/systemd`, `/var/lib/NetworkManager` and
company.

## It was not the Rp: that leaves the current

A full sweep with a forced reconnection at every step, which is the only valid
way to test it — a sink reads the Rp when it connects: `CC_CNTL1` at `0x40`,
`0x50`, `0x60` and `0x70`, verified by reading back after each attach. The hub
enumerates with none of them. **The Rp hypothesis is ruled out.**

Of the differences between the PC that does bring it up and this tablet, the
current remains. The SM5714 defines `OTG_CURRENT_500/900/1200/1500mA` in bits
7:6 of `BSTCNTL1` — hence 900 mA at 5.1 V being `0x46` — and **Samsung's mode
table picks 900 mA in every OTG row** on this board. Do not be misled by its
driver's `POWER_SUPPLY_PROP_VOLTAGE_MAX`, which prints "set otg current limit
1500mA" and **writes no register at all**: that is a log line, not a
configuration.

So raising it departs from what the manufacturer does, even though the chip
allows it. That is why `otg_ma` is a parameter defaulting to 900 mA, exactly as
today.

## It was the current, and the inrush appears in no log

The bus-powered hub with 3 USB ports and Ethernet starts with `otg_ma=3`
(1500 mA) and not with 900 mA. Measured: `BSTCNTL1=0xc6`, and `lsusb` shows the
Genesys Logic hub and its RTL8153, which binds `r8152` and presents an
interface.

The revealing part is what they declare once enumerated: **the hub asks for
100 mA and the Ethernet for 180 mA**. Nothing. What needed the headroom was the
**inrush** of their regulators and the PHY. With the ceiling at 900 mA the
charger's protection cut in before the hub could even signal attach, and since
the cut happens in the charger and not in the host, **nothing appears in any
log**: no over-current, no enumeration error, not one failed attempt. From the
host, there is simply nothing plugged in.

That is why it took so long: the symptom of "it lacks current" and the symptom
of "nothing is connected" are identical seen from Linux.

What makes raising it safe is that **the ceiling and the advertisement are
independent**. `otg_ma` raises the protection's limit; `otg_rp` leaves the
advertisement at the factory value, so no device is told it may draw 1.5 A
continuously. It is given headroom to start, not permission to consume.

The order of the tests, which took some learning: **the limit has to be raised
before plugging in**. Like the Rp, this is decided at connection.

## Minor graphical artefacts: investigation abandoned

On the Adreno 740, two low-severity defects were reproducible: banding and
tiling in Discord's gradient under Chromium/Wayland, and late corruption of
some `GtkSwitch` widgets. A linear capture of the primary KMS framebuffer
(2960×1848, XR30) contained the same defects, so they came from neither the
OLED panel, nor DSC, nor the photograph.

The general 3D path is not broken: games work correctly. Chromium came out
clean with explicit ANGLE/Vulkan and also under Xwayland. On Freedreno's
OpenGL Wayland path only `FD_MESA_DEBUG=flush` removed every defect, but it
forces a submit after each draw and is not acceptable as a global setting.
`noubwc`, `sysmem`, `notile`, `inorder`, `gmem`, `nobin`, `ddraw`, `dclear`,
`direct`, `noscis`, `serialc`, `nolrzfc`, `noindirect`, `noblit`, `nolrz`,
`nosbin`, `nofp16` and disabling `MESA_GLTHREAD` did not help.

Zink was ruled out too: a global override once stopped Mutter/GDM finding any
outputs after a reboot, leaving a blinking `_`; a variant limited to clients
survived boot but turned Discord's icons into blocks.
`ANGLE_DEFAULT_PLATFORM=vulkan` does not substitute for the flag in Chromium
either, because the browser requests an explicit backend.

No workaround from this session is shipped: no variables in `environment.d`, no
Mesa override, no alternative Mesa package, no browser launcher and no Mutter
change. If it is picked up again, the useful starting point is the implicit
dma-buf buffer handover in Ozone/Wayland; the compositor advertises no explicit
synchronisation protocols and Chrome uses `wl_buffer.release`.

### Hexagon disassembly of `sns_stk31610`: the site located, the cause not

A recipe that works, so as not to lose time on the tools again: `llvm-objdump`
does **not** accept a raw binary, but it does accept an ELF. Wrapping
`adsp.b18` in an ELF32 with `e_machine = 164` (EM_HEXAGON), one `PT_LOAD` and a
`.text` section at `0xb3200000` is enough: `llvm-objdump-18 -d b18.elf`
produces 453,900 lines with the `immext`s already fused, which is what allows
searching for string references by address.

The site that logs `[TOP-ALGO] all data was skipped` is at
**`b332ff88`–`b332fff0`**, inside the HAL's island code. Its chain of guards,
read backwards:

```
b332fea8: p0 = cmp.eq(r2, ##0x300)   ; r2 = memw(r3+#0x8); if not 768, it leaves
b332feb0: if (!p0) jump 0xb3330090   ; silent exit, logging nothing
b332ff10: call 0xb3120fa8            ; framework (another segment)
b332ff18: if (!p0) jump 0xb3330090   ; if it returns 0, it leaves
b332ff20: if (memw(r29+#0x1c)==0) jump 0xb3330090
b332ff40: p0 = cmp.eq(r0,#0x0)       ; r0 = memcmp(...)
          if (r0 != 0) jump 0xb332fff4   ; the "data accepted" branch
          otherwise it falls into the "all data was skipped" log
```

The log is limited to once by a counter at `r17+0x24`.

**Correcting one of my own readings:** `0xb32949f0` is **not** the function
that decides to accept or discard; it is `memcmp` (a byte-by-byte loop that
returns `mux(p0,#-0x1,#0x1)`, with `strcpy`/`strchr` as its neighbours).
Distrust identifying functions by their position in the call chain without
looking at them.

**This route ends here, and it is worth saying why.** Turning this into a fix
would mean symbolising the SEE framework, reconstructing the structures and
emulating; and even then, **the firmware is signed**, so the result would only
be useful if the condition turned out to be something adjustable from outside.
The known external levers — the registry, the enable request, `OPTION_DEFINE`
messages, factory mode — are all already ruled out by measurement. Do not take
this route expecting a fix: take it, at most, to document the cause.

## The S Pen's silo gives orientation and state, but no percentage

The X910 carries `PDCT` on TLMM GPIO137, active high when the pen is inside.
The port's ABI is the standard `SW_PEN_INSERTED` switch; no private event is
created. The complementary state comes from the Wacom command `0xee`: the
subtype 6 reply carries the discrete charge state in byte 2's low nibble and
the direction in byte 5.

Physical calibration on 2026-08-12: with the pen docked and its tip pointing at
the USB-C/right side, the controller answered `direction=2` (`downside`). Tab
Companion therefore translates `downside -> tip-right` and `upside ->
tip-left`; both orientations and removal/reinsertion are confirmed. During boot
the GPIO makes a brief out/in transition; the stable state and the subsequent
reply are what get published.

The silo's Wacom protocol contains no percentage. It only allows distinguishing
states such as charging, maintenance, charge complete or not charging. The
kernel registers `gts9u-spen` as a `power_supply` with `PRESENT`, `STATUS`,
`SCOPE` and `MODEL_NAME`, without `CAPACITY`. UPower correctly ignores that
supply as a battery with a level. The D-Bus API uses `PenBattery=-1` until it
can read the Battery Level characteristic of the Samsung BLE profile; that
route did return a physical 100 %. No level is ever estimated.

## The EF-DX920 already delivers Linux keycodes; it needs no second table in the kernel

In Samsung's driver's *bypass* mode, every word from the STM32 carries press in
bit 15 and the Linux keycode itself in bits 14:0. The port's mainline driver
already does exactly that translation. The X910 source defines DeX as
`KEY_DEX_ON=0x2bd` and the AI key as `KEYCODE_AI_HOT=0x2f8`. The physical
capture clarified that Finder does not use `KEY_SEARCH=217`: it emits 710,
while Fn+Finder/Settings emits 709. Fn+F1–F11 emit 757, 758, 759, 705, 254,
172, 224, 225, 113, 114 and 115. Fn+F12 produces not even a raw event on
firmware V37.

There is no keymap for `Fn+F1`–`Fn+F5` in the DTS: the EF-DX920 is model `0xd6`
and uses the bypass flow. The codes were obtained by pressing the physical
keyboard; the backend also keeps `BeginKeyCapture` to measure them again should
the firmware change. Do not assign standard F1–F5 by intuition.

The daemon uses `EVIOCGRAB` and relays every normal event through
`/dev/uinput`, including `SW_LID` and the Caps Lock LED's output. It replaces
only the source whose mapping is not "Keep the default action"; without the
exclusive grab, the original action and the chosen one would both fire. The
udev rule limits `uinput` to the `input` group.

## The S Pen's button needs no BLE; the movement does

`BTN_STYLUS` already arrives through the EMR digitizer while the tip is in
range. Tab Companion reads it without `EVIOCGRAB`: a release waits 300 ms
before declaring itself single, a second within that window makes it double,
and 600 ms held produces long. All three paths use exactly the same action
engine as the keyboard. This discovers no movements in the air.

The stock `AirCommand.apk` supplied the part that was not in the open sources.
Pairing is initiated by the pen after the Wacom `0xea` reset: Android opens the
GATT and accepts `PAIRING_VARIANT_CONSENT`, without calling a classic pairing.
On hardware, BlueZ received that authorisation and confirmed `Bonded`, `Paired`
and services resolved.

The application service is FD6C. Battery Level, Button State, Status, Firmware,
Mode, Battery Raw and the diagnostic channels were all identified. Mode `0x10`
keeps remote operation. Button State uses headers 0/3 for release/press and
14/15 (142/143 if the sample is impure) followed by little-endian `dx`, `dy`
and a sequence number. The displacements are incremental: Air Command
accumulates them before classifying the trajectory. The permanent service
accepts only a SPEN carrying both FD6C/FEF5 UUIDs while the physical sensor
says docked; it does not open a general authorisation to nearby devices. The
agent is the default one only during the 65-second window and deregisters on
bonding or on expiry, so as not to hijack other accessories' normal pairing.

The physical capture separated the six trajectories cleanly. Swipes are
resolved by the dominant axis and the sum's sign; circles have high energy on
both axes and are told apart by the sign of the oriented area. The live repeat
recognised, in order, up, down, left, right, anticlockwise and clockwise; an
additional clockwise test confirmed the sign. Crossing the movement threshold
cancels the long-press timer, preventing one stroke from firing two mappings.
The sample-by-sample dump stays in the diagnostic script only, not in the
permanent service.

## Identifying the X910's whole Book Cover Keyboard family

The DTS's `stm32,model_name` string is not decorative: it lists EF-DX915,
EF-DX910, EF-DX900, EF-DX925 and EF-DX920. The attach event supplies a model
byte, but the older revisions also need the VERSION reply's second position.
The correspondence observed in the stock source is:

- protocol `0xd1`/`0xd2`: EF-DX900;
- protocol `0x03`/`0xd3`/`0xd5`: EF-DX925;
- protocol `0xd6`: EF-DX920;
- for the rest, `version[1]` 0/1/2: EF-DX915/DX910/DX900.

That is why the driver must request VERSION before registering any candidate
and reject a model it cannot resolve. The `input` device's name is also the
user service's discovery ABI: it must keep the `Book Cover Keyboard` prefix and
end with the EF-DX number. The extension proves identification only; it
certifies neither keys nor touchpad of a model that is not connected.

## A removed S Pen does not advertise after a forced disconnection

`AirCommand.apk` contains the `KeepConnectedEnabled` preference, the reaction
to the insertion event and an explicit GATT disconnection path, but that does
not prove the X910 can wake the pen merely by removing it. The physical test
did settle it: after a `Disconnect` while docked, taking it out produced no BLE
advertisement; an active scan did not see it either and every BlueZ `Connect`
failed. Without a channel to notify the pen after losing the silo's contacts,
the policy breaks the gestures. Do not force that disconnection.

The percentage does have to be persisted when the connection sleeps of its own
accord. The Wacom silo cannot read it again, and publishing `-1` would make it
look as though the battery had been lost. The UI therefore distinguishes a
stored measured level from an estimate: it invents no values and changes the
bar only after a real Battery Level read or the discrete charge-complete state.
