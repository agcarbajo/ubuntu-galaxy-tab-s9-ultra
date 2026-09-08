#!/bin/sh
# Refresh only the saved Ubuntu boot image after a physically validated boot.
set -eu

usage()
{
	cat >&2 <<'EOF'
Usage: refresh-saved-ubuntu-boot.sh CANDIDATE EXPECTED_SHA256 --apply

The candidate and the active boot partition must both have EXPECTED_SHA256.
The script backs up the active partition and the previous saved image before
atomically replacing /var/lib/gts9u-boot-sets/ubuntu/boot.img. It never writes
the active partition or any other boot-set image.
EOF
	exit 2
}

[ "$#" -eq 3 ] || usage
candidate=$1
expected=$2
[ "$3" = --apply ] || usage

[ "$(id -u)" -eq 0 ] || {
	echo "Run this script as root (for example with pkexec)." >&2
	exit 1
}

case "$expected" in
	*[!0-9a-fA-F]*|'') echo "EXPECTED_SHA256 is not a hexadecimal digest." >&2; exit 2 ;;
esac
[ "${#expected}" -eq 64 ] || {
	echo "EXPECTED_SHA256 must contain 64 hexadecimal characters." >&2
	exit 2
}
expected=$(printf '%s' "$expected" | tr 'A-F' 'a-f')

boot_link=/dev/disk/by-partlabel/boot
saved=/var/lib/gts9u-boot-sets/ubuntu/boot.img
backup_root=/var/lib/gts9u-kernel-backups
expected_size=100663296

[ -f "$candidate" ] || { echo "Candidate is not a regular file: $candidate" >&2; exit 1; }
[ -f "$saved" ] || { echo "Saved Ubuntu boot image is missing: $saved" >&2; exit 1; }
[ -b "$boot_link" ] || { echo "The boot partition link is missing: $boot_link" >&2; exit 1; }

boot_device=$(readlink -f "$boot_link")
part_label=$(lsblk -dnro PARTLABEL "$boot_device")
part_size=$(lsblk -dnbro SIZE "$boot_device")
[ "$part_label" = boot ] || { echo "Refusing partition with label '$part_label'." >&2; exit 1; }
[ "$part_size" -eq "$expected_size" ] || {
	echo "Refusing boot partition with size $part_size (expected $expected_size)." >&2
	exit 1
}
[ "$(stat -c %s "$candidate")" -eq "$expected_size" ] || {
	echo "Candidate has the wrong size." >&2
	exit 1
}
[ "$(stat -c %s "$saved")" -eq "$expected_size" ] || {
	echo "Saved Ubuntu boot image has the wrong size." >&2
	exit 1
}

candidate_hash=$(sha256sum "$candidate" | awk '{print $1}')
active_hash=$(sha256sum "$boot_device" | awk '{print $1}')
saved_hash=$(sha256sum "$saved" | awk '{print $1}')
[ "$candidate_hash" = "$expected" ] || {
	echo "Candidate hash $candidate_hash does not match $expected." >&2
	exit 1
}
[ "$active_hash" = "$expected" ] || {
	echo "Active boot hash $active_hash does not match the validated candidate." >&2
	exit 1
}

umask 077
backup=$(mktemp -d "$backup_root/pre-saved-ubuntu-boot-sync-XXXXXXXX")
cleanup=
trap '[ -z "$cleanup" ] || rm -f "$cleanup"' EXIT HUP INT TERM

echo "Backing up the active and saved boot images to $backup"
dd if="$boot_device" of="$backup/active-boot.img" bs=4M iflag=fullblock status=none
cp --reflink=never --preserve=mode,timestamps "$saved" "$backup/saved-ubuntu-boot.img"
[ "$(sha256sum "$backup/active-boot.img" | awk '{print $1}')" = "$active_hash" ]
[ "$(sha256sum "$backup/saved-ubuntu-boot.img" | awk '{print $1}')" = "$saved_hash" ]

{
	printf 'boot_device=%s\n' "$boot_device"
	printf 'boot_partlabel=%s\n' "$part_label"
	printf 'boot_size=%s\n' "$part_size"
	printf 'active_sha256=%s\n' "$active_hash"
	printf 'previous_saved_sha256=%s\n' "$saved_hash"
	printf 'candidate_sha256=%s\n' "$candidate_hash"
	printf 'candidate=%s\n' "$candidate"
} > "$backup/manifest.txt"

cleanup="$(dirname "$saved")/.boot.img.new.$$"
install -o root -g root -m 0644 "$candidate" "$cleanup"
[ "$(sha256sum "$cleanup" | awk '{print $1}')" = "$expected" ]
sync "$cleanup" "$backup/active-boot.img" "$backup/saved-ubuntu-boot.img" "$backup/manifest.txt"
mv -f "$cleanup" "$saved"
cleanup=
sync "$saved"

final_hash=$(sha256sum "$saved" | awk '{print $1}')
[ "$final_hash" = "$expected" ] || {
	echo "Saved image verification failed after replacement." >&2
	exit 1
}

echo "Saved Ubuntu boot image now matches active boot: $final_hash"
echo "Recovery copy: $backup/saved-ubuntu-boot.img"
