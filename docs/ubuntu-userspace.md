# Building the Ubuntu 24.04 arm64 root filesystem

Last revised: 2026-08-19.

This document defines **how the Ubuntu userspace is built** and which decisions
belong to Ubuntu. The boot chain is in [`boot-strategy.md`](boot-strategy.md);
what is inherited from the postmarketOS port is in
[`hardware-status.md`](hardware-status.md).

## Guiding principle

The hardware is already solved in the kernel. Ubuntu must reinvent none of it:
it contributes userspace only. The pipeline is therefore split into two halves
with separate responsibilities:

| Half | Source | What it produces |
|---|---|---|
| Kernel and boot | Sources imported from the pmOS port (`kernel/`) | `boot`, `init_boot`, `vendor_boot`, `dtbo`, ath12k modules |
| Userspace | `mmdebstrap` over archive.ubuntu.com/ports | an ext4 root filesystem on the internal UFS |

Neither half may depend on the other having been assembled by hand on a live
installation.

## Build tool: mmdebstrap

**`mmdebstrap`** is used, not `debootstrap` and not a preinstalled Ubuntu
image, for three concrete reasons:

1. it accepts `--architecture=arm64` with `qemu-user-static` and needs no
   native arm64 environment, which does not exist here: the build runs in WSL
   x86-64;
2. it allows `--customize-hook` to inject configuration, local packages and
   overlays **inside** the same invocation, so the root filesystem is never
   modified "by hand" afterwards;
3. it produces the same result from the same package manifest, and allows
   pinning the archive snapshot if strict reproducibility is needed later.

`debootstrap` is rejected as the main tool because it would need a second
configuration phase outside the tool, which is exactly the "unrepeatable
installation" pattern this project forbids.

### Suite and components

- Suite: `noble` (Ubuntu 24.04 LTS).
- Architecture: `arm64`.
- Components: `main`, `restricted`, `universe`, `multiverse`.
- Mirror: `http://ports.ubuntu.com/ubuntu-ports`.
- Pockets enabled: `noble`, `noble-updates`, `noble-security`.

`ports.ubuntu.com` is mandatory: `archive.ubuntu.com` publishes no arm64.

### The first root filesystem's package set

The goal of milestones 1 and 2 is a system that boots and has networking and
SSH. The desktop is installed in the same root filesystem because milestone 3
needs it and rebuilding is cheap, but the validation order remains console →
network → desktop.

Base and boot:

```
ubuntu-minimal, ubuntu-standard, systemd, systemd-sysv, udev,
initramfs-tools, linux-firmware (generic only; the Samsung/Qualcomm blobs
arrive through the ZIP's overlay), e2fsprogs, dosfstools, parted, gdisk,
zstd, xz-utils
```

Network and access:

```
netplan.io, network-manager, wpasupplicant, openssh-server, avahi-daemon,
iputils-ping, curl, ca-certificates
```

Desktop:

```
ubuntu-desktop-minimal, gdm3, gnome-shell, gnome-control-center,
gnome-session, mutter, xdg-desktop-portal-gnome, gnome-snapshot,
mesa-vulkan-drivers, mesa-utils, libgl1-mesa-dri, vulkan-tools,
pipewire, pipewire-pulse, wireplumber, pipewire-audio-client-libraries,
libspa-0.2-bluetooth, gstreamer1.0-gl, bluez, alsa-ucm-conf, alsa-utils,
iio-sensor-proxy, upower, power-profiles-daemon
```

Diagnostics during bring-up:

```
gdb, strace, evtest, i2c-tools, v4l-utils, usbutils, pciutils, ethtool, tree,
libdrm-tests, drm-info, edid-decode
```

`v4l-utils` is still the CAMSS diagnostic tool, but the normal path no longer
ends at RAW10. `scripts/build-camera-packages.sh` pins and packages
`libcamera` 0.7.2 (`62d4bfc`) with the `simple` pipeline, the software ISP,
GStreamer, HI1337/HI847 tuning, full field-of-view preservation, and contrast
autofocus for the DW9808. It also rebuilds only PipeWire 1.0.5's libcamera SPA
(`a2287be`) with seven backports: libcamera 0.7 compatibility, the correct RGB
map, safe reuse of requests and buffers, borrowed descriptors, and delivery of
completions on the data loop. The resulting `.deb`s are `libcamera-gts9u` and
`libspa-0.2-libcamera-gts9u`; they replace only the archive's camera packages
and keep Noble's PipeWire and WirePlumber.

The device package also installs the udev rule for `/dev/udmabuf`, needed so
the software ISP can allocate buffers without privileges. The kernel includes a
pinned, signed `v4l2loopback` to create four capture nodes, and
`v4l2-relayd-gts9u` feeds them on demand from the PipeWire sources. The desktop
image includes GNOME Camera and `gstreamer1.0-gl`. A clean build therefore
offers the four named cameras to browsers and V4L2 applications with no scenes
and no per-user setup.

**OBS Studio is no longer shipped.** It travelled along as a camera
verification tool, together with `obs-v4l2-gts9u`; with that work closed, both
left in v2.23 of the device package, and with them the 77 MiB of VLC that
`obs-plugins` dragged in through `Recommends`. See "OBS was travelling along"
in the development notes.

The image creates no account. Since `ubuntu-gts9u-device 2.18`,
`ubuntu-gts9u-desktop-user` resolves the OOBE-created account on every boot,
enables its lingering, and generates the relay service's `User=`, `Group=` and
environment under `/run`. Its PipeWire therefore exists before the first login
too, and does not depend on an SSH session staying open. The service waits for
PipeWire's real PID and watches its lifetime; if PipeWire or a relay exits,
systemd rebuilds the four cameras as a single set. Version
`v4l2-relayd-gts9u 0.1.2-gts9u15` adds pre-emptive delivery and correctly keeps
the ISP owner's PID. This stops the nodes from staying enumerated but black
after a boot, an update or a sensor change.

`ubuntu-desktop-minimal` rather than `ubuntu-desktop` leaves out office
software and desktop snaps that contribute nothing to bring-up. Snap is
evaluated separately in milestone 5; it is not assumed from the start.

### Ubuntu decisions that must be tried natively first

From the postmarketOS baseline the project inherits hardware, **not** userspace
patches. These pieces must be tried natively before anything is ported:

| Piece | pmOS/Alpine | Ubuntu 24.04 — try first |
|---|---|---|
| Greeter | `gdm-greeter-*` accounts created by hand because Alpine builds systemd without `systemd-userdbd` | Native GDM3: Ubuntu **does** ship `systemd-userdbd`, so the workaround must not be copied |
| Sound server | PulseAudio 17 | PipeWire + WirePlumber, with `pipewire-pulse` as the compatibility layer |
| Split GPU/DPU topology | Patched Xorg + reverse PRIME | Mutter/Wayland handles `card0` (Adreno, render) and `card1` (DPU, KMS) unpatched; pmOS's Xorg stack is **not** ported |
| Rotation | Patched Mutter r6 | Ubuntu's Mutter as it is; the patch is ported only if the specific regression returns (an external mouse disabling auto-rotation) |
| Scaling | XFCE's manual GTK/Xft settings | Mutter's `scale-monitor-framebuffer` and GNOME's 200 % scaling |
| Sensors | Patched `iio-sensor-proxy` 3.9 + `libssc` + `hexagonrpcd` | Ubuntu's `iio-sensor-proxy`; `libssc` and `hexagonrpcd` **do** have to be packaged, because Ubuntu has neither. All three carry their own patches, `libssc` included |
| Network management | NetworkManager | NetworkManager with netplan as the frontend (Ubuntu's default) |

What does **not** translate and has to be repackaged as `.deb`:

- `libssc` and `hexagonrpcd` (the sensors' SSC/FastRPC client). `libssc` carries
  its own patch: its synchronous wait spun the GLib context without blocking,
  which cost a whole core as soon as the SSC left a request unanswered;
- `pd-mapper` (essential: without it the ADSP publishes no `servreg locator`
  and the ALSA card never appears);
- the device package with the equivalent udev rules, UCM, recovery services and
  `deviceinfo`.

## Root filesystem structure

Since v0.18 the root is **a single ext4 filesystem inside a partition** on the
internal UFS, labelled `UBTS9U_UFS`. That partition is `linuxroot` when the
disk has been split and `userdata` when it has not. The image the ZIP ships has
no partition table: it is the filesystem alone, because it is written inside a
partition that already exists.

`/boot` lives inside the root. The separate microSD partition existed because
the initramfs that fits in `init_boot` (8 MiB) cannot hold the full module tree
and the second stage had to live somewhere mountable; with a single root that
place is `/boot`, and no partition has to be requested that we are not going to
create.

Up to v0.17 the microSD carried **two partitions**:

| Partition | FS | Label | Contents |
|---|---|---|---|
| 1 | ext4 | `UBTS9U_BOOT` | `initramfs-extra`, the reference DTB and build metadata |
| 2 | ext4 | `UBTS9U_ROOT` | the Ubuntu root filesystem |

The labels are deliberately our own. Reusing `pmOS_boot`/`pmOS_root` would make
a postmarketOS initramfs and an Ubuntu one compete for the same medium; and
`UBTS9U_UFS` differs from `UBTS9U_ROOT` so that an old card forgotten in the
slot cannot win the `root=LABEL=` resolution against the internal installation.

The image is generated small (root filesystem plus slack) and a
`ubuntu-gts9u-grow-rootfs.service` unit expands it on the first boot. On the
UFS that means **`resize2fs` only**: the partition is already its full size and
no partitioning tool touches it. On a microSD the partition does have to be
extended first, and the script tells the two cases apart by device and label.

## Two-tier swap

The image carried **no** swap at all: with 14.2 GiB of usable RAM and a real
desktop load (Steam plus a browser), the only backstop against a spike was the
OOM killer. Since v2.22 of the device package there are two tiers, 23 GiB in
total:

| Tier | Size | Priority | Unit |
|---|---|---|---|
| zram (zstd) | 8 GiB | 100 | `ubuntu-gts9u-zram.service` |
| swapfile on the UFS | 16 GiB | 10 | `ubuntu-gts9u-swapfile.service` |

The decisions, and why:

- **zram first, and with `zstd`.** It costs not one write to the UFS. The
  kernel's default algorithm here is `lzo-rle`, but `zstd` is available:
  `CONFIG_CRYPTO_ZSTD` is module-only and this port installs no generic tree,
  but modern zram carries its own zstd backend and announces it in
  `comp_algorithm`. Measured on the tablet: **4.53×** — 0.65 GiB of pages
  occupying 0.16 GiB of RAM.
- **8 GiB of zram, half the RAM.** That is the reasonable ceiling: any larger
  and a run of incompressible pages could claim more memory than it saves.
  `comp_algorithm` only accepts writes while `disksize` is still unset, so that
  order in the script is not interchangeable.
- **The swapfile does not travel in the image.** 16 GiB of zeros would dwarf
  the flashable ZIP; it is created on the device, which is why the unit is
  ordered `After=` the root filesystem expansion: before that the filesystem is
  still the small one that was shipped.
- **`fallocate`, not `dd`.** ext4 with this kernel accepts a swapfile of
  unwritten extents — `mkswap` and `swapon` accept it, verified on the tablet —
  so creation is instant and adds nothing to boot. The `dd` is kept only as a
  fallback should `swapon` ever reject the file.
- **16 GiB, larger than RAM, on purpose.** It is 2 % of the free space and
  leaves hibernation arithmetically possible for anyone who wants to wire up
  `resume=`; it is not promised to work.
- **`vm.swappiness = 100` and `vm.page-cluster = 0`** (`90-gts9u-swap.conf`).
  With a compressed tier in front, evicting an anonymous page is cheap and
  worth preferring over dropping cache. The 180 of a zram-only machine is not
  used, because here there is a swapfile behind. `page-cluster = 0` because
  zram has no seek penalty and reading clusters of pages only wastes
  decompression.

Validated after an unattended reboot: both units active, the swapfile reused
rather than recreated, and a test that reserves 11 GiB without a single OOM
kill.

## Ubuntu's own initramfs

**The postmarketOS initramfs is not reused.** Ubuntu generates its own with
`initramfs-tools`, and it has to meet four requirements that do not come by
default:

1. **Find the root without device numbers.** The root is given as
   `root=LABEL=UBTS9U_UFS`, never `sda34` or `mmcblk1p2`. The enumeration order
   of the UFS LUNs and of `sdhc_2` is not guaranteed, and the label is also
   what separates the internal installation from an old microSD.
2. **Wait for the device to appear.** `rootwait` is already in `vendor_boot`'s
   cmdline; on top of that the local hook retries `blkid` instead of dropping
   to the emergency shell on the first failure.
3. **Be packed in legacy LZ4.** This is non-negotiable: the X910's ABL
   concatenates the generic ramdisk from `init_boot` with the fragment from
   `vendor_boot`, and with a gzip generic ramdisk Linux rejects the initrd with
   "invalid magic at start of compressed archive" even though the Android image
   is valid. `initramfs-tools` is configured with `COMPRESS=lz4` and the
   packager checks for the `02 21 4c 18` magic.
4. **Fit in 8 MiB minus the AVB footer.** `MODULES=dep`, not `most`. Since this
   port's critical providers are built in, the initramfs needs no large module
   tree; if it still does not fit, the answer is to move modules to
   `initramfs-extra` on the boot partition, not to cut needed drivers.

The validation script checks all four against the generated image, flashing
nothing.

## Firmware

The repository contains no blobs. The `scripts/stage-stock-*.sh` helpers are
adapted from the pmOS port, keeping its pinned hashes and changing only the
destination, which in Ubuntu is the Debian hierarchy:

| Contents | Path in the Ubuntu root filesystem |
|---|---|
| Adreno 740 GPU (`a740_*`, `gmu_gen70200.bin`) | `/lib/firmware/qcom/` |
| Samsung ADSP (`adsp*.mdt`, `adsp*.bNN`, `*.jsn`) | `/lib/firmware/qcom/sm8550/` |
| AudioReach topology | `/lib/firmware/qcom/sm8550/Samsung-Galaxy-Tab-S9-Ultra-tplg.bin` |
| WCN7850 Wi-Fi (official amss + QRD BDF in ELF) | `/lib/firmware/ath12k/WCN7850/hw2.0/` |
| Bluetooth (`hmtbtfw20.tlv`, `hmtnv20.b21`) | `/lib/firmware/qca/` |
| CS35L45 (protection, not loaded yet) | `/lib/firmware/` |
| Sensors' HexagonFS tree | `/usr/share/qcom/sm8550/Samsung/gts9uwifi/` |

In Ubuntu `/lib` is a symlink to `/usr/lib`, as it is in the postmarketOS
initramfs. This is the same trap that broke v0.69 of that port: the overlay
must be written into `/usr/lib/firmware/...`, never creating a `/lib` directory
over the symlink.

`hmtbtfw20.tlv` and `hmtnv20.b21` must **also** go in `vendor_boot`'s vendor
fragment, because `hci_qca` is built in and probes before the root is mounted.

## User, locale and input

- **The image carries no account.** Since v0.19 the owner creates it in GNOME's
  first-run wizard (`gnome-initial-setup`), which GDM launches when the machine
  has no ordinary account and `InitialSetupEnable=true` is set in
  `/etc/gdm3/custom.conf`. Name, password, language, keyboard and time zone are
  chosen there.

  This is not only convenience: the account used to be created with a password
  passed in `GTS9U_PW`, which cannot live in the repository, so **nobody who
  did not know it could make a clean build**. A release now needs no secret at
  all.

  `GTS9U_PW` still exists for development images, where working SSH before
  anyone touches the screen matters more.

  One consequence worth knowing when reaching a tablet over SSH: the account's
  name and password are whatever was typed in that wizard, and they change with
  every reinstall. The host keys do not — they travel inside the image.
- Nothing in the port may name a specific user any more. The flashlight
  extension is enabled through a gschema override, and
  `ubuntu-gts9u-desktop-user` resolves the ordinary account on every boot,
  enables its lingering, applies device groups and generates the relays'
  drop-in under `/run`.
- Locale `en_US.UTF-8`, time zone UTC and keyboard `us` as a neutral starting
  point; the wizard asks for all three.
- A hostname different from postmarketOS's, so two systems on the same LAN
  cannot be confused.
- 200 % scaling by default: 2960×1848 on 14.6" is unusable at 100 %.
- SSH enabled with a key; the user's password stays out of the repository.

## Build pipeline

Everything runs as root inside `wsl.exe -d Ubuntu-24.04`, based in
`/root/ubuntu-gts9u`. No script accepts a block device or writes to a
partition.

| Step | Script | Produces |
|---|---|---|
| 0 | `install-build-deps.sh` / `check-build-deps.sh` | a checked build environment |
| 0 | `fetch-mainline.sh` | checkout pinned at `a13c140c` (7.2-rc3) |
| 0 | `stage-android-tools.sh` | `mkbootimg`, `mkdtboimg`, `avbtool` |
| 0 | `import-kernel-sources.sh` | reimports DTS, drivers and patches with a source hash |
| 1 | `build-mainline-kernel.sh` | `Image.gz`, DTB, config, and the ath12k plus signed `v4l2loopback` modules |
| 1b | `build-camera-packages.sh` | `libcamera-gts9u` and the libcamera SPA for PipeWire |
| 1c | `build-extra-packages.sh` | Fastfetch and the V4L2 relay |
| 2 | `build-ubuntu-rootfs.sh` | the Ubuntu arm64 root filesystem, with `mmdebstrap` |
| 3 | `build-rootfs-overlay.sh` | the module and firmware overlay |
| 4 | `build-ufs-image.sh` | Ubuntu's initramfs and the root's ext4 image, with no partition table |
| 5 | `build-android-v4-bundle.sh` | `boot`, `init_boot`, `vendor_boot`, `dtbo`, `vbmeta` |
| 6 | `make-twrp-zip.py` | a deterministic TWRP ZIP with the root inside |
| 7 | `validate-bundle.sh` | static validation, flashing nothing |
| — | `make-initramfs.sh` | a checked legacy-LZ4 initramfs; both image builders use it |
| — | `build-sd-image.sh` | the two-partition microSD image, how installing worked up to v0.17 |
| — | `build-release.sh` | chains 1–7 and writes the manifest |

`make-initramfs.sh` fails the build if the initramfs is not legacy LZ4 or does
not fit in `init_boot`. Those two errors are found here rather than on the
tablet, and they live in one place so the UFS image and the microSD one cannot
diverge on exactly that.

`build-ufs-image.sh` produces the filesystem alone: no GPT, with `/boot`
inside, with the firmware overlay already integrated, labelled `UBTS9U_UFS`,
and reserving enough descriptor blocks (`-E resize=`) for the first boot to
grow online to 1 TiB. It refuses to write to a block device and aborts if the
image exceeds its size budget, because it travels whole inside the ZIP.

Two numbers in that script are deliberate and connected:

- **`-m 1` instead of ext4's default 5 % reserve.** The reserve is a percentage
  held in the superblock, so it survives the resize: 5 % of the partition the
  root grows into would be tens of gigabytes the owner never gets back.
- **The slack, and the budget it needs.** The installer seeds two boot sets of
  216 MiB each into this filesystem before it grows, so it must have room for
  both. The budget was raised from 4096 to 4608 MiB deliberately for that; empty
  space costs almost nothing in the ZIP, where 256 MiB of slack measured 784 KB.

## Validation order

1. `systemd` reaches `multi-user.target` with a persistent journal.
2. Wi-Fi and SSH.
3. GDM and a GNOME Wayland session.
4. Accelerated GPU checked with `eglinfo`/`vulkaninfo`, not assumed.
5. The rest of the hardware parity.

No component is marked working in the matrix merely because its driver bound.
