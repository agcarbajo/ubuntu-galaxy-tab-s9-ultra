# SM-X910 hardware status under Ubuntu 24.04

Last updated: 2026-08-19, after validating dual boot against both One UI and
LineageOS.

Ubuntu **boots** on the tablet. This matrix explicitly separates what is
inherited from what has been checked, and no component reaches ✅ without a real
observation.

## Baseline

- Device: Samsung Galaxy Tab S9 Ultra Wi-Fi, SM-X910, `gts9uwifi`.
- SoC: Qualcomm Snapdragon 8 Gen 2, SM8550/kalama; Adreno 740 GPU.
- Kernel: Linux mainline 7.2-rc3, pinned at commit
  `a13c140cc289c0b7b3770bce5b3ad42ab35074aa`.
- Origin of the hardware support: postmarketOS v1.71 (kernel r114, device r44,
  firmware r10).
- Target userspace: Ubuntu 24.04 LTS arm64, systemd, GNOME on Wayland.
- Root filesystem: ext4 on the internal UFS since v0.18 — in `linuxroot` when
  the disk has been split, in `userdata` when it has not. Samsung's ABL loads
  `boot` and `init_boot`, and the DTB/cmdline from `vendor_boot`, off that same
  UFS. Up to v0.17 the root lived on an ext4 microSD.

For the first milestone **the same 7.2-rc3 kernel and the same DTS already
proven** are used. Updating the kernel is postponed until parity is reached:
mixing a distribution change with a kernel jump would make any regression
impossible to attribute.

## Evidence levels

Every row in the matrix carries one of these. "The driver probes" is not
accepted as proof that something works.

| Level | Meaning |
|---|---|
| **measured** | Confirmed in logs or instrumentation of the Ubuntu system itself |
| **observed** | Seen physically by the assistant (an OBS capture) or by the owner |
| **confirmed** | The owner declares it working after a specific test |
| **inherited** | Validated on postmarketOS v1.71, not yet on Ubuntu |
| **assumed** | Neither tested nor validated on any distribution |

## Matrix

| Component | pmOS v1.71 | Ubuntu | Level | Notes |
|---|---|---|---|---|
| Android v4 boot + microSD root | ✅ | ✅ | confirmed | Boots from microSD with `root=LABEL=UBTS9U_ROOT`. Its own legacy-LZ4 initramfs inside `init_boot`. This is the chain up to v0.17 |
| Boot with the root on the UFS | — | ✅ | confirmed | v0.18 writes the root into `userdata` and boots with `root=LABEL=UBTS9U_UFS`. Flashed by sideload and booted on the device on 2026-08-10. Only where the initramfs looks for the root changes; the rest of the chain is the same |
| Dual boot beside Android | — | ✅ | confirmed | Since v1.0.0. `gts9u-split.zip` creates `linuxroot`, the installer goes there, and both systems' boot sets are saved while the ZIP runs. Tested in both directions against One UI and LineageOS |
| Internal display 2960×1848@120 | ✅ | ✅ | measured | The cold-boot recovery is validated under Ubuntu: the journal records `panel id 00 00 00` → a `pm_test=platform` cycle → `80 00 04` |
| Adreno 740 GPU | ✅ | ✅ | measured | Freedreno/Turnip works correctly in games. Minor, sporadic artefacts are seen in some Wayland clients (a Discord/Chromium gradient, and certain GTK controls after repaints). Session 48's investigation produced no generic fix without regressions, so no Mesa, ANGLE, GTK or launcher override is installed |
| GNOME/Wayland desktop | ✅ | ✅ | confirmed | Native GDM3 and GNOME 46, without Alpine's greeter-account workaround |
| Tab Companion | — | ✅ | confirmed | 1.0.0 adds the S Pen dock panel, the flashlight brightness slider, the Dualboot page and its quick-settings toggle. Validated on hardware |
| Brightness / blanking | ✅ | ⏳ | measured | DCS backlight and native manual control. GNOME has `ambient-enabled=true` but cannot do automatic brightness, because neither STK31610 route delivers lux |
| Goodix GT9916 touch | ✅ | ✅ | confirmed | Samsung's 16-byte event layout |
| Power and volume buttons | ✅ | ✅ | confirmed | |
| Internal UFS | ✅ | ✅ | measured | Six LUNs, `sda`–`sdf`. Since v0.18 it also holds the root. Whole-tablet installs reuse `userdata` (`sda34`, 1,007,985,586,176 B) **exactly as it is, creating, deleting and resizing nothing**; split installs add `linuxroot` (entry 35) and only then is the table rewritten, by the split ZIP. On the first boot only the filesystem is resized, with `resize2fs` |
| microSD | ✅ | ✅ | confirmed | Works normally as removable storage on the current UFS installation. Up to v0.17 it also held the `UBTS9U_ROOT` root; those images use a journal and `errors=remount-ro` to tolerate dirty shutdowns |
| WCN7850 Wi-Fi / ath12k | ✅ | ✅ | confirmed | Connected to the network by the owner; SSH in use for development |
| Bluetooth and A2DP | ✅ | ✅ | confirmed | The unit waits for `bluetoothd`, feeds `btmgmt` correctly and reapplies the native address; controller and A2DP validated |
| 4× CS35L45 speakers and DMICs | ✅ | ✅ | confirmed | Native PipeWire, no PulseAudio. Requires the late ADSP start and `protection-domain-mapper` |
| Speaker DSP protection | ❌ | ❌ | assumed | Cirrus firmware not loaded; conservative hardware volume |
| Battery | ✅ | ✅ | confirmed | SM5714: percentage, voltage, current and pack temperature |
| USB-PD/PPS charging | ✅ | ✅ | measured | SM5714 TCPM + SM5440 2:1. **25.2–25.5 W** sustained for five minutes with the EP-T4510, die at 49.5 °C and pack at 36.4 °C. The ceiling was the current requested in the PPS contract, fixed at 3000 mA; swept on hardware, the optimum is 3400 (above that `ibus` rises and the power does not, only the die). Adjustable in `/sys/module/sm5440_direct/parameters/pps_op_curr_ma` |
| Deep suspend | ✅ | ✅ | confirmed | It used to wake about a second after every suspend: the S Pen, charging in its dock, is registered as a power supply and `power_supply_register()` marks those as wakeup sources. A udev rule disables that one wakeup source. Suspend now holds |
| Cover switch | ✅ | ✅ | confirmed | Closing the cover blanks the screen and opening it wakes the tablet. It is **not** a Hall sensor: the Wacom digitizer reports the cover in a `0x0d` notification packet, bit 7 of `0x0a`, and the driver publishes `SW_MACHINE_COVER` and `SW_LID` from it. logind gets a 5 s `HoldoffTimeoutSec` so the lock screen does not swallow the first event after a resume |
| Accelerometer and auto-rotation | ✅ | ✅ | confirmed | SSC exposed to GNOME. `iio-sensor-proxy` no longer spins: libssc's synchronous wait blocks in `poll()` instead of iterating the context without blocking. 1 tick per 2 s against 199, and 48.9 °C against 94.7. The owner confirmed by rotating the tablet that rotation still works after the change |
| LSM6DSO gyroscope | ✅ | ✅ | measured | The same SSC channel. The LSM6DSO hangs off **SPI** (`bus_type=3`, `bus_instance=1`) |
| AK0991x compass | ✅ | ✅ | measured | **On the SSC's I²C, and working**: `bus_instance=2`, 0x0c, `dri_irq_num=89`, real rail `/pmic/client/sensor_vddio`. `monitor-sensor` gives a live heading (127–134°) once claimed. A trap when checking it: the interface is on the `/net/hadess/SensorProxy/Compass` object, not on `/net/hadess/SensorProxy`, and claiming sensors over SSH needs a temporary polkit rule because the session is not "active" |
| CPU frequency scaling | ✅ | ✅ | measured | It had never probed: `qcom-cpufreq-hw` needs its interconnect paths, and `INTERCONNECT_QCOM_OSM_L3` was a module in a port that installs no module tree, so all eight cores ran at a fixed clock with no governor. Built in, `schedutil` takes over |
| USB gadget / RNDIS | ✅ | ⏳ | inherited | |
| USB host, HID and storage | ✅ | ✅ | confirmed | With and without external power |
| USB-C DisplayPort | ✅ | ✅ | confirmed | Video output confirmed by the owner |
| RTL8153 Ethernet | 🟡 | ⏳ | inherited | Enumerates and loads firmware; real link and traffic still missing |
| UAS | ❓ | ❓ | assumed | Never tested: no drive with a UAS interface was available |
| STK31610 ambient light | ❌ | ❌ | measured | Samsung's registry places both chips on I²C `bus_instance` 3 and 4, slave 72 (**0x48**), rails `dummy_vdd`. Those two engines are `i2c_hub_3` (0x98c000) and `i2c_hub_4` (0x990000), which the AP already drives over GPI-DMA: a full `i2cdetect` of both returns **only** 0x63 (SM5440) and 0x18 (MAX77816), and 0x48 NAKs on all 16 AP buses. That closes the AP route — an IIO driver would have nothing to bind to — but proves **nothing** about the chip: the compass, which does work, is equally invisible to the AP. **The sensor is there**: pointing the registry at a bus with no chip makes the DSP refuse to publish the SUID (`Unable to initialize light sensor: UNKNOWN`), while on buses 3 and 4 it publishes it and accepts the enable with `SUCCESS`. It probes, identifies itself, and emits not one sample: the boundary is *streaming*, inside Samsung's signed ADSP blob. `ssc-light` is not offered, so GNOME is not blocked |
| Proximity | — | — | — | The X910's stock SSC firmware does not instantiate the sensor |
| S Pen: writing (Wacom I²C 0x56) | ❌ | ✅ | confirmed | Our own driver: hover with distance, pressure 0–4095, tilt ±63 and the side button. Automatic attach, ~440 Hz and correct rotation in all four orientations. Leaving range is also synthesised from silence (a 250 ms timer): without it the controller went quiet when the pen was moved away and `BTN_TOOL_PEN` stayed at 1 until reboot |
| S Pen: docking and orientation | ❌ | ✅ | confirmed | The driver claims TLMM GPIO137 (`PDCT`), publishes `SW_PEN_INSERTED` and sysfs attributes. The owner confirmed removal/reinsertion and both orientations. The Wacom IRQ stays live to refresh the direction even when coordinates are filtered with the pen docked |
| S Pen: battery and charging | ❌ | ✅ | measured | On docking, the kernel automatically sends enable/start/keep-on. The dock delivers a discrete state and the Samsung GATT delivers a real percentage: 100 %, 90 % and 80 % were measured across different connection/charge cycles |
| S Pen: BLE pairing | ❌ | ✅ | confirmed | The Wacom command 0xea opens the advertisement on docking. The service accepted the pen-initiated authorisation and confirmed `Bonded`, `Paired`, `Trusted` with no interaction. Docked it always uses Mode `0x10`. Tab Companion validates the real GATT, discards cached percentages and automatically replaces an unusable bond. Post-reboot recovery is bounded to two 12 s attempts. Since 0.10.8, switching Bluetooth off suspends the remote features without modifying the preference, and the `Powered` signal restores them immediately when it comes back |
| S Pen: gestures and pointer | ❌ | ✅ | measured | The BLE single/double/long gestures and the six movements are confirmed. The pointer enables the raw sensor at ~24 Hz, discards the lengthwise X roll and projects gyro Y/Z with gravity to compensate for the pen's roll. After the visual test both axes were inverted and X uses a 1.6× gain. In Pointer mode, `BTN_STYLUS` produces a held `BTN_LEFT` for click and drag, with a safety release. One capture produced 621 `REL_X/REL_Y` events |
| Touch: an area that only answers the pen | — | ❌ | **open** | Intermittent. A region stops accepting new finger touches; a drag started outside does cross it. The S Pen's stuck proximity flag was ruled out as a sufficient explanation: with the flag pinned and verified, there was no dead zone. Undiagnosed; `work/catch-dead-zone.sh` decides whether the touches reach the kernel |
| EF-DX920 pogo keyboard (STM32 I²C 0x2a) | ❌ | ✅ | confirmed | Requires V37 on the MCU. Measured: Galaxy AI 760, DeX 701, Finder 710, Settings 709, and Fn+F1–F11: 757, 758, 759, 705, 254, 172, 224, 225, 113, 114 and 115. Fn+F12 produces no raw event. Tab Companion keeps Fn+F6–F11's home/brightness/volume by default and can restore every value |
| Other EF-DX900/910/915/925 covers | ❌ | 🟡 | measured | The X910's official DTS declares all five models. The driver already tells the identifiers and VERSION apart, and the app publishes name/model and adapts the AI row. Only the DX920 is available: enumeration, special keys and touchpads of the other four still await real hardware |
| Fingerprint: EL721/UDFPS infrastructure | ❌ | 🟡 | partial | QTEE 5.2.0, UID 122, FlatZ HBM, watchdog, the GNOME indicator and the Goodix-FOD events/suppression are physically validated. TrustZone accepts and cleanly unloads the signed 19.9 MB `dualfp` TA through shared memory; the late GPIO91/GPIO155 power and the BAUTH protocol still need validating. The DDIC circle does not draw without Self Display and is not used; details in [fingerprint-reader.md](fingerprint-reader.md) |
| Fingerprint: enrolment, verification and GDM | ❌ | ❌ | assumed | There is still no secure backend for `libfprint`/`fprintd`. Biometric authentication is not offered until enrolment, verification, cancellation, lockout and GDM are validated end to end |
| Haptics | ❌ | ✅ | confirmed | The stock DTS identifies a `dc_vibrator` COINDC on TLMM GPIO18 and mainline publishes it as `gpio-vibrator`/`FF_RUMBLE`. The owner confirmed the motor and the on-screen keyboard; Tab Companion offers 24/42/66 ms pulses. Notifications vibrate optionally, and a real test measured GPIO554 active for 64.5 ms |
| Flash / torch | ❌ | ✅ | observed | PM8550 SID 1, channels 0+1 grouped by `leds-qcom-flash`; real illumination observed in strobe and torch modes. The **Flashlight** quick-settings tile is installed, active and physically tested, with a brightness submenu and state shared with the shortcut actions |
| Cameras | ❌ | 🟡 | observed | All four sensors take pictures and go through `libcamera` simple plus the software ISP, appearing as exactly four normal, named V4L2 cameras. GNOME Camera, Chrome WebRTC and OBS opened and switched between all four with changing video, including after a cold boot; the main rear focuses with its DW9808. Switching between sensors is closed. Factory calibration and automatic photographic flash remain open |
| Modem | — | — | — | Not applicable to the Wi-Fi model |

### Cameras and flash: the exact scope of the validation

Enumeration was not taken as proof. Each physical link was configured
separately towards `msm_csid0` → `msm_vfe0_rdi0` → `/dev/video0` and a full
frame was saved. The observed relationship is:

| Lens | Sensor / subdevice | CSIPHY | Captured format |
|---|---|---|---|
| main rear | HI1337 `1-0021`, `/dev/v4l-subdev32` | `msm_csiphy1` | 4128×3096 RAW10, 16,000,128 bytes |
| wide rear | HI847 `0-0021`, `/dev/v4l-subdev34` | `msm_csiphy2` | 3264×2448 RAW10, 9,987,840 bytes |
| main front | HI1337 `3-0020`, `/dev/v4l-subdev31` | `msm_csiphy4` | 3408×2556 RAW10, 10,919,232 bytes |
| wide front | HI1337 `9-0021`, `/dev/v4l-subdev30` | `msm_csiphy5` | 4000×3000 RAW10, 15,024,000 bytes |

`/dev/video0` is the common capture node: on its own it identifies no lens; the
sensor is chosen by changing the media graph's links and formats. On top of
that layer, `libcamera` 0.7.2 is packaged with the `simple` pipeline, the
software ISP and HI1337/HI847 gain helpers. The tuning applies a RAW10
pedestal, AE, grey-world AWB and a conservative colour matrix. After 150
convergence frames, all four RGB outputs showed usable exposure and whites and
greys free of the magenta cast of the initial conversion:

- [wide front](../work/resultado-frontal-angular.jpg);
- [main front](../work/resultado-frontal-principal.jpg);
- [main rear](../work/resultado-trasera-principal.jpg);
- [wide rear](../work/resultado-trasera-angular.jpg).

The ISP's scaling now preserves the sensor's full rectangle: it uses a centred
*contain* fit with black padding when the requested ratio does not match,
instead of cropping the sides to fill the output. The base V4L2 interface is
1280×960 (4:3); a client wanting 16:9 can apply its own crop-and-scale
afterwards. The main rear still has a naturally narrower optical field than the
ultra-wides.

The main rear links the DW9808 actuator `2-000c` as the HI1337's lens. The
driver exposes `focus_absolute` 0–1023, and the software IPA does a coarse
contrast sweep and then a fine one before holding the best position. Under
continuous light, the text on a banknote was legible in both GNOME Camera and
OBS.

`/dev/udmabuf` is handed to `video` through udev. PipeWire keeps the four
libcamera sources and four `v4l2-relayd` processes connect them on demand to
`/dev/video20`–`23`, created by a patched, signed `v4l2loopback` built against
the exact kernel. The cameras are named `GTS9U-Front-Ultra-Wide`,
`GTS9U-Front-Main`, `GTS9U-Rear-Main` and `GTS9U-Rear-Ultra-Wide`; they need no
scenes and no per-user configuration.

The four sensors share CAMSS/ISP, so the relays serialise their inputs. If an
application opens the new camera before closing the previous one, the new relay
asks to pre-empt the current owner and waits for libcamera to have released
CAMSS. The media links are reset before each configuration, and
`v4l2loopback`'s output queue survives the consumer's negotiation. The lock's
owner is rewritten from offset zero: without that detail the file accumulated
NUL gaps and the next relay could not discover whom to signal, leaving a black
or frozen image.

The relays used to cost 2.4 cores at idle, with the four GStreamer pipelines
running a full-resolution conversion whether or not anyone was watching. Their
caps are now 640×480 and the splash is converted once and frozen: 32 % → 2.5 %
CPU, and about 58 °C → 40 °C, with the four cameras still available.

Chrome enumerated only those four cameras and opened each at 1280×720 through
WebRTC. Three consecutive rounds required more than a second of media time and
changing pixels between samples two seconds apart; all twelve openings passed.
After another cold boot the first consumer repeated 4/4 with 2.030–2.034 s and
98.76–100 % changing pixels in the available scene. The standard V4L2 selector
of a completely empty OBS profile showed the same four and captured each of
`/dev/video20`–`23`. Two captures three seconds apart per camera changed
between 20.04 % and 31.12 % of the preview's pixels, so they were not cached
images. The packaged plugin hides only the internal `Qualcomm Camera Subsystem`
RAW endpoints and fixes the case where the `by-id`/`by-path` directories do not
exist, which used to end in `SIGSEGV`.

Discord in Chrome also enumerates the four correct V4L2 identifiers. Its
preview selector, as observed, internally keeps the default `/dev/video20`
stream even when the label changes to a rear one; that same Chrome immediately
opens those rear cameras by their exact `deviceId` in WebRTC. This is recorded
as behaviour of that Discord interface, not as an alias or a camera missing
from the system; no userscript or per-profile configuration is installed to
paper over it.

Real boots end with four nodes, four relays and the four PipeWire sources
usable before a graphical login. The owner's account keeps its systemd manager
through lingering; its name and UID are resolved on every boot and written into
a drop-in under `/run`, never into the packaged unit. The service watches
PipeWire's real PID: if it changes, it destroys and recreates the whole set of
relays rather than leaving active V4L2 nodes that only deliver black.

The post-reboot captures showed balanced channels on both front cameras and a
moderate green cast on neutral surfaces lit by the rear flash. The rear scene
was dominated by red and brown objects, so grey-world AWB can skew; no global
matrix was applied, as it would have degraded other lighting. Factory
calibration stays open until a neutral and colour chart is measured under
several controlled illuminations.

The flash was verified on both of its hardware routes. The strobe was armed
through the V4L2 flash class and fired during one capture; the torch kept both
channels on during another. Both images show reflections and lighting absent
from the capture without light.

For daily use, GNOME loads the `flashlight@ubuntu-gts9u` system extension and
shows **Flashlight** in quick settings (`Super+S`). The tile uses continuous
light at a conservative 128/255, reflects the LED's real state and switches it
off when disabled. `gts9u-flashlight on|off|toggle|status` is also available
and needs no `sudo`. Udev grants the `video` group write access to `brightness`
only: strobe, timeout and faults remain `root` controls. A suspend hook forces
level zero so the LED cannot be left on inside a cover.

After a reboot caused by a stuck media session, 120 frames of RAW video, 60
encoded/decoded VP9 frames and 30 frames from each of the four PipeWire sources
were repeated. Later validations with GNOME Camera and OBS confirmed
orientation on all four: the monitor upright on the front cameras and the
banknote upright on both rear ones. The main rear additionally showed
close-range detail once autofocus converged.

## Ubuntu's risks: how they turned out

The five risks anticipated before the first boot, with what actually happened.

1. **UCM — resolved.** The X910's own profile coexists with Ubuntu's
   `alsa-ucm-conf` without conflict; it installs into `conf.d/sm8550/` and
   `Qualcomm/sm8550/GTS9U/` and takes priority.
2. **PipeWire against PulseAudio — resolved in PipeWire's favour.** PulseAudio
   was not needed: native PipeWire exposes the four CS35L45s and the DMICs. The
   boot orders the panel recovery before the ADSP and refreshes WirePlumber
   when `controlC0` appears; two consecutive reboots left `HiFi`, speaker and
   microphone active, with 351,781 and 351,547 non-zero samples.
3. **`initramfs-tools` — resolved, with work.** It meets the three hard
   requirements, but only after forcing `COMPRESS=lz4`, correcting `MODULES`
   and pruning udev's database to fit in `init_boot`.
4. **AppArmor — never showed up.** The panel recovery and ADSP start services
   write to `/sys/power` and to `remoteproc` with no profile blocking them.
   AppArmor has not been touched.
5. **Sensors — confirmed as the anticipated gap, and resolved.** `pd-mapper`
   does exist in Ubuntu (`protection-domain-mapper`), but `libssc` and
   `hexagonrpcd` do not. Packaging them was necessary but not sufficient: three
   more fixes were needed, all in the repository and none specific to Ubuntu.
   See "Auto-rotation: the four obstacles" in the porting log.

### Measured support: the EF-DX920 keyboard cover

v0.9 reproduces Samsung's state machine: QUPv3 SE15, VDDO, SE4's MAX77816, both
IRQs and entering/leaving the ROM bootloader. The STM32 moved from the old
application `00 34 00 34` to the X910's official image `00 37 00 37`; its
52,132 bytes were read back and compared before starting it. Without the extra
reset after VDDO — which the stock does not do — the controller announces model
`0xd6` and Linux registers `Book Cover Keyboard Slim (EF-DX920)`. The device
only exists while the real model is present, so GNOME does not lose
auto-rotation to a phantom keyboard. The stock application phase also answers
with version, mode, CRC and the expected absence of a touchpad. The right
sequence — read VERSION inside the IRQ and defer the rest by 10 ms — unblocked
the keystrokes: `evtest` measured real presses and releases.

That first success at 400 kHz did not survive the next reboot: under typing,
dozens of GPIO62s appeared, along with NACK `-6`, timeouts and `event3` being
recreated. Forcing SE15's runtime PM to `on` did not change the pattern, so
autosuspend was ruled out. The timing difference showed transactions and
retries of ~230–250 ms on the bad boot. Reducing only SE15's
`clock-frequency` to 100 kHz removed the idle storm across three consecutive
boots and after a driver rebind, but did not survive sustained typing: the
owner saw stuck keys again and the journal accumulated `-110`, NACKs, resets
and GPIO62 pulses. The frequency stands as an idle improvement, not as the root
cause.

Moving GPIO75's logical read from the thread into the hard IRQ did produce a
significant stable window: 2,046 transitions over more than eight hours,
`keys_down=0` and correct physical reconnection. A first reboot took another 61
transitions. The reboot after that, however, brought stuck keys back and
stopped input with the same `boot`, `vendor_boot` and DT frequency. That test
therefore proves no definitive root cause: what changes is the STM32/keyboard's
cold state or the transport's timing phase, not the images.

The later investigation changed the conclusion. A complete, strictly read-only
dump of the STM32's 64 KiB gave SHA-256
`8937281d2efa08400390f9a2b02e40ca914b634e646d6dd544980c38464533ef`, contains
`00 34 00 34` at `0x200`, and contains no copy of V37. It is a coherent ARM
image and its strings explicitly identify `TabS9(STM32G0) Series -> V34`; V34 is
therefore neither a marginal read nor evidence of corruption.

From that it was inferred that One UI used V34 and that the gap was in our cold
initialisation. **That was a leap**: the image being valid says nothing about
who put it there. The project's only blob — the X910's official one, the same
pmOS packages — is V37, and it is what session 8 programmed to get the first
real keystrokes. The MCU had gone back to V34 on its own.

Reprogramming it to V37 with the driver's own updater restored the keyboard
instantly and survived a cold boot: `0xd6` at 4.5 s, application initialisation
at 7.6 s, real typing by the owner and correct physical reconnection of the
cover. **What** returned the MCU to V34 has still not been measured; the most
likely candidate is Samsung's `stm32_pogo_v3.ko` under One UI or Ubuntu Touch,
so booting those systems may degrade it again. Recovery is one command:

```
sudo env GTS9U_ALLOW_POGO_FLASH=YES \
  /usr/libexec/ubuntu-gts9u-pogo-firmware-update
```

The ROM command `GO 0x08000000` was also tried without writing flash, first
alone and then with VDDO/MAX77816 active and 100 ms of settling. The bootloader
accepted both jumps, but the application still did not raise DATA or announce
`0xd6`; GPIO62 kept pulsing every ~2.126 s. That was the V34 application, which
the mainline driver does not know how to talk to. The final source went back
exactly to the driver of the last known good state (`504ff29`). Automatic
writes to the accessory remain blocked: they require the explicit
`GTS9U_ALLOW_POGO_FLASH=YES` guard and the service stays masked, so no MCU
programming happens during boot.

## Inherited invariants that cannot be broken

- Critical providers **built in**; only ath12k/ath12k_wifi7 as isolated signed
  modules, and always from the same build as `boot`.
- Changing the DTS means rewriting `vendor_boot`.
- Do not re-enable `lpass_ag_noc`: it caused hangs, and audio works without it.
- Keep the DisplayPort HPD deferred until after the panel's cold-boot recovery.
- Wi-Fi with the official firmware and the QRD BDF **with** its ELF wrapper.
  Samsung's HMT.2.0 BDF crashes the HMT.1.1 amss and must be neither mixed nor
  stripped of its ELF.
- Do not add improvised MMIO/ioremap reads to diagnose probes.
- Never write the PIT, EFS, persist, modem/modemst or the calibration
  partitions.
