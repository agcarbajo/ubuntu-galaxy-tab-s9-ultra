#!/bin/bash
# A text timeline of the boot: when each unit began starting and when it was
# up, for every unit that took at least a given time.  `systemd-analyze blame`
# says how long units took and `critical-chain` follows one path; neither
# shows what was running *while* the greeter was waiting, which is the
# question when the login screen is late.  Read-only; needs no root.
#
#   scripts/diagnostics/boot-timeline.sh [minimum-seconds] [until-seconds]
set -u
MIN=${1:-0.4}
UNTIL=${2:-40}

systemctl list-units --all --no-legend --plain --type=service,target,socket 2>/dev/null |
	awk '{print $1}' |
	xargs -r systemctl show -p Id -p InactiveExitTimestampMonotonic -p ActiveEnterTimestampMonotonic 2>/dev/null |
	awk -v min="$MIN" -v last="$UNTIL" '
		/^Id=/ { id = substr($0, 4) }
		/^InactiveExitTimestampMonotonic=/ { s = substr($0, 32) / 1000000 }
		/^ActiveEnterTimestampMonotonic=/ {
			e = substr($0, 31) / 1000000
			if (s > 0 && e >= s && e <= last && (e - s >= min || id ~ /[.]target$/))
				printf "%8.3f  %8.3f  %7.3f  %s\n", s, e, e - s, id
		}' |
	sort -n |
	awk 'BEGIN { print "   start        up     took  unit" } { print }'
