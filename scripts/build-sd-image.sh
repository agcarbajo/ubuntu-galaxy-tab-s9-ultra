#!/bin/bash
# Assemble the two-partition microSD image from an already built Ubuntu rootfs,
# and generate the Ubuntu initramfs inside it.
#
# It writes only to a regular file under the build base.  It never accepts a
# block device and therefore cannot overwrite a physical card.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
rootfs=${ROOTFS_DIR:-$base/rootfs}
out=${IMAGE_OUT:-$base/out/ubuntu-gts9uwifi.img}
kernel_out=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}
kernel_release=${KERNEL_RELEASE:-$(cat "$kernel_out/kernel.release" 2>/dev/null || echo 7.2.0-rc3)}
boot_mb=${BOOT_PART_MB:-256}
slack_mb=${ROOT_SLACK_MB:-1536}
boot_label=UBTS9U_BOOT
root_label=UBTS9U_ROOT

test -d "$rootfs/etc" || { echo "missing rootfs: $rootfs" >&2; exit 1; }
test -d "$rootfs/usr/lib/modules/$kernel_release" || \
	test -d "$rootfs/lib/modules/$kernel_release" || {
	echo "rootfs has no modules for $kernel_release" >&2
	exit 1
}

case "$out" in
	/dev/*) echo 'refusing to write to a block device' >&2; exit 1 ;;
esac
[ -b "$out" ] && { echo "refusing: $out is a block device" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Generate the Ubuntu initramfs inside the rootfs
# ---------------------------------------------------------------------------

initramfs=$(ROOTFS_DIR="$rootfs" KERNEL_OUT_DIR="$kernel_out" \
	KERNEL_RELEASE="$kernel_release" \
	bash "$repo/scripts/make-initramfs.sh")

# ---------------------------------------------------------------------------
# Image geometry
# ---------------------------------------------------------------------------

root_mb=$(( $(du -sm --apparent-size "$rootfs" | cut -f1) + slack_mb ))
total_mb=$(( 1 + boot_mb + root_mb + 1 ))

echo "image: ${total_mb} MiB (boot ${boot_mb} MiB, root ${root_mb} MiB)"
rm -f "$out"
truncate -s "${total_mb}M" "$out"

# The image is a freshly recreated regular file, so there is no stale GPT to
# wipe.  Do not use `sgdisk --zap-all` here: gdisk calls the global sync(2),
# which can block indefinitely in WSL 2 (observed with kernel 6.6.87.2) even on
# a new 16 MiB test image.  sfdisk uses the same GPT layout without that WSL
# failure mode.  The physical-media installation procedure still wipes the SD
# with `sgdisk --zap-all` before writing the finished image.
boot_sectors=$((boot_mb * 2048))
root_start=$((2048 + boot_sectors))
sfdisk "$out" <<EOF
label: gpt
unit: sectors
first-lba: 2048

start=2048, size=${boot_sectors}, type=linux, name="${boot_label}"
start=${root_start}, type=linux, name="${root_label}"
EOF
sfdisk --dump "$out"

loop=$(losetup --find --show --partscan "$out")
used_kpartx=0
release_loop() {
	sync
	umount "$base/mnt/boot" 2>/dev/null || true
	umount "$base/mnt/root" 2>/dev/null || true
	[ "$used_kpartx" = 1 ] && kpartx -d "$loop" 2>/dev/null
	losetup -d "$loop" 2>/dev/null || true
}
trap release_loop EXIT

# There is no udev in this build environment, so the partition nodes that
# --partscan asks for are not guaranteed to appear.  Nudge the kernel, wait,
# and fall back to device-mapper rather than assuming /dev/loopNpM exists.
partprobe "$loop" 2>/dev/null || partx -u "$loop" 2>/dev/null || true
for _ in $(seq 20); do
	[ -b "${loop}p1" ] && [ -b "${loop}p2" ] && break
	sleep 0.5
done

if [ -b "${loop}p1" ] && [ -b "${loop}p2" ]; then
	part1=${loop}p1
	part2=${loop}p2
else
	echo 'partition nodes did not appear; falling back to kpartx'
	kpartx -a -s "$loop"
	used_kpartx=1
	name=${loop##*/}
	part1=/dev/mapper/${name}p1
	part2=/dev/mapper/${name}p2
	[ -b "$part1" ] && [ -b "$part2" ] || {
		echo 'kpartx did not create the partition mappings either' >&2
		exit 1
	}
fi
echo "partitions: $part1 $part2"

# The root filesystem keeps its journal, and says so loudly when it breaks.
#
# It was created with -O ^has_journal to spare the microSD some writes.  That
# is the wrong trade for the root of a tablet the owner power-cycles: without a
# journal every unclean shutdown can leave unattached inodes and bitmap damage,
# and it did.  On 2026-08-03 the accumulated damage reached the point where
# e2fsck refused to fix it unattended, systemd-fsck-root failed, and systemd
# dropped to emergency.target.  With no display manager running that presents
# as a tablet that will not turn on, which is a miserable thing to debug from a
# black screen.
#
# errors=remount-ro compounds the point: the default, "continue", lets ext4
# carry on after detecting corruption, so damage accumulates silently until the
# day it does not.  Read-only is visible, survivable and repairable.
mkfs.ext4 -q -F -L "$boot_label" "$part1"
mkfs.ext4 -q -F -L "$root_label" -e remount-ro "$part2"

mkdir -p "$base/mnt/boot" "$base/mnt/root"
mount "$part2" "$base/mnt/root"
mount "$part1" "$base/mnt/boot"

echo 'copying the rootfs'
tar -C "$rootfs" --numeric-owner --xattrs --acls -cf - . \
	| tar -C "$base/mnt/root" --numeric-owner --xattrs --acls -xf -

# /boot lives on its own partition: the second-stage initramfs pieces and the
# reference DTB go there, and the copy under the root filesystem is removed so
# the two do not silently diverge.
mkdir -p "$base/mnt/boot"
cp -a "$base/mnt/root/boot/." "$base/mnt/boot/"
rm -rf "$base/mnt/root/boot"/*
install -m 0644 "$kernel_out/sm8550-samsung-gts9uwifi.dtb" \
	"$base/mnt/boot/sm8550-samsung-gts9uwifi.dtb"
{
	printf 'kernel_release=%s\n' "$kernel_release"
	printf 'kernel_image_sha256=%s\n' \
		"$(sha256sum "$kernel_out/Image.gz" | cut -d' ' -f1)"
	printf 'kernel_dtb_sha256=%s\n' \
		"$(sha256sum "$kernel_out/sm8550-samsung-gts9uwifi.dtb" | cut -d' ' -f1)"
	printf 'initramfs_sha256=%s\n' "$(sha256sum "$initramfs" | cut -d' ' -f1)"
	printf 'built=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$base/mnt/boot/BUILD-METADATA.txt"

sync
release_loop
trap - EXIT

echo '=== image ==='
stat -c '%n %s bytes' "$out"
sha256sum "$out"
