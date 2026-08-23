# The EL721 fingerprint reader under Ubuntu

This document describes the experimental infrastructure for the Galaxy Tab S9
Ultra Wi-Fi's (`SM-X910`) under-display optical reader. **Enrolment,
verification and fingerprint login do not work yet.** The secure transport is
solved and a complete userspace backend now exists — a QTEE bridge to Samsung's
signed BAUTH application plus an `EL721` driver for `libfprint` — but no
fingerprint has yet been enrolled or matched on the tablet, so every claim
below about capture and matching is about code that has been written and
partially exercised, not about a working reader.

## Confirmed identification

- Sensor: EgisTec EL721, identified by the R03 overlay and Samsung's official
  GPL driver for the `el7xx` family.
- Type: optical reader under the AMOLED panel.
- 3.3 V supply: TLMM GPIO91 (`etspi-ldoPin`).
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
             control 49, carrying the active user identifier
             command 13, the authentication token, right before enrolling
             command 2  EnrollInit  -> CAPTURE_READY
             command 3  EnrollDo, repeatedly; opcode 4 is
                        BAUTH_OP_CODE_WAIT_INTERRUPT with timeout -1, and the
                        host enables the sensor interrupt and waits
             controls 87 and 80 between captures
             command 4  EnrollFinal, then control 76
```

Reproducing that sequence corrected several things in the bridge, all of them
read out of the TA rather than guessed. Its control command validates a
response-capacity field the caller writes into the output buffer at
`0x2a300c`; operation 12 refuses to run with anything under `0x226000` and
answers 51, which is what that number always means — the declared wire sizes
are not the ones the handler expects. Operation 48 is
`BAUTH_OP_CODE_SEND_STOREPATH` and answers 29 until it is given a path.
Operation 49 needs the user identifier. The optical `egoptbds.dat` goes up in
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
serial engine's clock is not the obstacle. And control 49 is `decode_metadata`,
which decodes an existing template blob — it answers 51 to anything that is not
one, so it is not a precondition for a first enrolment at all.

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

Two facts point at where to look next. The tablet's own clock tree shows
`gcc_qupv3_wrap1_s2_clk` disabled with its source parked at 5.12 MHz, while
the TA asks for 20 MHz; and `gcc_qupv3_wrap1_s7_clk` is enabled, so the
wrapper itself is powered and its AHB clocks cannot be the whole story. The remaining gate is inside Samsung's engine
rather than in the transport: the enrolment worker in `tz_vigis_api.c` reaches
`fp_enroll_init` in `vigis_controller.c`, and that call returns failure. The
same TA also validates authentication tokens — a zeroed `BAuth_Hat_OP`
(command 13, `0x48d`/`0x40c`) is rejected with 62 rather than ignored — so the
token path is live and may well be the gate.

The older risk has not gone away either: the TA also carries `BAuth_Hat_OP`,
`BAuth_GetK_From_KM` and `BAuth_Generate_Challenge`, so enrolment may still
require a Gatekeeper-signed authentication token that this platform cannot
produce. That would be a boundary rather than a defect. If a template does come
back, what remains is ordinary engineering: the identify loop and its control
sub-opcodes, replacing the 45 ms Goodix poll with the sensor's own interrupt,
template persistence across reboots, the GDM and session integration, and the
validation matrix above.
