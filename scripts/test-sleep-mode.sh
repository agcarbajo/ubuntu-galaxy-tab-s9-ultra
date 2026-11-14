#!/bin/bash
# Test bench for the sleep-state selection.
#
# Deep suspend on this board sometimes comes back without the internal
# storage.  Nothing here fixes that; what this decides is whether a tablet
# that has already lost its storage once keeps offering it the chance to
# happen again.  The evidence is the previous boot's kernel log, because the
# hook that sees the failure cannot write anything by then.
#
# Runs under dash with a faked journal and a faked /sys/power/mem_sleep.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
SCRIPT="$repo/packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-sleep-mode"
[ -f "$SCRIPT" ] || { echo "not found: $SCRIPT" >&2; exit 1; }

W=$(mktemp -d /tmp/gts9u-sleepmode.XXXXXX)
trap 'rm -rf "$W"' EXIT
failures=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; failures=$((failures + 1)); }

FAULT='kernel: ufshcd-qcom 1d84000.ufshc: Failed to calibrate PHY: -110
kernel: ufs_device_wlun 0:0:0:49488: ufshcd_wl_resume failed: -5'
CLEAN='kernel: PM: suspend entry (deep)
kernel: PM: suspend exit'

reset() {  # $1 = previous boot log, $2 = the mem_sleep line
	rm -rf "$W/state" "$W/bin" "$W/log"
	mkdir -p "$W/state" "$W/bin"
	printf '%s\n' "$2" > "$W/mem_sleep"
	printf '#!/bin/sh\ncat <<JOURNAL\n%s\nJOURNAL\n' "$1" > "$W/bin/journal"
	chmod +x "$W/bin/journal"
	printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/log"\n' "$W" > "$W/bin/logger"
	chmod +x "$W/bin/logger"
}

run() {
	PATH="$W/bin:$PATH" \
	GTS9U_SLEEP_STATE="$W/state" \
	GTS9U_SLEEP_MEM_SLEEP="$W/mem_sleep" \
	GTS9U_SLEEP_JOURNAL="$W/bin/journal" \
		dash "$SCRIPT" 2>&1
}

echo '== 1. a tablet that has never failed keeps deep sleep =='
reset "$CLEAN" '[s2idle] deep'
run > /dev/null
[ -e "$W/state/force-light-sleep" ] && bad 'a healthy tablet was marked' \
	|| ok 'no marker after a clean boot'
grep -q s2idle "$W/mem_sleep" && [ "$(cat "$W/mem_sleep")" = '[s2idle] deep' ] \
	&& ok 'the sleep state is left exactly as it was' \
	|| bad "mem_sleep was changed: $(cat "$W/mem_sleep")"

echo
echo '== 2. the previous boot lost its storage =='
reset "$FAULT" 's2idle [deep]'
run > /dev/null
[ -e "$W/state/force-light-sleep" ] && ok 'the failure is remembered' \
	|| bad 'the failure was forgotten'
[ "$(cat "$W/mem_sleep")" = 's2idle' ] && ok 'light sleep is selected for this boot' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"
grep -q 'lost its storage on resume' "$W/log" && ok 'the reason reaches the journal' \
	|| bad "nothing explained: $(cat "$W/log" 2>/dev/null)"

echo
echo '== 3. a tablet already marked does not need the evidence again =='
reset "$CLEAN" 's2idle [deep]'
: > "$W/state/force-light-sleep"
run > /dev/null
[ "$(cat "$W/mem_sleep")" = 's2idle' ] && ok 'the marker alone selects light sleep' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"

echo
echo '== 4. the owner can go back to deep sleep =='
reset "$CLEAN" 's2idle [deep]'
run > /dev/null
[ "$(cat "$W/mem_sleep")" = 's2idle [deep]' ] \
	&& ok 'removing the marker restores deep sleep on the next boot' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"

echo
echo '== 5. a kernel with no light sleep is left alone =='
reset "$FAULT" '[deep]'
run > /dev/null
[ "$(cat "$W/mem_sleep")" = '[deep]' ] && ok 'a kernel without s2idle is not written to' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"
grep -q 'no s2idle' "$W/log" && ok 'and it says why' || bad 'no explanation logged'

echo
echo '== 6. light sleep already in force is not rewritten =='
reset "$CLEAN" '[s2idle] deep'
: > "$W/state/force-light-sleep"
run > /dev/null
[ "$(cat "$W/mem_sleep")" = '[s2idle] deep' ] \
	&& ok 'an already selected state is left untouched' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"

echo
if [ "$failures" -eq 0 ]; then echo 'ALL CORRECT'; else echo "$failures FAILURES"; fi
exit "$failures"
