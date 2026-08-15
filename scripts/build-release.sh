#!/bin/bash
# Produce a complete, installable release: kernel, rootfs, overlay, root
# filesystem image, Android v4 bundle, TWRP ZIP and a SHA-256 manifest.
#
# The release is a single flashable ZIP.  Everything the tablet needs is in it,
# including the root filesystem, which the installer writes into the internal
# UFS; there is no second file to write to a card by hand any more.
#
# Every stage is a separate script that can be run on its own; this only fixes
# the order and the data flow between them.  Nothing is flashed here: the owner
# flashes the ZIP from TWRP.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
version=${RELEASE_VERSION:?set RELEASE_VERSION, for example 0.1}
profile=${GTS9U_PROFILE:-desktop}
artifacts=${ARTIFACTS_DIR:-$repo/artifacts}

kernel_out=$base/out/kernel-gts9uwifi
rootfs=$base/rootfs
overlay=$base/out/rootfs-overlay
initramfs_overlay=$base/out/initramfs-overlay
bundle=$base/out/bundle
image=$base/out/ubuntu-gts9uwifi-v$version-ufs.img
zip=$artifacts/ubuntu-24.04-gts9uwifi-v$version-sm-x910-twrp.zip

# No secret is needed to build a shipping image any more: it has no account,
# and the owner creates theirs in the first-boot wizard.  GTS9U_PW is only for
# development images that must be reachable over SSH before anyone logs in.

step() { printf '\n########## %s\n' "$1"; }

step "1/7 kernel, device tree and isolated ath12k modules"
if [ "${SKIP_KERNEL:-0}" = 1 ] && [ -f "$kernel_out/Image.gz" ]; then
	echo 'reusing the existing kernel build'
else
	bash "$repo/scripts/build-mainline-kernel.sh"
fi

kernel_release=$(cat "$kernel_out/kernel.release")

step "2/7 Ubuntu $profile rootfs"
if [ "${SKIP_ROOTFS:-0}" = 1 ] && [ -d "$rootfs/etc" ]; then
	echo 'reusing the existing rootfs'
else
	GTS9U_PROFILE="$profile" \
	KERNEL_MODULES_ROOT="$kernel_out/modules-root" \
	KERNEL_RELEASE="$kernel_release" \
		bash "$repo/scripts/build-ubuntu-rootfs.sh"
fi

step "3/7 firmware and module overlay, and early Bluetooth firmware"
bash "$repo/scripts/build-rootfs-overlay.sh"

step "4/7 UFS root filesystem image and Ubuntu initramfs"
IMAGE_OUT="$image" KERNEL_RELEASE="$kernel_release" \
	bash "$repo/scripts/build-ufs-image.sh"

initramfs=$rootfs/boot/initrd.img-$kernel_release
test -f "$initramfs" || { echo "missing initramfs: $initramfs" >&2; exit 1; }

step "5/7 Android boot header v4 bundle"
INITRAMFS="$initramfs" \
INITRAMFS_OVERLAY_DIR="$initramfs_overlay" \
	bash "$repo/scripts/build-android-v4-bundle.sh"

step "6/7 TWRP ZIP"
mkdir -p "$artifacts"
python3 "$repo/scripts/make-twrp-zip.py" "$bundle" "$zip" \
	--project "$repo" \
	--rootfs "$image" \
	--label "Ubuntu 24.04 LTS v$version for SM-X910 (mainline $kernel_release)"

step "7/7 static validation and manifest"
bash "$repo/scripts/validate-bundle.sh" "$zip"

{
	printf 'Ubuntu 24.04 LTS for Samsung Galaxy Tab S9 Ultra Wi-Fi (SM-X910)\n'
	printf 'release: v%s (%s profile)\n' "$version" "$profile"
	printf 'generated: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	printf 'kernel_release: %s\n' "$kernel_release"
	printf 'kernel_source: %s\n' \
		"$(git -C "$base/linux-mainline" rev-parse HEAD)"
	printf 'port_revision: %s\n' "$(git -C "$repo" rev-parse HEAD)"
	printf '\n'
	printf 'install_target: internal UFS, linuxroot if present, else userdata\n'
	printf 'rootfs_image_sha256: %s\n' \
		"$(sha256sum "$image" | cut -d' ' -f1)"
	printf 'rootfs_image_bytes: %s\n' "$(stat -c %s "$image")"
	printf '\n'
	( cd "$artifacts" && sha256sum "${zip##*/}" )
	printf '\n'
	cat "$bundle/SHA256SUMS"
} > "$artifacts/MANIFEST-v$version.txt"

printf '\n=== release v%s ===\n' "$version"
cat "$artifacts/MANIFEST-v$version.txt"
printf '\nNothing was flashed. Flash the ZIP from TWRP, from external media.\n'
