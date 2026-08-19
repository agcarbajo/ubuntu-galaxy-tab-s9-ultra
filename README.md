# Ubuntu 24.04 LTS for Samsung Galaxy Tab S9 Ultra Wi-Fi

Ubuntu 24.04 LTS arm64 for the Samsung Galaxy Tab S9 Ultra Wi-Fi
(`SM-X910`, `gts9uwifi`), running GNOME 46 on Wayland and upstream Linux
7.2-rc3.

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
| Keyboard cover | ✅ | Only EF-DX920 tested, not sure if other models will work |
| Cover switch | ✅ | Closing the cover turns off the display |
| Power and volume buttons | ✅ | Including suspend from the power button |
| Wi-Fi | ✅ | WCN7850 / ath12k |
| Bluetooth | ✅ | Controller, audio and S Pen BLE |
| Speakers and microphones | ✅ | Four speakers and digital microphones |
| Vibration / haptics | ✅ | On-screen keyboard feedback |
| Motion sensors | ✅ | Rotation, accelerometer, gyroscope and compass |
| Battery telemetry | ✅ | Charge, voltage, current and temperature |
| USB-PD/PPS charging | ✅ | Up to 25 W measured into the battery |
| Suspend / resume | ✅ | Deep suspend |
| microSD | ✅ | Read and write storage works normally |
| USB host | ✅ | HID and storage, powered or unpowered |
| USB-C DisplayPort | ✅ | External video output |
| Cameras and flash | ✅ | Four cameras, autofocus and flashlight work; colour tuning remains a future improvement |
| Ambient light sensor | ❌ | Currently not working |
| Fingerprint reader | 🟡 | Work in progress |
| Waydroid | ❓ | Not tested |

✅ working on the physical tablet · 🟡 experimental or partially validated ·
❌ unavailable · ❓ not tested

The evidence and technical limitations for every component are documented in
[hardware-status.md](docs/hardware-status.md).

## Tab Companion

Tab Companion 1.0.0 is preinstalled and provides:

- full S Pen settings (pairing, gestures and air-pointer mouse mode);
- remapping for compatible Samsung Book Cover Keyboard keys;
- adjustable vibration feedback for GNOME's on-screen keyboard and optional notification vibration;
- dualboot to Android with an optional toggle on quick settings

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

### Before you start

1. **An unlocked bootloader.**
2. **ROOT with magisk** (only if you want dualboot).
3. Get `ubuntu-24.04-gts9uwifi-vX.X.X-sm-x910-twrp.zip` from the [latest release](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/releases/latest). `gts9u-split.zip` and `Dualboot-vX.X.X.apk` only if you want dualboot.
4. **[TWRP](https://github.com/rainbowdashh/android_device_samsung_gts9u/releases/tag/V2)** and **a `vbmeta` with AVB verification disabled** ([the one published alongside TWRP](https://xdaforums.com/attachments/vbmeta-1-tar.6077784/)). Flash both files in AP using Odin or Heimdall (you will need to reboot again to download mode between flashes).
5. After flashing both files from step 4 reboot to TWRP. **Don't let One UI boot** or TWRP will be overwritten with the stock recovery and you will need to flash the files again.

### Ubuntu on the whole tablet

1. From TWRP just flash the installation ZIP (`ubuntu-24.04-gts9uwifi-v1.0.0-sm-x910-twrp.zip`) using a microSD, external USB storage or sideload. **Don't flash it from internal storage** as it will get wiped.
2. Reboot and enjoy!

### Ubuntu beside Android

> [!IMPORTANT]
> Default split is 50% of the storage for Android and 50% for Linux. If you want to modify it just change the value of `ANDROID-PERCENT` inside `gts9u-split.zip` to the percentage you want Android to keep (between 5% and 95%).

1. Flash `gts9u-split.zip`. It shortens `userdata`, creates `linuxroot`
   beside it, and recreates Android's data so Android can make fresh encryption
   keys on its next boot.
2. Reboot TWRP (reboot > recovery).
3. Wipe > Format Data.
4. Flash the installation ZIP (`ubuntu-24.04-gts9uwifi-v1.0.0-sm-x910-twrp.zip`).
5. Reboot and enjoy! (check below how to reboot to Android).

### Switching systems

From **Ubuntu**, just use the toggle that you should see on quick settings or from the Tab Companion app under the Dualboot tab.

From **Android**, install the `Dualboot-vX.X.X.apk` app and give it root access, then reboot from the app or add the toggle to quick settings.

Both One UI and LineageOS have been tested in dualboot with Ubuntu and they work fine.

## Known Issues

- Regarding official cover keyboard, as I said, only EF-DX920 cover keyboard has been tested. EF-DX900, EF-DX910, EF-DX915 and
EF-DX925 are untested as I don't have them, so they might not work.
- Text might not display correctly in some chromium based apps.
- Front cameras are zoomed in for some reason.

## Documentation

| Document | Contents |
|---|---|
| [Boot strategy](docs/boot-strategy.md) | Requirements, partitions, the boot chain and recovery |
| [Dual boot](docs/dual-boot.md) | How switching systems works, and what it never touches |
| [Hardware status](docs/hardware-status.md) | Evidence, limitations and pending hardware tests |
| [Tab Companion](docs/tab-companion.md) | S Pen and keyboard behaviour, architecture and diagnostics |
| [Ubuntu userspace](docs/ubuntu-userspace.md) | Root filesystem and desktop integration |
| [Fingerprint reader](docs/fingerprint-reader.md) | EL721/UDFPS architecture, security model and validation plan |
| [Development notes](docs/development-notes.md) | Durable technical conclusions and rejected approaches |
| [Porting log](docs/porting-log.md) | Chronological engineering history |

## Repository layout

```text
kernel/       Device tree, drivers, patches and kernel configuration
packaging/    Debian packages installed in the Ubuntu image
android/      The Dualboot app, which switches systems from the Android side
configs/      System configuration, service overlays and the TWRP installers
scripts/      Reproducible build and validation tools
docs/         Detailed documentation and engineering history
artifacts/    Generated release files; not versioned
work/         Scratch space for builds; not versioned
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
