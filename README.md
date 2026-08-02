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

Ubuntu boots on the tablet. Milestones 1 to 3 are done: the build is
reproducible from source, the system reaches a GNOME desktop on the native
panel, and display, GPU, touch, buttons, Wi-Fi, battery, lid wake, audio, USB
host and DisplayPort have all been confirmed on hardware. The current
reproducible release is **v0.10**.

Bluetooth/A2DP and automatic rotation are also working. The Samsung EF-DX920
pogo controller now boots its official firmware, identifies the attached
keyboard as model `0xd6`, and creates a real Linux input device only while the
cover is connected. Physical `EV_KEY` press/release transitions are now proven;
the driver filters stale DATA IRQs before touching I²C and no longer mistakes
a legitimately held key for a stalled stream. Release v0.10 also runs the
STM32 bus at 100 kHz: three cold boots and a driver reconnect remained stable
after physical key input, without timeout or recovery reset. Normal sustained typing
still needs final confirmation by the owner. A
rollback build of the postmarketOS v1.71 baseline is kept outside Git.

See [docs/hardware-status.md](docs/hardware-status.md) for what is inherited,
what has been proven under Ubuntu, and what is still assumed.

## Hardware support

Nothing below is claimed for Ubuntu until it has been observed on the physical
tablet. The "postmarketOS" column records the validated baseline that this
port is expected to reproduce.

| Component | postmarketOS v1.71 | Ubuntu 24.04 |
|---|---|---|
| Display 2960×1848@120 (DSI + DSC + TE) | ✅ | ✅ |
| GPU Adreno 740 (Mesa/Freedreno/Turnip) | ✅ | ✅ |
| Desktop (GNOME/Wayland) | ✅ | ✅ |
| Touchscreen (Goodix GT9916) | ✅ | ✅ |
| Buttons (power, volume) | ✅ | ✅ |
| microSD rootfs | ✅ | ✅ |
| Wi-Fi (WCN7850 / ath12k) | ✅ | ✅ |
| Speakers (4× CS35L45) and DMIC | ✅ | ✅ |
| Battery telemetry | ✅ | ✅ |
| Suspend / resume, lid wake | ✅ | ✅ |
| USB host | ✅ | ✅ |
| USB-C DisplayPort | ✅ | ✅ |
| Bluetooth + A2DP | ✅ | ✅ |
| USB-PD/PPS charging | 🟡 | ⏳ not tested |
| USB gadget / RNDIS | ✅ | ⏳ not tested |
| Ethernet (RTL8153) / UAS | 🟡 / ❓ | ⏳ not tested |
| Motion sensors and autorotation | ✅ | ✅ |
| Ambient light (STK31610) | ❌ | ❌ |
| Pogo keyboard (EF-DX920) | ❌ | 🟡 keys work; 100 kHz stable across reboots, sustained typing pending |
| S Pen, fingerprint, haptics | ❌ | ❌ |
| Speaker protection DSP | ❌ | ❌ |
| Flash / cameras | ❌ | ❌ |

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
