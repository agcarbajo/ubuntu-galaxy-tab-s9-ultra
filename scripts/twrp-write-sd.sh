#!/bin/bash
# Write a microSD image to the card inserted in the tablet, over ADB, with the
# tablet sitting in TWRP.  Useful when the build machine has no card reader.
#
# It inspects and reports by default.  Writing requires both --write and an
# explicit --device, and every guard below has to pass first.  It can only ever
# target a removable SD block device; the internal UFS and every Android
# partition are rejected outright.
set -uo pipefail

adb=${ADB:-/mnt/c/Users/agcar/ADB/platform-tools/adb.exe}
image=""
device=""
do_write=0

usage() {
	cat <<'EOF'
Usage:
  twrp-write-sd.sh                              inspect the tablet and stop
  twrp-write-sd.sh --image IMG                  inspect and report the plan
  twrp-write-sd.sh --image IMG --device DEV --write   write, after all guards

The tablet must be in TWRP with the microSD inserted and USB debugging
reachable.  DEV must be a whole SD device such as /dev/block/mmcblk1.
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
		--image) image=$2; shift 2 ;;
		--device) device=$2; shift 2 ;;
		--write) do_write=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown argument: $1" >&2; usage; exit 2 ;;
	esac
done

sh_() { "$adb" shell "$@" 2>/dev/null | tr -d '\r'; }
# The Windows adb.exe terminates every line with CRLF, so anything anchored to
# end-of-line silently fails to match unless the carriage return is stripped.
adb_() { "$adb" "$@" 2>&1 | tr -d '\r'; }

echo '=== adb ==='
adb_ version | head -1
count=$(adb_ devices | grep -cE '[[:space:]](device|recovery)$')
if [ "$count" -eq 0 ]; then
	echo 'No device is reachable. Put the tablet in TWRP and connect USB.' >&2
	exit 1
fi
if [ "$count" -gt 1 ]; then
	echo 'More than one device is attached; refusing to guess.' >&2
	adb_ devices
	exit 1
fi
adb_ devices -l | grep -E '[[:space:]](device|recovery)[[:space:]]'

echo
echo '=== the device must be in TWRP, not in a booted system ==='
bootmode=$(sh_ getprop ro.bootmode)
twrp=$(sh_ getprop ro.twrp.version)
model=$(sh_ getprop ro.boot.em.model)
codename=$(sh_ getprop ro.product.device)
printf 'bootmode=%s twrp=%s model=%s codename=%s\n' \
	"$bootmode" "${twrp:-none}" "${model:-unknown}" "${codename:-unknown}"

in_recovery=0
case "$codename" in
	gts9u|gts9uwifi) ;;
	*)
		echo "This is not an SM-X910 (codename '$codename'); refusing." >&2
		exit 1
		;;
esac
if [ -n "$twrp" ] || [ "$bootmode" = recovery ] || \
	[ -n "$(sh_ ls /sbin/recovery 2>/dev/null)" ]; then
	in_recovery=1
fi
if [ "$in_recovery" -ne 1 ]; then
	echo 'The tablet does not look like it is in TWRP.' >&2
	echo 'Writing the card from a booted system would corrupt a mounted filesystem.' >&2
	exit 1
fi
echo 'TWRP confirmed.'

echo
echo '=== block devices ==='
# Sectors are converted to bytes here, not on the tablet: TWRP's busybox shell
# does 32-bit arithmetic, so sectors*512 wraps and a 29.7 GiB card was first
# reported as 1.72 GiB.
sh_ 'for d in /sys/block/*; do
	n=$(basename $d)
	case $n in
		loop*|ram*|zram*|dm-*) continue ;;
	esac
	printf "%s %s %s %s %s\n" "$n" \
		"$(cat $d/size 2>/dev/null || echo 0)" \
		"$(cat $d/removable 2>/dev/null || echo ?)" \
		"$(cat $d/device/type 2>/dev/null || echo -)" \
		"$(cat $d/device/name 2>/dev/null || echo -)"
done' | while read -r n sectors rem type name; do
	[ -n "$n" ] || continue
	printf '%-10s %16s bytes  removable=%s type=%-4s name=%s\n' \
		"$n" "$((sectors * 512))" "$rem" "$type" "$name"
done

echo
echo '=== mounted filesystems on removable media ==='
sh_ 'grep -E "mmcblk" /proc/mounts || echo "nothing from an SD card is mounted"'

if [ -z "$image" ]; then
	echo
	echo 'No --image given; inspection only. Nothing was written.'
	exit 0
fi

if [ ! -f "$image" ]; then
	echo "image not found: $image" >&2
	exit 1
fi
image_bytes=$(stat -c %s "$image")
image_sha=$(sha256sum "$image" | cut -d' ' -f1)
echo
echo '=== image ==='
printf '%s\n%s bytes\nsha256 %s\n' "$image" "$image_bytes" "$image_sha"

if [ -z "$device" ]; then
	echo
	echo 'No --device given; inspection only. Nothing was written.'
	exit 0
fi

echo
echo '=== target guards ==='
fail=0
check() {
	if [ "$1" = 0 ]; then printf 'PASS  %s\n' "$2"; else printf 'FAIL  %s\n' "$2"; fail=1; fi
}

case "$device" in
	/dev/block/mmcblk[0-9])
		check 0 "target $device is a whole mmc device" ;;
	*)
		check 1 "target $device is not a whole /dev/block/mmcblkN device" ;;
esac

base=$(basename "$device")

# device/type == SD is the decisive signal.  The `removable` flag is NOT usable
# here: this platform's SD host reports removable=0 for a card that plainly is
# one, so requiring it would reject the only valid target.
dtype=$(sh_ "cat /sys/block/$base/device/type 2>/dev/null")
[ "$dtype" = SD ] && check 0 'target reports device type SD' || \
	check 1 "target device type is '$dtype', expected SD"

removable=$(sh_ "cat /sys/block/$base/removable 2>/dev/null")
name=$(sh_ "cat /sys/block/$base/device/name 2>/dev/null")
printf 'info  target card name %s, removable flag %s (not used as a guard)\n' \
	"${name:-unknown}" "${removable:-?}"

# Internal storage on this device is UFS and enumerates as sd*, so an mmcblk
# target cannot be it.  Assert that separation rather than assume it.
if sh_ 'ls /sys/block' | grep -q '^sda$'; then
	check 0 'internal UFS is present separately as sda, so the target is not it'
else
	check 1 'internal UFS was not found as sda; the storage layout is not what this script expects'
fi

# Sectors are converted on this host: the tablet's shell would overflow.
sectors=$(sh_ "cat /sys/block/$base/size 2>/dev/null")
target_bytes=$(( ${sectors:-0} * 512 ))
printf 'info  target capacity %s bytes (%s sectors)\n' "$target_bytes" "${sectors:-0}"
[ "$target_bytes" -ge "$image_bytes" ] && check 0 'target is large enough' || \
	check 1 'target is smaller than the image'

mounts=$(sh_ "grep '^$device' /proc/mounts")
if [ -z "$mounts" ]; then
	check 0 'no partition of the target is mounted'
else
	printf 'info  currently mounted from the target:\n%s\n' "$mounts"
	check 0 'partitions of the target are mounted; they will be unmounted before writing'
fi

if [ "$fail" -ne 0 ]; then
	echo
	echo 'Guards failed. Nothing was written.' >&2
	exit 1
fi

if [ "$do_write" -ne 1 ]; then
	echo
	echo "Plan: write $image_bytes bytes to $device on the tablet."
	echo 'Re-run with --write to do it. Nothing was written.'
	exit 0
fi

echo
echo "=== unmounting anything from $device ==="
# Writing under a mounted filesystem would corrupt it and the kernel would keep
# stale cached blocks.  The whole card is about to be overwritten anyway.
sh_ "grep '^$device' /proc/mounts | cut -d' ' -f2" | while read -r mp; do
	[ -n "$mp" ] || continue
	echo "umount $mp"
	"$adb" shell "umount '$mp'" 2>&1 | tr -d '\r'
done
still=$(sh_ "grep -c '^$device' /proc/mounts")
if [ "${still:-0}" != 0 ]; then
	echo 'could not unmount every filesystem from the target; refusing to write' >&2
	sh_ "grep '^$device' /proc/mounts"
	exit 1
fi
echo 'nothing from the target is mounted now'

echo
echo "=== writing to $device ==="
echo 'This erases the card completely.'
if ! "$adb" exec-in "dd of=$device bs=4M conv=fsync" < "$image"; then
	echo 'streaming failed; the card is now in an undefined state' >&2
	exit 1
fi
"$adb" shell sync

echo
echo '=== verifying the data read back ==='
readback=$("$adb" exec-out \
	"dd if=$device bs=1M count=$(( (image_bytes + 1048575) / 1048576 )) 2>/dev/null | head -c $image_bytes | sha256sum" \
	| tr -d '\r' | cut -d' ' -f1)
printf 'written  %s\nreadback %s\n' "$image_sha" "$readback"
if [ "$image_sha" = "$readback" ]; then
	echo 'VERIFIED: the card matches the image byte for byte.'
	exit 0
fi
echo 'MISMATCH: do not boot this card.' >&2
exit 1
