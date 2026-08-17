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

Both ways use the same installation ZIP. The only difference is whether you
split the UFS first.

> [!WARNING]
> Either way, **everything Android keeps in `userdata` is erased**: its apps,
> its settings and its files. Android's system itself is not touched. Back up
> anything you want to keep first.

### Ubuntu on the whole tablet

1. Copy the installation ZIP to a microSD or a USB-OTG drive.
2. Boot TWRP.
3. Flash it.
4. Reboot and complete GNOME's first-run setup.

It has to come from external media here, because Ubuntu is being written into
the very partition TWRP offers as internal storage. The installer checks, and
refuses to start if it finds itself sitting on it.

### Ubuntu beside Android

1. Flash `gts9u-split-50-50.zip`. It shortens `userdata`, creates `linuxroot`
   beside it, and recreates Android's data so One UI can make fresh encryption
   keys on its next boot.
2. Flash the installation ZIP. Finding `linuxroot`, it installs there and
   leaves Android's own `userdata` alone.
3. Reboot and complete GNOME's first-run setup.

Here the ZIPs may sit on internal storage, because the partition being written
is not the one they are on.

The released ZIP splits it in half. The number in it is the share of `userdata`
Android keeps, so any other split is one command away — build your own and flash
that instead:

```bash
# 30 % Android, 70 % Ubuntu
python3 scripts/make-repartition-zip.py out/gts9u-split-30-70.zip --android-percent 30
```

Anything from 5 to 95 is accepted, and the installer on the tablet checks the
same bounds.

Flashing it on a tablet that is already split does nothing and says so, so
there is no harm in running it twice.

### Switching systems

No PC needed. The **Dualboot** app on Android and Tab Companion's Dualboot page
on Ubuntu each replace the four boot partitions and restart, and both offer a
quick-settings toggle. Switching takes seconds and cannot lose data: nothing is
moved, resized or reformatted. See [dual-boot.md](docs/dual-boot.md).

Neither ZIP touches Samsung's bootloader, EFS, calibration or modem-related
partitions, neither touches `super`, and neither reboots by itself. Full
installation, recovery and boot-chain details are in
[boot-strategy.md](docs/boot-strategy.md).

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
