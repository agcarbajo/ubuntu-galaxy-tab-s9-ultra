#!/bin/bash
# Read-only idle probe: who wakes up, who burns CPU, who talks on the system bus.
# Samples for 20 s.  Run as root.
set -u
WINDOW=20

snap() {
	for d in /proc/[0-9]*; do
		pid=${d#/proc/}
		v=$(awk '/^voluntary_ctxt_switches/ {print $2}' "$d/status" 2>/dev/null) || continue
		[ -n "$v" ] || continue
		t=$(awk '{print $14 + $15}' "$d/stat" 2>/dev/null) || continue
		c=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null | cut -c1-70)
		[ -n "$c" ] || c="[$(cat "$d/comm" 2>/dev/null)]"
		printf '%s\t%s\t%s\t%s\n' "$pid" "$v" "$t" "$c"
	done
}

snap > /tmp/idle.a
( timeout "$WINDOW" busctl monitor --system 2>/dev/null > /tmp/idle.bus ) &
sleep "$WINDOW"
snap > /tmp/idle.b
wait

echo "=== wakeups per second and CPU ticks over ${WINDOW}s (top 18) ==="
awk -F'\t' -v w="$WINDOW" '
	NR == FNR { v[$1] = $2; t[$1] = $3; next }
	($1 in v) { dv = $2 - v[$1]; dt = $3 - t[$1];
	            if (dv > 0 || dt > 0) printf "%8.1f wakeups/s  %5.1f%% cpu  %s\n", dv / w, dt / w, $4 }
' /tmp/idle.a /tmp/idle.b | sort -rn | head -18

echo
echo "=== system bus: messages in ${WINDOW}s by sender and member (top 12) ==="
awk '
	/^‣ Type=/ { sender = ""; member = "" }
	/Sender=/ { for (i = 1; i <= NF; i++) if ($i ~ /^Sender=/) sender = substr($i, 8) }
	/Member=/ { for (i = 1; i <= NF; i++) if ($i ~ /^Member=/) member = substr($i, 8) }
	/Path=/   { for (i = 1; i <= NF; i++) if ($i ~ /^Path=/) path = substr($i, 6) }
	/^$/ { if (member != "") count[path " " member]++; member = "" }
	END { for (k in count) printf "%6d  %s\n", count[k], k }
' /tmp/idle.bus | sort -rn | head -12
echo "total bus messages: $(grep -c '^‣ Type=' /tmp/idle.bus)"

echo
echo "=== interrupts that fired most in the window are not sampled here; load ==="
cat /proc/loadavg
rm -f /tmp/idle.a /tmp/idle.b /tmp/idle.bus
