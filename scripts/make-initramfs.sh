#!/bin/bash
# Generate the Ubuntu initramfs inside an already built rootfs and check that
# it is the stream Samsung's ABL accepts and that it fits init_boot.
#
# Both image builders need exactly this, and an initramfs that differs between
# the microSD and the UFS install would be the kind of divergence that only
# shows up as a black panel.  It lives here so there is one copy of it.
#
# It writes only inside the rootfs directory and prints the resulting path on
# stdout.  Nothing is flashed.
set -euo pipefail

base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
rootfs=${ROOTFS_DIR:-$base/rootfs}
kernel_out=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}
kernel_release=${KERNEL_RELEASE:-$(cat "$kernel_out/kernel.release" 2>/dev/null || echo 7.2.0-rc3)}

test -d "$rootfs/etc" || { echo "missing rootfs: $rootfs" >&2; exit 1; }
test -d "$rootfs/usr/lib/modules/$kernel_release" || \
	test -d "$rootfs/lib/modules/$kernel_release" || {
	echo "rootfs has no modules for $kernel_release" >&2
	exit 1
}

echo "generating the initramfs for $kernel_release" >&2
mount --bind /dev "$rootfs/dev"
mount -t proc proc "$rootfs/proc"
mount -t sysfs sys "$rootfs/sys"
unmount_pseudo() {
	umount -l "$rootfs/sys" 2>/dev/null || true
	umount -l "$rootfs/proc" 2>/dev/null || true
	umount -l "$rootfs/dev" 2>/dev/null || true
}
trap unmount_pseudo EXIT

chroot "$rootfs" update-initramfs -c -k "$kernel_release" >&2

initramfs=$rootfs/boot/initrd.img-$kernel_release
test -f "$initramfs" || { echo "update-initramfs produced nothing" >&2; exit 1; }

magic=$(head -c4 "$initramfs" | od -An -tx1 | tr -d ' \n')
if [ "$magic" != 02214c18 ]; then
	echo "initramfs is not LZ4 legacy (magic $magic)" >&2
	echo 'Samsung ABL needs the stock LZ4 legacy stream; check' >&2
	echo '/etc/initramfs-tools/initramfs.conf COMPRESS=lz4' >&2
	exit 1
fi

size=$(stat -c %s "$initramfs")
limit=$((8388608 - 8192))
echo "initramfs: $size bytes (init_boot budget $limit)" >&2
if [ "$size" -gt "$limit" ]; then
	echo 'initramfs does not fit init_boot minus its AVB footer' >&2
	echo 'reduce MODULES or move modules to the boot partition' >&2
	exit 1
fi

unmount_pseudo
trap - EXIT

printf '%s\n' "$initramfs"
