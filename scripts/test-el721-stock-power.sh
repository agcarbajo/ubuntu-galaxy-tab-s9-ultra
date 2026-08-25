#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Run the EL721 QTEE self-test with the cold power sequence used by One UI.
# The diagnostic rail module owns power and GPIO155, so the normal userspace
# helper must be told not to touch the built-in companion driver's controls.

set -u

module=${1:-/home/agcar/gts9u-fprail.ko}
selftest=${2:-/home/agcar/el721-qtee-selftest}
firmware=${3:-/var/lib/gts9u-fingerprint-test-20260821/ta}
enroll_user=${4:-}
fprintd_was_active=false
qtee_service_was_active=false
qtee_service=ubuntu-gts9u-qcomtee.service
fprail_loaded=false

if [ "$(id -u)" -ne 0 ]; then
	echo "test-el721-stock-power: run as root" >&2
	exit 2
fi
if [ ! -f "$module" ] || [ ! -x "$selftest" ] || [ ! -d "$firmware" ]; then
	echo "test-el721-stock-power: module, self-test, or firmware is missing" >&2
	exit 2
fi

systemctl is-active --quiet fprintd.service && fprintd_was_active=true
systemctl is-active --quiet "$qtee_service" && qtee_service_was_active=true

cleanup()
{
	status=$?
	trap - EXIT INT TERM
	modprobe -r qcomtee 2>/dev/null || true
	if $fprail_loaded; then
		rmmod gts9u_fprail 2>/dev/null || true
	fi
	if $qtee_service_was_active; then
		systemctl start "$qtee_service" 2>/dev/null || true
	fi
	if $fprintd_was_active; then
		systemctl start fprintd.service 2>/dev/null || true
	fi
	sleep 1
	if [ -d /sys/kernel/debug/regulator/vreg_l2b_3p3 ]; then
		echo "RAIL_AFTER=present" >&2
		status=1
	else
		echo "RAIL_AFTER=absent"
	fi
	exit "$status"
}
trap cleanup EXIT INT TERM

systemctl stop fprintd.service "$qtee_service" 2>/dev/null || true
modprobe -r qcomtee 2>/dev/null || true

echo PRECHECK
grep -E "qcomtee|gts9u_fprail" /proc/modules || true
if [ -d /sys/kernel/debug/regulator/vreg_l2b_3p3 ]; then
	echo "RAIL_BEFORE=present" >&2
	exit 1
fi
echo "RAIL_BEFORE=absent"

insmod "$module" power=1 enable_line=1 settle_ms=0 reset_pulse=0
fprail_loaded=true
echo "FPRAIL_LOAD_RC=0"
dmesg | grep gts9u-fprail | tail -n 8

modprobe qcomtee
if [ -n "$enroll_user" ]; then
	EL721_SKIP_POWER=1 "$selftest" "$firmware" "$enroll_user"
else
	EL721_SKIP_POWER=1 "$selftest" "$firmware"
fi
selftest_status=$?
echo "SELFTEST_RC=$selftest_status"

exit "$selftest_status"
