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
the pogo keyboard all confirmed on the physical hardware. The current
reproducible release is **v0.17**, built from a clean tree.

Evidence level per component, what is still inherited from the postmarketOS
baseline rather than proven under Ubuntu, and the open problems are in
[docs/hardware-status.md](docs/hardware-status.md). A rollback build of the
postmarketOS v1.71 baseline is kept outside Git.

| Component | Status | Notes |
|---|---|---|
| **Display** | ✅ | 2960×1848 at 120 Hz, DSI + DSC + TE, native panel |
| **Desktop** | ✅ | GNOME 46 on Wayland with GDM3, stock Ubuntu packages |
| **GPU** | ✅ | Adreno 740 through Mesa (Freedreno/Turnip); no Android graphics stack |
| **Touchscreen** | ✅ | Goodix Berlin / GT9916, Samsung 16-byte event layout |
| **Buttons** | ✅ | Power and volume; a short press on power suspends |
| **Keyboard cover** | ✅ | Samsung EF-DX920 pogo keyboard |
| **Cover / lid switch** | ✅ | Closing the cover blanks the screen |
| **Wi-Fi** | ✅ | WCN7850 / ath12k, official firmware and the QRD board data |
| **Bluetooth** | ✅ | Controller and A2DP, with the tablet's own address from the Samsung EFS |
| **Speakers / microphones** | ✅ | Four CS35L45 and the digital microphones, natively through PipeWire |
| **Motion sensors** | ✅ | Accelerometer, gyroscope, compass and autorotation via the SSC DSP |
| **Battery** | ✅ | SM5714 telemetry: percentage, voltage, current and pack temperature |
| **Suspend / resume** | ✅ | Deep suspend, validated with the cover |
| **USB host** | ✅ | HID and storage, with and without external power |
| **USB-C DisplayPort** | ✅ | Video output confirmed |
| **Audio/sensor DSPs** | ✅ | ADSP and SSC both reach `running`; prerequisite for audio and sensors |
| **Package management** | ✅ | A stock Ubuntu userspace: `apt`, PPAs and snaps all work |
| **SSH over Wi-Fi** | ✅ | Used for development throughout |
| **Storage** | 🟡 | Root filesystem on microSD; the internal UFS carries only the boot partitions |
| **Backlight** | ❔ | Inherited from postmarketOS, not re-validated here. Automatic brightness works on no distribution |
| **Charging (USB-PD/PPS)** | ❔ | SM5714 TCPM and SM5440; inherited, not re-validated |
| **USB gadget / RNDIS** | ❔ | Inherited, not re-validated |
| **Ethernet (RTL8153)** | ❔ | Enumerates and loads firmware; real link and traffic untested |
| **Waydroid** | ❔ | Never tried |
| **Ambient light** | ❌ | STK31610 is discovered by the SSC but emits no lux |
| **Speaker protection** | ❌ | Cirrus protection firmware not loaded; hardware volume kept conservative |
| **S Pen** | ❌ | Wacom digitiser not brought up |
| **Fingerprint** | ❌ | No mainline driver for the EgisTec sensor |
| **Vibration / haptics** | ❌ | Hardware not identified |
| **Flash / cameras** | ❌ | Not started |
| **Modem** | — | Not applicable to the Wi-Fi-only model |

✅ tested on the physical tablet · 🟡 partially working · ❌ known not to work
or not integrated · ❔ not tested yet · — not applicable

Every ✅ entry was observed on the physical tablet. A driver merely binding is
not considered proof that a subsystem works, and nothing is marked ✅ because it
works under another operating system on the same hardware.

## Installing

Installation has two manual steps, exactly as in the postmarketOS baseline:

1. **Write the image to a microSD.** The owner writes it and verifies the data
   read back before rebooting.
2. **Flash the TWRP ZIP.** It writes `boot`, `init_boot`, `vendor_boot` and
   `dtbo`, checks the ext4 rootfs before mounting it, and applies the
   firmware/configuration overlay onto the card.

The build tooling never writes to a partition or to a card. The exact boot
chain, safe iteration procedure and recovery paths are in
[docs/boot-strategy.md](docs/boot-strategy.md).

### The microSD is the starting point, not the destination

Installing to a card was chosen because it leaves the tablet's own storage
alone: nothing on the internal UFS is written except the boot partitions, so
going back to One UI is an Odin flash and nothing else. That safety is worth a
lot while a port is still moving, but it costs speed and it makes a removable
card a single point of failure.

The intent is to move the root filesystem onto the **internal UFS**, and
ideally to install it **alongside Android rather than instead of it**, so the
tablet can dual boot. Neither is implemented, and neither is promised here;
they are the direction, and the boot chain has been kept deliberately close to
Samsung's so that the move stays possible.

### The pogo keyboard needs one thing after a fresh install

The Book Cover Keyboard talks to an STM32G0 **inside the tablet**, and that
controller runs one of two applications. This port only speaks the V37 one; a
controller left on V34 boots normally, pulses its connection line every two
seconds and never announces itself, so the cover looks broken.

Booting One UI or Ubuntu Touch appears to put it back to V34. The first boot
after an install restores V37 by itself — `ubuntu-gts9u-pogo-firmware.service`,
using Samsung's own hash-pinned blob — as long as the cover is attached and the
battery is at least half full. To check afterwards:

```
grep -o 'flash_version=[0-9]*' /sys/bus/i2c/devices/6-002a/diagnostics
```

`00370037` is healthy. See
[pogo-keyboard.md](packaging/ubuntu-gts9u-device/usr/share/doc/ubuntu-gts9u-device/pogo-keyboard.md).

## Documentation

> The documents below are written in **Spanish**. This README is the only
> English-language document in the repository.

| Document | Contents |
|---|---|
| [docs/hardware-status.md](docs/hardware-status.md) | Current hardware matrix and evidence level per component |
| [docs/ubuntu-userspace.md](docs/ubuntu-userspace.md) | Rootfs construction and Ubuntu-specific decisions |
| [docs/boot-strategy.md](docs/boot-strategy.md) | Boot chain, partitions, installation and recovery |
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
