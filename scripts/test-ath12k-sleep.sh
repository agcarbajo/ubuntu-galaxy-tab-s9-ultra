#!/bin/bash
# Test bench for the Wi-Fi sleep hook.
#
# The hook unbinds WCN7850 before suspend and binds it again afterwards.  The
# bind used to be a single write: if the card was still powering its MHI stack
# up, that write was refused and the tablet had no Wi-Fi until the next reboot.
# Two owners report that pair -- "Wi-Fi has stopped working" and boots that are
# hit or miss -- and a card that answers a second later is indistinguishable
# from a card that never answers unless the hook tries again.
#
# The driver, device and state paths are redirected; a bind that must fail is
# a directory, which refuses a write even for root.  No PCI, no suspend.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
HOOK="$repo/packaging/ubuntu-gts9u-device/usr/lib/systemd/system-sleep/ubuntu-gts9u-ath12k-sleep"
[ -f "$HOOK" ] || { echo "not found: $HOOK" >&2; exit 1; }

W=$(mktemp -d /tmp/gts9u-ath12k.XXXXXX)
trap 'rm -rf "$W"' EXIT
failures=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; failures=$((failures + 1)); }

BDF=0000:01:00.0

reset() {
	rm -rf "$W/driver" "$W/devices" "$W/bin" "$W/state" "$W/log"
	mkdir -p "$W/driver" "$W/devices/$BDF" "$W/bin"
	: > "$W/driver/unbind"
	: > "$W/driver/bind"
	ln -s "$W/driver" "$W/devices/$BDF/driver"
	# the driver lists every device bound to it as a symlink of its own
	ln -s "$W/devices/$BDF" "$W/driver/$BDF"
	printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/log"\n' "$W" > "$W/bin/logger"
	chmod +x "$W/bin/logger"
}

run() {
	PATH="$W/bin:$PATH" \
	GTS9U_ATH12K_DRIVER="$W/driver" \
	GTS9U_ATH12K_DEVICES="$W/devices" \
	GTS9U_ATH12K_STATE="$W/state" \
	GTS9U_ATH12K_ATTEMPTS="${ATTEMPTS:-5}" \
	GTS9U_ATH12K_PAUSE="${PAUSE:-1}" \
		dash "$HOOK" "$@" 2>&1
}

echo '== 1. the card is back immediately =='
reset
printf '%s\n' "$BDF" > "$W/state"
run post > /dev/null
[ -e "$W/state" ] && bad 'the saved device survived a successful bind' \
	|| ok 'a card that is already bound ends the hook'
grep -q 'attempt 1' "$W/log" 2>/dev/null && ok 'the first attempt is reported' \
	|| bad "no attempt logged: $(cat "$W/log" 2>/dev/null)"

echo
echo '== 2. the card answers a second late =='
# This is the case that used to lose the Wi-Fi: one refused write and the hook
# gave up for the rest of the boot.
reset
rm "$W/devices/$BDF/driver"          # not bound yet
rm "$W/driver/bind"; mkdir "$W/driver/bind"   # a write here is refused
printf '%s\n' "$BDF" > "$W/state"
( sleep 2; rmdir "$W/driver/bind"; : > "$W/driver/bind" ) &
helper=$!
run post > /dev/null
status=$?
wait "$helper" 2>/dev/null
if [ "$status" -eq 0 ] && [ ! -e "$W/state" ]; then
	ok 'the hook waits for the card and binds it'
else
	bad "the hook gave up on a card that came back: status $status"
fi
grep -qE 'attempt [2-9]' "$W/log" 2>/dev/null && ok 'it says which attempt worked' \
	|| bad "no later attempt logged: $(cat "$W/log" 2>/dev/null)"

echo
echo '== 3. a card that never answers =='
reset
rm "$W/devices/$BDF/driver"
rm "$W/driver/bind"; mkdir "$W/driver/bind"
printf '%s\n' "$BDF" > "$W/state"
ATTEMPTS=3 PAUSE=0 run post > /dev/null
status=$?
[ "$status" -ne 0 ] && ok 'a card that never answers fails the hook' \
	|| bad 'a failed bind reported success'
grep -q 'after 3 attempts' "$W/log" 2>/dev/null \
	&& ok 'the log says how many attempts were made' \
	|| bad "attempts not reported: $(cat "$W/log" 2>/dev/null)"
grep -q 'stays down until reboot' "$W/log" 2>/dev/null \
	&& ok 'the log says what it means for the owner' \
	|| bad 'the consequence is not in the log'
[ -e "$W/state" ] && ok 'the saved device is kept for the next resume' \
	|| bad 'the saved device was dropped after a failure'

echo
echo '== 4. nothing saved means nothing to do =='
reset
run post > /dev/null
status=$?
[ "$status" -eq 0 ] && ok 'a resume with no saved device is a no-op' \
	|| bad "status $status with no state file"

echo
echo '== 5. a corrupt state file is refused =='
reset
printf 'not-a-bdf\n' > "$W/state"
run post > /dev/null
status=$?
[ "$status" -ne 0 ] && ok 'an invalid saved device is refused' \
	|| bad 'an invalid saved device was written to bind'

echo
echo '== 6. suspend still saves and unbinds =='
reset
run pre > /dev/null
if [ -s "$W/state" ] && [ "$(cat "$W/state")" = "$BDF" ]; then
	ok 'the device is saved before suspend'
else
	bad "the device was not saved: $(cat "$W/state" 2>/dev/null)"
fi
grep -q 'unbound' "$W/log" 2>/dev/null && ok 'the unbind is logged' \
	|| bad 'the unbind was not logged'

echo
if [ "$failures" -eq 0 ]; then echo 'ALL CORRECT'; else echo "$failures FAILURES"; fi
exit "$failures"
