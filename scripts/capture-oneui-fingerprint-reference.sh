#!/bin/bash
# Capture the active One UI fingerprint APEX and non-biometric diagnostics.
#
# This deliberately refuses every device except an SM-X910/gts9u tablet. It
# does not read Android's fingerprint template or keystore directories and it
# never writes a partition.
set -euo pipefail

adb=${ADB:-adb}
serial=${1:-}
output=${2:-}
apex_name=com.samsung.android.biometrics.fingerprint
apex_path=/apex/$apex_name

usage() {
	cat <<'EOF'
Usage: capture-oneui-fingerprint-reference.sh SERIAL OUTPUT_DIRECTORY

The tablet must be booted into rooted One UI, unlocked, and visible to ADB.
ADB may be overridden with the ADB environment variable.
EOF
}

die() {
	echo "ABORTED: $*" >&2
	exit 1
}

[ -n "$serial" ] && [ -n "$output" ] || {
	usage >&2
	exit 64
}
case $serial in
	*[!A-Za-z0-9._:-]*) die "invalid ADB serial: $serial" ;;
esac
[ ! -e "$output" ] || die "output already exists: $output"

state=$("$adb" -s "$serial" get-state 2>/dev/null || true)
[ "$state" = device ] || die "$serial is not an authorised ADB device"

model=$("$adb" -s "$serial" shell getprop ro.product.model | tr -d '\r')
device=$("$adb" -s "$serial" shell getprop ro.product.device | tr -d '\r')
case $model:$device in
	SM-X910:gts9u|SM-X910:gts9uwifi) ;;
	*) die "refusing $model/$device; this capture is only for the SM-X910" ;;
esac

root_id=$("$adb" -s "$serial" shell su -c id 2>/dev/null | tr -d '\r')
case $root_id in
	uid=0*) ;;
	*) die "root through 'su -c' is unavailable" ;;
esac

mkdir -p "$output"

"$adb" -s "$serial" shell su -c \
	"printf 'model='; getprop ro.product.model; \
	 printf 'device='; getprop ro.product.device; \
	 printf 'display='; getprop ro.build.display.id; \
	 printf 'fingerprint='; getprop ro.build.fingerprint; \
	 printf 'oneui='; getprop ro.build.version.oneui; \
	 printf 'kernel='; uname -r" \
	| tr -d '\r' > "$output/build.txt"

"$adb" -s "$serial" shell su -c \
	"printf 'resolved_apex='; readlink -f '$apex_path'; \
	 mount | grep '$apex_name' || true; \
	 find '$apex_path' -maxdepth 6 -type f -exec ls -l {} \; 2>/dev/null" \
	| tr -d '\r' > "$output/apex-layout.txt"

"$adb" -s "$serial" shell su -c \
	"find /data/apex/active -maxdepth 2 -type f \
	 \( -iname '*fingerprint*' -o -iname '*biometric*' \) \
	 -exec ls -l {} \; 2>/dev/null" \
	| tr -d '\r' > "$output/active-apex.txt"

"$adb" -s "$serial" shell su -c \
	"sha256sum '$apex_path'/etc/ta/fpta/* \
	 /vendor/firmware_mnt/image/dualfp.* \
	 /vendor/firmware_mnt/image/fingerpr.* 2>/dev/null || true" \
	| tr -d '\r' > "$output/ta-sha256.txt"

"$adb" -s "$serial" shell su -c \
	"cat /sys/kernel/tracing/available_events \
	 2>/dev/null || cat /sys/kernel/debug/tracing/available_events 2>/dev/null || true" \
	| tr -d '\r' \
	| grep -Ei 'smcinvoke|qsee|clk|gpio|regulator|interconnect|rpmh' \
	> "$output/relevant-trace-events.txt" || true

# The mounted APEX contains code/TA files, not enrolled prints. Pulling the
# public mount avoids copying anything from Android's private biometric store.
mkdir -p "$output/apex"
"$adb" -s "$serial" pull "$apex_path/." "$output/apex" \
	> "$output/adb-pull.txt" 2>&1

echo "Captured the active $apex_name reference in $output"
