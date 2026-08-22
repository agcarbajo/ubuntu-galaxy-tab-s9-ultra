#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# One-shot EL721 power + bounded TrustZone validation for the physical X910.

set -eu

if [ "$(id -u)" -ne 0 ]; then
	echo "run as root" >&2
	exit 77
fi
if [ "$#" -lt 2 ] || [ "$#" -gt 6 ]; then
	echo "usage: $0 PROBE SPLIT_DIRECTORY [BASENAME [LOAD_NAME [SELECTOR [CLIENT_ENV]]]]" >&2
	exit 64
fi

probe=$1
split_dir=$2
basename=${3:-dualfp}
load_name=${4:-dualfp}
# Operation selector: TypeCheck range, or the stock-equivalent Prepare command.
selector=${5:---type-check}
client_env=${6:-}
fp_sysfs=
qcomtee_loaded=0
sensor_powered=0
qcomtee_module=${QCOMTEE_MODULE:-}
reset_before_type_check=${EL721_RESET_BEFORE_TYPE_CHECK:-0}
reset_count_before=

case $reset_before_type_check in
	0|1) ;;
	*) echo "EL721_RESET_BEFORE_TYPE_CHECK must be 0 or 1" >&2; exit 64 ;;
esac

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

# A live One UI 8 service-start trace shows no reset between raising GPIO155
# and TypeCheck.  Keep the already-negative reset experiment available only as
# an explicit diagnostic instead of changing the stock-equivalent default.
if [ "$reset_before_type_check" = 1 ]; then
	if [ ! -w "$fp_sysfs/reset" ] || [ ! -r "$fp_sysfs/reset_count" ]; then
		echo "EL721 reset interface not found" >&2
		exit 1
	fi
	reset_count_before=$(cat "$fp_sysfs/reset_count")
	printf '1\n' > "$fp_sysfs/reset"
	sleep 0.01
	if [ "$(cat "$fp_sysfs/reset_count")" -le "$reset_count_before" ]; then
		echo "EL721 reset pulse was not recorded" >&2
		exit 1
	fi
	echo "EL721 powered and reset (count $reset_count_before -> $(cat "$fp_sysfs/reset_count"))"
fi

if [ -n "$qcomtee_module" ]; then
	[ -r "$qcomtee_module" ] || {
		echo "QCOMTEE_MODULE is not readable: $qcomtee_module" >&2
		exit 1
	}
	insmod "$qcomtee_module"
else
	modprobe qcomtee
fi
qcomtee_loaded=1
if [ ! -c /dev/tee0 ]; then
	echo "QCOMTEE did not publish /dev/tee0" >&2
	exit 1
fi

if [ "$client_env" = kernel ]; then
	"$probe" "$split_dir" "$basename" "$load_name" "$selector" \
		--kernel-client-env
elif [ -n "$client_env" ]; then
	case $client_env in
		*[!0-9]*) echo "CLIENT_ENV must be 'kernel' or a numeric UID" >&2; exit 64 ;;
	esac
	"$probe" "$split_dir" "$basename" "$load_name" "$selector" \
		"--client-uid=$client_env"
else
	"$probe" "$split_dir" "$basename" "$load_name" "$selector"
fi
