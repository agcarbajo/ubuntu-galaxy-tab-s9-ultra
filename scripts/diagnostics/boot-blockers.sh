#!/bin/bash
# What a unit was actually waiting for: every unit it is ordered after, with
# the moment each one was up, latest last.  The last line is the blocker.
# `systemd-analyze critical-chain` follows only one of these; when the login
# screen is late, the unit that held it is often not on that path.
#
#   scripts/diagnostics/boot-blockers.sh gdm.service [more units...]
set -u
[ "$#" -gt 0 ] || { echo "usage: $0 UNIT..." >&2; exit 2; }

for unit in "$@"; do
	began=$(systemctl show "$unit" -p InactiveExitTimestampMonotonic --value 2>/dev/null)
	printf '== %s began starting at %.3f s; it is ordered after:\n' "$unit" \
		"$(awk -v v="${began:-0}" 'BEGIN { print v / 1000000 }')"
	systemctl show "$unit" -p After --value 2>/dev/null | tr ' ' '\n' | grep . |
		xargs -r systemctl show -p Id -p ActiveEnterTimestampMonotonic 2>/dev/null |
		awk '
			/^Id=/ { id = substr($0, 4) }
			/^ActiveEnterTimestampMonotonic=/ {
				e = substr($0, 31) / 1000000
				if (e > 0) printf "%9.3f  %s\n", e, id
			}' | sort -n | tail -6
done
