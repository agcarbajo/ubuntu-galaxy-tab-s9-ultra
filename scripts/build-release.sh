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
version=${RELEASE_VERSION:-$(tr -d '[:space:]' < "$repo/VERSION")}
suite=${UBUNTU_SUITE:-resolute}
migration_backend=${MIGRATION_BACKEND:-}
case "$suite" in
	noble) ubuntu_version=24.04; update_format=1 ;;
	resolute)
		ubuntu_version=26.04; update_format=2
		# Resolute used to require the migration backend unconditionally,
		# because the only Resolute release there had ever been was the one
		# that carried 1.3.0 installations across from Noble.  Every release
		# is Resolute now, and an ordinary 26.04 port release has no
		# distribution to migrate: without a backend the payload is an
		# update_kind=port release whose source_suites is Resolute alone, so a
		# Noble tablet refuses it instead of half-taking it.  Naming a backend
		# that is not there is still always a mistake.
		if [ -n "$migration_backend" ] && [ ! -f "$migration_backend" ]; then
			echo "MIGRATION_BACKEND is set to '$migration_backend', which is not a file" >&2
			exit 2
		fi
		;;
	*) echo "unsupported release suite: $suite" >&2; exit 2 ;;
esac
if [ -n "$migration_backend" ]; then
	echo "building a $ubuntu_version release that migrates Noble installations"
else
	echo "building an ordinary $ubuntu_version port release (no distribution migration)"
fi
export UBUNTU_SUITE="$suite"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
	echo "invalid release version: $version" >&2
	exit 2
}
# A release has to say which revision it was built from.  The manifest falls
# back to `git -C "$repo" rev-parse HEAD` when there is no BUILD-SOURCE.json,
# and that prints nothing at all when the build runs from an immutable
# snapshot -- which is the recommended way to build.  An empty port_revision
# is precisely the line the manifest exists for, and it was only noticed after
# a complete build, so the check is here instead of at step 7.
if [ ! -f "$repo/BUILD-SOURCE.json" ] && ! git -C "$repo" rev-parse HEAD >/dev/null 2>&1; then
	echo "no provenance for this build: $repo has neither BUILD-SOURCE.json nor a git checkout" >&2
	echo 'freeze the tree with scripts/snapshot-build-source.py --output <path> and build from it' >&2
	exit 2
fi
profile=${GTS9U_PROFILE:-desktop}
artifacts=${ARTIFACTS_DIR:-$repo/artifacts}

kernel_out=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}
rootfs=${ROOTFS_DIR:-$base/rootfs}
overlay=${OVERLAY_OUT_DIR:-$base/out/rootfs-overlay}
initramfs_overlay=${INITRAMFS_OVERLAY_DIR:-$base/out/initramfs-overlay}
bundle=${BUNDLE_OUT_DIR:-$base/out/bundle}
image=${IMAGE_OUT:-$base/out/ubuntu-gts9uwifi-v$version-ufs.img}
payload=${UPDATE_PAYLOAD_OUT_DIR:-$base/out/update-payload}
zip=$artifacts/ubuntu-$ubuntu_version-sm-x910-v$version.zip
export ROOTFS_DIR="$rootfs" BUNDLE_OUT_DIR="$bundle" KERNEL_OUT_DIR="$kernel_out"
if [ -e "$zip" ] || [ -e "$image" ]; then
	echo 'refusing to overwrite an existing release ZIP or filesystem image' >&2
	exit 2
fi

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
	if ! grep -qx "VERSION_ID=\"$ubuntu_version\"" "$rootfs/etc/os-release"; then
		echo "refusing to reuse a rootfs that is not Ubuntu $ubuntu_version" >&2
		exit 2
	fi
	echo 'reusing the existing rootfs'
else
	GTS9U_PROFILE="$profile" \
	KERNEL_MODULES_ROOT="$kernel_out/modules-root" \
	KERNEL_RELEASE="$kernel_release" \
		bash "$repo/scripts/build-ubuntu-rootfs.sh"
fi

python3 "$repo/scripts/sanitize-release-rootfs.py" "$rootfs"

step "3/7 firmware and module overlay, and early Bluetooth firmware"
if [ "${SKIP_OVERLAY:-0}" = 1 ]; then
	test -d "$overlay/usr/lib/modules/$kernel_release"
	test -d "$overlay/usr/lib/firmware"
	test -d "$initramfs_overlay/usr/lib/firmware/qca"
else
	bash "$repo/scripts/build-rootfs-overlay.sh"
fi

step "4/7 UFS root filesystem image and Ubuntu initramfs"
python3 - "$rootfs" "$version" "$kernel_release" <<'PY'
import json, pathlib, sys
root, version, kernel = sys.argv[1:]
pathlib.Path(root, 'usr/lib/gts9u-release.json').write_text(json.dumps({
    'device': 'gts9uwifi', 'version': version, 'tag': 'v' + version,
    'kernel_release': kernel}) + '\n')
PY
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
payload_options=(--suite "$suite" --update-format "$update_format" --rootfs "$rootfs")
if [ -n "${LOCAL_DEBS_INPUT_DIR:-}" ]; then payload_options+=(--local-debs "$LOCAL_DEBS_INPUT_DIR"); fi
if [ -n "$migration_backend" ]; then
	payload_options+=(--migration-backend "$migration_backend" --hardware-revision "${HARDWARE_REVISION:-3}")
fi
if [ -n "${UPDATE_PAYLOAD_OUT_DIR:-}" ]; then payload_options+=(--output "$payload"); fi
python3 "$repo/scripts/build-update-payload.py" --base "$base" --version "$version" \
	--bootstrap "$base/out/gts9u-update-v$version.pyz" "${payload_options[@]}"
python3 "$repo/scripts/make-twrp-zip.py" "$bundle" "$zip" \
	--project "$repo" \
	--update-payload "$payload" \
	--rootfs "$image" \
	--label "Ubuntu $ubuntu_version LTS v$version for SM-X910 (mainline $kernel_release)"

step "7/7 static validation and manifest"
bash "$repo/scripts/validate-bundle.sh" "$zip"
python3 "$repo/scripts/validate-update-zip.py" "$zip"

{
	printf 'Ubuntu %s LTS for Samsung Galaxy Tab S9 Ultra Wi-Fi (SM-X910)\n' "$ubuntu_version"
	printf 'release: v%s (%s profile)\n' "$version" "$profile"
	printf 'generated: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	printf 'kernel_release: %s\n' "$kernel_release"
	printf 'kernel_source: %s\n' \
		"$(git -C "$base/linux-mainline" rev-parse HEAD)"
	if [ -f "$repo/BUILD-SOURCE.json" ]; then
		python3 - "$repo/BUILD-SOURCE.json" <<'PY'
import json, pathlib, sys
source = json.loads(pathlib.Path(sys.argv[1]).read_text())
print('port_revision:', source['port_revision'])
print('port_source_tree_sha256:', source['source_tree_sha256'])
PY
	else
		printf 'port_revision: %s\n' "$(git -C "$repo" rev-parse HEAD)"
	fi
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
