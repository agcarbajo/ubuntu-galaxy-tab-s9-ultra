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
need qemu-aarch64-static 'apt install qemu-user-static'
need dpkg-deb 'apt install dpkg'
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
need dtc 'apt install device-tree-compiler'
need python3 'apt install python3'
need xz 'apt install xz-utils'
need zstd 'apt install zstd'
need unzip 'apt install unzip'

echo '=== aarch64 emulation ==='
if [ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
	echo 'OK    binfmt qemu-aarch64 registered'
else
	echo 'MISS  binfmt qemu-aarch64 (apt install binfmt-support qemu-user-static)'
	missing=$((missing + 1))
fi

echo
if [ "$missing" -eq 0 ]; then
	echo 'All build dependencies are present.'
else
	echo "$missing dependency/dependencies missing."
fi
exit 0
