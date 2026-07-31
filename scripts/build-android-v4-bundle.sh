#!/bin/bash
# Package the Ubuntu kernel and initramfs as the Android boot header v4 images
# the SM-X910 boot chain expects.
#
# Derived from scripts/build-android-v4-bundle.sh of the postmarketOS
# gts9uwifi port (MIT), with two changes: the kernel payload comes straight
# from our own build instead of an EFI zboot wrapper, and the vendor ramdisk
# fragment is normalised to mtime 0 so the image is byte-reproducible.
#
# This script never flashes anything.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
tools=${ANDROID_TOOLS:-$base/tools}
kernel_out=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}
out_dir=${BUNDLE_OUT_DIR:-$base/out/bundle}
initramfs=${INITRAMFS:?set INITRAMFS to the Ubuntu initramfs to package}
initramfs_overlay=${INITRAMFS_OVERLAY_DIR:-}

boot_size=100663296
init_boot_size=8388608
vendor_boot_size=100663296
dtbo_size=16777216
vbmeta_size=131072

mkbootimg=$tools/mkbootimg.py
avbtool=$tools/avbtool.py
image=$kernel_out/Image.gz
dtb=${KERNEL_DTB:-$kernel_out/sm8550-samsung-gts9uwifi.dtb}
cmdline_file=$repo/configs/vendor_boot/cmdline.txt
bootconfig=$repo/configs/vendor_boot/bootconfig.txt

for file in "$mkbootimg" "$avbtool" "$image" "$dtb" "$initramfs" \
	"$cmdline_file" "$bootconfig"; do
	test -f "$file" || { echo "missing input: $file" >&2; exit 1; }
done
if [ -n "$initramfs_overlay" ]; then
	test -d "$initramfs_overlay" || {
		echo "missing initramfs overlay: $initramfs_overlay" >&2
		exit 1
	}
fi

mkdir -p "$base/build" "$out_dir"
tmp=$(mktemp -d "$base/build/boot-bundle.XXXXXX")
cleanup() {
	case "$tmp" in
		"$base"/build/boot-bundle.*) rm -rf -- "$tmp" ;;
	esac
}
trap cleanup EXIT

add_hash_footer() {
	local target=$1 partition_name=$2 partition_size=$3 salt
	# Deterministic salt: a random one would change the image hash on every
	# rebuild even when nothing else did.
	salt=$(sha256sum "$target" | cut -d' ' -f1)
	python3 "$avbtool" add_hash_footer \
		--image "$target" \
		--partition_name "$partition_name" \
		--partition_size "$partition_size" \
		--salt "$salt"
}

cmdline=$(tr '\n' ' ' < "$cmdline_file" | sed 's/[[:space:]]*$//')

# Samsung's X910 ABL concatenates the generic init_boot ramdisk with the
# vendor_boot fragments, and stock uses the legacy LZ4 stream format for both.
# A gzip generic ramdisk is a valid Android v4 image but Linux rejects the
# resulting initrd with "invalid magic at start of compressed archive".
case $(head -c4 "$initramfs" | od -An -tx1 | tr -d ' \n') in
	02214c18)
		generic_ramdisk=$initramfs
		;;
	1f8b*)
		echo 'initramfs is gzip; recompressing to stock LZ4 legacy'
		generic_ramdisk=$tmp/initramfs.lz4
		gzip -dc "$initramfs" | lz4 -l -12 - "$generic_ramdisk" >/dev/null
		;;
	*)
		echo 'initramfs is neither LZ4 legacy nor gzip; refusing' >&2
		exit 1
		;;
esac

# Samsung ABL rejects a mainline base DTB through its downstream ufdt path.
# The validated route is an appended DTB plus a deliberately non-DT-table dtbo
# image, which makes ABL take that fallback.
boot_kernel=$tmp/Image.gz-dtb
cat "$image" "$dtb" > "$boot_kernel"

python3 "$mkbootimg" \
	--kernel "$boot_kernel" \
	--cmdline '' \
	--header_version 4 \
	--os_version 13 \
	--os_patch_level 2025-07 \
	-o "$out_dir/boot.img"
add_hash_footer "$out_dir/boot.img" boot "$boot_size"

python3 "$mkbootimg" \
	--ramdisk "$generic_ramdisk" \
	--header_version 4 \
	-o "$out_dir/init_boot.img"
add_hash_footer "$out_dir/init_boot.img" init_boot "$init_boot_size"

# ABL concatenates this platform fragment after the generic initramfs, so
# firmware placed here is available to built-in drivers during their first
# probe.  hci_qca in particular is built-in and runs long before the microSD
# root is mounted.
mkdir -p "$tmp/vendor-ramdisk"
if [ -n "$initramfs_overlay" ]; then
	cp -a "$initramfs_overlay/." "$tmp/vendor-ramdisk/"
fi
# cpio --reproducible normalises device and inode numbers but NOT mtime, so
# without this the fragment (and therefore vendor_boot.img) changes hash on
# every build even with identical contents.
find "$tmp/vendor-ramdisk" -exec touch -h -d '@0' {} +
(
	cd "$tmp/vendor-ramdisk"
	find . -print0 | LC_ALL=C sort -z \
		| cpio --reproducible --null -o --format=newc 2>/dev/null
) | lz4 -l -12 - "$tmp/vendor_ramdisk.lz4" >/dev/null

python3 "$mkbootimg" \
	--ramdisk_type platform \
	--ramdisk_name '' \
	--vendor_ramdisk_fragment "$tmp/vendor_ramdisk.lz4" \
	--dtb "$dtb" \
	--vendor_cmdline "$cmdline" \
	--header_version 4 \
	--vendor_boot "$out_dir/vendor_boot.img" \
	--base 0x80000000 \
	--kernel_offset 0x8000 \
	--ramdisk_offset 0x02000000 \
	--tags_offset 0x01e00000 \
	--pagesize 4096 \
	--dtb_offset 0x1f00000 \
	--vendor_bootconfig "$bootconfig"
add_hash_footer "$out_dir/vendor_boot.img" vendor_boot "$vendor_boot_size"

# Qualcomm ABL falls back to the appended kernel DTB when dtbo is not an
# Android DT table.  The zero prefix is deliberate; AVB still authenticates the
# full partition-sized image below.
rm -f "$out_dir/dtbo.img"
truncate -s 4096 "$out_dir/dtbo.img"
add_hash_footer "$out_dir/dtbo.img" dtbo "$dtbo_size"

python3 "$avbtool" make_vbmeta_image \
	--output "$out_dir/vbmeta.img" \
	--flags 2 \
	--padding_size "$vbmeta_size"

for spec in \
	"boot.img:$boot_size" \
	"init_boot.img:$init_boot_size" \
	"vendor_boot.img:$vendor_boot_size" \
	"dtbo.img:$dtbo_size" \
	"vbmeta.img:$vbmeta_size"; do
	name=${spec%%:*}
	expected=${spec##*:}
	actual=$(stat -c %s "$out_dir/$name")
	[ "$actual" -eq "$expected" ] || {
		echo "$name: expected $expected bytes, got $actual" >&2
		exit 1
	}
done

( cd "$out_dir" && sha256sum ./*.img > SHA256SUMS )
{
	printf 'kernel_source=%s\n' \
		"$(git -C "$base/linux-mainline" rev-parse HEAD)"
	printf 'kernel_release=%s\n' "$(cat "$kernel_out/kernel.release")"
	printf 'kernel_payload_sha256=%s\n' "$(sha256sum "$image" | cut -d' ' -f1)"
	printf 'boot_kernel_sha256=%s\n' "$(sha256sum "$boot_kernel" | cut -d' ' -f1)"
	printf 'kernel_config_sha256=%s\n' \
		"$(sha256sum "$kernel_out/config" | cut -d' ' -f1)"
	printf 'kernel_dtb_sha256=%s\n' "$(sha256sum "$dtb" | cut -d' ' -f1)"
	printf 'initramfs_source_sha256=%s\n' \
		"$(sha256sum "$initramfs" | cut -d' ' -f1)"
	printf 'initramfs_packaged_sha256=%s\n' \
		"$(sha256sum "$generic_ramdisk" | cut -d' ' -f1)"
} > "$out_dir/BUILD-METADATA.txt"

cat "$out_dir/SHA256SUMS"
