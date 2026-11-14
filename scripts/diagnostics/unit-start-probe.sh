#!/bin/bash
# What does starting a unit cost on this tablet, and what is it paced by?
#
# During boot PID 1 completes about one job every 135 ms, like a metronome,
# and with some 250 units that queue is most of the boot.  This times a
# trivial transient unit, a cgroup create and remove, and a fixed CPU-bound
# job, three ways: as the tablet idles, with expedited RCU, and with the
# `performance` governor.  It changes those two settings for a few seconds
# each and puts back what it found.  Run as root, on an idle tablet.
set -u
[ "$(id -u)" = 0 ] || { echo 'run this with sudo' >&2; exit 2; }

declare -A governor
for policy in /sys/devices/system/cpu/cpufreq/policy*; do
	governor[$policy]=$(cat "$policy/scaling_governor")
done
rcu=$(cat /sys/kernel/rcu_expedited 2>/dev/null || echo 0)
restore() {
	for policy in "${!governor[@]}"; do echo "${governor[$policy]}" > "$policy/scaling_governor"; done
	echo "$rcu" > /sys/kernel/rcu_expedited 2>/dev/null
}
trap restore EXIT

unit() {  # ms per transient unit
	local n=20 start end
	start=$(date +%s%N)
	for _ in $(seq 1 "$n"); do
		systemd-run --quiet --wait --collect --unit "gts9u-probe-$RANDOM" true 2>/dev/null
	done
	end=$(date +%s%N)
	echo $(( (end - start) / 1000000 / n ))
}

cgroup() {  # ms per cgroup mkdir + rmdir
	local n=30 start end base=/sys/fs/cgroup/gts9u-probe
	start=$(date +%s%N)
	for i in $(seq 1 "$n"); do mkdir "$base-$i" && rmdir "$base-$i"; done
	end=$(date +%s%N)
	echo $(( (end - start) / 1000000 / n ))
}

cpu() {  # ms for a fixed CPU-bound job
	local start end
	start=$(date +%s%N)
	python3 -c 'import hashlib; h = hashlib.sha256(); [h.update(b"x" * 4096) for _ in range(120000)]'
	end=$(date +%s%N)
	echo $(( (end - start) / 1000000 ))
}

row() { printf '%-16s %5s ms/unit  %4s ms/cgroup  %5s ms cpu job\n' "$1" "$(unit)" "$(cgroup)" "$(cpu)"; }

sleep 2
row 'as it idles'
echo 1 > /sys/kernel/rcu_expedited
row 'expedited RCU'
echo "$rcu" > /sys/kernel/rcu_expedited
for policy in "${!governor[@]}"; do echo performance > "$policy/scaling_governor"; done
sleep 1
row 'performance'
