# Ubuntu 24.04 LTS for Samsung Galaxy Tab S9 Ultra Wi-Fi

Ubuntu 24.04 LTS arm64 for the Samsung Galaxy Tab S9 Ultra Wi-Fi
(`SM-X910`, `gts9uwifi`), running GNOME 46 on Wayland and upstream Linux
7.2-rc3.

The current release is **v0.26**. It installs to the tablet's internal storage
from one TWRP-flashable ZIP; a microSD is not required after installation.

## Hardware compatibility

| Component | Status | Summary |
|---|---:|---|
| Display | ✅ | Native 2960×1848 at 120 Hz |
| Desktop | ✅ | GNOME 46, Wayland and GDM |
| GPU | ✅ | Adreno 740 with Freedreno/Turnip |
| Touchscreen | ✅ | Goodix multitouch |
| S Pen writing | ✅ | Hover, pressure, tilt, side button and palm rejection |
| S Pen dock | ✅ | Insertion, orientation and charging |
| S Pen BLE | ✅ | Pairing, real battery levels, air gestures and pointer mode fully validated |
| Tab Companion | ✅ | S Pen remote modes, behaviour options, haptics and keyboard remapping |
| Keyboard cover | ✅ | EF-DX920 validated; four related Samsung models are recognised but untested |
| Cover switch | ✅ | Closing the cover turns off the display |
| Power and volume buttons | ✅ | Including suspend from the power button |
| Wi-Fi | ✅ | WCN7850 / ath12k |
| Bluetooth | ✅ | Controller, audio and S Pen BLE |
| Speakers and microphones | ✅ | Four speakers and digital microphones |
| Vibration / haptics | ✅ | On-screen keyboard feedback and optional notification vibration |
| Motion sensors | ✅ | Rotation, accelerometer, gyroscope and compass |
| Battery telemetry | ✅ | Charge, voltage, current and temperature |
| USB-PD/PPS charging | ✅ | Up to 25 W measured into the battery |
| Suspend / resume | ✅ | Deep suspend |
| microSD | ✅ | Read and write storage works normally |
| USB host | ✅ | HID and storage, powered or unpowered |
| USB-C DisplayPort | ✅ | External video output |
| Cameras and flash | ✅ | Four cameras, autofocus and flashlight work; colour tuning remains a future improvement |
| Ambient light sensor | ❌ | No usable lux data from the sensor DSP |
| Fingerprint reader | 🟡 | Optical HBM, FOD touch isolation and the signed EL721 TrustZone app are validated; enrolment/login remain unavailable |
| Waydroid | ❓ | Not tested |

✅ working on the physical tablet · 🟡 experimental or partially validated ·
❌ unavailable · ❓ not tested

The evidence and technical limitations for every component are documented in
[hardware-status.md](docs/hardware-status.md).

## Tab Companion

Tab Companion 0.10.8 is preinstalled and provides:

- S Pen battery, charging and dock status;
- automatic dock-initiated BLE pairing, air gestures and an air-pointer mode;
- a switch that disconnects all S Pen remote features while preserving writing;
- finger rejection while the S Pen is hovering;
- optional S Pen digitizer disabling while the pen is docked;
- remapping for compatible Samsung Book Cover Keyboard keys;
- application, command, simulated-key and flashlight actions;
- adjustable vibration feedback for GNOME's on-screen keyboard and optional notification vibration;
- English, Spanish, French, German, Italian and Portuguese interfaces.

The EF-DX920 is physically validated. EF-DX900, EF-DX910, EF-DX915 and
EF-DX925 are recognised but still need tests with the real accessories. See
[tab-companion.md](docs/tab-companion.md) for implementation and diagnostics.

The air-pointer concept is inspired by
[PenMouse S](https://github.com/jojczak/PenMouseS) by Jakub J (`@jojczak`).
Tab Companion uses an independent native Linux implementation.

## Installation

There are two ways to install, and they use the same installation ZIP. The
difference is whether the UFS is split first.

**Ubuntu on the whole tablet.** Nothing else is needed.

1. Copy the installation ZIP to external media, or use `adb sideload`.
2. Boot TWRP.
3. Flash it and wait for its verification to finish.
4. Reboot and complete GNOME's first-run setup.

> [!WARNING]
> On an unsplit tablet the installer writes Ubuntu over Android's `userdata`.
> Android's apps and user data are erased. Back up anything important first.

It must run from external media in this case, because the partition it is
installing into is the one TWRP offers as internal storage — and the installer
refuses to start if it finds itself sitting there.

**Ubuntu beside Android.** Flash the split ZIP first.

1. Flash `gts9u-split-<n>-<m>.zip`, which shortens `userdata` and creates
   `linuxroot` beside it. It writes nothing but those two GPT entries.
2. Reboot to recovery so the kernel rereads the table.
3. TWRP → Wipe → Format Data. Android cannot mount the shortened `userdata`
   until it is recreated, and this is what makes One UI regenerate the
   encryption keys it needs to boot.
4. Flash the installation ZIP. Finding `linuxroot`, it installs there and
   leaves Android's `userdata` alone.

Build the split ZIP with the share of `userdata` Android keeps:

```bash
python3 scripts/make-repartition-zip.py out/gts9u-split-40-60.zip --android-percent 40
```

Switching between the two systems afterwards needs no PC: the `Dualboot` app on
Android and Tab Companion's Dualboot page on Ubuntu each replace the four boot
partitions and restart. See [dual-boot.md](docs/dual-boot.md).

Neither ZIP touches Samsung's bootloader, EFS, calibration or modem-related
partitions, and neither reboots by itself. Full installation, recovery and
boot-chain details are in [boot-strategy.md](docs/boot-strategy.md).

## Documentation

The detailed project documentation is written in Spanish:

| Document | Contents |
|---|---|
| [Hardware status](docs/hardware-status.md) | Evidence, limitations and pending hardware tests |
| [Fingerprint reader](docs/fingerprint-reader.md) | EL721/UDFPS architecture, security model and validation plan |
| [Tab Companion](docs/tab-companion.md) | S Pen and keyboard behaviour, architecture and diagnostics |
| [Boot strategy](docs/boot-strategy.md) | Installation, partitions, boot chain and recovery |
| [Ubuntu userspace](docs/ubuntu-userspace.md) | Root filesystem and desktop integration |
| [Development notes](docs/development-notes.md) | Durable technical conclusions and rejected approaches |
| [Porting log](docs/porting-log.md) | Chronological engineering history |

## Repository layout

```text
kernel/       Device tree, drivers, patches and kernel configuration
packaging/    Debian packages installed in the Ubuntu image
configs/      System configuration and service overlays
scripts/      Reproducible build and validation tools
docs/         Detailed documentation and engineering history
artifacts/    Generated release files; not versioned
```

## Firmware and licensing

Proprietary Samsung and Qualcomm firmware is not stored in Git. Build helpers
stage it from the owner's tablet or official Samsung firmware and verify pinned
checksums.

The project default license is MIT; per-file SPDX headers take precedence.
Kernel code and patches remain GPL-2.0-only, and the device tree remains
BSD-3-Clause. Imported sources are listed in
[kernel/PROVENANCE.md](kernel/PROVENANCE.md).

Contributions must be reproducible in the repository and validated on physical
hardware before a component is marked as working.
