# Ubuntu 24.04 LTS for Samsung Galaxy Tab S9 Ultra Wi-Fi

<img width="2319" height="1306" alt="20260805_041759" src="https://github.com/user-attachments/assets/1d8ddb29-a499-430c-b1b8-078672399d81" />

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
| Tab Companion | ✅ | S Pen remote modes, behaviour options, haptics, keyboard remapping and fingerprint settings |
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
| Fingerprint reader | ✅ | Working for login and enrolment in Ubuntu Settings or Tab Companion |
| Ambient light sensor | ❌ | Currently not working |
| NPU | ❌ | Currently not working |
| Waydroid | ❓ | Not tested |

✅ working on the physical tablet · 🟡 experimental or partially validated ·
❌ unavailable · ❓ not tested

The evidence and technical limitations for every component are documented in
[hardware-status.md](docs/hardware-status.md).

This table describes the current source tree; previously published installation
ZIPs may not include the latest changes.

## Tab Companion
<img width="2164" height="1764" alt="Screenshot from 2026-08-20 04-02-55" src="https://github.com/user-attachments/assets/df7cddca-46e8-438a-bcb8-be713cc93bed" />

Tab Companion provides:

- full S Pen settings (pairing, gestures and air-pointer mouse mode);
- remapping for compatible Samsung Book Cover Keyboard keys;
- adjustable vibration feedback for GNOME's on-screen keyboard and optional notification vibration;
- fingerprint enrolment with progress, deletion and recognition tests, using the same fingerprints as Ubuntu Settings and login;
- dual boot to Android, with an optional toggle in quick settings.

The air-pointer concept is inspired by
[PenMouse S](https://github.com/jojczak/PenMouseS) by Jakub J (`@jojczak`).
Tab Companion uses an independent native Linux implementation.

## Installation

Both ways use the same installation ZIP. The only difference is whether you
split the UFS first.

> [!WARNING]
> Either way, **everything Android keeps in `userdata` is erased**: its apps,
> its settings and its files. Android's system itself is not touched. Back up
> anything you want to keep first. On another note, the project seems really stable so far, but as always: I'm not responsible for bricked devices, missing recovery partitions, nuclear wars or you getting fired because you forgot to boot back into android for the alarm.

### Before you start

1. **An unlocked bootloader.**
2. **Root with Magisk** (only if you want dual boot).
3. Get `ubuntu-24.04-sm-x910-vX.X.X.zip` from the [latest release](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/releases/latest). `gts9u-split.zip` and `Dualboot-vX.X.X.apk` only if you want dual boot.
4. **[TWRP](https://github.com/rainbowdashh/android_device_samsung_gts9u/releases/tag/V2)** and **a `vbmeta` with AVB verification disabled** ([the one published alongside TWRP](https://xdaforums.com/attachments/vbmeta-1-tar.6077784/)). Flash both files in the AP slot using Odin or Heimdall (you will need to reboot again to download mode between flashes).
5. After flashing both files from step 4 reboot to TWRP. **Don't let One UI boot** or TWRP will be overwritten with the stock recovery and you will need to flash the files again.

### Ubuntu on the whole tablet

1. From TWRP just flash the installation ZIP (`ubuntu-24.04-sm-x910-v1.1.0.zip`) using a microSD, external USB storage or sideload. **Don't flash it from internal storage** as it will get wiped.
2. Reboot and enjoy!

### Ubuntu beside Android

> [!IMPORTANT]
> The default split is 50% of the storage for Android and 50% for Linux. If you want to modify it just change the value of `ANDROID-PERCENT` inside `gts9u-split.zip` to the percentage you want Android to keep (between 5% and 95%).

1. Flash `gts9u-split.zip`. It shortens `userdata`, creates `linuxroot`
   beside it, and recreates Android's data so Android can make fresh encryption
   keys on its next boot.
2. Reboot to TWRP (Reboot > Recovery).
3. Wipe > Format Data.
4. Flash the installation ZIP (`ubuntu-24.04-sm-x910-v1.1.0.zip`).
5. Reboot and enjoy! (see below for how to reboot to Android).

### Switching systems

From **Ubuntu**, just use the toggle that you should see on quick settings or from the Tab Companion app under the Dualboot tab.

From **Android**, install the `Dualboot-vX.X.X.apk` app and give it root access, then reboot from the app or add the toggle to quick settings.

Both One UI and LineageOS have been tested in dual boot with Ubuntu and they work fine.

Liked the project? you might want to [buy me a coffee](https://paypal.me/agcarbajo1), I'll be very grateful!

## Known issues

- Regarding the official cover keyboard, as I said, only EF-DX920 cover keyboard has been tested. EF-DX900, EF-DX910, EF-DX915 and
EF-DX925 are untested as I don't have them, so they might not work.
- Text might not display correctly in some Chromium-based apps.
- Front cameras are zoomed in for some reason.

## Documentation

| Document | Contents |
|---|---|
| [Boot strategy](docs/boot-strategy.md) | Requirements, partitions, the boot chain and recovery |
| [Dual boot](docs/dual-boot.md) | How switching systems works, and what it never touches |
| [Hardware status](docs/hardware-status.md) | Evidence, limitations and pending hardware tests |
| [Tab Companion](docs/tab-companion.md) | S Pen, keyboard and fingerprint settings, architecture and diagnostics |
| [System updates](docs/system-updates.md) | GitHub and local ZIP updates, current-build repair and the updater for older installations |
| [Ubuntu userspace](docs/ubuntu-userspace.md) | Root filesystem and desktop integration |
| [Fingerprint reader](docs/fingerprint-reader.md) | Working EL721/UDFPS integration, validation evidence and maintenance constraints |
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

Keep in mind project has been made with the help of agentic AIs (codex and claude code), so some things might not be done in the best possible way.

Proprietary Samsung and Qualcomm firmware is not stored in Git. Build helpers
stage it from the owner's tablet or official Samsung firmware and verify pinned
checksums.

The project default license is MIT; per-file SPDX headers take precedence.
Kernel code and patches remain GPL-2.0-only, and the device tree remains
BSD-3-Clause. Imported sources are listed in
[kernel/PROVENANCE.md](kernel/PROVENANCE.md).

Contributions must be reproducible in the repository and validated on physical
hardware before a component is marked as working.

## Updating an existing installation

Starting with v1.1.0, open **Tab Companion → Updates** to update the complete
port. For v1.0.0 installations without the updater, run:

```sh
d=$(mktemp -d) && curl -fL https://raw.githubusercontent.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/main/scripts/update-to-latest.py -o "$d/update.py" && sudo python3 "$d/update.py"
```

Save your work first. Type `y` when asked; the script prepares the latest
release and restarts automatically to install it.
Updates preserve your data and settings. See [system updates](docs/system-updates.md)
for local ZIP installation, repair and troubleshooting.
