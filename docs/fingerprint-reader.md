# The EL721 fingerprint reader under Ubuntu

This document describes the experimental infrastructure for the Galaxy Tab S9
Ultra Wi-Fi's (`SM-X910`) under-display optical reader. Real capture has reached
17 accepted samples and 100% secure-world coverage. The template-encryption
blocker is now resolved: Ubuntu reconstructs HwVault's volatile context from
the tablet's K250A secure element and `dualfp` can derive its key. The remaining
functional proof is a new physical enrolment followed by same/different-finger
verification and GDM/PAM testing. The
[latest checkpoint](#authenticated-hwvault-restore-and-integrated-fprintd)
supersedes the historical investigation notes. Capture coverage is not the
percentage of the complete implementation.

### Requested desktop follow-up (after functional enrol/verify)

GNOME Settings 46.7 already handles `EnrollStatus`: progress, accepted-stage
animation, retry instructions and errors. The current console-driven probes
do not open that dialog, and the target overlay is not an enrolment wizard.
Reuse and validate the native dialog rather than duplicate it. GNOME Shell's
authentication prompt also supports feedback from GDM; placement near this
physical under-display sensor still requires device-specific integration.

After encrypted storage and real matching are working:

1. Show a dim fingerprint icon while waiting; illuminate the optical target
   only during actual contact/capture, then restore brightness on release,
   completion, cancellation or failure.
2. Anchor the target to the physical sensor using the monitor's **applied
   transform**, not raw accelerometer orientation. Turning a rotation-locked
   tablet must not move the target away from the sensor.
3. Validate both screen unlock and GDM login. Keep the physical target fixed
   but orient any nearby failure text with the displayed UI.
4. Avoid overlap with the on-screen password keyboard, especially in portrait.
   If the keyboard covers the sensor, suppress the target rather than move it
   to a non-sensing location or consume password keystrokes. Password entry
   must remain usable throughout.

References: [GNOME 46.7 enrol dialog](https://github.com/GNOME/gnome-control-center/blob/46.7/panels/system/users/cc-fingerprint-dialog.c#L639),
[GNOME 46 authentication prompt](https://github.com/GNOME/gnome-shell/blob/46.0/js/gdm/authPrompt.js).

## Confirmed identification

- Sensor: EgisTec EL721, identified by the R03 overlay and Samsung's official
  GPL driver for the `el7xx` family.
- Type: optical reader under the AMOLED panel.
- 3.3 V supply: PMIC-B LDO2 (`VDD_BTP_3P3` / `vreg_l2b_3p3`). The stock
  X910 node has no `etspi-ldoPin`; GPIO91 is a legacy port assumption, not the
  reader's supply.
- Enable/reset: TLMM GPIO155 (`etspi-sleepPin`).
- Model reported by Samsung: `X916`.
- Stock position:
  `16.70,0.00,9.10,9.10,14.80,14.80,12.00,12.00,5.00`.

The sensor works in secure mode. Samsung's Linux driver contains neither the
recognition algorithm nor a normal path to obtain images: enrolment, matching
and templates are delegated to signed applications inside TrustZone.

The official firmware's chain is precisely identified:

```text
fingerprint-service
  → libsfp_sensor
  → libsfp_teegw
  → libQSEEComAPI (objects)
  → compatible AppLoader, UID 122
  → lookupTA("dualfp") → 23 (not loaded)
  → signed dualfp TA from /vendor/firmware_mnt/image
  → QSEEComCompat controller → BAUTH
```

No `securefp.mbn` file exists in `system`, `vendor`, `odm` or the biometric
APEX. Static analysis had shown that Samsung's gateway can use either
`securefp` or `dualfp`, but a traced One UI 8 service restart settled the live
path: it asks for `dualfp`, receives AppLoader result `23`, and loads the split
image explicitly. Both the mounted fingerprint APEX and its active update
directory are empty of TAs. A full analysis of `NON-HLOS.bin` resolved the
remaining ambiguity: `fingerpr.b00`–`b08` holds the generic QFP engine, while
`dualfp.b00`–`b08` holds the Samsung/Egis implementation of the EL721, BAUTH,
matching and templates. Preloading `authnr.mbn`, another authenticator that
references both names, did not alter Ubuntu's result.

The assembled `dualfp` image is 19,927,128 bytes. The compatible AppLoader UID
122 accepts it with `loadFromRegion` and returns a valid QSEEComCompat handle;
the subsequent unload also completes correctly. That proves the required secure
TA is present and executable from Ubuntu. A root client registered by the
upstream `quic-teec` helper does not find a preloaded object and therefore
loads the signed image explicitly, just as the measured One UI path does.

### One UI 8 as the live reference

The rooted Android 16 / One UI 8 build `X910XXS5DZA1` was measured without
reading or copying any enrolled template. Its public kernel interfaces report
`EGISTEC`, `EL721`, type `8`, a 20 MHz secure SPI clock and product ID
`EL721-B`. The fingerprint service is the AIDL v2
`vendor.samsung.hardware.biometrics.fingerprint-service`, runs as Android's
`system` UID 1000, opens `/dev/esfp0` and talks through `/dev/smcinvoke`.

A system-wide `smcinvoke` trace of a clean service start and a real fingerprint
unlock settles the important transport details:

- the service calls `lookupTA("dualfp")`, gets result `23`, allocates the TA
  image from `qcom,qseecom-ta` and opens a session successfully;
- its two persistent BAUTH buffers are `0x2a4000` bytes each and come from the
  CMA-backed `qcom,qseecom` dma-heap;
- the SHM bridges expose the rounded TA at physical `0xf5400000` with size
  `0x1302000`, and the BAUTH buffers at `0xfc300000` and `0xfc600000`; all
  three use HLOS VMID 3 and read/write permission 6;
- BAUTH requests use controller operation 0 with counts `0x0424` — four input
  buffers, two output buffers and four input objects — exactly the layout
  emitted by the Ubuntu probe;
- the real unlock trace recorded 3,839 samples with none lost; every one of the
  fingerprint service's observed controller calls completed with result zero.

A later service restart exposed an important distinction. Samsung's
`fingerprint.ko` initialises its cached sensor type to `-1` at a cold probe, but
the running One UI instance had already cached `8` in the driver. The service
therefore logged `already sensor_type checked`, skipped command `16`
(`TypeCheck`) and made command `1` (`Prepare`) its first real TA operation.
`libsfp_sensor` maps the EL721 name enum `21` to type `8`; this mapping is fixed
for the soldered X910 hardware and is not a user-selected value.

The current `dualfp` image is still 19,927,128 bytes and its code still opens
QUP1_SE2 at 20 MHz, maps input sensor-name enum `21` (`EL721`) to output type
`8`, and uses the same TypeCheck command and shared-buffer sizes. There is no
protocol drift caused by One UI 8 or by the dual-boot changes.

One UI reports its active FOD rectangle as `854,2689,993,2829`. Ubuntu's
slightly different `[854,2732]–[994,2872]` rectangle remains the one physically
validated against the Goodix raw coordinate stream; the stock value is a
reference to reconcile when rotation and the final GNOME overlay are wired up,
not a reason to change the working touch exclusion blindly.

The official image also contains Samsung's biometric service and the Egis
libraries, but they depend on Bionic, Binder, Android's biometric AIDL and
Gatekeeper tokens. That is why they are not a directly interchangeable backend
for `fprintd`.

## The prepared architecture

The infrastructure is deliberately **opt-in**. A normal build uses exactly the
DT and panel driver of the last validated commit, does not apply the Goodix FOD
extension and does not compile the EL721. QCOMTEE keeps the base's modular
configuration but stays blacklisted. For a controlled test, the combined
selector `ENABLE_FINGERPRINT_EXPERIMENTAL=1` can be used, or
`FINGERPRINT_PANEL_FOD`, `FINGERPRINT_TOUCH_FOD` and `FINGERPRINT_EL721`
enabled separately. The signed QCOMTEE module only loads with `modprobe
qcomtee`, after booting and enabling logging. This separation was introduced
after observing a reboot before the root filesystem was mounted, and it stops
another failure from becoming a bootloop.

The implementation separates four responsibilities:

1. `egis_el721.c` controls only the 3.3 V rail and the enable/reset line. It
   publishes `/dev/esfp0` for the non-sensitive part of the Egis ABI; it does
   not register the sensor as an SPI peripheral reachable from Linux.
2. `CONFIG_TEE=y` keeps the common infrastructure. In experimental builds,
   `CONFIG_QCOMTEE=m` packages Qualcomm's QTEE object transport; loading it
   manually publishes `/dev/tee0`. The Qualcomm Diagnostics transport and the
   UID 122 AppLoader are physically validated. Messages keep the upstream 4 MiB
   limit; larger TAs are delivered with a TEE memory object through
   `loadFromRegion`, without inflating the message or duplicating 20 MiB in
   CMA.
3. `panel-samsung-ana38407.c` offers the high-brightness mode an optical reader
   requires. It preserves the brightness GNOME asked for, restores it at the
   end, and forces cleanup after 15 seconds. A GNOME extension draws the target
   and compensates the global HBM outside that region.
4. The Goodix driver suppresses fingers only inside the sensor's rectangle and
   only during a biometric operation. The firmware already delivers real FOD
   `press/release` events and does not forward that contact as a normal touch.
   The rest of the screen stays usable, and disabling the session releases any
   held contacts. The session is also cancelled, rather than restored, when the
   system suspends.

GNOME 46 and `fprintd` do not themselves know a UDFPS's geometry and do not
control the panel's HBM. The `gts9u-fingerprint-overlay@agcarbajo` system
extension covers that gap in the session and at unlock; it still has to be
wired to the backend and loaded in GDM too.

## Security boundaries

These boundaries are part of the design, not optional tasks:

- Linux must not expose the EL721's frames, registers or raw SPI transactions.
  Unknown `/dev/esfp0` operations fail with `EOPNOTSUPP`.
- `/dev/esfp0` is created mode `0600`; its `ioctl`s require `CAP_SYS_ADMIN`.
  The sensor starts powered off and is powered off on suspend, on driver removal
  and at shutdown.
- Templates and matching must stay in QTEE. The port neither imports, exports
  nor reuses the fingerprints enrolled under Android.
- The legacy QSEECOM machine list is not modified. The chosen route is the
  modern QTEE transport that already exists in the pinned kernel.
- Touch exclusion must be limited to the sensor's rectangle and only during an
  active operation. Grabbing the whole device with `EVIOCGRAB` would block the
  lock screen and is not acceptable.
- Every exit, cancellation, error, suspend or client shutdown must run the
  reverse sequence: remove the circle, leave HBM, power the sensor down and
  re-enable touches. The panel's watchdog is a second line of defence, not the
  normal way to close.

## Kernel interfaces

The paths contain dynamically assigned names; the device has to be discovered
rather than its index hardcoded.

### The EL721 sensor

The character node is fixed:

```text
/dev/esfp0
```

The platform device exposes these attributes:

| Attribute | Access | Contents |
|---|---|---|
| `vendor` | read | `EGISTEC` |
| `name` | read | `EL721` |
| `model` | read | `X916` |
| `position` | read | geometric metadata from the stock overlay |
| `type_check` | read | fixed/cached Samsung sensor type (`8` for EL721) |
| `sensor_power` | read/write | state and control of GPIO91/GPIO155 |
| `reset` | write | controlled reset; accepts only `1` |
| `reset_count` | read | resets performed since boot |

They can be located without assuming the device's name:

```sh
find /sys/bus/platform/devices -type f -name vendor -exec grep -l EGISTEC {} +
```

### The ANA38407 panel

The attributes appear next to the ANA38407 backlight:

| Attribute | Access | Contents |
|---|---|---|
| `fod_ready` | read | `1` when the panel is ready and on |
| `fod_mode` | read/write | optical HBM and the FlatZ sequence |
| `fod_circle` | read/write | a diagnostic DDIC command; requires `fod_mode=1`, but draws nothing without Self Display |
| `cell_id` | read | the panel's 22-character module identifier, or `ENODATA` |

`cell_id` exists because Samsung's fingerprint TA binds the optical
calibration to the panel it was measured on. The driver reads `RX_MODULE_INFO`
(DCS `0xa1`, eleven bytes under the level-0 key) while the panel is coming up
and publishes it in Android's byte order: bytes 4..10 followed by 0..3, as
lowercase hexadecimal. It is read once per power-on, never written, and the
attribute fails with `ENODATA` rather than inventing a value if the DDIC does
not answer.

The panel keeps the desktop's requested brightness in parallel. Writing
`fod_mode=0` restores that value, and also switches the circle off if it was
active. The watchdog returns both controls to zero after 15 seconds.

This layer has already run in isolation on hardware. HBM, the watchdog and the
exact brightness restoration were validated. `fod_circle=1` reaches the DDIC
without error but produces no visible image: the Samsung kernel first loads a
Self Display image and checks its checksum. Porting that subsystem just for the
indicator gains no capture; GNOME's target is used instead. The panel on its
own is ruled out as the cause of the initial bootloop.

The ANA38407 offers no local HBM. Reading a fingerprint puts it into global
FlatZ/HBM and GNOME darkens the pixels outside the target. Being OLED, those
pixels physically emit less light even though the region is selected in the
compositor. The opacity is computed from the current brightness with the
official table: normal mode reaches 420 cd/m² at `WRDISBV=2047`, and
fingerprint FlatZ 650 cd/m². The target is left out of the compensation and
receives the optical maximum; the rest keeps roughly its previous luminance.
The extension recalculates every 100 ms in case a key changes the brightness
during the read.

### Goodix touch

The UDFPS block is configured on the Goodix I²C device through four sysfs
attributes:

| Attribute | Access | Contents |
|---|---|---|
| `fod_rect` | root read/write | `left top right bottom` in raw Goodix coordinates |
| `fod_enable` | root read/write | enables the FOD sponge and the regional suppression |
| `fod_property` | root read/write | Samsung's `fast/strict` policy, values `0`–`3`; default `3` |
| `fod_state` | read, pollable | `idle|pressed|released|out|vi x y sequence` |

The driver obtains the sponge's address from the SEC extension the GT6936
firmware publishes; it hardcodes no controller registers. On the physical unit
it announces `0x29800`, length 1024. The SEC structure starts after
`IC_INFO`'s ten trailing reserved bytes; skipping them yields a false address.
Like Samsung's driver, every access first wakes the firmware into normal mode
with command `0x9f` and then confirms the sponge with `0xf2`.

The raw rectangle `[854,2732]–[994,2872]` was physically validated: a finger at
the visual centre produced `released 911 2808` and `released 945 2809`. During
that same test no `BTN_TOUCH`, tracking ID or normal coordinate appeared. Each
slot is classified when it starts: a finger begun inside is consumed until
`UP`, while one begun outside keeps working even as it crosses the rectangle.

## The intended sequence for a read

The future `fprintd` backend must treat every read as a transaction:

1. check the panel, QTEE and the sensor;
2. transform the geometry to the current orientation and enable the Goodix
   exclusion for that area only;
3. power the EL721 up and, if needed, reset it;
4. show GNOME's mask/target and enable `fod_mode`;
5. ask `dualfp` for the capture or match through QTEE;
6. in an unconditional cleanup block, remove the circle and HBM, power the
   sensor down and re-enable touch.

The sensor, the circle and HBM must not be kept active between samples for
longer than the secure application asks.

## Layered validation

### 1. Non-destructive probing

After booting an experimental build, first confirm QTEE is still unloaded and
load it only with a recovery channel available:

```sh
test ! -e /dev/tee0
lsmod | grep -q '^qcomtee ' && exit 1
sudo modprobe qcomtee
```

Then:

```sh
test -c /dev/esfp0
test -c /dev/tee0
fp_vendor=$(grep -l '^EGISTEC$' /sys/bus/platform/devices/*/vendor | head -n1)
test -n "$fp_vendor"
fp_sysfs=${fp_vendor%/vendor}
for attr in vendor name model position sensor_power; do
	printf '%s: ' "$attr"
	cat "$fp_sysfs/$attr"
done
dmesg | grep -Ei 'egis|el721|qcomtee|fingerprint'
```

The expected result before starting an operation is `sensor_power=0`. The mere
existence of these nodes validates infrastructure only; it does not prove a
fingerprint can be enrolled or recognised.

### 2. Power and reset

The test runs as `root`, must be brief, and ends by powering the sensor down
even if a command fails:

```sh
fp_vendor=$(grep -l '^EGISTEC$' /sys/bus/platform/devices/*/vendor | head -n1)
test -n "$fp_vendor"
fp_sysfs=${fp_vendor%/vendor}
trap 'printf 0 > "$fp_sysfs/sensor_power"' EXIT
printf 1 > "$fp_sysfs/sensor_power"
cat "$fp_sysfs/sensor_power"
printf 1 > "$fp_sysfs/reset"
cat "$fp_sysfs/reset_count"
```

It must also be verified that the rail returns to zero after a reboot, a
shutdown, or forcing the driver's removal.

### 3. The optical panel

Tested only as `root` and with the screen on. The change must be observed for a
few seconds, never leaving HBM latched:

```sh
bl=$(for d in /sys/class/backlight/*; do
	test -e "$d/fod_ready" && { printf '%s\n' "$d"; break; }
done)
test -n "$bl"
test "$(cat "$bl/fod_ready")" = 1
trap 'printf 0 > "$bl/fod_mode"' EXIT
printf 1 > "$bl/fod_mode"
sleep 2
printf 0 > "$bl/fod_mode"
```

The validation must confirm that the previous brightness returns, that
suspending or powering off cleans the state, and that the watchdog acts if the
client dies.

### 4. Touch exclusion

Validated on 14 August 2026 on the physical tablet. With `fod_property=3`, the
GT6936 delivered `released` inside the rectangle and a simultaneous listen on
`/dev/input/event5` received no normal contact. Disabling the session made the
screen respond immediately. What remains is repeating the full authentication
experience in GDM and in all four orientations, once the backend exists.

### 5. QTEE and full authentication

The read-only query with the official `quic-teec` tools already confirms QTEE
5.2.0, Qualcomm Diagnostics and the compatible UID 122 AppLoader. Ubuntu gets
result `2` from `lookupTA("securefp")` as root and after reproducing Android's
numeric UID 1000. The live One UI 8 service does not use that alias either: it
gets `23` from `lookupTA("dualfp")` and loads the signed image. Client identity
and a supposedly hidden preloaded controller are therefore ruled out.

`scripts/probe-qtee-securefp.c` implements exactly that query. It is built
against `quic-teec` `736419e25a2036aac3292a10a93e394a90750ca3` and QCBOR
`4ace4620d549f22c1163c5b00d3ae0c0dae1d207`: it opens UID 122, runs only
`lookupTA("securefp")` and releases the returned handle without obtaining the
application object or sending it an operation. Its optional
`--client-uid=UID` opens `/dev/tee0` first and then irreversibly removes the
process's groups, UID and GID before `registerAsClient`; it cannot regain root.
This reproduced Samsung's numeric UID 1000 credential without loosening
`/dev/tee0` permissions and gave the same negative result as UID 0.

`scripts/probe-qtee-load-securefp.c` reassembles a stock split image with the
ELF offsets Qualcomm uses. It takes the segments' base name and the load name
separately. For `dualfp` it reserves a TEE memory object and uses
`loadFromRegion`; QTEE accepted the 19,927,128 bytes as `dualfp` and unloaded
them cleanly. The probe also offers `--type-check[=FIRST[-LAST]]`: the request
reaches the TA (`invoke result 0`). The stock HAL identifies `EL721` with name
enum `21` and translates it to sensor type `8`; the probe reproduces that exact
mapping. Its mutually exclusive `--prepare` selector sends the stock command
`1` in no-calibration mode and reports only result fields and returned byte
counts. Neither selector starts capture, enrolment or matching.

Qualcomm's pinned credential callback serialises `getuid()` and the current
time into the CBOR object passed to `IClientEnv.registerAsClient`. The probes
also expose a diagnostic `--kernel-client-env` path: with a narrowly gated
kernel patch it reproduces downstream smcinvoke's root operation 5 with a NULL
credentials object. That exact path also loads `dualfp` but TypeCheck remains
at type zero. The patch is disabled in normal and release builds. These are
controlled hypothesis tests, not a service design: a production backend will
run under a dedicated unprivileged identity with narrowly granted device
access.

For three sessions the TA answered `29` to everything. The cause was resolved
on 14 August 2026 by disassembling the TA itself, which is not encrypted. Its
dispatcher rejects the request and writes `29` into `rsp[4]` when the prior
validation of the embedded pointers fails, and that validation consists of
**registering each of them again as a shared buffer of `0x2a4000` bytes**:

```text
4280:  bl   0x1b0                 ; qsee_register_shared_buffer(ptr, 0x2a4000)
42b4:  cbz  w0, ok
42b8:  log  "FAIL_REGISTER_SB(%d)"
42dc:  mov  w0, #0x1d             ; 29
```

The stock gateway declares 8 bytes of payload, but its `dmabuf` allocations are
much larger, so the registration works for it. Reserving both TEE memory
objects at that exact size makes the TA accept the request and run the command:
`invoke result 0`, `trustlet=0`, response envelope zeroed. `29` simply meant
the buffers were too small.

With the transport correct, the standalone `TypeCheck` diagnostic still
returns type `0`. That command performs up to three SPI transfers and requires
reading `rx[42]==0x07` and `rx[46]==21` to declare `ET721`. It was initially
treated as the blocking result. The live service restart showed that it is not
part of the steady-state path once the platform driver already knows its one
soldered sensor, so Ubuntu now also publishes the fixed type `8` instead of
making normal operation depend on this cold-discovery helper.

The decisive follow-up reproduces `BAuth_Prepare` instead. Samsung uses a
`0x80010`-byte wire view over each persistent `0x2a4000` shared buffer. With no
Ubuntu calibration file, the input is command `1`, mode `2`, zero calibration
bytes. On the physical tablet on 22 August 2026, the signed TA answered:

```text
Prepare: invoke result 0; trustlet=0, payload=0,
         sensor_type=8, function_status=0, calibration_bytes=0
```

This is the first successful secure EL721 initialisation from Ubuntu. It also
proves that QUP1_SE2 ownership and the trusted sensor path work; the earlier
`TypeCheck=0` result is a limitation of that discovery command in this boot
context, not evidence that the TA cannot communicate with the sensor. The
one-shot cleanup then measured `sensor_power=0`, removed `/dev/tee0` and
unloaded QCOMTEE.

The bus is **QUP1_SE2**, and its pins are worth pinning down properly because
an earlier measurement was made on the wrong ones. The TA names its pads
`qup1_se2_l0..l3`, and `qup1_se2` is **gpio36–gpio39**, not gpio64–67 — those
are `qup2_se2`. The numbering agrees between the stock tree and mainline:
gpio26 is `qup1_se7` in both.

Those pins are **out of Linux's reach by design**, here and in stock: this port
declares `gpio-reserved-ranges = <36 4>` and the stock tree
`qcom,gpios-reserved = <0x20 … 0x27>`, precisely because TrustZone governs
them. The kernel does not expose them, so no sampling from user space can
observe them, and **there is no valid measurement of whether TrustZone drives
that bus or not**. The one published earlier looked at gpio64–67 and proves
nothing.

The rest of the Linux layer already mirrors stock exactly, which was checked
one item at a time: the `spi@a88000` node (`qupv3_se2_spi`) is disabled in the
stock tree too and the X910's overlay never references it; Samsung's driver in
a secure build is a `platform_driver` hanging off `soc`; and the SE's clocks
come up disabled from the bootloader, Linux does not disable them — the command
line already carries `clk_ignore_unused`, `pd_ignore_unused` and
`regulator_ignore_unused`. Holding `gcc_qupv3_wrap1_s2_clk` on from a module
does not change the result.

TrustZone's generic log is not a usable diagnostic path on this firmware. The
stock tree describes `tz-log@146AA720`, but that window contains pointers into
secure memory; reading Android's generic `/proc/tzdbg/log` rebooted the tablet.
It must not be probed again. The classic SIP call (service 6, command 2)
answers "not supported", and QTEE's Diagnostics service (UID 143) only returns
the list of loaded TAs. This no longer blocks the port because `Prepare`
provides a successful end-to-end sensor result.

It was verified that the tablet's active partitions match the analysed firmware
byte for byte: `apnhlos` matches `NON-HLOS.bin` (SHA-256 `1aa9de73…`) and `tz`
matches `tz.mbn` (`865b32e1…`). The result is not down to mixed versions or to
anti-rollback.

The helper tools live in `scripts/` and are not installed in the final image:
`probe-el721-abi.c` checks that the restricted ABI exposes only the model,
`probe-qtee-securefp.c` queries a logical name, and `probe-qtee-load-ta.c`
allows loading and unloading a small, already-assembled TA.
`probe-qtee-load-securefp.c` contains the bounded EL721 `TypeCheck` and
`Prepare` calls, while `probe-stock-qseecom.c` keeps the equivalent experiment
for linking against the stock Bionic library. None of them enrols templates or
is used as an authentication backend.

`fprintd` is now present in the image, but nothing can be enrolled through it
yet and the reader is not advertised as working. These have to be validated, in
this order, before that changes:

- enrolment and cancellation without leaving HBM, the sensor or the touch block
  active;
- several correct verifications and wrong fingers;
- unlocking GNOME and authenticating in GDM;
- suspend/resume, rotation and brightness changes during a read;
- a reboot with no loss and no exposure of templates;
- recovery after the backend crashes and after the watchdog expires.

Until that whole matrix passes, the public status stays experimental and
fingerprint authentication is considered unavailable.

## The userspace backend

With `Prepare` working, the probes stopped being the right shape for the job
and the backend was written properly. It lives in `packaging/libfprint/` and is
built into a replacement `libfprint-2-2` package by
`scripts/build-libfprint-el721.sh`; the Noble package it replaces keeps its ABI
version, so the device package pins the local build explicitly.

`el721-qtee.c` is the QTEE side. It owns the whole secure transaction: it opens
`/dev/tee0`, registers as a client, assembles and loads the signed `dualfp`
image, keeps the two `0x2a4000` shared buffers alive for the session, serves
the QIS callback listener the TA registers, and exposes Samsung's BAUTH command
set as ordinary C functions — `Prepare`, the generic control command `12`, the
active-group key, and the `EnrollInit`/`Do`/`Final`,
`IdentifyInit`/`Do`/`Final` and `Cancel` pairs. Three details were measured on
the tablet rather than guessed: the calibrated `Prepare` is retried through the
same opcode transitions One UI uses, where opcode `8` means reset the sensor
and opcode `9` is acknowledged with control opcode `83` instead of a power
cycle; the two bootstrap controls are advisory, and operation `76` answers
status `51` on this tablet while startup continues; and the optical
`egoptbds.dat` blob is uploaded in chunks through the control command rather
than in one message.

The calibration inputs are proprietary and stay out of the repository.
`scripts/import-fingerprint-firmware.sh` packages them from a directory the
tablet's owner extracts from their own matching firmware, checking each file
against a pinned hash: the nine `dualfp` segments, `calib.dat` and
`egoptbds.dat`. The panel's `cell_id` completes that set from the running
hardware.

`el721.c` is the `libfprint` driver on top. `libfprint` has no bus that can see
a platform device, so `patches/0001-el721-platform-driver.patch` adds the
enumeration path; the driver itself powers the rail, runs `Prepare`, raises the
panel's HBM for the duration of the operation, follows the finger through the
Goodix FOD state, drives the enrol and identify loops, converts the TA's opaque
template blob into an `FpPrint`, and unwinds power, HBM and touch suppression
on every exit — including cancellation and timeout. Templates are stored by
`fprintd` as the TA emitted them; Linux never parses them and never touches
Android's enrolled data.

The lifecycle around it is packaged too. `ubuntu-gts9u-qcomtee.service` loads
the QCOMTEE module before `fprintd`, a drop-in grants `fprintd` the single
extra device it needs (`/dev/tee0` read/write, leaving the rest of the stock
sandbox intact), and `ubuntu-gts9u-fingerprint-cleanup` returns HBM, the touch
block and the sensor rail to zero if `fprintd` dies or is upgraded mid-read.

## What 29 and 51 actually mean

Two status codes drove most of the guesswork, and disassembling the TA's own
dispatcher settled both. The command table is a jump table of nineteen
entries, and every handler starts by checking the exact wire sizes of the
request and the response:

| Command | Input | Output |
|---|---|---|
| 1 `Prepare` | `0x80010` | `0x80010` |
| 2 `EnrollInit` | `0x178` | `0xc` |
| 8 | `0x510` | `0x40c` |
| 9 | `0x914` | `8` |
| 10 `Cancel` | `8` | `8` |
| 12 `Control` | `0x2a3110` | `0x2a3010` |
| 13 `HatOp` | `0x48d` | `0x40c` |

**51 is a size mismatch.** A handler that does not recognise the declared
lengths logs `invalid length` and answers 51; every control operation that
answered 51 was answering that, not refusing the operation.

**29 has two different sources.** The dispatcher registers both non-secure
pointers with `qsee_register_shared_buffer` before it dispatches, and writes
29 if that fails — this is the historical meaning, and it is satisfied. The
enrolment path returns the same number for an unrelated reason:
`init_enroll_stub` calls into Samsung's `tz_vigis_api.c`, which returns `0x1d`
when the optical engine's global context is still NULL. The context is created
by `prepare_stub`, and Ubuntu's `Prepare` returns all zeros without creating
it, because it is missing the optical data One UI loads first.

The kernel side of the old theory was still worth fixing and is in tree.
`qcomtee-bridge-large-objects.patch` gives every memory object in the BAUTH
size range its own contiguous DMA32 allocation and its own SHM bridge, instead
of a suballocation inside a larger bridged TZMEM area; the threshold matters,
because 2.76 MB fell under `SZ_4M` and silently took the page-backed path.

## The current state and the next step

Everything above the secure boundary is written; nothing above it is proven.
The last measured milestone is still the calibrated `Prepare`. The enrol chain
— generating the active-group key, `EnrollInit`, the `EnrollDo` loop with a
real finger under HBM, and an `EnrollFinal` that returns a template — has been
exercised repeatedly against the TA but has never been carried through to a
stored template, and identification has not been attempted at all.

`el721-qtee-selftest.c` is the harness for exactly that step. It powers the
sensor, opens the session, runs the calibrated `Prepare`, optionally sets the
active group and issues a single `EnrollInit` followed by `Cancel`, and powers
the sensor back down whether or not the call succeeded. It records no biometric
data.

The next milestone is therefore a single successful enrolment, and it is also
the port's go/no-go point. Booting One UI settled what of the optical bring-up
is actually missing, and it is less than it looked. `gdxrtcalib.dat` and
`cbge_*.dat` do not exist anywhere on this tablet: those are Goodix paths that
the gateway carries for other models, and the Egis EL721 never uses them.
`/data/vendor/biometrics/meta` holds exactly the two files already imported.
The panel's `window_type` reads `80 00 04` under One UI, and its `cell_id`
matches the value the ported ANA38407 driver publishes byte for byte. With
those bytes supplied, controls 401 and 402 are both accepted.

A traced One UI enrolment then gave the exact sequence the service performs,
which is worth writing down because it is the specification the Ubuntu backend
has to meet:

```text
pre_enroll : control 22 (set_enroll_session, gSession_Flag = 1)
             command 19 (generate challenge)
enroll     : control 84 (the gateway logs "skip")
             register the QIS callback
             skeymast command 0x203, dualfp command 15, then control 49
             to install dualfp's HAT HMAC key without exposing it to Linux
             command 13, the authentication token, right before enrolling
             command 2  EnrollInit  -> CAPTURE_READY
             command 3  EnrollDo, repeatedly; opcode 4 is
                        BAUTH_OP_CODE_WAIT_INTERRUPT with timeout -1, and the
                        host enables the sensor interrupt and waits
             on opcode 5: control 87 with one response byte, then control 80
                          with four response bytes
             on opcode 87: control 87 with one response byte
             command 4  EnrollFinal after every capture, then repeat Init
```

Reproducing that sequence corrected several things in the bridge, all of them
read out of the TA rather than guessed. Its control command validates a
response-capacity field the caller writes into the output buffer at
`0x2a300c`; operation 12 refuses to run with anything under `0x226000` and
answers 51, which is what that number always means — the declared wire sizes
are not the ones the handler expects. Operation 48 is
`BAUTH_OP_CODE_SEND_STOREPATH` and answers 29 until it is given a path.
Operation 49 is `SEND_KEY`: it consumes the metadata returned by dualfp's
command 15 after skeymast encapsulates the current HAT key for target
`"dualfp"` with command `0x203`. Linux relays only the secure-world envelope
and decoded metadata; the raw HMAC key never enters normal-world memory. The
optical `egoptbds.dat` goes up in
`0x3000`-byte pieces with nothing in the scalar field, exactly as One UI's
`load_bds()` walks it. Operations 401, 402, 84 and 108 land in the TA's
default case, so 21 simply means this build does not implement them.

The command table itself is now mapped, so no size has to be guessed again:

| Command | Input | Output |
|---|---|---|
| 1 Prepare | `0x80010` | `0x80010` |
| 2 EnrollInit | `0x178` | `0xc` |
| 3 EnrollDo | `0xc` | `0x230024` |
| 4 EnrollFinal | `0xc` | `0xa018` |
| 6 IdentifyDo | `0xc` | `0x230089` |
| 10 Cancel | `8` | `8` |
| 13 Hat_OP | `0x48d` | `0x40c` |
| 19 Challenge | `0xc` | `0x44` |

With every one of those corrections in place, `EnrollInit` still answers 29,
and so do `EnrollDo` and `IdentifyDo` — with or without a preceding `Prepare`,
and against a freshly loaded TA. Disassembling that number to its source
settles what is really wrong, and it is not the transport.

`tz_vigis_api.c` answers 29 when the optical engine's global context is
missing. That context is created in `fp_prepare_state_handler`, and only after
`fpsec_open_sensor` succeeds — which first calls `fpsec_spi_open`, which opens
the secure SPI instance and sets its clock to 20 MHz. When that fails the
handler logs, skips the allocation and still lets `Prepare` return zero in
every field the caller can see. So the successful `Prepare` never meant the
sensor had been opened: it means the command ran, and the sensor type is a
constant the TA already knows.

That reading was wrong, and the correction matters. `prepare_stub` calls
`fp_sdk_uninit` first, which is what puts the state global at zero, and
`fp_prepare_state_handler` propagates any failure back through `Prepare`'s
result word. Since that word is zero, the sensor does open and the engine
context is created. The enrolment path returns 29 from the other branch that
yields the same number: `fp_enroll_init` calls `enroll_init_v2`, the Egis
matcher's own entry point, and that is what fails.

Two further things were settled by measurement. Holding
`gcc_qupv3_wrap1_s2_clk` on with its source at 80 MHz changes nothing, so the
serial engine's clock is not the obstacle. The earlier conclusion that control
49 decoded a template was wrong: its internal `decode_metadata` call decodes
the key metadata produced by command 15, then copies the resulting 32-byte key
into dualfp's HAT verifier. It is a prerequisite for authenticated enrolment.

A traced One UI **cold start** — restarting the stock service with the log
running — then gave the init sequence, which had been guesswork until now:

```text
load the TA, then two shared buffers of 0x2a3110 and 0x2a3010 bytes
command 1   Prepare
control 76  with room declared for a response
control 88  (this build answers 51; the stock service skips the calibration
            update for an optical sensor anyway)
control 81  reset the optical blob
control 82  the blob itself, 1204124 bytes in one piece
control 22  set_enroll_session
```

Two of those were wrong here and are now fixed. Operation 76 answers 51 unless
the caller declares a response capacity, exactly like operation 12. And the
optical blob does not go through operation 81 at all: 81 only frees whatever
the TA holds, and 82 appends, with a chunk index of 0 to 3 in the scalar field
and up to `0x2a3000` bytes per chunk, the first chunk declaring the total. This
port was sending the bytes to 81, which threw them away.

Disassembling what the matcher's configuration is built from finally named the
missing input. The TA carries a table of twenty-nine Samsung model codes —
`A505`, `T865`, … `X916`, `S711` — and looks the running board up in it by
name, storing the index in the sensor structure the matcher configuration is
built from. Index 27 is `X916`, exactly what this tablet's kernel driver
reports and what the stock service logs as `mi X916` at start-up. Control
operation 88, the one this port had been sending empty, is that lookup.

Two operations reach that setter, 88 and 90, and the difference between them
is one log line: the 88 case also prints the name, and doing that over the
non-secure buffer takes the TA down — QTEE then answers -90 to the invocation,
and it happens for any declared payload length above zero. Operation 90 does
the same lookup without the log and is accepted, so the bridge uses 90.

With the model selected, control 76 answered, the optical blob uploaded
through 82 and the enrolment session set, the initialisation now matches the
stock trace call for call, and `EnrollInit` still answers 29.

What remains is below all of that, and two measurements say so plainly.

`Prepare` takes **1.06 seconds** here. The same command in the traced One UI
cold start takes **32 milliseconds**. And it takes the same 1.06 seconds with
the sensor's rail on as with it off — if the TA were running SPI transfers, an
unpowered sensor would not cost exactly as much as a powered one. A second
`Prepare` in the same session returns in 130 ms, which is the short path the
handler takes once the state is no longer zero.

Put together: the first `Prepare` runs the full path, spends about a second
inside `fpsec_open_sensor` getting nothing, leaves the engine context
unallocated and still reports zero in every field the caller can see. Every
later failure follows from that — `enroll_init_v2` finds no matter at field
`0x2f98` of a handle that was never built, and answers 29.

So the remaining defect is that **TrustZone gets nothing from the EL721 over
the secure SPI in this boot**, and the BAUTH command sequence above it is now
correct. Command 16 is the one-line probe for it: it answers zero whether the
sensor is powered or not, where stock reads a real type.

Chasing why led somewhere embarrassing and simple. The reader's 3.3 V does not
come from a GPIO-controlled LDO on this board: the stock node carries
`etspi-regulator = "VDD_BTP_3P3"` and no `etspi-ldoPin`, and the fixups map
that rail to the PMIC's `pm_humu_l2`. This port drives GPIO91 as if it were an
LDO enable and never claims a supply at all, so the kernel log reads

```text
egis-el721 egis-el721: supply vdd not found, using dummy regulator
```

The device the port registers for the reader is synthetic and carries no
device-tree node, so the `vdd-supply` written next to `egistec,el721` never
reaches it. Claiming the rail by name from a test module gets a consumer onto
`vreg_l2b_3p3`, but that regulator refuses both `regulator_set_voltage` and
`regulator_get_voltage` with `EINVAL` and reports 0 mV, so it is not driving
anything either.

**The EL721 had never been powered under this port.** Everything above follows
from that: no sensor answers, so TrustZone's `fpsec_open_sensor` spends a
second getting nothing, the engine context is never allocated, and every
biometric command answers 29. The driver now claims `vdd` and sequences it the
way the stock driver does.

Getting the rail itself to exist took three tries, and the reasons are worth
keeping. It cannot be described in the board file: Samsung's ABL bootloops on
any vendor_boot DTB whose structure moves, measured twice, and repacking that
image with the tree untouched reproduces the working one to the byte, so the
packing was never at fault. It cannot be added from `postcore_initcall`
either — that panics before anything can be logged. What does work is adding
it later, from a module, with `of_changeset`: a sibling `regulators-el721`
node under the same RSC, carrying `ldo2`, plus a consumer node that references
it by phandle. Giving that node its own platform device gets the RPMh driver
to register the rail without disturbing the rails already up.

The last obstacle there was arithmetic. The stock overlay asks this rail for
3.3 V exactly, but mainline's PMIC5 p-type LDO steps 8 mV from 1.504 V and
3.3 V lands half a step off the grid, so registration failed with
`ENOTRECOVERABLE` until the constraint was widened to the neighbouring points.
The rail now registers and enables at **3,296,000 µV**.

With it powered, the TA's answer changes for the first time in this whole
investigation: `Prepare` returns `sensor_type=0` where it had always returned
the constant 8. It only does so when the rail is up *and* the GPIO lines are
driven — rail alone, or lines alone, still give 8. So the reader is finally
being reached, and what the TA now reports is that it cannot identify it.

Narrowing that further ruled out the obvious suspects. GPIO91, which this port
drives as if it enabled an LDO although the stock node declares no
`etspi-ldoPin`, turns out not to matter: with the rail up and only the stock
sleep line driven, the answer is the same zero. Neither a reset pulse on that
line nor settling for 200 ms changes it, and `Prepare` still takes its full
second. The reader has power, its enable line is high and it has been reset,
and TrustZone still cannot identify it over the secure SPI.

Two facts point at where to look next. The tablet's own clock tree shows
`gcc_qupv3_wrap1_s2_clk` disabled with its source parked at 5.12 MHz, while
the TA asks for 20 MHz; and `gcc_qupv3_wrap1_s7_clk` is enabled, so the
wrapper itself is powered and its AHB clocks cannot be the whole story. The remaining gate is inside Samsung's engine
rather than in the transport: the enrolment worker in `tz_vigis_api.c` reaches
`fp_enroll_init` in `vigis_controller.c`, and that call returns failure. The
same TA also validates authentication tokens — an all-zero `BAuth_Hat_OP`
envelope (command 13, `0x48d`/`0x40c`) is rejected with 62 rather than ignored
— so the token path is live and may well be the gate.

The older risk has not gone away either: the TA also carries `BAuth_Hat_OP`,
`BAuth_GetK_From_KM` and `BAuth_Generate_Challenge`, so enrolment may still
require a Gatekeeper-signed authentication token that this platform cannot
produce. That would be a boundary rather than a defect. If a template does come
back, what remains is ordinary engineering: the identify loop and its control
sub-opcodes, replacing the 45 ms Goodix poll with the sensor's own interrupt,
template persistence across reboots, the GDM and session integration, and the
validation matrix above.

## The secure SPI pins belong to TrustZone, and must not be touched

With the rail up, the panel awake and its optical mode engaged, `Prepare` still
answers `sensor_type=0` and `EnrollInit` still answers 29, so the display state
is not the gate either.

The pin muxing looked like the next candidate, and the reasoning was sound as
far as it went. `qup1_se2` — the serial engine behind `spi@a88000`, the one the
TA's clock request names — spans `gpio36`..`gpio39` here, and pinctrl reports
all four as `UNCLAIMED`: no Linux driver owns them, because neither the stock
tree nor this port describes an SPI controller for the reader. The TA's own log
strings name a matching failure, `qsee_tlmm_get_gpio_id: BLSP_CLK Failed`,
which is what a serial-engine function lookup returns when no pin carries it.

That hypothesis is wrong, and the way it failed is the answer. debugfs is
locked down here, so `pinmux-select` returns `EPERM`; writing the four TLMM
configuration registers directly from a module instead **hard-resets the
tablet**. The kernel log of that boot simply stops — no shutdown sequence, no
panic, nothing flushed — which is the signature of an XPU violation, not of a
software fault.

So those registers are secure-owned. TrustZone holds the pins exactly as it
holds the serial engine, it muxes them itself, and a non-secure write to them
takes the SoC down. `UNCLAIMED` in pinctrl means only that Linux has not
claimed them, which is the correct and expected state on this board.

Two things follow. The mux is not the defect and cannot be made one from
Linux — that avenue is closed, and the module that tried it has been deleted so
it cannot be loaded again by accident. And the reset is itself a positive
result: it confirms that `gpio36`..`gpio39` really are the reader's secure SPI
and that TrustZone owns that path end to end.

## What 29 really was: the matcher was never built

Disassembling the number to its source, rather than reasoning about it, ended
the investigation. The chain is short and every link is checkable.

`EnrollInit` reaches `fp_enroll_init`, which calls `matcher_api_enroll_init`,
whose very first act is `enroll_init_v2`. That function asks the fingerprint
context for its matcher object — field `0x2f98` — and fails immediately when it
is null. Only one function in the whole TA ever writes that field, and it is
reached only from `matcher_api_init`.

`matcher_api_init` builds the matcher from one of two sources. If the model
index is set it reads the matcher configuration from the global the model
lookup fills. Otherwise it falls back to the sensor type and accepts only the
values 1 to 4 — and on anything else it returns without building anything,
which is exactly the silent path this port was taking. That also settles an old
red herring: the `sensor_type` this port used to report, 8, would have failed
that test just as surely as the 0 it reports now. Sensor identification was
never the route to enrolment; the model index is.

The model index is set by `fp_set_model_type`, and the dispatcher reaches it
from two control operations. Reading the jump table at `0x27a0e0` names them
exactly:

| operation | what it does |
| --- | --- |
| 88 | `fp_set_model_type`, **then builds the matcher configuration** |
| 90 | `fp_set_model_type` and nothing else |

This port had been sending 90, on the belief that 88 crashed the TA. It does
not: both operations log the model name identically, so the log was never the
difference, and 88 accepts the same five-byte `"X916"` payload without
complaint. The earlier failure belonged to how the call was framed, not to the
operation.

With the bridge switched to operation 88, `EnrollInit` answers
`result=0 status=0 opcode=0` for the first time in this port's history, and
`Cancel` — corrected to its measured 8-byte envelope — answers cleanly too.

## Where the port stands after enrolment starts

With operation 88 in place the whole enrolment chain runs, and a first live test
with a finger on the reader measured exactly where it stops.

```text
EnrollInit user=User_0: result=0 status=0 opcode=0
EnrollDo 1: result=0 status=-1 quality=0 progress=0 remaining=0
EnrollDo 2: result=0 status=0  quality=0 progress=0 remaining=0
EnrollDo 3: BAUTH command 3 failed (trustlet=39)
```

The reply is identical with a finger pressed on the reader and with the screen
untouched, and the same 39 comes back from `EnrollFinal` when nothing was
captured. So the state machine is correct and the sequence above it is correct;
what does not happen is the capture itself.

That is consistent with everything else measured. The TA's enrolment worker
waits in `[ESTATE_FINGER_DOWN]` for `fpsec_start_get_image`, and finger
presence on this reader is reported over the sensor's own link — the stock node
declares no interrupt line, only `etspi-sleepPin`. With TrustZone getting
nothing back over the secure SPI there is no finger-down to wait for, so the
worker falls through and the capture returns empty.

One open item therefore remains, and it is now stated much more narrowly than
before: **TrustZone cannot read the EL721 over the secure SPI.** Power, the
sleep line, the panel state, the pin mux and the whole BAUTH command sequence
have each been tested and are not the cause. Until that is solved a finger
cannot be enrolled, and until a finger can be enrolled the libfprint and
fprintd integration cannot be validated.

## Enrolment is an interactive protocol, and this port was not speaking it

The captured One UI enrolment trace settles how a capture actually works, and
it is not the loop this port was running. `EnrollDo` does not take an image and
return it. It returns an **opcode** telling the non-secure side what to do next,
and expects to be called again once that has been done:

```text
cmd 0x2  EnrollInit  -> opcode 0,  function_status 0   CAPTURE_READY
cmd 0x3  EnrollDo    -> opcode 4,  timeout -1          BAUTH_OP_CODE_WAIT_INTERRUPT
         (host enables the reader's interrupt, waits for it, disables it)
cmd 0x3  EnrollDo    -> opcode 5                       BAUTH_OP_CODE_NOTIFY_DOWN
         control 87, then control 80                   CAPTURE_STARTED
cmd 0x3  EnrollDo    -> opcode 87
         control 87
cmd 0x3  EnrollDo    -> opcode 6                       NOTIFY_CAPTURE_SUCCESS
cmd 0x3  EnrollDo    -> opcode 0,  function_status 1   CAPTURE_COMPLETED
cmd 0x4  EnrollFinal                                   CAPTURE_SUCCESS
         control 76, and the whole sequence repeats for the next capture
```

Two things follow that were not understood before. `EnrollFinal` runs once per
capture rather than once per enrolment, each pass starting again at
`EnrollInit`. And the earlier reading of the first live finger test — that the
reader was returning "no finger" — was wrong: the port was calling `EnrollDo`
repeatedly without honouring the opcode or issuing controls 87 and 80, which is
why the TA eventually answered 39. The harness now implements the protocol.

That correction does not make capture work, and it sharpens where it stops. The
port's first `EnrollDo` answers `opcode 0` with `function_status -1`, where
stock answers `opcode 4` at exactly the same point — so the failure is inside
the first call, before any interrupt is ever waited for.

The same trace also shows stock issuing `Challenge` (command 19) and then
`Hat_OP` (command 13) before `EnrollInit`. `Challenge` succeeds here.
`Hat_OP` does not: it needs its full 1165-byte envelope — anything else is
refused with 51 — and refuses an all-zero envelope with 62. That is a
Gatekeeper-signed authentication token, and this platform has no Gatekeeper to
produce one.

So two candidate blockers remain, and they have not yet been told apart:
TrustZone getting nothing from the sensor, and the missing authentication
token. The TA's own sensor self-test is control operation 19, and it is accepted
when no response capacity is declared, which is the thread to pull next.

## The reader answers an all-zero identity, and that is the whole defect

Following the failure inside the first `EnrollDo` reaches the sensor rather than
the token, which tells the two remaining candidates apart. `fp_enroll_state_handler`
fails in `[ESTATE_INIT]` on a virtual call into the TA's own sensor driver, so
the missing Gatekeeper token is not what stops a capture.

The identification path then explains every symptom at once.
`fpsec_open_sensor` calls `device_identify_type`, which polls
`device_et7xx_get_fp_type` — a three-byte read of the reader's identity
register — **twenty-one times**, one millisecond apart, giving up only when the
type is still zero. That is exactly the second that `Prepare` costs here, where
the traced One UI cold start costs 32 ms because it identifies on the first
attempt. With no type, the TA binds no sensor driver, and every later call into
that driver fails.

So the defect is not in the command sequence, the matcher, the model, the
protocol or the token: **the EL721 returns an all-zero identity to TrustZone.**

One real fault was found and fixed while confirming this. The rail module drove
the sleep line *before* enabling the rail, the reverse of the stock driver's
order, which leaves the part without a clean reset because a signal pin is being
driven into an unpowered chip. It now enables the rail, settles 2.3 ms, then
takes the line low and raises it with the stock's 1.1 ms and 5 ms waits. That is
correct on its own terms and should stay, but it does not change the answer: the
identity still reads zero and `Prepare` still costs its full second.

## The QUP serial engine route, tested and excluded

The identity read timing — about 60 ms per attempt, twenty-one attempts — says
the transfers are timing out rather than returning zeros quickly, which pointed
at the serial engine itself. That has now been tested from every angle Linux can
reach, and none of it is the cause.

**Clocks.** The QUP wrapper's core clocks are reachable only straight from the
GCC provider, having no consumer in the device tree, and mainline leaves them
gated. Holding `gcc_qupv3_wrap1_core_2x_clk`, `gcc_qupv3_wrap1_core_clk`, the
`m_ahb`/`s_ahb` pair and the serial engine's own branch all on at once, with the
interconnect paths voted, changes nothing: the identity still reads zero and
`Prepare` still costs its full second. The captured stock kernel trace settles
why that was never promising — Android does not touch `gcc_qupv3_wrap1_s2_clk`
during fingerprint activity either, so enabling it was never the HLOS's job.

**Callbacks.** Stock registers a "QSEE Interrupt Service Listener" at boot, which
raised the possibility that TrustZone waits on the non-secure world to forward
the serial engine's interrupt — a good fit for 60 ms timeouts. It does not
apply. This port's bridge already runs a supplicant that services secure-world
callbacks, and instrumenting it shows the TA making exactly two callbacks up
front and then none at all across the 1.2 seconds of the identification loop.
TrustZone is not waiting on us; it is driving the bus itself and getting
nothing back.

What remains unexamined is the serial engine's own state — whether it is
configured and running at all — and those registers cannot be read from Linux
without risking the same XPU fault that the pin experiment produced.

## One UI says the sensor type is 8, and that changes the diagnosis

Booting the stock firmware and asking its own driver, with the reader working,
settles what a correct reading looks like:

```text
name         EL721
vendor       EGISTEC
type_check   8
bfs_values   "FP_SPICLK":"20000000"
```

**Eight is the right answer.** It is exactly what this port reported before any
of the power work, and what was written off here as a constant the TA already
knew. The zero it reports now is the broken reading, not the honest one — this
document had it backwards, and so did every conclusion drawn from it.

The stock driver's periodic state dump says the rest:

```text
fps_el7xx_work_func_debug: ldo: 0, sleep: 0, tz: 1, spi_value: 0x0, type: EL721
```

At idle the LDO pin is low and **the sleep line is low**, where this port holds
it high continuously. So the two defects were masking each other. While the port
reported the correct 8, enrolment failed for an unrelated reason — the model was
being selected through operation 90, which never builds the matcher. By the time
operation 88 fixed that, the reader had been moved into a state that reports 0.

What this predicts is specific and cheap to test: back under Ubuntu, without the
rail module driving the sleep line, `Prepare` should report 8 again, and with
the model now selected through 88 the enrolment chain should run against a
sensor that answers.

## The earlier enrolment success was on a degenerate path

Back under Ubuntu with nothing forcing the sleep line, `Prepare` reports
`sensor_type=8` again, exactly as One UI does. That confirms the reading above
and forces a correction to the section before it.

Operation 88 was reported here as the fix that made `EnrollInit` succeed. It
does — **but only while the reader has not been identified.** With the sensor
answering 8, operation 88 takes the TA down with `-90` every time: before the
optical blob and after it, with a declared response capacity and without, sent
from the bridge's own init or from the harness. It never crashed earlier only
because the rail module had driven the reader into the state that answers 0, so
the TA had bound no sensor driver and the call stopped short of
`fp_check_white_spot_and_apply_wsc_to_wk_bk`.

So that `EnrollInit user=User_0: result=0` was a matcher built over an
unidentified sensor. It could never have enrolled a finger, and the claim that
enrolment "starts" was wrong.

With the reader answering properly the position is:

| model selection | result |
| --- | --- |
| operation 88 | the TA goes down with `-90` |
| operation 90 | `EnrollInit` answers 29, the matcher is not built |
| skipped | `EnrollInit` answers 29 |

One suspicion was checked and cleared while narrowing this. The per-device
factory calibration `fp_check_white_spot_and_apply_wsc_to_wk_bk` needs is not
missing: `sec_efs/biometrics/meta/egis_calibration_data.bin` is byte-identical
to the port's `calib.dat`, the optical blob matches the size the stock service
uploads, and the stored `cell_id` matches the panel's. The inputs are right.

The default therefore goes back to operation 90, which leaves the matcher
unbuilt but cannot crash the TA; `EL721_MODEL_OP` selects the other.

## What the reader must answer, to the byte

The identification is a three-byte read, and the TA maps it with no room for
interpretation:

| bytes 4 and 5 | sensor type |
| --- | --- |
| `07 0D` | 2 |
| `07 0F` | 3 |
| `07 15` | 4 — the ET721, this reader |
| anything else | 0 |

The driver selector then binds a sensor driver for **2, 3 and 4 only**. Every
other value, zero included, leaves `[0x4a0310 + 0x150]` null, and that null is
the crash: `fpsec_get_badpixel_map_EL721` loads its method from that pointer's
vtable, which is where operation 88 takes the TA down.

This corrects the section above it, which was too quick. One UI's `type_check`
of 8 is the **kernel driver's** own enum, not the TA's, and the two are not the
same scale — the TA has no type 8 at all. So the port reporting 8 was never
evidence that the reader had been identified, and neither 8 nor 0 binds a
driver. Both mean the same thing: the reader did not answer `07 15`.

That is the defect, stated as precisely as it can be: **the EL721 does not
return its identity bytes to TrustZone over the secure SPI.** Everything else —
the transport, the command envelopes, the model table, the matcher, the
interactive capture protocol, the calibration inputs, the rail and its
sequencing — is correct and verified. Nothing above this layer can work until
the reader answers, and the answer it must give is `07 15`.

## Cold-boot parity and the early-rail boot regression

A cold One UI trace removes the last ambiguity in the non-secure power path.
At uptime 8.707239 it enables `VDD_BTP_3P3`, at 8.719568 it raises GPIO155,
and only then enters `smcinvoke`. It neither claims nor drives GPIO91, and it
does not ask HLOS to claim or clock the secure QUP engine. This is the sequence
the port must reproduce: PMIC rail first, GPIO155 second, trusted call last.

Three Ubuntu A/B images then reset between ABL decompression and the first
persisted Linux message: an incremental build without GPIO91, a clean build
without it, and a same-tree rebuild with GPIO91 restored. All kept the known
DTB hash `613b3bb7...`; all failed before a panic or kernel log existed. The
known-good `boot.img` (`9d4ace88...`) boots with either module set and its
kernel contains no `vreg_l2b_3p3` publication code. GPIO91 is therefore not the
cause of this bootloop.

The common delta was `postcore_initcall(el721_add_rail)`, which changed the
live OF tree while core providers were still starting. That path has been
removed. The companion now probes with no supply mutation and publishes the
already-validated `regulators-el721` sibling only on the first explicit
fingerprint power request. It uses the PMIC5-valid 3,296,000–3,304,000 µV
window, attaches the synthetic consumer after the changeset is live, and
allows the RPMh regulator driver to finish binding before acquisition.

The redesigned driver and complete experimental kernel compile cleanly;
`checkpatch.pl` reports no warnings and the linked image has SHA-256
`1539dd48f6562a39edab3cad6dfe03e1b896d82102a6f1ae14e1453166c9be13`.
The same late changeset was first loaded on the stable tablet with power
disabled, registered `vreg_l2b_3p3`, and reverted cleanly without a reboot.
The reviewed image was then packed as Android v4 boot
`d315e4ffc751a6fb2e96ccb5b49fa623c0dfe760000882bcbd5e552574d7cbb4`
and booted on the first attempt. At idle `/el721-supply` was absent and the
companion reported the sensor off. Its first explicit power request created
the supply, registered the regulator at 3,296 mV and raised its consumer count
to one; powering off returned that count to zero without a reset or warning.

The current QTEE-backed self-test then loaded the signed `dualfp` application
and ran calibrated `Prepare`. Transport, invoke result, function status and
opcode were all zero. That reply was initially rejected because word zero was
still being interpreted as an internal sensor type.

## A zeroed `Prepare` is success, and `EnrollInit` now works

The stock cold-start log resolves the ambiguity in that response. Its public
type `8` comes from command 16, the separate `TypeCheck`; after command 1 it
logs a successful `check_opcode` with every status field zero. The `8` once
seen in word zero of Ubuntu's unpowered `Prepare` was a host-work/reset status,
not an EL721 identity. Treating it as the sensor type both skipped that work
and made the properly powered all-zero reply look like failure.

A signed diagnostic module then reproduced the complete stock sequence from a
cold Ubuntu boot: GPIO155 was acquired low, the regulator load was set to
100 mA, `vreg_l2b_3p3` was enabled at 3,296 mV, the stock 2.3 ms delay elapsed,
and only then was GPIO155 raised. Calibrated `Prepare` returned `0/0/0/0` and
continued successfully through control 76 and the optical blob upload. The
module always lowered GPIO155, disabled the rail, removed the temporary
regulator node and unloaded QCOMTEE on exit.

The remaining matcher failure was the model selector. Operation 90 only stores
the `X916` table index and leaves the matcher absent, so `EnrollInit` answers
29. Operation 88 performs the same lookup and constructs the matcher. With 88
as the default, the physical tablet now reports:

```text
Prepare:       status=0 result=0 function_status=0 opcode=0
EnrollInit:    result=0 status=0 opcode=0
Cancel:        result=0 status=0 opcode=0
```

This supersedes the earlier secure-SPI diagnosis and the claim that operation
88 succeeds only on a degenerate path. The sensor and trusted path initialise
well enough to create the real matcher and enter enrolment. A single
non-interactive `EnrollDo` without HBM, a finger or the Android pre-enrol token
sequence returns status `-1` and no template, as expected; physical capture is
the next unproven boundary.

Controls 45 and 46 were also mislabelled in the early bridge as a wrapped
active-group-key pair. Static names and the stock trace identify them as secure
authenticator-ID operations, while Android's active-user path uses storage
operation 48. The self-test no longer sends 45/46 by default.

The corrected complete libfprint driver builds in the pinned ARM64 environment
without an EL721 warning. Package `gts9u4` was installed over `gts9u3` after
backing up the previous library. Through the system library — not an injected
test copy — the tablet enumerated the EL721, loaded `dualfp`, completed the
all-zero `Prepare`, selected `X916`, uploaded the optical blob, opened the
device and closed it with the rail off. The two owner-derived calibration files
were also installed in the firmware directory the production driver uses; no
template or fingerprint image was read or written.

## The production enrol path now consumes physical FOD events

Running the driver through `fprintd-enroll` exposed integration faults which
the standalone harness could not show. A second `Prepare` in the already-open
QTEE session was rejected with BAUTH status 29, so operation setup now only
restores sensor power. The ten libfprint finger identifiers are mapped
deterministically onto BAUTH's four secure template slots; the four-print limit
and collision policy still need a user-facing decision.

Optical mode has also been made suitable for a real enrol operation. Libfprint
refreshes `fod_mode` every five seconds so the panel's 15-second safety
watchdog cannot terminate HBM in the middle of enrolment. It no longer tries
to call a user's D-Bus session from root. Overlay version 7 instead polls the
panel's `fod_mode` and follows that kernel state. This ordering is important:
the temporary test watcher could show its compensating black shade before HBM
was active, briefly making the entire desktop and target darker before the
panel brightened. Version 7 should remove that race, but it remains a visual
acceptance test after GNOME Shell loads the new extension version.

The Goodix touch sponge can publish a press and release between two 45 ms
polls. The driver therefore records the sequence number in `fod_state` and
treats a newly latched release as one contact when the press was missed. With
package `gts9u9`, physical contacts at the stock FOD coordinates reached the
real `EnrollDo` command through the system fprintd service. Cleanup returned
`sensor_power`, `fod_enable` and `fod_mode` to zero.

Those calls returned the same `-1, 0, 0` sequence as the earlier tokenless
harness and produced no template. This proves the complete desktop-to-touch-
to-BAUTH path, but not secure capture. Stock sends `Challenge` and a
Gatekeeper-signed `Hat_OP` before `EnrollInit`, then follows the interactive
opcode 4/5/87/6 loop with controls 87 and 80. The production driver does not
yet supply such a token or implement that complete loop. No fingerprint image,
template or Android authentication token has been copied from the device.

The command-13 envelope has since been reproduced field for field from the
stock gateway rather than as a zero-filled raw command. It contains the packed
69-byte Android hardware-auth token at offset 4, a selector at 73, up to 1024
bytes of optional payload at 77, its length at 1101 and the 60-byte challenge
record at 1105. Command 19 returns that challenge record at output offset 8.
The bridge now has typed calls for both commands.

The distinction changes the diagnostic result. A completely empty command-13
body still returns 62, but a freshly generated challenge plus a HAT carrying
the correct challenge ID and no HMAC reaches the authentication check and is
rejected with secure-world code 28. Thus 62 was an invalid challenge envelope,
not proof of a parsed but unsigned HAT. Code 28 is the first direct evidence
that the remaining pre-capture boundary is a legitimately signed hardware
authentication token. The test generated no credential and deliberately did
not import one from Android.

## Gatekeeper authorization and the complete capture transaction

The remaining HAT boundary is now implemented without Android credentials.
Ubuntu creates a random, root-only Gatekeeper identity, re-enrols that same
secret into Samsung's `skeymast` instance for each QTEE session, verifies the
current BAUTH challenge and receives a signed 69-byte HAT. Before verification,
`skeymast` command `0x203`, dualfp command 15 and control 49 provision the
target-bound HMAC key entirely inside TrustZone. `Hat_OP` now returns zero and
`EnrollInit` returns zero; neither a user password nor an Android PIN, HAT or
template is read.

The response layout of command 3 was also corrected from the stock gateway.
Its real opcode is output word zero; timeout is at `+8`, function status at
`+12`, and the three enrolment metrics at `+16/+20/+24` with progress and
remaining reordered by the gateway. A physical capture now follows the
measured sequence `4 → 5 → 87 → 6/0`, closes with `EnrollFinal` even on
BAD_QUALITY 39, and starts the next transaction with `EnrollInit`. This avoids
the old permanent `0x80000000` sentinel after one rejected image.

Opcode 5 uses control 87 with one byte of input and control 80 with four;
opcode 87 uses control 87 with one. The old bridge had mistaken those fields
for response capacities. Static analysis of `TeeProxy::ControlOp` and
`BAuth_Control_OP` proves that the third pointer and following length are
copied into the command-12 input payload. For control 80, Samsung fills that
four-byte input with `/sys/class/power_supply/battery/temp`; Ubuntu exposes the
same tenths-of-a-degree value through `sm5714-battery/temp`. The reversed
framing made control 80 return 51 and is corrected in `gts9u26`. The earlier
98.7% estimate is superseded below.

The first physical `gts9u26` run then exposed the remaining value mismatch.
One UI's live optical-capture trace prints `tfd 2 0 1` at NOTIFY_DOWN and the
following capture step. With its override field clear, control 87 receives the
first byte: **2 (finger pressed)**. Ubuntu had sent zero. That still allowed a
few images through, but after repeated quality retries the trustlet terminated
the partially populated enrolment with result 70. The production path and the
self-test now send the measured pressed state 2.

## Full-coverage capture and the HwVault boundary

The 2026-08-26 Ubuntu tests establish the following:

- fprintd's `ProtectSystem=strict` originally prevented saving the new local
  Gatekeeper state. Adding `StateDirectory=gts9u-fingerprint` permits just its
  private state directory, alongside the stock `fprint` directory. The new
  directory is root-only (0700); the 99-byte state file is 0600. The obsolete
  copy in fprintd's per-user print directory was removed after the replacement
  was present; no Android credential was involved.
- Real captures complete `4 → 5 → 87 → 6 → 0`. Opcode 63 is an acquired/progress
  callback, not a missing control request. The bounded loop now handles it.
- The first metric is increasing coverage; the third is accepted-sample count,
  not samples remaining. A run reached 17 accepted samples and coverage 100.
  The timeout now measures 90 seconds of inactivity between transactions, not
  the total duration of enrolment. Rejected samples still close with Final
  before starting the next Init.
- Result 70 was temporarily treated as a retry in the deployed `gts9u20`
  experiment. Stock `enrollDo` treats it as an error, so `gts9u21` restores that
  behaviour. Only the stock recoverable results 39/41 are retried; a fatal
  result must not be hidden by a simultaneous retry code from Final.
- At full coverage, EnrollDo returned result 71 with zero template bytes.
  EnrollFinal returned zero but no template. Static analysis follows this to
  `encode_each_templ_ver3 → getTemplateEncryptionKey → HwVaultHal_deriveKey`.
  Result 71 is a key-derivation failure, never a successful enrolment.

The stock gateway extracts the **encrypted template from EnrollDo** at
`+0x1c`, using length `+0x22601c`, maximum `0x226000`, in an output of
`0x230024` bytes. EnrollFinal's optional `0xa000`-byte payload is bitmap/debug
output and must not become an `FpPrint`. Package `gts9u21` validates and copies
only a successful terminal EnrollDo template, preserves it across Final's
shared-buffer overwrite, and publishes it only if Final also succeeds.
It does not copy Final bitmap data or log any template bytes.

`scripts/test-el721-enroll-wire.sh` provides 11 offline synthetic tests:
successful copying, empty/max/oversized/overflow lengths, short/long/null
responses, key failure, intermediate opcodes and partial coverage. These pass
in the ARM64 build environment; they do not substitute for real enrol/verify.
They also pass with UndefinedBehaviorSanitizer. AddressSanitizer under the
emulated build environment exited without a diagnostic, so no ASan pass is
claimed. The ARM64 `gts9u21` package built successfully and was installed on
the tablet; libfprint enumeration, Prepare and close passed without a capture
or reboot. It has since been superseded by the integrated `gts9u22` package
documented in the latest checkpoint below.

### HwVault investigation (no Android state imported)

Samsung's signed `hwvault.b00`–`b08` were read from the tablet's APNHLOS firmware
partition, mounted read-only. The assembled 1,101,912-byte TA loads and unloads
successfully via QTEE. The firmware remains a local, ignored artifact and is
not distributed by this repository. Loading it alone is not sufficient:
its `get_derived_key` explicitly reads cached credential index 11, then derives
the requested key for the caller. Android's live reference logs show that same
index. No cached credential or Android vault file was read.

Static analysis identified commands `0x271b` (generate a wrapped HwVault root)
and `0x271c` (load one into the TA). A bounded generation diagnostic returned
status **9936** and no wrapped bytes, so it performed no SetRoot and saved no
file. That result originally suggested that Ubuntu needed its own StrongBox
root. Later One UI tracing disproved the premise: the fingerprint service does
not generate a new root during normal startup. It restores existing,
authenticated K250A credentials into each fresh HwVault instance. The failed
generator remains useful negative evidence, but it is no longer the path being
implemented.

### K250A transport and authenticated credential exchange

Samsung's GPL K250A driver has now been ported to the mainline 7.2 kernel. The
shipping board connects the secure element to QUP SE10 I2C at address `0x23`
and powers it from PM8550VS-G LDO2 at 1.8 V. The boot-compatible DTB already
contains that controller but marks it disabled. To avoid another ABL bootloop,
the module applies a reversible live-device-tree changeset, instantiates the
controller and client only while loaded, and restores `status = "disabled"`
on removal. It drives the dedicated LDO through the public RPMh interface.
No replacement DTB or persistent firmware state is involved.

The signed module was exercised on the tablet under kernel lockdown. Load,
open/power, unload and live-DT rollback all succeeded. `CORE_OPEN` returned
`9000`, establishing end-to-end RPMh, GENI I2C and ISO7816 T=1 transport. The
module deliberately returns `ENODEV` for the absent reset GPIO, matching the
stock X910 DT and driver behaviour instead of simulating a reset by cycling
power.

The authenticated K250A exchange has since been reproduced completely; see the
latest checkpoint below. No Android file, PIN or userspace credential was read,
imported or changed.

### SPSS userspace boot coordination

The clean SPSS transport test proved that `qcom_spss`, GLINK, SPCOM and all six
`sec_nvm` service channels work. One UI's successful sequence has an additional
process, `spdaemon`, between SPSS boot and Keymaster use. Static analysis of Samsung's
`libspcom.so` found that this is not coordinated through `/dev/spcom`: the
library opens `/dev/spss_utils` and uses the exact legacy event ABI
`WAIT_FOR_EVENT`, `SIGNAL_EVENT` and `IS_EVENT_SIGNALED`. The event IDs are 0
(`pil_called`), 1 (`nvm_ready`) and 2 (`spu_ready`). The previously ported
SPCOM source even declared `spss_utils` as a soft dependency, but that second
driver had not been included.

The experimental kernel now packages a mainline adaptation of Samsung's GPL
`spss_utils` driver. It preserves the stock IOCTL numbers, structures, status
values and duplicate-signal behaviour, creates `/dev/spss_utils`, and ties
power-up/power-down event reset to the actual SPSS `remoteproc` lifecycle. The
bootloader-sensitive DTB remains untouched: `qcom_spss` publishes both
userspace bridge devices below its dynamically created remote processor.
Samsung's downstream IAR/CMAC handoff is not emulated because it requires a
hypervisor memory-assignment API absent from this mainline platform; attempts
to use it fail explicitly instead of reporting a false secure handoff.

A delayed manual launch also exposed an ordering constraint. SPSS advertises
`cryptoapp`, `sp_keymaster` and `sp_nvm` shortly after GLINK comes up, and its
production firmware no longer completed a symmetric OPEN requested much later
by `spdaemon`. Predefining those application channels in SPCOM was tested and
then rejected: the stock SM-X910 DT defines only `sp_kernel` and `sp_ssr`.
Android instead starts `sec_nvm` and `spdaemon` as part of the same boot
sequence. Ubuntu must preserve that split and coordinate userspace with SPSS
startup, rather than changing the kernel's channel ownership model.

The modules compile cleanly against Linux 7.2, pass `checkpatch` with no errors
or warnings and are signed by the same kernel build key. Subsequent hardware
work established the shared `qcom,sp-hlos` DMA-BUF heap and the complete SPSS
startup path. More importantly, tracing the consumer showed that generating a
new HwVault root was the wrong success criterion; the normal fingerprint path
is the authenticated credential restore documented next.

## Authenticated HwVault restore and integrated fprintd

The 2026-09-02 checkpoint closes the template-encryption infrastructure gap:

- Reverse engineering Samsung's `libese-grdg.so` established the namespace
  selector in the K250A GET APDU: `P1=1` for persistent credentials and `P1=0`
  for ordinary credentials. One UI restores persistent indices 0 and 1, then
  ordinary index 11.
- Ubuntu now selects the `SECURE_NVM` applet, obtains a fresh nonce, asks
  HwVault command `0x2714` to sign each GET, reads the encrypted credential and
  response authenticator from K250A, and returns both to command `0x2715` for
  verification and caching. The measured payloads are 353 bytes (index 0),
  2,533 bytes (index 1), and 185 bytes (index 11); every HwVault status is zero.
- `libfprint` retains that restored HwVault object for the complete EL721
  session. A tablet self-test then completed BAUTH `Prepare` with transport,
  result, function status and opcode all zero, reported bootstrap 76/model 88,
  loaded the optical calibration blob and exited `PASS`.
- The real systemd sandbox grants only `/dev/tee0` and `/dev/k250a` in addition
  to its existing policy. `fprintd-list agcar` detects `EgisTec EL721 UDFPS`
  through the installed package and exits zero. No fingerprint is currently
  enrolled.
- The 11 synthetic encrypted-enrolment protocol tests pass in the full ARM64
  package build. Installed package:
  `1:1.94.7+tod1-0ubuntu5~24.04.8+gts9u22`; SHA-256:
  `c8272978855f837f98e36de06e08b37acfb6410efbe6c4c3cacabf11760e1ab9`.

The proprietary signed TAs and device calibration remain user-supplied,
hash-validated local firmware and are not distributed by this repository. The
restore uses only authenticated GET operations against the tablet's secure
element; it does not import Android files, a PIN or a fingerprint template.

The implementation is approximately **99%** complete. The remaining one per
cent is deliberately not claimed from synthetic testing: physically enrol a
fresh finger into an encrypted template, verify the same and a different
finger, then validate cancellation, lockout, PAM/GDM and the lock-screen FOD
overlay. Only after those functional tests should the requested icon-on-touch,
rotation anchoring, on-screen-keyboard collision avoidance and failure text be
polished.

The latest physical run also established that the Goodix firmware normally
publishes one `released` record rather than separate press/release records.
The driver now consumes the first isolated release after enabling FOD as a
stale arming event and accepts subsequent releases as real contacts. The user
confirmed that the target appears correctly on repeated touches. Captures
reached 96% coverage and 16 accepted samples before the incorrectly framed
control path returned EnrollDo result 70. Samsung maps 70 to its system-failure
state, so the temporary retry was removed rather than hiding or looping the
failure. The corrected `gts9u26` package is the next physical enrolment test.

## Press-capable Goodix path and persistent test reports

The current kernel no longer waits for the firmware's late dedicated FOD
release gesture. Its first ordinary coordinate press inside
`854 2732 994 2872` publishes `pressed`, suppresses that contact from the
desktop, and publishes `released` when the slot ends. This starts secure
capture while the finger is still covering the optical reader.

Once userspace observes that press-capable protocol it permanently disables
the older release-only fallback for the current operation. The firmware can
publish a second dedicated release after the synthetic coordinate release;
treating it as another contact caused one no-finger capture per real touch,
many result-39 quality retries and eventually fatal result 70. Package
`gts9u29` contains this fix, uses the trustlet's measured 17 enrolment stages
and emits one compact aggregate sample record for diagnostics.

Tab Companion 1.1.3 exposes the bounded test under Info. A completed run is a
normal right-index enrolment; timeout, Stop and Escape cancel without saving a
partial template. Live coverage, accepted samples, retries and the secure
result are shown in the window. The latest report is always:

```text
~/.local/state/tab-companion/fingerprint-tests/latest.jsonl
```

Timestamped siblings retain earlier runs. Records contain timing and aggregate
result fields only; raw images, template contents, HATs and vault credentials
never leave their existing secure boundaries.

The press-capable kernel is now a required part of this feature branch, so
userspace no longer treats isolated legacy RELEASE events as captures. The
firmware can emit those events while FOD mode is starting; accepting them
caused a false first stage before any touch. Per-contact and per-sample
aggregate records use journal level MESSAGE so the persistent test report sees
them without enabling global libfprint debug output.

The first fully instrumented run contained 31 genuine PRESS captures: 30
returned quality result 39, one reached 2% coverage/one accepted sample, and
the next capture exhausted the trustlet's 30-retry budget with result 70.
Every matching RELEASE had `capture=0`, confirming that duplicate capture is
fixed. Package `gts9u31` tested a 250 ms press-settle interval and recorded
press coordinates plus actual hold time. The follow-up run placed every long
contact around the physical centre `(924, 2802)` and still returned result 39,
so neither alignment nor settling explains the regression.

The earlier high-yield runs processed the sample after RELEASE. The sensor
acquires while covered, but that paired Samsung event is the point at which
its buffered optical image is ready for the trustlet. Package `gts9u32`
therefore captures on exactly the first RELEASE following a real PRESS.
Isolated startup releases and the later duplicate release have no preceding
live contact and cannot consume a sample.

## Per-sample finger-leave closure

The first release-timed diagnostic accepted 10 of 11 physical samples and
advanced from 0 to 62% coverage before EnrollDo returned result 70. This rules
out alignment and capture timing as the remaining cause. The complete One UI
enrolment trace shows one additional mandatory transition after every sample:
immediately after EnrollFinal, Samsung sends payload-free control 76
(`CAPTURE_FINGER_LEAVE`) before the next EnrollInit. The Linux driver omitted
that transition, allowing stale contact state to accumulate in the trustlet.
Package `gts9u33` now mirrors that ordering for accepted and rejected samples.
Tab Companion 1.1.4 also keeps journal collection alive for 750 ms after the
fprintd client exits so a terminal secure result is never lost from the JSONL
report.
