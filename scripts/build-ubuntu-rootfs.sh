#!/bin/bash
# Build a reproducible Ubuntu 24.04 LTS arm64 root filesystem for the Samsung
# Galaxy Tab S9 Ultra Wi-Fi (SM-X910).
#
# The result is a directory tree, not an image; scripts/build-sd-image.sh turns
# it into the two-partition microSD image.  Nothing here writes to a device.
#
# Profiles:
#   minimal   base system, network and SSH only (Hito 2)
#   desktop   adds GNOME/Wayland, PipeWire and Mesa (Hito 3, default)
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
rootfs=${ROOTFS_DIR:-$base/rootfs}
profile=${GTS9U_PROFILE:-desktop}
suite=${UBUNTU_SUITE:-noble}
mirror=${UBUNTU_MIRROR:-http://ports.ubuntu.com/ubuntu-ports}
hostname=${GTS9U_HOSTNAME:-ubuntu-gts9u}
username=${GTS9U_USER:-ubuntu}
# Neutral defaults, because these are what the first-boot wizard starts from:
# whatever the image ships is what it shows pre-selected.  Shipping Spanish
# meant every owner was offered Spanish first, including those who had never
# heard of this port's author.  English, a US layout and UTC are the neutral
# choices, and the wizard asks for all three anyway.
#
# The variables remain, so a build for one particular person can still set them.
locale=${GTS9U_LOCALE:-en_US.UTF-8}
timezone=${GTS9U_TIMEZONE:-UTC}
keymap=${GTS9U_KEYMAP:-us}
kernel_release=${KERNEL_RELEASE:-7.2.0-rc3}
modules_root=${KERNEL_MODULES_ROOT:-}
authorized_keys=${GTS9U_AUTHORIZED_KEYS:-}
# No account is created by default.  The image ships without one and GNOME's
# first-boot wizard asks the owner for a name, a password, the language, the
# keyboard layout and the time zone, which is both nicer than inheriting a
# stranger's `ubuntu` account and the only way this build stays reproducible:
# it used to require a password that could not live in the repository, so a
# clean build was impossible for anyone who did not already know it.
#
# Setting GTS9U_PW brings the old behaviour back for development images, where
# an unattended SSH login matters more than the wizard.
password=${GTS9U_PW:-}

command -v mmdebstrap >/dev/null || {
	echo 'mmdebstrap is missing; run scripts/install-build-deps.sh' >&2
	exit 1
}
[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] || {
	echo 'binfmt qemu-aarch64 is not registered; run scripts/install-build-deps.sh' >&2
	exit 1
}

case "$rootfs" in
	"$base"/*) ;;
	*) echo "refusing to build outside $base: $rootfs" >&2; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# Package sets
# ---------------------------------------------------------------------------

# snapd and apparmor are listed explicitly rather than left to Recommends.
# A build that relied on ubuntu-desktop-minimal recommending snapd produced a
# rootfs without it, and `apt install firefox` then fails: in Ubuntu that
# package exists only to install a snap.  apparmor userspace matters now that
# the kernel enables the LSM, or the profiles Ubuntu ships never load.
base_packages='
ubuntu-minimal,ubuntu-standard,
systemd,systemd-sysv,systemd-resolved,udev,dbus,
initramfs-tools,busybox-initramfs,
e2fsprogs,dosfstools,parted,gdisk,
zstd,xz-utils,lz4,
sudo,locales,tzdata,console-setup,keyboard-configuration,
cloud-guest-utils,
apparmor,apparmor-utils,
snapd,squashfs-tools,
netplan.io,network-manager,wpasupplicant,
openssh-server,avahi-daemon,
protection-domain-mapper,qrtr-tools,
iputils-ping,curl,wget,ca-certificates,
nano,less,htop,rsync,unzip,acl,
usbutils,pciutils,ethtool,evtest,i2c-tools,v4l-utils,
strace,tree
'

# Two more things ubuntu-desktop-minimal only recommends, and that a build
# without them gets wrong in ways that look like distro bugs:
#
#   yaru-theme-icon    without it only yaru-theme-gnome-shell arrives, the icon
#                      theme falls back to Adwaita, and the Ubuntu-specific
#                      entries in Settings show a generic placeholder icon.
#   gnome-keyring      GNOME Shell's NetworkManager secret agent is backed by
#                      the keyring.  Without it no agent registers, joining a
#                      protected Wi-Fi never prompts for the password, and
#                      NetworkManager just logs "no secrets: No agents were
#                      available for this request" and fails.
desktop_packages='
ubuntu-desktop-minimal,gdm3,gnome-shell,gnome-session,gnome-control-center,
gnome-initial-setup,
gnome-terminal,nautilus,gnome-text-editor,
gnome-snapshot,gstreamer1.0-gl,
mutter,xdg-desktop-portal-gnome,xdg-user-dirs,
yaru-theme-icon,yaru-theme-gtk,yaru-theme-sound,yaru-theme-gnome-shell,
gnome-keyring,libpam-gnome-keyring,
mesa-utils,mesa-vulkan-drivers,libgl1-mesa-dri,vulkan-tools,
libdrm-tests,edid-decode,
pipewire,pipewire-pulse,pipewire-audio,wireplumber,
pulseaudio-utils,
libspa-0.2-bluetooth,bluez,alsa-ucm-conf,alsa-utils,
iio-sensor-proxy,upower,power-profiles-daemon,
fprintd,libpam-fprintd,
fonts-ubuntu,language-pack-es,language-pack-gnome-es,
locales-all,
gnome-software,gnome-software-plugin-snap
'

packages=$(printf '%s' "$base_packages" | tr -d ' \n')
if [ "$profile" = desktop ]; then
	packages="$packages,$(printf '%s' "$desktop_packages" | tr -d ' \n')"
fi

# ---------------------------------------------------------------------------
# Customisation applied inside the same mmdebstrap invocation, so the rootfs is
# never modified afterwards by hand.
# ---------------------------------------------------------------------------

hooks=$base/hooks
rm -rf -- "$hooks"
mkdir -p "$hooks"

cat > "$hooks/configure.sh" <<HOOK
#!/bin/sh
set -eu
target="\$1"

# --- identity -------------------------------------------------------------
echo '$hostname' > "\$target/etc/hostname"
cat > "\$target/etc/hosts" <<EOF
127.0.0.1	localhost
127.0.1.1	$hostname
::1		localhost ip6-localhost ip6-loopback
fe00::0		ip6-localnet
ff00::0		ip6-mcastprefix
ff02::1		ip6-allnodes
ff02::2		ip6-allrouters
EOF

# --- locale, timezone and keyboard ---------------------------------------
# The first-boot wizard offers the languages the system actually has locales
# for, and an image that generated only one offered exactly one: Spanish, with
# no way to pick anything else.  locales-all carries all 327 of them
# pre-generated, which also keeps locale-gen — slow under emulation — out of
# the build.
#
# Every language pack ships too, so the desktop is actually translated in
# whichever language is picked and not just formatted for it.  That is about a
# gigabyte, which was judged too much once and is not: this is a tablet with
# 256 GB at the low end, and the alternative is a machine that offers you
# Japanese and then talks to you in English.
echo '$locale UTF-8' > "\$target/etc/locale.gen"
echo 'LANG=$locale' > "\$target/etc/default/locale"
ln -sf "/usr/share/zoneinfo/$timezone" "\$target/etc/localtime"
echo '$timezone' > "\$target/etc/timezone"
cat > "\$target/etc/default/keyboard" <<EOF
XKBMODEL="pc105"
XKBLAYOUT="$keymap"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"
EOF

# --- filesystems ----------------------------------------------------------
# Labels, never device numbers: microSD and UFS enumeration order is not
# guaranteed on this platform.
cat > "\$target/etc/fstab" <<EOF
LABEL=UBTS9U_ROOT	/	ext4	defaults,noatime,errors=remount-ro	0 1
LABEL=UBTS9U_BOOT	/boot	ext4	defaults,noatime	0 2
EOF

# --- initramfs --------------------------------------------------------------
# LZ4 legacy is mandatory: Samsung ABL concatenates the generic init_boot
# ramdisk with the vendor_boot fragment, and a gzip generic ramdisk makes Linux
# reject the initrd with "invalid magic at start of compressed archive".
# MODULES must not be "dep": that asks initramfs-tools to inspect the root
# device of the machine running the build, which here is the WSL host, and it
# fails with "failed to determine device for /".  "most" is safe and still tiny
# for this port, because the only modules installed are the two isolated ath12k
# ones; every critical provider is built into the kernel.
cat > "\$target/etc/initramfs-tools/initramfs.conf" <<EOF
MODULES=most
BUSYBOX=y
KEYMAP=n
COMPRESS=lz4
COMPRESSLEVEL=9
DEVICE=
NFSROOT=auto
RUNSIZE=10%
EOF

# --- network --------------------------------------------------------------
mkdir -p "\$target/etc/netplan"
cat > "\$target/etc/netplan/01-network-manager-all.yaml" <<EOF
network:
  version: 2
  renderer: NetworkManager
EOF
chmod 0600 "\$target/etc/netplan/01-network-manager-all.yaml"

# --- apt pockets ----------------------------------------------------------
cat > "\$target/etc/apt/sources.list.d/ubuntu.sources" <<EOF
Types: deb
URIs: $mirror
Suites: $suite $suite-updates $suite-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: $mirror
Suites: $suite-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
rm -f "\$target/etc/apt/sources.list"

# --- ssh ------------------------------------------------------------------
mkdir -p "\$target/etc/ssh/sshd_config.d"
cat > "\$target/etc/ssh/sshd_config.d/10-gts9uwifi.conf" <<EOF
PasswordAuthentication yes
PermitRootLogin no
EOF
HOOK
chmod +x "$hooks/configure.sh"

# Local packages: the device integration, plus the three sensor pieces Ubuntu
# does not ship at all.  All are installed inside the same mmdebstrap
# invocation, so the rootfs never depends on a manual dpkg run afterwards.
bash "$repo/scripts/build-companion-package.sh" >/dev/null

# libfprint has no upstream EL721 driver.  Build the full runtime with this
# board's secure QTEE backend; it replaces Noble's ABI-compatible package.
fingerprint_stamp=$base/out/packages/.gts9u-libfprint-inputs.sha256
fingerprint_fingerprint=$(
	{
		sha256sum "$repo/scripts/build-libfprint-el721.sh"
		find "$repo/packaging/libfprint" -type f -print0 |
			sort -z | xargs -0 sha256sum
	} | sha256sum | awk '{print $1}'
)
fingerprint_cached=$(cat "$fingerprint_stamp" 2>/dev/null || true)
fingerprint_missing=0
ls "$base"/out/packages/libfprint-2-2_*+gts9u*_arm64.deb \
	>/dev/null 2>&1 || fingerprint_missing=1
if [ "$fingerprint_missing" = 1 ] || \
   [ "$fingerprint_cached" != "$fingerprint_fingerprint" ]; then
	echo 'EL721 libfprint inputs changed or package is missing; rebuilding it'
	bash "$repo/scripts/build-libfprint-el721.sh" >/dev/null
	printf '%s\n' "$fingerprint_fingerprint" > "$fingerprint_stamp"
fi

# The device package embeds the native boot owner and matching signed IRQ
# module. Build these after libfprint has provided the pinned QTEE dependencies.
bash "$repo/scripts/build-fingerprint-secure-owner.sh" >/dev/null
bash "$repo/scripts/build-spss-irq-module.sh" >/dev/null
bash "$repo/scripts/build-device-package.sh" >/dev/null

# Companion's one-touch named test needs the additive matched-finger signal.
# Keep the original fprintd/PAM protocol and libfprint matcher unchanged.
fprintd_stamp=$base/out/packages/.gts9u-fprintd-inputs.sha256
fprintd_version=$(cat "$repo/packaging/fprintd/version")
fprintd_fingerprint=$(
	{
		sha256sum "$repo/scripts/build-fprintd-matched.sh" \
			"$repo/scripts/build-fprintd-pam-package.sh" \
			"$repo/scripts/check-fprintd-package-pair.sh" \
			"$repo/scripts/test-fprintd-packages.py"
		find "$repo/packaging/fprintd" -type f -print0 | sort -z | xargs -0 sha256sum
	} | sha256sum | awk '{print $1}'
)
if [ ! -f "$base/out/packages/fprintd_${fprintd_version}_arm64.deb" ] || \
   [ ! -f "$base/out/packages/libpam-fprintd_${fprintd_version}_arm64.deb" ] || \
   [ "$(cat "$fprintd_stamp" 2>/dev/null || true)" != "$fprintd_fingerprint" ]; then
	bash "$repo/scripts/build-fprintd-matched.sh" >/dev/null
	printf '%s\n' "$fprintd_fingerprint" > "$fprintd_stamp"
fi
bash "$repo/scripts/check-fprintd-package-pair.sh" \
	"$base/out/packages/fprintd_${fprintd_version}_arm64.deb" \
	"$base/out/packages/libpam-fprintd_${fprintd_version}_arm64.deb"

# The signed Samsung TA is proprietary.  A builder may opt in with an extracted
# directory; hashes are checked before a local, non-redistributable .deb exists.
fingerprint_firmware_package=
if [ -n "${GTS9U_FINGERPRINT_FIRMWARE_DIR:-}" ]; then
	bash "$repo/scripts/import-fingerprint-firmware.sh" \
		"$GTS9U_FINGERPRINT_FIRMWARE_DIR" >/dev/null
	fingerprint_firmware_package=ubuntu-gts9u-fingerprint-firmware
fi

# A package filename is not a valid cache key: the locally patched
# iio-sensor-proxy deliberately keeps its upstream version, so changing one of
# our patches used to leave an old .deb silently embedded in a fresh rootfs.
# Hash every input owned by this repository and rebuild when it changes.
sensor_stamp=$base/out/packages/.gts9u-sensor-inputs.sha256
sensor_fingerprint=$(
	{
		sha256sum "$repo/scripts/build-sensor-packages.sh"
		find "$repo/packaging/sensors" -type f -print0 |
			sort -z | xargs -0 sha256sum
	} | sha256sum | awk '{print $1}'
)
sensor_cached=$(cat "$sensor_stamp" 2>/dev/null || true)
sensor_missing=0
for pkg in libssc hexagonrpcd iio-sensor-proxy; do
	ls "$base"/out/packages/${pkg}_*.deb >/dev/null 2>&1 || sensor_missing=1
done
if [ "$sensor_missing" = 1 ] || [ "$sensor_cached" != "$sensor_fingerprint" ]; then
	echo 'sensor package inputs changed or packages are missing; rebuilding them'
	bash "$repo/scripts/build-sensor-packages.sh" >/dev/null
	printf '%s\n' "$sensor_fingerprint" > "$sensor_stamp"
fi

camera_stamp=$base/out/packages/.gts9u-camera-inputs.sha256
camera_fingerprint=$(
	{
		sha256sum "$repo/scripts/build-camera-packages.sh"
		find "$repo/packaging/libcamera" "$repo/packaging/pipewire" \
			-type f -print0 | sort -z | xargs -0 sha256sum
	} | sha256sum | awk '{print $1}'
)
camera_cached=$(cat "$camera_stamp" 2>/dev/null || true)
camera_missing=0
for pkg in libcamera-gts9u libspa-0.2-libcamera-gts9u; do
	ls "$base"/out/packages/${pkg}_*.deb >/dev/null 2>&1 || camera_missing=1
done
if [ "$camera_missing" = 1 ] || [ "$camera_cached" != "$camera_fingerprint" ]; then
	echo 'camera package inputs changed or packages are missing; rebuilding them'
	bash "$repo/scripts/build-camera-packages.sh" >/dev/null
	printf '%s\n' "$camera_fingerprint" > "$camera_stamp"
fi

# Noble lacks fastfetch and this port also carries the camera relay. Hash those
# inputs so a clean image cannot silently reuse the old manual GStreamer
# integration from a previous build.
extra_stamp=$base/out/packages/.gts9u-extra-inputs.sha256
extra_fingerprint=$(
	{
		sha256sum "$repo/scripts/build-extra-packages.sh"
		find "$repo/packaging/v4l2-relayd" \
			-type f -print0 | sort -z | xargs -0 sha256sum
	} | sha256sum | awk '{print $1}'
)
extra_cached=$(cat "$extra_stamp" 2>/dev/null || true)
extra_missing=0
for pkg in fastfetch v4l2-relayd-gts9u; do
	ls "$base"/out/packages/${pkg}_*.deb >/dev/null 2>&1 || extra_missing=1
done
if [ "$extra_missing" = 1 ] || [ "$extra_cached" != "$extra_fingerprint" ]; then
	echo 'extra package inputs changed or packages are missing; rebuilding them'
	bash "$repo/scripts/build-extra-packages.sh" >/dev/null
	printf '%s\n' "$extra_fingerprint" > "$extra_stamp"
fi

# Newest build of each, so repeated builds do not accumulate stale versions.
stage_debs=$base/out/local-debs
rm -rf -- "$stage_debs"
mkdir -p "$stage_debs"
for pkg in libssc hexagonrpcd iio-sensor-proxy \
	libfprint-2-2 $fingerprint_firmware_package \
	libcamera-gts9u libspa-0.2-libcamera-gts9u \
	ubuntu-gts9u-device ubuntu-gts9u-companion fastfetch v4l2-relayd-gts9u; do
	deb=$(ls -t "$base"/out/packages/${pkg}_*.deb 2>/dev/null | head -1 || true)
	if [ -z "$deb" ]; then
		echo "missing local package: $pkg" >&2
		exit 1
	fi
	cp "$deb" "$stage_debs/"
	echo "local package: ${deb##*/}"
done

# This exact matched pair was checked above. Do not pick each half separately
# by file mtime: a cached daemon/PAM from different builds can break all of APT.
cp "$base/out/packages/fprintd_${fprintd_version}_arm64.deb" \
	"$base/out/packages/libpam-fprintd_${fprintd_version}_arm64.deb" "$stage_debs/"

cat > "$hooks/local-packages.sh" <<HOOK
#!/bin/sh
set -eu
target="\$1"
mkdir -p "\$target/tmp/local-debs"
cp $stage_debs/*.deb "\$target/tmp/local-debs/"
# Install one local transaction so APT resolves both dependency order and the
# archive camera packages replaced by our ABI-matched builds.  Plain dpkg
# cannot remove an already installed package that a local .deb Conflicts with.
chroot "\$target" sh -c 'apt-get install -y /tmp/local-debs/*.deb'
chroot "\$target" apt-get check
rm -rf "\$target/tmp/local-debs"

# Every language pack.  mmdebstrap's --include takes no globs, so this is the
# place: apt expands the pattern itself.  Roughly a gigabyte, deliberately —
# see the note by locales-all above.
chroot "\$target" sh -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y \
	"language-pack-*" "language-pack-gnome-*" >/dev/null'
installed_langs=\$(chroot "\$target" sh -c \
	'dpkg-query -W -f "\${Package}\n" "language-pack-*" 2>/dev/null | wc -l')
echo "language packs installed: \$installed_langs"
[ "\$installed_langs" -gt 50 ] || {
	echo 'the language pack glob matched almost nothing' >&2
	exit 1
}

# OBS Studio used to ride along here: obs-v4l2-gts9u needed it, obs-studio
# recommends obs-plugins, and obs-plugins recommends vlc, which is how 77 MiB of
# VLC used to reach the image through the one apt-get in this build that honours
# Recommends.  The camera work it served as the verification tool for is closed,
# so the whole branch is gone and with it the purge-and-reinstall dance that kept
# VLC out without losing obs-plugins.
#
# Assert rather than assume.  None of the three should be reachable now, but
# each arrived as a Recommends of something else once already, and an image that
# silently grew a streaming studio and a media player again would only show up
# as size.
for unwanted in obs-studio obs-plugins vlc; do
	if chroot "\$target" dpkg-query -W -f '\${Status}' "\$unwanted" 2>/dev/null | \
		grep -q ' installed'; then
		echo "\$unwanted is installed; something pulled it back in" >&2
		exit 1
	fi
done
HOOK
chmod +x "$hooks/local-packages.sh"

cat > "$hooks/chroot-setup.sh" <<HOOK
#!/bin/sh
set -eu
target="\$1"

chroot "\$target" locale-gen
chroot "\$target" update-locale LANG=$locale

chroot "\$target" passwd -l root

if [ -n '$password' ]; then
	# Development image: an account the build knows, so SSH works before
	# anyone has touched the screen.
	chroot "\$target" useradd -m -s /bin/bash -G sudo,adm,dialout,cdrom,audio,video,plugdev,netdev,input,render '$username'
	echo '$username:$password' | chroot "\$target" chpasswd
	chroot "\$target" /usr/libexec/ubuntu-gts9u-enable-extension \
		'$username' flashlight@ubuntu-gts9u || true
	chroot "\$target" /usr/libexec/ubuntu-gts9u-enable-extension \
		'$username' gts9u-fingerprint-overlay@agcarbajo || true
	# Camera relays are system services backed by this user's PipeWire graph.
	# Keep its user manager alive from boot, including before the first
	# graphical login.
	chroot "\$target" /usr/libexec/ubuntu-gts9u-desktop-user || true
else
	# Shipping image: no account, so GDM runs gnome-initial-setup and the
	# owner creates their own.  GDM only takes that path when the machine has
	# no ordinary accounts at all, which is exactly the state of this rootfs,
	# and when it is told to.  Ubuntu ships custom.conf with every key
	# commented out, so the key has to be written rather than uncommented.
	mkdir -p "\$target/etc/gdm3"
	if grep -q '^InitialSetupEnable' "\$target/etc/gdm3/custom.conf" 2>/dev/null; then
		sed -i 's/^InitialSetupEnable.*/InitialSetupEnable=true/' \
			"\$target/etc/gdm3/custom.conf"
	else
		sed -i '/^\[daemon\]/a InitialSetupEnable=true' \
			"\$target/etc/gdm3/custom.conf"
	fi
	grep -q '^InitialSetupEnable=true' "\$target/etc/gdm3/custom.conf" || {
		echo 'could not enable the first-boot wizard in gdm3 custom.conf' >&2
		exit 1
	}
fi

chroot "\$target" systemctl enable ssh.service
chroot "\$target" systemctl enable NetworkManager.service
chroot "\$target" systemctl enable systemd-timesyncd.service || true
chroot "\$target" systemctl enable ubuntu-gts9u-grow-rootfs.service || true

# Persistent journal: the panel can stay dark long before a display manager
# starts, so the journal is the primary diagnostic channel.
mkdir -p "\$target/var/log/journal"
mkdir -p "\$target/etc/systemd/journald.conf.d"
cat > "\$target/etc/systemd/journald.conf.d/10-gts9uwifi-persistent.conf" <<EOF
[Journal]
Storage=persistent
SystemMaxUse=256M
EOF

# No apt-installed kernel: this port boots the mainline kernel written to the
# Android boot partition, and its modules are staged by the image pipeline.
cat > "\$target/etc/apt/preferences.d/no-distro-kernel" <<EOF
Package: linux-image-* linux-headers-* linux-generic*
Pin: release *
Pin-Priority: -1
EOF
HOOK
chmod +x "$hooks/chroot-setup.sh"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

rm -rf -- "$rootfs"
mkdir -p "$rootfs" "$base"

echo "building $profile rootfs: $suite arm64 -> $rootfs"
mmdebstrap \
	--architecture=arm64 \
	--variant=important \
	--components='main,restricted,universe,multiverse' \
	--include="$packages" \
	--customize-hook="$hooks/configure.sh" \
	--customize-hook="$hooks/local-packages.sh" \
	--customize-hook="$hooks/chroot-setup.sh" \
	--verbose \
	"$suite" \
	"$rootfs" \
	"deb $mirror $suite main restricted universe multiverse" \
	"deb $mirror $suite-updates main restricted universe multiverse" \
	"deb $mirror $suite-security main restricted universe multiverse"

# ---------------------------------------------------------------------------
# Kernel modules and optional development key
# ---------------------------------------------------------------------------

if [ -n "$modules_root" ]; then
	test -d "$modules_root"
	echo "staging kernel modules from $modules_root"
	cp -a "$modules_root/." "$rootfs/"
	chroot "$rootfs" depmod -a "$kernel_release"
	# initramfs-tools reads /boot/config-<release> to check that the kernel
	# actually supports the compressor we ask for; without it the LZ4
	# requirement degrades to an unverified warning.
	kernel_config=${KERNEL_CONFIG:-${modules_root%/modules-root}/config}
	if [ -f "$kernel_config" ]; then
		install -m 0644 "$kernel_config" \
			"$rootfs/boot/config-$kernel_release"
	else
		echo "WARNING: no kernel config at $kernel_config" >&2
	fi
else
	echo 'WARNING: no KERNEL_MODULES_ROOT given; /lib/modules is empty and' >&2
	echo '         update-initramfs cannot run yet.' >&2
fi

if [ -n "$authorized_keys" ] && [ -f "$authorized_keys" ]; then
	if [ -n "$password" ]; then
		install -d -m 0700 -o 1000 -g 1000 "$rootfs/home/$username/.ssh"
		install -m 0600 -o 1000 -g 1000 "$authorized_keys" \
			"$rootfs/home/$username/.ssh/authorized_keys"
	else
		# There is no home directory to put this in yet.  /etc/skel is copied
		# into whatever account the first-boot wizard creates, so the key
		# arrives with it and the owner's name never has to be guessed.
		install -d -m 0700 "$rootfs/etc/skel/.ssh"
		install -m 0600 "$authorized_keys" \
			"$rootfs/etc/skel/.ssh/authorized_keys"
	fi
fi

echo '=== rootfs summary ==='
du -sh "$rootfs"
chroot "$rootfs" dpkg-query -f '${binary:Package}\n' -W | wc -l | \
	sed 's/^/packages installed: /'
