#!/bin/bash
# Assemble the ext4 root filesystem image that the TWRP ZIP writes into the
# tablet's internal UFS.
#
# The image is a bare filesystem, not a disk: it carries no partition table,
# because it is written into a partition that already exists.  The installer
# copies it onto `userdata` with dd, so nothing on this device ever creates,
# moves, resizes or deletes a partition, and the GPT Samsung shipped stays
# exactly as it is.
#
# Unlike the microSD image there is no separate boot partition: /boot stays
# inside the root filesystem.  ABL loads the kernel from the `boot` partition
# and never reads a filesystem, so a second partition would carry nothing the
# tablet needs and would mean asking for a partition we are not going to make.
#
# It writes only to a regular file under the build base.  It never accepts a
# block device and therefore cannot overwrite the tablet or a card.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
rootfs=${ROOTFS_DIR:-$base/rootfs}
overlay=${OVERLAY_OUT_DIR:-$base/out/rootfs-overlay}
out=${IMAGE_OUT:-$base/out/ubuntu-gts9uwifi-ufs.img}
kernel_out=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}
kernel_release=${KERNEL_RELEASE:-$(cat "$kernel_out/kernel.release" 2>/dev/null || echo 7.2.0-rc3)}
slack_mb=${ROOT_SLACK_MB:-512}
root_label=${ROOT_LABEL:-UBTS9U_UFS}
# The whole image travels inside the ZIP, and the owner has to download it and
# write it through TWRP's unzip.  Keeping it small is what makes that bearable:
# the filesystem is grown to the full partition on first boot anyway.
max_mb=${UFS_IMAGE_MAX_MB:-4096}

test -d "$rootfs/etc" || { echo "missing rootfs: $rootfs" >&2; exit 1; }
test -d "$rootfs/usr/lib/modules/$kernel_release" || \
	test -d "$rootfs/lib/modules/$kernel_release" || {
	echo "rootfs has no modules for $kernel_release" >&2
	exit 1
}
test -d "$overlay" || {
	echo "missing rootfs overlay: $overlay" >&2
	echo 'run scripts/build-rootfs-overlay.sh first' >&2
	exit 1
}

case "$out" in
	/dev/*) echo 'refusing to write to a block device' >&2; exit 1 ;;
esac
[ -b "$out" ] && { echo "refusing: $out is a block device" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Ubuntu initramfs
# ---------------------------------------------------------------------------

initramfs=$(ROOTFS_DIR="$rootfs" KERNEL_OUT_DIR="$kernel_out" \
	KERNEL_RELEASE="$kernel_release" \
	bash "$repo/scripts/make-initramfs.sh")

# ---------------------------------------------------------------------------
# Filesystem geometry
# ---------------------------------------------------------------------------

content_mb=$(( $(du -sm --apparent-size "$rootfs" | cut -f1) \
	+ $(du -sm --apparent-size "$overlay" | cut -f1) ))
image_mb=$(( content_mb + slack_mb ))

echo "image: ${image_mb} MiB (content ${content_mb} MiB, slack ${slack_mb} MiB)"
if [ "$image_mb" -gt "$max_mb" ]; then
	echo "the image is larger than the ${max_mb} MiB budget" >&2
	echo 'raise UFS_IMAGE_MAX_MB deliberately, or take content out' >&2
	exit 1
fi

rm -f "$out"
truncate -s "${image_mb}M" "$out"

# Same two decisions as the microSD image, for the same reasons: the journal
# stays, because an unclean power-off without one accumulates damage until
# e2fsck refuses to fix it unattended; and errors=remount-ro makes corruption
# visible and survivable instead of silently compounding.
#
# -E resize=... is what lets first boot grow this filesystem to the whole
# userdata partition.  Without enough reserved group descriptor blocks,
# resize2fs on a 939 GiB partition would need an offline pass; with them the
# online resize on first boot is a few seconds.  The value is 1 TiB in 4 KiB
# blocks, which covers the 939 GiB userdata of every SM-X910 variant.
mkfs.ext4 -q -F -L "$root_label" -e remount-ro \
	-E resize=268435456 "$out"

mnt=$base/mnt/ufs
mkdir -p "$mnt"
mount -o loop "$out" "$mnt"
release_mount() {
	sync
	umount "$mnt" 2>/dev/null || true
}
trap release_mount EXIT

echo 'copying the rootfs'
# GNU tar's --xattrs carries only the user.* namespace by default, so
# security.capability is dropped in silence: every image this port built before
# this line shipped a ping without cap_net_raw and a snap-confine without its
# capability set.  Nothing warns; the binaries simply lose privileges they were
# built with, and it surfaces much later as "why does this need sudo now".
tar -C "$rootfs" --numeric-owner --acls \
	--xattrs --xattrs-include='*' -cf - . \
	| tar -C "$mnt" --numeric-owner --acls \
	--xattrs --xattrs-include='*' -xf -

# The firmware and the isolated ath12k modules are installed here rather than
# by the installer.  On the microSD they had to be applied at flash time,
# because the card was written by hand from a different machine; the UFS image
# is built in one place, so the card's "incomplete until step 2" state simply
# does not exist any more.
echo 'merging the firmware and module overlay'
tar -C "$overlay" --numeric-owner -cf - . \
	| tar -C "$mnt" --numeric-owner -xf -

# /boot is part of the root filesystem here, so the fstab entry for the
# microSD boot partition would fail at every boot.  The root entry has to name
# the label this image actually carries.
fstab=$mnt/etc/fstab
test -f "$fstab" || { echo 'the rootfs has no /etc/fstab' >&2; exit 1; }
sed -i -e '/UBTS9U_BOOT/d' -e "s/UBTS9U_ROOT/$root_label/" "$fstab"
grep -q "LABEL=$root_label[[:space:]]\+/[[:space:]]" "$fstab" || {
	echo 'the rewritten fstab has no root entry' >&2
	cat "$fstab" >&2
	exit 1
}

install -m 0644 "$kernel_out/sm8550-samsung-gts9uwifi.dtb" \
	"$mnt/boot/sm8550-samsung-gts9uwifi.dtb"
{
	printf 'kernel_release=%s\n' "$kernel_release"
	printf 'root_label=%s\n' "$root_label"
	printf 'install_target=%s\n' 'internal UFS, linuxroot if present, else userdata'
	printf 'kernel_image_sha256=%s\n' \
		"$(sha256sum "$kernel_out/Image.gz" | cut -d' ' -f1)"
	printf 'kernel_dtb_sha256=%s\n' \
		"$(sha256sum "$kernel_out/sm8550-samsung-gts9uwifi.dtb" | cut -d' ' -f1)"
	printf 'initramfs_sha256=%s\n' "$(sha256sum "$initramfs" | cut -d' ' -f1)"
	printf 'built=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$mnt/boot/BUILD-METADATA.txt"

sync
release_mount
trap - EXIT

# A filesystem that is not clean here would be dd'd onto the tablet dirty, and
# the first thing the tablet would do with it is fsck it in the dark.
e2fsck -fp "$out" || {
	rc=$?
	[ "$rc" -le 1 ] || { echo "e2fsck rejected the finished image ($rc)" >&2; exit 1; }
}

echo '=== image ==='
stat -c '%n %s bytes' "$out"
sha256sum "$out"
