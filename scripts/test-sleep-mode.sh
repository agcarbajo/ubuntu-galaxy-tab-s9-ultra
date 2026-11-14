#!/bin/bash
# Test bench for the sleep-state selection.
#
# Deep suspend on this board sometimes ends in a forced restart instead of a
# resume.  Nothing here fixes that; what this decides is whether a tablet that
# has already been through it keeps offering it the chance to happen again.
#
# The first version of this looked for the failure in the previous boot's
# kernel log, and would never have fired: measured on the tablet, that log
# ends at "PM: suspend entry (deep)", because the disk it would be written to
# is what fails.  The evidence is the marker the sleep hook writes before
# every suspend -- "<PMIC counter> <battery percent>" -- and removes after
# every healthy resume.  These cases are about reading it correctly, and above
# all about not convicting a battery that simply ran out.
#
# Runs under dash with a faked marker, PMIC counter and /sys/power/mem_sleep.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
SCRIPT="$repo/packaging/ubuntu-gts9u-device/usr/libexec/ubuntu-gts9u-sleep-mode"
[ -f "$SCRIPT" ] || { echo "not found: $SCRIPT" >&2; exit 1; }

W=$(mktemp -d /tmp/gts9u-sleepmode.XXXXXX)
trap 'rm -rf "$W"' EXIT
failures=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; failures=$((failures + 1)); }

reset() {  # $1 = the mem_sleep line, $2 = the PMIC counter now
	rm -rf "$W/state" "$W/bin" "$W/log"
	mkdir -p "$W/state" "$W/bin"
	printf '%s\n' "$1" > "$W/mem_sleep"
	printf '%s\n' "$2" > "$W/counter"
	printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/log"\n' "$W" > "$W/bin/logger"
	chmod +x "$W/bin/logger"
	: > "$W/log"
}

marker() { printf '%s %s\n' "$1" "$2" > "$W/state/suspend-in-progress"; }

run() {
	PATH="$W/bin:$PATH" \
	GTS9U_SLEEP_STATE="$W/state" \
	GTS9U_SLEEP_MEM_SLEEP="$W/mem_sleep" \
	GTS9U_SLEEP_COUNTER="$W/counter" \
		dash "$SCRIPT" 2>&1
}

chosen() { [ -e "$W/state/force-light-sleep" ]; }

echo '== 1. a tablet whose every suspend ended well keeps deep sleep =='
reset 's2idle [deep]' 500000
run > /dev/null
chosen && bad 'a healthy tablet was moved to light sleep' || ok 'no choice is made without evidence'
[ "$(cat "$W/mem_sleep")" = 's2idle [deep]' ] && ok 'the sleep state is left exactly as it was' \
	|| bad "mem_sleep was changed: $(cat "$W/mem_sleep")"

echo
echo '== 2. the case from the tablet: asleep 73 s at 61%, then a forced restart =='
reset 's2idle [deep]' 1487000
marker 1486800 61
run > /dev/null
chosen && ok 'the failed resume is remembered' || bad 'the failed resume was not recognised'
[ "$(cat "$W/mem_sleep")" = 's2idle' ] && ok 'light sleep is selected for this boot' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"
[ -e "$W/state/suspend-in-progress" ] && bad 'the marker would be counted again next boot' \
	|| ok 'the marker is consumed'
grep -q 'ended in a restart' "$W/log" && ok 'the journal says what was seen' \
	|| bad "nothing explained: $(cat "$W/log")"

echo
echo '== 3. a battery that ran out while it slept is not a failed resume =='
reset 's2idle [deep]' 1487000
marker 1486800 7
run > /dev/null
chosen && bad 'a flat battery was taken for a resume failure' \
	|| ok 'a suspend that began at 7% is left alone'
grep -q 'battery may simply have run out' "$W/log" && ok 'and the journal says why' \
	|| bad "no explanation: $(cat "$W/log")"

echo
echo '== 4. nor is a tablet left in a drawer for a week =='
reset 's2idle [deep]' 2100000
marker 1486800 80
run > /dev/null
chosen && bad 'a week asleep was taken for a resume failure' \
	|| ok 'a suspend cut short after seven days is left alone'

echo
echo '== 5. a PMIC counter that restarted cannot be reasoned about =='
reset 's2idle [deep]' 300
marker 1486800 80
run > /dev/null
chosen && bad 'a restarted counter produced a verdict' || ok 'a restarted counter is ignored'

echo
echo '== 6. a marker that is not two numbers is ignored =='
reset 's2idle [deep]' 1487000
printf 'garbage\n' > "$W/state/suspend-in-progress"
run > /dev/null
chosen && bad 'garbage produced a verdict' || ok 'an unreadable marker is ignored'
[ -e "$W/state/suspend-in-progress" ] && bad 'the unreadable marker was kept' \
	|| ok 'and it is removed rather than judged again'

echo
echo '== 7. a tablet already on light sleep stays there =='
reset 's2idle [deep]' 1487000
: > "$W/state/force-light-sleep"
run > /dev/null
[ "$(cat "$W/mem_sleep")" = 's2idle' ] && ok 'the remembered choice selects light sleep' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"

echo
echo '== 8. the owner can go back to deep sleep =='
reset 's2idle [deep]' 1487000
run > /dev/null
[ "$(cat "$W/mem_sleep")" = 's2idle [deep]' ] \
	&& ok 'with the choice removed, deep sleep is back on the next boot' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"

echo
echo '== 9. a kernel with no light sleep is left alone =='
reset '[deep]' 1487000
marker 1486800 61
run > /dev/null
[ "$(cat "$W/mem_sleep")" = '[deep]' ] && ok 'a kernel without s2idle is not written to' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"
grep -q 'no s2idle' "$W/log" && ok 'and it says why' || bad 'no explanation logged'

echo
echo '== 10. light sleep already in force is not rewritten =='
reset '[s2idle] deep' 1487000
: > "$W/state/force-light-sleep"
run > /dev/null
[ "$(cat "$W/mem_sleep")" = '[s2idle] deep' ] \
	&& ok 'an already selected state is left untouched' \
	|| bad "mem_sleep is $(cat "$W/mem_sleep")"

echo
if [ "$failures" -eq 0 ]; then echo 'ALL CORRECT'; else echo "$failures FAILURES"; fi
exit "$failures"
