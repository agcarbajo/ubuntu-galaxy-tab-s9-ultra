# The EL721 fingerprint reader under Ubuntu

This document describes the experimental infrastructure for the Galaxy Tab S9
Ultra Wi-Fi's (`SM-X910`) under-display optical reader. **Enrolment,
verification and fingerprint login do not work yet**: no support will be
installed or advertised in GNOME until there is a secure backend for
`libfprint`/`fprintd` and it has been validated on the tablet.

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
mapping. No capture, enrolment or match is started.

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

With the transport now correct, the blockage moves to the sensor. `TypeCheck`
returns type `0`, meaning "not identified": the TA performs up to three SPI
transfers and requires reading `rx[42]==0x07` and `rx[46]==21` to declare
`ET721` and return type `8`. That the TA does get as far as running that query
is proven: poisoning the output buffer before the call, it comes back with its
first eight bytes written and the rest untouched.

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

TrustZone's log, which is where the TA records the reason, has not been read
either. The stock tree describes `tz-log@146AA720`, but that window is an area
of pointers in IMEM: its first quadword is `0x14696000`, and mapping that
address reboots the tablet, because it is secure memory. The classic SIP call
(service 6, command 2) answers "not supported" on this firmware, and QTEE's
Diagnostics service (UID 143) only returns the list of loaded TAs
(`keymaster64`, `featenabler`, `tz_hdm`, `tz_iccc`).

It was verified that the tablet's active partitions match the analysed firmware
byte for byte: `apnhlos` matches `NON-HLOS.bin` (SHA-256 `1aa9de73…`) and `tz`
matches `tz.mbn` (`865b32e1…`). The result is not down to mixed versions or to
anti-rollback.

The helper tools live in `scripts/` and are not installed in the final image:
`probe-el721-abi.c` checks that the restricted ABI exposes only the model,
`probe-qtee-securefp.c` queries a logical name, and `probe-qtee-load-ta.c`
allows loading and unloading a small, already-assembled TA.
`probe-stock-qseecom.c` keeps the equivalent experiment for linking against the
stock Bionic library. None of them enrols templates or is used as an
authentication backend.

Only once a secure backend exists will `fprintd` be installed, and these
validated, in this order:

- enrolment and cancellation without leaving HBM, the sensor or the touch block
  active;
- several correct verifications and wrong fingers;
- unlocking GNOME and authenticating in GDM;
- suspend/resume, rotation and brightness changes during a read;
- a reboot with no loss and no exposure of templates;
- recovery after the backend crashes and after the watchdog expires.

Until that whole matrix passes, the public status stays experimental and
fingerprint authentication is considered unavailable.

## The current blockage and the next step

`libfprint` has no support for the EL721 and the sensor delivers no images to
Linux. The QTEE transport, the AppLoader, loading `dualfp`, the optical
illumination and the Goodix FOD signal/suppression are all checked. So is the
deferred power: on 14 August 2026 the 3.3 V rail and the enable line were
switched on and off on the tablet, with a reset and without rebooting it.

The BAUTH packing is solved: with shared buffers of the size the TA demands it
accepts and runs the command, and One UI's live IPC trace confirms the same
parameter counts. Numeric UID 1000, downstream's operation-5/NULL client
environment and preloading `authnr` have each returned the same sensor type
zero, so none explains the difference.

The backing-memory hypothesis is now ruled out too. A clean Linux 7.2-rc3
variant routes every QTEE object of at least 2 MiB through `qcom_tzmem`, asks
for DMA32 and passes the physical address—not the qcomtee device's DMA/IOVA—to
the SHM bridge. A live SCM trace measured the rounded TA at `0xf1a00000` with
size `0x1302000` and the two BAUTH regions at `0xf2e00000` and `0xf3100000`,
each with size `0x2a4000`. As on One UI, all three were below 4 GiB and used
VMID 3 with read/write permission 6. The signed TA loaded and the request
completed successfully, but `TypeCheck` still returned sensor type zero.

The observed host-side start sequence now matches stock as well: only
`VDD_BTP_3P3` is enabled, GPIO155 rises 2.856 ms later, no reset pulse is sent,
and Linux does not claim or clock QUP1_SE2 before the TA call. The unresolved
boundary is therefore inside secure sensor communication: either a secure
firmware resource/ownership prerequisite not visible in the Linux trace or an
unread TA error. The next useful work is a read-only TrustZone/QSEE log path or
a comparison of secure resource setup. Repeating identities, reset pulses or
memory layouts is no longer justified, and Linux must not take QUP1_SE2 away
from TrustZone or sample its secure pins.

After that comes the minimal bridge to `libfprint`/`fprintd`. Templates and
matching will stay in TrustZone. `fprintd` is neither added nor enabled while
that backend is missing: showing a fingerprint option in GNOME without being
able to complete it would be a false positive of compatibility.

`scripts/test-el721-type-check.sh` runs that physical test as a single
transaction. It refuses an already-active sensor or `/dev/tee0`, checks the
nine signed segments, and guarantees through `trap` that GPIO91/GPIO155 return
to zero and that QCOMTEE is unloaded even if `TypeCheck` fails. It takes a fifth
argument with the selector passed to the probe and an optional sixth client
environment (`kernel` or a numeric UID). Opening the TEE device remains
privileged; numeric identities are dropped irreversibly before their credential
object is created. It does not enable HBM, request a capture or record
biometric data.
