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
locale=${GTS9U_LOCALE:-es_ES.UTF-8}
timezone=${GTS9U_TIMEZONE:-Europe/Madrid}
keymap=${GTS9U_KEYMAP:-es}
kernel_release=${KERNEL_RELEASE:-7.2.0-rc3}
modules_root=${KERNEL_MODULES_ROOT:-}
authorized_keys=${GTS9U_AUTHORIZED_KEYS:-}
password=${GTS9U_PW:?set GTS9U_PW to the password for the graphical user}

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

base_packages='
ubuntu-minimal,ubuntu-standard,
systemd,systemd-sysv,systemd-resolved,udev,dbus,
initramfs-tools,busybox-initramfs,
e2fsprogs,dosfstools,parted,gdisk,
zstd,xz-utils,lz4,
sudo,locales,tzdata,console-setup,keyboard-configuration,
cloud-guest-utils,
netplan.io,network-manager,wpasupplicant,
openssh-server,avahi-daemon,
iputils-ping,curl,wget,ca-certificates,
nano,less,htop,rsync,
usbutils,pciutils,ethtool,evtest,i2c-tools,
strace,tree
'

desktop_packages='
ubuntu-desktop-minimal,gdm3,gnome-shell,gnome-session,gnome-control-center,
gnome-terminal,nautilus,gnome-text-editor,
mutter,xdg-desktop-portal-gnome,xdg-user-dirs,
mesa-utils,mesa-vulkan-drivers,libgl1-mesa-dri,vulkan-tools,
libdrm-tests,edid-decode,
pipewire,pipewire-pulse,pipewire-audio,wireplumber,
libspa-0.2-bluetooth,bluez,alsa-ucm-conf,alsa-utils,
iio-sensor-proxy,upower,power-profiles-daemon,
fonts-ubuntu,language-pack-es,language-pack-gnome-es
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

# The device package is built from packaging/ and installed here, inside the
# same invocation, so the rootfs never depends on a manual dpkg run afterwards.
device_deb=$(ls "$base"/out/packages/ubuntu-gts9u-device_*.deb 2>/dev/null | tail -1 || true)
if [ -z "$device_deb" ]; then
	bash "$repo/scripts/build-device-package.sh" >/dev/null
	device_deb=$(ls "$base"/out/packages/ubuntu-gts9u-device_*.deb | tail -1)
fi
echo "device package: $device_deb"

cat > "$hooks/device-package.sh" <<HOOK
#!/bin/sh
set -eu
target="\$1"
install -m 0644 '$device_deb' "\$target/tmp/ubuntu-gts9u-device.deb"
chroot "\$target" dpkg -i /tmp/ubuntu-gts9u-device.deb
rm -f "\$target/tmp/ubuntu-gts9u-device.deb"
HOOK
chmod +x "$hooks/device-package.sh"

cat > "$hooks/chroot-setup.sh" <<HOOK
#!/bin/sh
set -eu
target="\$1"

chroot "\$target" locale-gen
chroot "\$target" update-locale LANG=$locale

chroot "\$target" useradd -m -s /bin/bash -G sudo,adm,dialout,cdrom,audio,video,plugdev,netdev,input,render '$username'
echo '$username:$password' | chroot "\$target" chpasswd
chroot "\$target" passwd -l root

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
	--customize-hook="$hooks/device-package.sh" \
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
	install -d -m 0700 -o 1000 -g 1000 "$rootfs/home/$username/.ssh"
	install -m 0600 -o 1000 -g 1000 "$authorized_keys" \
		"$rootfs/home/$username/.ssh/authorized_keys"
fi

echo '=== rootfs summary ==='
du -sh "$rootfs"
chroot "$rootfs" dpkg-query -f '${binary:Package}\n' -W | wc -l | \
	sed 's/^/packages installed: /'
