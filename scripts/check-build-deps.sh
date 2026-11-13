#!/bin/bash
# Report which host tools the Ubuntu image pipeline needs and which are
# missing.  Read-only: it installs nothing and touches no device.
set -uo pipefail

missing=0

need() {
	if command -v "$1" >/dev/null 2>&1; then
		printf 'OK    %-20s %s\n' "$1" "$(command -v "$1")"
	else
		printf 'MISS  %-20s (%s)\n' "$1" "$2"
		missing=$((missing + 1))
	fi
}

echo '=== rootfs construction ==='
need mmdebstrap 'apt install mmdebstrap'
if command -v qemu-aarch64-static >/dev/null 2>&1; then
	need qemu-aarch64-static 'apt install qemu-user-static'
else
	need qemu-aarch64 'apt install qemu-user-binfmt (or its HWE provider)'
fi
need dpkg-deb 'apt install dpkg'
need msgfmt 'apt install gettext (flashlight tile translations)'
need glib-compile-resources 'apt install libglib2.0-dev-bin (Tab Companion resources)'
need glib-compile-schemas 'apt install libglib2.0-bin (Tab Companion settings)'
need desktop-file-validate 'apt install desktop-file-utils (Tab Companion launcher)'
need appstreamcli 'apt install appstream (Tab Companion metadata)'
need debootstrap 'apt install debootstrap (fallback only)'

echo '=== image assembly ==='
need sgdisk 'apt install gdisk'
need parted 'apt install parted'
need kpartx 'apt install kpartx'
need mkfs.ext4 'apt install e2fsprogs'
need resize2fs 'apt install e2fsprogs'

echo '=== Android v4 packaging ==='
need lz4 'apt install lz4'
need cpio 'apt install cpio'
need readelf 'apt install binutils'
need dtc 'apt install device-tree-compiler'
need python3 'apt install python3'
need xz 'apt install xz-utils'
need zstd 'apt install zstd'
need unzip 'apt install unzip'

echo '=== aarch64 emulation ==='
if [ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
	echo 'OK    binfmt qemu-aarch64 registered'
	# The registration alone is not the whole story.  mmdebstrap execs the
	# interpreter *inside* the arm64 chroot, so a dynamically linked one has
	# to find its x86-64 shared libraries there and does not.  Noble registers
	# a symlink to the static build; Questing and later dropped that package
	# and `qemu-user-binfmt` registers the dynamic emulator from `qemu-user`.
	# Report it here rather than let the rootfs build die inside a chroot.
	interpreter=$(awk '$1 == "interpreter" { print $2 }' \
		/proc/sys/fs/binfmt_misc/qemu-aarch64)
	flags=$(awk '$1 == "flags:" { print $2 }' \
		/proc/sys/fs/binfmt_misc/qemu-aarch64)
	if [ -n "$interpreter" ] && command -v file >/dev/null 2>&1; then
		if file -bL "$interpreter" 2>/dev/null | grep -q 'static'; then
			printf 'OK    %-20s %s (flags %s)\n' 'static interpreter' \
				"$interpreter" "${flags:-none}"
		else
			printf 'WARN  %-20s %s (flags %s)\n' 'dynamic interpreter' \
				"$interpreter" "${flags:-none}"
			echo '      mmdebstrap runs this inside the arm64 chroot, where its'
			echo '      libraries are absent.  Install a static build if the'
			echo '      archive still has one, or build the rootfs in a'
			echo '      container that carries the host libraries.'
		fi
	fi
else
	echo 'MISS  binfmt qemu-aarch64 (apt install binfmt-support and the package'
	echo '      scripts/select-qemu-user-package.sh picks for this host)'
	missing=$((missing + 1))
fi

echo
if [ "$missing" -eq 0 ]; then
	echo 'All build dependencies are present.'
else
	echo "$missing dependency/dependencies missing."
fi
exit 0
