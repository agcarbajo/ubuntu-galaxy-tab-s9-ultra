- Automatic screen brightness using the ambient light sensors.
- Added NPU support.
- Fixed suspend/resume, including storage recovery and waking when the cover is opened.
- Improved performance and efficiency: the prime CPU core can reach 3.36 GHz and the Adreno 740 GPU 719 MHz, with dynamic frequency scaling retained.
- Initial support for Qualcomm’s Gunyah hypervisor. Guest virtual machines remain under development.
- Fixed cropped camera images and improved camera performance with GPU processing.
- Fixed visual corruption and improved performance in Chrome and other Chromium-based apps while retaining GPU acceleration.
- Updated Android Dualboot app: automatically refreshes the saved Android boot images and system name after Android updates. Includes creator/project links and version information.

### Updating an existing installation

From v1.1.0 or any later version, update directly from **Tab Companion → Updates**.

From v1.0.0, run this in Ubuntu to update to the latest stable release:

```sh
d=$(mktemp -d) && curl -fL https://raw.githubusercontent.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra/main/scripts/update-to-latest.py -o "$d/update.py" && sudo python3 "$d/update.py"
```

For a fresh installation, flash `ubuntu-24.04-sm-x910-v1.2.0.zip` from TWRP; this wipes the Ubuntu target partition. Use the same ZIP in Tab Companion to update an existing installation while preserving your data and settings.

`Dualboot-v1.1.0.apk` contains the Android app improvements. `gts9u-split.zip` is unchanged. Both are only needed for dual boot.

<!-- gts9u-update-format: 1 -->

## SHA-256

```
1dc47f81196284b26931c2fd91ae20c662404dd4659f730f8dd463006acab307  ubuntu-24.04-sm-x910-v1.2.0.zip
ef60183e1db8eb2f854f29c046be858b6eeb9f271e95faf7eae31bfad822f9ff  gts9u-split.zip
264ade366cc850b7609d061e1a4a5bd2d6c0cee254044277cf8ee11b35b1cb55  Dualboot-v1.1.0.apk
```
