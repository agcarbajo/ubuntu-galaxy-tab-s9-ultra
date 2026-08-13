# Ubuntu 24.04 LTS for the Samsung Galaxy Tab S9 Ultra Wi-Fi

An **Ubuntu 24.04 LTS arm64** userspace on the Samsung Galaxy Tab S9 Ultra
Wi-Fi (**SM-X910**, codename `gts9uwifi`, Qualcomm Snapdragon 8 Gen 2 / SM8550
"kalama"), running upstream Linux **7.2-rc3**.

This is not a bring-up from scratch. The hardware enablement — device tree,
panel driver, charging, USB-C/DisplayPort, Wi-Fi and audio — is inherited from
the physically validated
[postmarketOS port](https://github.com/agcarbajo/postmarketos-galaxy-tab-s9-ultra)
baseline v1.71. The goal here is to keep that hardware parity while replacing
the Alpine userspace with Ubuntu, so that standard Debian/Ubuntu desktop
software, and later Vulkan/Turnip-based gaming stacks, become usable.

## Status

Ubuntu boots and is usable as a desktop tablet: GNOME on the native panel, with
display, GPU, touch, audio, Wi-Fi, Bluetooth, sensors, USB host, DisplayPort and
the pogo keyboard all confirmed on the physical hardware. The current release is
**v0.18**: it installs to the tablet's own internal storage as a single
flashable ZIP, and it has been flashed and booted from there on the tablet. A
microSD is no longer part of the system.

Evidence level per component, what is still inherited from the postmarketOS
baseline rather than proven under Ubuntu, and the open problems are in
[docs/hardware-status.md](docs/hardware-status.md). A rollback build of the
postmarketOS v1.71 baseline is kept outside Git.

| Component | Status | Notes |
|---|---|---|
| **Display** | ✅ | 2960×1848 at 120 Hz, DSI + DSC + TE, native panel |
| **Desktop** | ✅ | GNOME 46 on Wayland with GDM3, stock Ubuntu packages |
| **Tab Companion** | 🟡 | Native GTK4/libadwaita settings app, packaged and preinstalled. Version 0.7 adds a graphical action/app/command chooser, reset-to-default, remembered disconnected keyboards, a battery bar and complete English, Spanish, French, German, Italian and Portuguese UI. Its tested `uinput` engine preserves ordinary keys and replaces only configured mappings |
| **GPU** | ✅ | Adreno 740 through Mesa (Freedreno/Turnip); no Android graphics stack |
| **Touchscreen** | ✅ | Goodix Berlin / GT9916, Samsung 16-byte event layout |
| **Buttons** | ✅ | Power and volume; a short press on power suspends |
| **Keyboard cover** | ✅ | Samsung EF-DX920 pogo keyboard physically validated; EF-DX900, EF-DX910, EF-DX915 and EF-DX925 identification is integrated from Samsung's X910 model table but awaits each physical cover. The tablet's STM32 is repaired automatically if another OS downgrades it ([details](packaging/ubuntu-gts9u-device/usr/share/doc/ubuntu-gts9u-device/pogo-keyboard.md)) |
| **Cover / lid switch** | ✅ | Closing the cover blanks the screen |
| **S Pen (writing)** | ✅ | Wacom EMR digitiser: hover, pressure, tilt and the side button, with this port's own driver |
| **Wi-Fi** | ✅ | WCN7850 / ath12k, official firmware and the QRD board data |
| **Bluetooth** | ✅ | Controller and A2DP, with the tablet's own address from the Samsung EFS |
| **Speakers / microphones** | ✅ | Four CS35L45 and the digital microphones, natively through PipeWire |
| **Motion sensors** | ✅ | Accelerometer, gyroscope, compass and autorotation via the SSC DSP, at idle CPU cost. Compass re-measured under Ubuntu: `HasCompass=true` and a live heading tracking 127–134° |
| **Battery** | ✅ | SM5714 telemetry: percentage, voltage, current and pack temperature |
| **Charging (USB-PD/PPS)** | ✅ | 25 W into the pack over PPS with the SM5440 2:1 pump, sustained and thermally flat |
| **Suspend / resume** | ✅ | Deep suspend, validated with the cover |
| **USB host** | ✅ | HID and storage, with and without external power |
| **USB-C DisplayPort** | ✅ | Video output confirmed |
| **Audio/sensor DSPs** | ✅ | ADSP and SSC both reach `running`; prerequisite for audio and sensors |
| **Package management** | ✅ | A stock Ubuntu userspace: `apt`, PPAs and snaps all work |
| **SSH over Wi-Fi** | ✅ | Used for development throughout |
| **Storage** | ✅ | Root filesystem on the internal UFS, in the partition Android used for user data: no microSD needed and no partition table change. Flashed and booted from there |
| **Swap** | ✅ | Two tiers, 23 GiB total: 8 GiB of zstd-compressed zram in front of a 16 GiB swapfile on the UFS. Measured 4.5× compression, and 11 GiB allocated with no OOM kill |
| **Backlight** | ❔ | Inherited from postmarketOS, not re-validated here. Automatic brightness works on no distribution |
| **USB gadget / RNDIS** | ❔ | Inherited, not re-validated |
| **Ethernet (RTL8153)** | ❔ | Enumerates and loads firmware; real link and traffic untested |
| **Waydroid** | ❔ | Never tried |
| **S Pen docking** | ✅ | GPIO137 and `SW_PEN_INSERTED` report removal/reinsertion; both physical orientations are confirmed and exposed by Tab Companion |
| **S Pen battery / charging** | 🟡 | Automatic dock charging and discrete state work. The identified Samsung BLE Battery characteristic returned the real 100 % level while connected; an intermediate physical level is still pending |
| **S Pen pairing (BLE)** | 🟡 | The bundled pen is bonded and trusted. A restricted system service reproduces One UI's dock-initiated authorization flow and never accepts an arbitrary Bluetooth device. A clean boot preserves the bond. Forced docked disconnection was physically rejected: the removed pen does not advertise, so insertion remains the reliable wake/reconnect trigger |
| **S Pen gestures** | 🟡 | Single, double and long side-button presses work through EMR. Over BLE, all six air gestures were captured and classified on the physical pen: up, down, left, right, clockwise and counterclockwise. Each runs its Tab Companion mapping; visible per-action UI checks remain open |
| **Ambient light / automatic brightness** | ❌ | 0x48 answers on no AP-reachable bus, so a mainline IIO driver has nothing to bind to. That is a limit on the AP route only: the working compass is equally invisible to the AP, because SSC sensors hang off the DSP's own I²C. The ALS remains an SSC-side failure — it enumerates and accepts its enable but never emits lux. GNOME's support is ready and the unusable ALS is deliberately not exposed |
| **Speaker protection** | ❌ | Cirrus protection firmware not loaded; hardware volume kept conservative |
| **Fingerprint** | ❌ | No mainline driver for the EgisTec sensor |
| **Vibration / haptics** | ❌ | Hardware not identified |
| **Flash / cameras** | 🟡 | All four sensors take pictures, and the flash works. They are processed by a tuned libcamera software ISP and exposed as exactly four named, ordinary V4L2 cameras, so GNOME Camera and Chrome WebRTC can switch through all four without per-user scenes. Repeated browser and OBS tests verified advancing video rather than a cached frame, including after a cold reboot; OBS was the verification tool and is no longer shipped in the image. The software ISP preserves each sensor's full field of view, and the rear-main DW9808 has validated continuous autofocus. A native **Flashlight** tile controls continuous light without root. Automatic exposure-synchronised photo flash and factory colour calibration remain open |
| **Modem** | — | Not applicable to the Wi-Fi-only model |

✅ tested on the physical tablet · 🟡 partially working · ❌ known not to work
or not integrated · ❔ not tested yet · — not applicable

Every ✅ entry was observed on the physical tablet. A driver merely binding is
not considered proof that a subsystem works, and nothing is marked ✅ because it
works under another operating system on the same hardware.

## Installing

Installation is **one flashable ZIP**. Copy it to a microSD or a USB-OTG
drive, boot TWRP, and flash it. There is no image to write to a card by hand
any more, and no second step.

The ZIP writes `boot`, `init_boot`, `vendor_boot` and `dtbo`, and copies the
Ubuntu root filesystem into the tablet's internal UFS. It reads the root
filesystem back and compares its SHA-256 before writing anything else, it does
not reboot, and on any failure it stops with TWRP still running. The exact
boot chain, the installation procedure step by step and the recovery paths are
in [docs/boot-strategy.md](docs/boot-strategy.md).

Flash it **from external media** — `adb sideload` is the simplest. The
installer refuses to run from the tablet's internal storage, because that is
the partition it is about to overwrite.

The image ships **without a user account**. On the first boot GNOME's setup
wizard asks for a name, a password, the language, the keyboard layout and the
time zone, the way any Ubuntu install does. Nothing in the image is named after
a user, and building a release needs no password and no secret of any kind.

### Installing to the UFS without repartitioning

Ubuntu's root filesystem goes into the partition Android calls `userdata`,
which on the SM-X910 is 939 GiB. It is written there as a plain ext4 image and
grown to the whole partition on first boot.

The partition table is never touched. Nothing in the build tooling or in the
installer creates, deletes, moves or resizes a partition, and neither one runs
`mkfs`, `parted` or `sgdisk` against the tablet — `dd` into partitions that
already exist is the only write there is. `super`, the bootloader chain, EFS,
persist, modem and the calibration partitions are all left alone, so restoring
One UI is still an Odin flash of the official firmware and nothing else.

What this **does** replace is everything Android kept in `userdata`. Android's
system image survives in `super`, but its user data does not; there is no
partition left over for it, and this is not a dual boot.

Installing to a microSD is what the port did up to v0.17, and those releases
still work: their root filesystem carries the label `UBTS9U_ROOT`, while a UFS
install carries `UBTS9U_UFS`, so a card left in the slot cannot be mistaken for
the internal install by either one.

The remaining direction is to install **alongside Android rather than instead
of it**, so the tablet can dual boot. That is not implemented and is not
promised here; the boot chain is kept deliberately close to Samsung's so that
it stays possible.

## Documentation

> The documents below are written in **Spanish**. This README is the only
> English-language document in the repository.

| Document | Contents |
|---|---|
| [docs/hardware-status.md](docs/hardware-status.md) | Current hardware matrix and evidence level per component |
| [docs/ubuntu-userspace.md](docs/ubuntu-userspace.md) | Rootfs construction and Ubuntu-specific decisions |
| [docs/boot-strategy.md](docs/boot-strategy.md) | Boot chain, partitions, installation and recovery |
| [docs/tab-companion.md](docs/tab-companion.md) | Tab Companion architecture, usage and the remaining hands-on validation checklist |
| [docs/development-notes.md](docs/development-notes.md) | Durable conclusions and the "do not retry" inventory |
| [docs/porting-log.md](docs/porting-log.md) | Chronological engineering log, including failures |

## Layout

```text
├── kernel/       Imported DTS, drivers, patches and kernel config
├── packaging/    Debian packaging for the device support packages
├── configs/      Audio, Bluetooth, display, sensors, USB and systemd overlays
├── scripts/      Reproducible rootfs, image, bundle and validation tooling
├── docs/         Reference documentation and chronological history
├── artifacts/    Generated output only; intentionally not versioned
└── work/         Disposable local scratch space
```

## Firmware

This repository contains **no proprietary firmware**. Samsung and Qualcomm
blobs — Wi-Fi, Bluetooth, GPU, ADSP, CS35L45, audio topology and the STM32
keyboard application — are staged
from the owner's device or from the official Samsung firmware package by the
`scripts/stage-stock-*.sh` helpers, which verify pinned checksums. Generated
images and ZIP files are ignored by Git.

## Licensing

The project default is **MIT** (see [LICENSE](LICENSE)), except where a file's
SPDX header states otherwise; that per-file header always takes precedence.
Kernel drivers and patches remain `GPL-2.0-only` and the device tree remains
`BSD-3-Clause`. Imported files record their origin in
[kernel/PROVENANCE.md](kernel/PROVENANCE.md).

## Contributing

Two project rules carry over from the postmarketOS port:

- **No live-only fixes:** every change belongs in a reproducible DTS, config,
  package or script.
- **Verify on hardware:** a successful probe is not a functional test.
