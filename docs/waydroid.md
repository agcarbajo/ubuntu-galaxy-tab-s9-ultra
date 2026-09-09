# Waydroid

## Physical validation (2026-09-08)

Waydroid 1.6.2 boots the official LineageOS 20 / Android 13 GAPPS image on
the SM-X910, under GNOME Wayland and kernel 7.2.0-rc3-dirty. Initialization
selects `waydroid_arm64_only` automatically. Both system and MAINLINE vendor
images are dated 2026-04-03 and were downloaded and validated by Waydroid.

Measured after repairing the missing host modules:

- `sys.boot_completed=1`, with system_server and Google Play Services running;
- Google Services Framework, Play Services and Play Store installed;
- Play Store renders its sign-in screen;
- DHCP, DNS and external ICMP work; HTTPS returns 204 with TLS verification 0;
- Android reports Ethernet `INTERNET` and `VALIDATED`;
- SurfaceFlinger reports `freedreno, FD740, OpenGL ES 3.2 Mesa 26.0.1`.

No Google account was entered. Account authentication, Play certification,
purchases, DRM and individual app compatibility are not claimed as tested.
One graphics-composer process aborted during first initialization and Android
restarted it; the subsequent desktop and Play Store rendered successfully.
After the One UI investigation the tablet returned to the same Ubuntu kernel.
On 2026-09-09, after login to GNOME Wayland, `check-waydroid.sh` also passed
the post-reboot boot/GApps/HTTPS/network-validation/hardware-rendering check.

## Build fix

The first launch failed in `waydroid-net.sh`: `ip_tables` and the filter/NAT
tables were configured as modules but absent from the shipped module payload.
The old kernel build only staged selected hardware modules.

`scripts/build-netfilter-modules.sh` builds the configured Netfilter and
IPv4/IPv6 modules together, resolves their mutual exports, strips and signs
them with the kernel's key. `build-mainline-kernel.sh` includes them in the
normal module payload before depmod. The desktop config explicitly retains
the network tables and adds Android's owner match. No global firewall flush,
disabled firewall or hardcoded tablet IP is needed.

For the already running development kernel, the same modules were compiled
against its exact source/object tree and signing key, installed, and loaded
without a tablet reboot. Never reuse those binaries with a different kernel.

## Install and check

Follow the [official installation instructions](https://docs.waydro.id/usage/install-on-desktops)
to configure the signed Ubuntu Noble repository, then:

```sh
sudo apt install waydroid
sudo waydroid init -s GAPPS
waydroid session start
```

From another terminal in the same desktop session:

```sh
waydroid show-full-ui
sudo bash scripts/check-waydroid.sh
```

The check expects an already running session and the official GAPPS image.
It checks boot completion, Google packages, real HTTPS including certificate
validation, Android network validation and hardware rendering.

If Google reports an uncertified device, follow
[Waydroid's Google Play certification procedure](https://docs.waydro.id/faq/google-play-certification).
The Android ID and the Google account belong to the owner and must not be
committed to this repository.

## Newer Android images: research only

No alternative image was installed. As checked on 2026-09-08:

- [WayDroid-ATV Android 16 / LineageOS 23.2](https://github.com/WayDroid-ATV/waydroid-builds/releases)
  offers GAPPS builds, but the GitHub assets actually returned for 20260302
  are x86-64. A newer release points ARM64 users to that older release;
  this contradicts its current assets. Do not install an x86-64 image on
  this tablet. Its [ARM64 request](https://github.com/WayDroid-ATV/waydroid-builds/issues/28)
  also records problems with arm64_only.
- [AviumUI Waydroid A16](https://github.com/phxinyang/aviumui-waydroid-a16)
  provides an ARM64-only Android 16 / LineageOS 23.2 source recipe with pinned
  inputs and a GApps source component. It produces paired system/vendor
  images, but does not publish a ready-to-download release. This is an
  experimental build candidate, not a physically validated replacement.
- No usable Android 17 ARM64 GAPPS Waydroid image was verified.

For AviumUI, follow its build README in a separate Linux build workspace.
The outputs are under `out/target/product/waydroid_arm64_only/`. After checking
the image's Google-app contents and converting Android sparse images with
`simg2img` if necessary, installation uses Waydroid's
[custom image procedure](https://docs.waydro.id/faq/using-custom-waydroid-images):

```sh
waydroid session stop
sudo systemctl stop waydroid-container
# Back up /var/lib/waydroid and ~/.local/share/waydroid before replacing images.
sudo install -d /etc/waydroid-extra/images
sudo install -m 0644 /path/to/raw/system.img /etc/waydroid-extra/images/system.img
sudo install -m 0644 /path/to/raw/vendor.img /etc/waydroid-extra/images/vendor.img
sudo waydroid init -f -i /etc/waydroid-extra/images
sudo systemctl start waydroid-container
waydroid session start
```

Both images must come from the same ARM64 build. A major Android upgrade can
require clean Waydroid user data; keep the backup rather than deleting it.
