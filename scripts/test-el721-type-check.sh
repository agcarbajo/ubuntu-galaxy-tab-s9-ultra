#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# One-shot EL721 power + TrustZone TypeCheck validation for the physical X910.

set -eu

if [ "$(id -u)" -ne 0 ]; then
	echo "run as root" >&2
	exit 77
fi
if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
	echo "usage: $0 PROBE SPLIT_DIRECTORY [BASENAME [LOAD_NAME]]" >&2
	exit 64
fi

probe=$1
split_dir=$2
basename=${3:-dualfp}
load_name=${4:-dualfp}
fp_sysfs=
qcomtee_loaded=0
sensor_powered=0

for candidate in /sys/bus/platform/devices/*; do
	if [ -r "$candidate/vendor" ] &&
	   [ "$(cat "$candidate/vendor")" = EGISTEC ]; then
		fp_sysfs=$candidate
		break
	fi
done

if [ -z "$fp_sysfs" ] || [ ! -w "$fp_sysfs/sensor_power" ]; then
	echo "EL721 sensor_power interface not found" >&2
	exit 1
fi
if [ ! -x "$probe" ]; then
	echo "probe is not executable: $probe" >&2
	exit 1
fi
for segment in 00 01 02 03 04 05 06 07 08; do
	if [ ! -r "$split_dir/$basename.b$segment" ]; then
		echo "missing signed TA segment: $basename.b$segment" >&2
		exit 1
	fi
done
if [ -e /dev/tee0 ]; then
	echo "refusing to reuse an existing /dev/tee0 session" >&2
	exit 1
fi
if [ "$(cat "$fp_sysfs/sensor_power")" != 0 ]; then
	echo "refusing to start with EL721 already powered" >&2
	exit 1
fi

cleanup()
{
	set +e
	if [ "$sensor_powered" -eq 1 ]; then
		printf '0\n' > "$fp_sysfs/sensor_power"
	fi
	if [ "$qcomtee_loaded" -eq 1 ]; then
		modprobe -r qcomtee
	fi
}
trap cleanup EXIT HUP INT TERM

printf '1\n' > "$fp_sysfs/sensor_power"
sensor_powered=1
sleep 0.02
if [ "$(cat "$fp_sysfs/sensor_power")" != 1 ]; then
	echo "EL721 did not enter the powered state" >&2
	exit 1
fi

modprobe qcomtee
qcomtee_loaded=1
if [ ! -c /dev/tee0 ]; then
	echo "QCOMTEE did not publish /dev/tee0" >&2
	exit 1
fi

"$probe" "$split_dir" "$basename" "$load_name" --type-check
