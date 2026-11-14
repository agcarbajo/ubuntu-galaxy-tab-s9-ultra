#!/bin/bash
# Test bench for gts9u-fingerprint-check.
#
# The command exists so a report that says only "the fingerprint reader is not
# detected" becomes a report that says which of the five stages failed.  That
# is worth nothing if the verdict names the wrong one, so each case here puts
# exactly one stage in the state a broken unit would be in and checks that the
# verdict names that stage and no other.
#
# Everything it calls is faked on PATH, and the three absolute paths it reads
# are redirected through the environment.  No root, no device, no network.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
COMMAND="$repo/packaging/ubuntu-gts9u-device/usr/bin/gts9u-fingerprint-check"
[ -f "$COMMAND" ] || { echo "not found: $COMMAND" >&2; exit 1; }

W=$(mktemp -d /tmp/gts9u-fpcheck.XXXXXX)
trap 'rm -rf "$W"' EXIT
failures=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; failures=$((failures + 1)); }

mkfake() {  # $1 = name, rest = body
	local name=$1; shift
	printf '#!/bin/sh\n%s\n' "$*" > "$W/bin/$name"
	chmod +x "$W/bin/$name"
}

reset() {  # a tablet where every stage is satisfied
	rm -rf "$W/bin" "$W/device" "$W/tod" "$W/provision" "$W/state"
	mkdir -p "$W/bin" "$W/device" "$W/tod" "$W/state/firmware"
	# A unit that read its own calibration out of its own EFS.
	printf 'calibration' > "$W/state/firmware/calib.dat"
	printf '#!/bin/sh\necho "EL721 provisioning status"\necho "  device node: present"\n' \
		> "$W/provision"
	chmod +x "$W/provision"
	: > "$W/tod/libfprint-tod-el721.so"
	mkfake id 'echo 0'
	mkfake date 'echo 2026-11-13T00:00:00+01:00'
	mkfake systemctl 'case "$1" in
  is-enabled) echo enabled ;;
  is-active) echo active ;;
  show) echo success ;;
esac'
	mkfake journalctl 'echo "kernel: egis-el721 el721: X916 secure companion ready"'
	mkfake dpkg-query 'echo 1.2.3'
	mkfake busctl 'echo "ao 1 \"/net/reactivated/Fprint/Device/0\""'
}

run() {
	PATH="$W/bin:/usr/bin:/bin" \
	GTS9U_FP_PROVISION="$W/provision" \
	GTS9U_FP_DEVICE="$W/device" \
	GTS9U_FP_TOD_DIR="$W/tod" \
	GTS9U_FP_STATE="$W/state" \
		bash "$COMMAND" 2>&1
}

verdict() { run | sed -n '/^== verdict/,$p'; }

echo '== 1. a tablet where every stage is satisfied =='
reset
out=$(verdict)
case "$out" in
	*'Every stage above reports what a working reader reports'*)
		ok 'a healthy unit gets no false fault' ;;
	*) bad "healthy unit reported a fault: $out" ;;
esac

echo
echo '== 2. the platform device never appeared =='
reset
rmdir "$W/device"
out=$(verdict)
case "$out" in
	*'EL721 platform device is not there'*) ok 'a missing platform device is named' ;;
	*) bad "unexpected verdict: $out" ;;
esac

echo
echo '== 3. the provisioning service failed =='
reset
mkfake systemctl 'case "$1" in
  is-enabled) echo enabled ;;
  is-active) echo failed ;;
  show) [ "$5" = ubuntu-gts9u-fingerprint-provision ] && echo exit-code || echo success ;;
esac'
out=$(verdict)
case "$out" in
	*'ubuntu-gts9u-fingerprint-provision did not finish: exit-code'*)
		ok 'a failed provisioning unit is named with its result' ;;
	*) bad "unexpected verdict: $out" ;;
esac

echo
echo '== 4. libfprint has no EL721 TOD driver =='
reset
rm -f "$W/tod"/*.so
out=$(verdict)
case "$out" in
	*'EL721 TOD driver is not installed'*) ok 'a missing TOD driver is named' ;;
	*) bad "unexpected verdict: $out" ;;
esac

echo
echo '== 5. fprintd runs but offers nothing =='
reset
mkfake busctl 'echo "ao 0"'
out=$(verdict)
case "$out" in
	*'fprintd is running but offers no device'*) ok 'an empty fprintd is named' ;;
	*) bad "unexpected verdict: $out" ;;
esac

echo
echo '== 6. no calibration of this tablet =='
# The packaged directory is another unit's calibration: the reader enrols and
# never recognises a finger, and before this the only sign was silence.
reset
rm -f "$W/state/firmware/calib.dat"
out=$(verdict)
case "$out" in
	*'no calibration of its own'*) ok 'a foreign calibration is named as the fault' ;;
	*) bad "unexpected verdict: $out" ;;
esac

echo
echo '== 7. the first unsatisfied stage wins =='
# Both the device and the TOD driver are missing: the verdict must name the
# one that comes first, because fixing a later stage cannot help.
reset
rmdir "$W/device"
rm -f "$W/tod"/*.so
out=$(verdict)
case "$out" in
	*'EL721 platform device is not there'*) ok 'the earliest stage is the verdict' ;;
	*) bad "unexpected verdict: $out" ;;
esac

echo
echo '== 8. it refuses to run without root =='
reset
mkfake id 'echo 1000'
out=$(run)
case "$out" in
	*'run this with sudo'*) ok 'a non-root run says what to do' ;;
	*) bad "unexpected output: $out" ;;
esac

echo
if [ "$failures" -eq 0 ]; then echo 'ALL CORRECT'; else echo "$failures FAILURES"; fi
exit "$failures"
