# Ubuntu 26.04 LTS for Samsung Galaxy Tab S9 Ultra Wi-Fi

<img width="4000" height="2252" alt="20260911_124542" src="https://github.com/user-attachments/assets/80a44675-d588-43b5-b86d-514cd7875800" />

Ubuntu 26.04 LTS arm64 for the Samsung Galaxy Tab S9 Ultra Wi-Fi
(`SM-X910`, `gts9uwifi`), with GNOME 50 on Wayland and Linux 7.2.9.

Upgrading from Ubuntu 24.04? Follow [Updating an existing installation](#updating-an-existing-installation) to retain your files and settings.

## Hardware compatibility

| Component | Status | Summary |
|---|---:|---|
| Display | ✅ | Native 2960×1848 at 120 Hz |
| Desktop | ✅ | GNOME 50, Wayland and GDM |
| GPU | ✅ | Adreno 740 hardware acceleration, up to 719 MHz |
| Touchscreen | ✅ | Goodix multitouch |
| S Pen writing | ✅ | Hover, pressure, tilt, side button and palm rejection |
| S Pen dock | ✅ | Insertion, orientation and charging |
| S Pen BLE | ✅ | Pairing, battery, air gestures and pointer mode |
| [Galaxy Companion](https://github.com/agcarbajo/galaxy-companion) | ✅ | Device settings, dual boot and updates |
| Keyboard cover | ✅ | EF-DX920 tested |
| Cover switch | ✅ | Suspend on close and wake on open |
| Power and volume buttons | ✅ | Power, wake and volume controls |
| Wi-Fi | ✅ | WCN7850 / ath12k |
| Bluetooth | ✅ | Controller, audio and S Pen BLE |
| Speakers and microphones | ✅ | All four speakers and microphones work fine |
| Vibration / haptics | ✅ | On-screen keyboard, including login and lock screen |
| Motion sensors | ✅ | Rotation, accelerometer, gyroscope and compass |
| Battery telemetry | ✅ | Charge, voltage, current and temperature |
| USB-PD/PPS charging | ✅ | Up to 25 W measured into the battery |
| Suspend / resume | ✅ | Deep sleep and reliable storage recovery |
| microSD | ✅ | Read and write storage works normally |
| USB host | ✅ | HID and storage, powered or unpowered |
| USB-C DisplayPort | ✅ | External video and HDMI audio |
| Cameras and flash | ✅ | Four cameras, full field of view, autofocus and flash |
| Fingerprint reader | ✅ | Login, enrolment and recognition |
| Ambient light sensor | ✅ | Automatic screen brightness |
| NPU | ✅ | Hardware acceleration support |
| Virtual machines | 🟡 | Gunyah host support; guest VMs still in development |
| Waydroid | ✅ | Android with Google Play, GPU acceleration and Internet |

✅ working on the physical tablet · 🟡 experimental or partially validated ·
❌ unavailable · ❓ not tested

The evidence and technical limitations for every component are documented in
[hardware-status.md](docs/hardware-status.md).

This table records behavior on the development SM-X910. The fingerprint runtime
and calibration are provisioned from each tablet; a second unit has not yet
been physically validated. Other cover models and display-resume combinations
still need testing; see Known issues.

## Galaxy Companion
<img width="2164" height="1764" alt="Screenshot from 2026-08-20 04-02-55" src="https://github.com/user-attachments/assets/df7cddca-46e8-438a-bcb8-be713cc93bed" />

[Galaxy Companion](https://github.com/agcarbajo/galaxy-companion), formerly Tab
Companion and now a separate project that serves other Samsung devices through
device profiles, provides on this tablet:

- full S Pen settings (pairing, gestures and air-pointer mouse mode);
- remapping for compatible Samsung Book Cover Keyboard keys;
- adjustable vibration feedback for GNOME's on-screen keyboard and optional notification vibration;
- fingerprint enrolment with progress, deletion and recognition tests, using the same fingerprints as Ubuntu Settings and login;
- dual boot to Android, with an optional toggle in quick settings;
- updater for future builds of the port directly from the app.

The air-pointer concept is inspired by
[PenMouse S](https://github.com/jojczak/PenMouseS) by Jakub J (`@jojczak`).
Galaxy Companion uses an independent native Linux implementation.

## Installation

Both ways use the same installation ZIP. The only difference is whether you
split the UFS first.

> [!WARNING]
> Either way, **everything Android keeps in `userdata` is erased**: its apps,
> its settings and its files. Android's system itself is not touched. Back up
> anything you want to keep first. On another note, the project seems really stable so far, but as always: I'm not responsible for bricked devices, missing recovery partitions, nuclear wars or you getting fired because you forgot to boot back into android for the alarm.

### Before you start

1. **An unlocked bootloader.** One UI 8 and later remove the *OEM unlocking*
   switch, so unlock while still on One UI 7 or earlier and only then update
   ([details and the One UI 7 → 8 route](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/issues/3)). With a screen lock set, the
   Download Mode key combination stops at a teal *Reboot Device - D2* screen
   that never enumerates over USB: remove the screen lock first.
2. **Root with Magisk** (only if you want dual boot).
3. Get `ubuntu-26.04-sm-x910-v2.0.0.zip` from the [latest release](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/releases/latest). `gts9u-split.zip` and the [new Android Dualboot APK](https://github.com/agcarbajo/galaxy-companion/releases/download/v1.0.0/galaxy-companion-dualboot_1.0.0.apk) are only needed for dual boot.
4. **[TWRP](https://github.com/rainbowdashh/android_device_samsung_gts9u/releases/tag/V2)** and **a `vbmeta` with AVB verification disabled** ([the one published alongside TWRP](https://xdaforums.com/attachments/vbmeta-1-tar.6077784/)). Flash both files in the AP slot using Odin or Heimdall (you will need to reboot again to download mode between flashes).
5. After flashing both files from step 4 reboot to TWRP. **Don't let One UI boot** or TWRP will be overwritten with the stock recovery and you will need to flash the files again.

### Ubuntu on the whole tablet

1. From TWRP just flash the installation ZIP (`ubuntu-26.04-sm-x910-v2.0.0.zip`) using a microSD, external USB storage or sideload. **Don't flash it from internal storage** as it will get wiped.
2. Reboot and enjoy!

### Ubuntu beside Android

> [!IMPORTANT]
> The default split is 50% of the storage for Android and 50% for Linux. If you want to modify it just change the value of `ANDROID-PERCENT` inside `gts9u-split.zip` to the percentage you want Android to keep (between 5% and 95%).

1. Flash `gts9u-split.zip`. It shortens `userdata`, creates `linuxroot`
   beside it, and recreates Android's data so Android can make fresh encryption
   keys on its next boot.
2. Reboot to TWRP (Reboot > Recovery).
3. Wipe > Format Data.
4. Flash the installation ZIP (`ubuntu-26.04-sm-x910-v2.0.0.zip`).
5. Reboot and enjoy! (see below for how to reboot to Android).

### Switching systems

From **Ubuntu**, just use the toggle that you should see on quick settings or from the Galaxy Companion app under the Dualboot tab.

From **Android**, **uninstall the old Dualboot app first**, then install the
[new Galaxy Companion Dualboot APK](https://github.com/agcarbajo/galaxy-companion/releases/download/v1.0.0/galaxy-companion-dualboot_1.0.0.apk)
and grant it root access. Open it and choose **Restart** for Ubuntu 26.04.
The quick-settings tile is also available. Uninstalling the old app does not
remove Ubuntu or its files.

Both One UI and LineageOS have been tested in dual boot with Ubuntu and they work fine.

Liked the project? you might want to buy me a coffee, I'll be very grateful!

<a href='https://ko-fi.com/V7W426ZJIP' target='_blank'><img height='36' style='border:0px;height:36px;' src='https://storage.ko-fi.com/cdn/kofi5.png?v=6' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>

## Updating an existing installation

### From 1.3.0 (Ubuntu 24.04)

1. Download [Galaxy Companion 1.0.0](https://github.com/agcarbajo/galaxy-companion/releases/download/v1.0.0/galaxy-companion_1.0.0_all.deb)
   and the [Tab Companion transition package](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/releases/download/v2.0.0/ubuntu-gts9u-companion_1.0.0_all.deb).
   In the folder containing both files, run:

   ```sh
   sudo apt-get install ./galaxy-companion_1.0.0_all.deb ./ubuntu-gts9u-companion_1.0.0_all.deb
   ```

2. Close Tab Companion and open **Galaxy Companion → Updates → Check for updates**.
   Download and prepare **2.0.0**, authenticate, save your work, then select
   **Restart and install**. For a downloaded ZIP, use **Install from a ZIP** instead.
3. Keep the charger connected and allow the migration to finish. It preserves
   your files, settings and shared home, and retains the previous system for
   recovery. The copy needs free space for the existing system plus **24 GiB**.
4. For dual boot, **uninstall the old Android Dualboot app**, install the
   [new APK](https://github.com/agcarbajo/galaxy-companion/releases/download/v1.0.0/galaxy-companion-dualboot_1.0.0.apk)
   and grant root. It returns to the selected Ubuntu 26 installation.

The 1.3.0 updater included the format-2 bridge, but still used Tab Companion's
state and handoff conventions. Install the two packages first to use the
current migration entry point and status handling. This step updates the app,
not Ubuntu or the boot images.

### From 1.2.0 or earlier

First install the published **1.3.0 bridge**, then follow the steps above.
This command also works on installations without the Updates page; it asks
for confirmation before preparing the bridge and restarting:

```sh
d=$(mktemp -d) && curl -fL https://raw.githubusercontent.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/main/scripts/update-to-latest.py -o "$d/update.py" && sudo python3 "$d/update.py" --bridge
```

**Do not flash the TWRP installer to upgrade while preserving data.** It is for
clean installations and replaces Ubuntu's filesystem. See
[system updates](docs/system-updates.md) for details and troubleshooting.

### If Ubuntu no longer boots after an update

Start TWRP and connect ADB. Mount the Ubuntu partition **read-only** to inspect
it (`linuxroot` for a split installation, `userdata` otherwise):

```sh
mkdir -p /u
mount -o ro,noload /dev/block/by-name/linuxroot /u
```

- After migration, `/u/.gts9u-root/selected` identifies the active slot. Its root
  is `/u/.gts9u-root/slots/<id>/root`; inspect its
  `var/lib/galaxy-companion-update/status.json`. The previous system remains
  at `/u`, and its matching boot backup is in
  `/u/.gts9u-root/slots/<id>/backup/`.
- Without a migrated slot, inspect
  `/u/var/lib/galaxy-companion-update/status.json` (or `tab-companion-update`
  on older installations) and the transaction's `backup/` directory.
- Restore **matching root, boot images and modules** together. Check backup
  hashes, partition sizes and complete write readback before restarting.
  Restoring only an old kernel while leaving a new slot selected is not a
  recovery. Never restore the old system's boot set if
  `.gts9u-root/previous-system-removed` exists.

Keep the original installation, slot directory and backups intact while
recovering. See [migration recovery](docs/recovery-26.04-bootloop-20261018.md)
for the boot layout and diagnosis. Do not use the clean installer unless you
intend to erase Ubuntu. If packages need repair, run `sudo dpkg --configure -a`
and `sudo apt-get check` only after booting the correct Ubuntu installation.

## Known issues

- **Fingerprint on other units:** per-device runtime/calibration provisioning is
  included and works on the development SM-X910; confirmation on a second unit
  remains pending ([#8](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/issues/8),
  [#9](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/issues/9)).
- **EF-DX925 keyboard backlight and Fn+F12 stay dark** ([#8](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/issues/8)): the
  MAX77816 booster was left at 3.3 V. The kernel raises it to Samsung's
  5.14 V for the DX915/DX925, untested here without that cover.
- Regarding the official cover keyboard, as I said, only EF-DX920 cover keyboard has been tested. EF-DX900, EF-DX910, EF-DX915 and
EF-DX925 are untested as I don't have them, so they might not work.
- Guest virtual machines remain under development; initial Gunyah host support is included.
- Sometimes returning from deep suspend might need a hard reset.

## Documentation

| Document | Contents |
|---|---|
| [Boot strategy](docs/boot-strategy.md) | Requirements, partitions, the boot chain and recovery |
| [Dual boot](docs/dual-boot.md) | How switching systems works, and what it never touches |
| [Hardware status](docs/hardware-status.md) | Evidence, limitations and pending hardware tests |
| [Galaxy Companion](docs/tab-companion.md) | The settings application, now in its own repository and pinned here as the `external/galaxy-companion` submodule |
| [System updates](docs/system-updates.md) | GitHub and local ZIP updates, current-build repair and the updater for older installations |
| [Ubuntu userspace](docs/ubuntu-userspace.md) | Root filesystem and desktop integration |
| [Fingerprint reader](docs/fingerprint-reader.md) | Working EL721/UDFPS integration, validation evidence and maintenance constraints |
| [Gunyah virtual machines](docs/gunyah.md) | Host-driver architecture, current validation and tablet test procedure |
| [Development notes](docs/development-notes.md) | Durable technical conclusions and rejected approaches |
| [Porting log](docs/porting-log.md) | Chronological engineering history |

## Repository layout

```text
kernel/       Device tree, drivers, patches and kernel configuration
packaging/    Debian packages installed in the Ubuntu image
external/     Galaxy Companion submodule, including the Android Dualboot app
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
