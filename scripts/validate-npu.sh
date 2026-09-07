#!/bin/bash
# Safe on-device validation. It never enters system suspend or changes the boot target.
set -euo pipefail

duration=0
cycles=10
client_delay=${NPU_VALIDATION_CLIENT_DELAY:-0}
report=${NPU_VALIDATION_REPORT:-"$PWD/npu-validation-$(date +%Y%m%d-%H%M%S)"}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --soak-hours) duration=$(( ${2:?missing hours} * 3600 )); shift 2 ;;
        --cycles) cycles=${2:?missing cycles}; shift 2 ;;
        --report) report=${2:?missing directory}; shift 2 ;;
        *) echo "Usage: sudo $0 [--cycles N] [--soak-hours N] [--report DIR]" >&2; exit 2 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo 'Run with sudo.' >&2; exit 2; }
tr '\0' '\n' </proc/device-tree/compatible | grep -qx samsung,gts9uwifi
for file in /opt/gts9u-npu-bionic/bin/linker64 /opt/gts9u-npu-bionic/bin/probe-npu-htp; do
    test -x "$file"
done
[ "$cycles" -ge 1 ] && [ "$cycles" -le 100000 ]
[[ "$client_delay" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]]
install -d -m0755 "$report"
exec > >(tee "$report/runtime.log") 2>&1
start_epoch=$(date +%s)
end_epoch=$((start_epoch + duration))
passes=0
max_cdsp=0
max_cpu=0
min_battery=101
before_shmem=$(awk '/^Shmem:/{print $2}' /proc/meminfo)

cleanup() { systemctl stop gts9u-npu.service || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM

# On a clean boot the session service creates the CDSP remoteproc device by
# loading the board bootstrap module. Discovering it before the first start
# made validation fail without output even though inference was healthy.
systemctl start gts9u-npu.service
cdsp=
for _ in $(seq 1 100); do
    cdsp=$(for r in /sys/class/remoteproc/remoteproc*; do
        if [ "$(cat "$r/name")" = cdsp ]; then
            echo "$r"
        fi
    done)
    [ -n "$cdsp" ] && break
    sleep 0.1
done
[ -n "$cdsp" ]

echo "START=$(date --iso-8601=seconds) BOOT=$(cat /proc/sys/kernel/random/boot_id)"
while :; do
    systemctl start gts9u-npu.service
    [ -e /run/gts9u-npu/power-ready ]
    systemd-inhibit --list --no-pager >"$report/inhibitors.txt"
    systemctl is-active --quiet gts9u-npu.service
    [ -e /run/gts9u-npu/power-ready ]
    if ! LD_LIBRARY_PATH=/opt/gts9u-npu-bionic/lib \
        ADSP_LIBRARY_PATH=/opt/gts9u-npu-bionic/dsp \
        DSP_LIBRARY_PATH=/opt/gts9u-npu-bionic/dsp \
        timeout 30 /opt/gts9u-npu-bionic/bin/linker64 \
        /opt/gts9u-npu-bionic/bin/probe-npu-htp 100 \
        >"$report/last-probe.log" 2>&1; then
        echo "HTP client failed after $passes successful clients" >&2
        tail -n 80 "$report/last-probe.log" >&2
        exit 1
    fi
    if ! grep -q 'PASS HTP MatMul+Relu runs=100 ' "$report/last-probe.log"; then
        echo "HTP client returned without PASS after $passes successful clients" >&2
        tail -n 80 "$report/last-probe.log" >&2
        exit 1
    fi
    passes=$((passes + 1))
    for zone in /sys/class/thermal/thermal_zone*; do
        [ -r "$zone/type" ] || continue
        temp=$(cat "$zone/temp"); type=$(cat "$zone/type")
        case "$type" in
            cdsp*) [ "$temp" -gt "$max_cdsp" ] && max_cdsp=$temp ;;
            cpu*) [ "$temp" -gt "$max_cpu" ] && max_cpu=$temp ;;
        esac
    done
    if [ "$max_cdsp" -ge 75000 ] || [ "$max_cpu" -ge 75000 ]; then
        echo "Thermal safety ceiling reached: CDSP=${max_cdsp}mC CPU=${max_cpu}mC" >&2
        exit 1
    fi
    if [ $((passes % 100)) -eq 0 ]; then
        echo "PROGRESS=$(date --iso-8601=seconds) clients=$passes executions=$((passes*100)) cdsp_mC=$max_cdsp cpu_mC=$max_cpu heap_refs=$(cat /sys/module/system_heap/refcnt 2>/dev/null || echo unknown)"
    fi
    [ "$client_delay" = 0 ] || sleep "$client_delay"
    battery=$(cat /sys/class/power_supply/sm5714-battery/capacity 2>/dev/null || echo 100)
    [ "$battery" -lt "$min_battery" ] && min_battery=$battery
    if [ "$passes" -ge "$cycles" ] && { [ "$duration" -eq 0 ] || [ "$(date +%s)" -ge "$end_epoch" ]; }; then break; fi
    if [ "$(cat /sys/class/power_supply/sm5714-battery/status 2>/dev/null || true)" = Discharging ] && [ "$battery" -le 30 ]; then
        echo 'Battery floor reached before requested soak duration' >&2; exit 1
    fi
done
systemctl stop gts9u-npu.service
[ "$(cat "$cdsp/state")" = offline ]
after_shmem=$(awk '/^Shmem:/{print $2}' /proc/meminfo)
delta_shmem=$((after_shmem - before_shmem))
[ "$delta_shmem" -lt 65536 ]
findmnt -no OPTIONS / | tr ',' '\n' | grep -qx rw
alerts=$(journalctl -k -b --since "@$start_epoch" --no-pager | grep -Eic 'oops|BUG:|refcount|ext4.*error|ufs.*error|I/O error' || true)
[ "$alerts" -eq 0 ]
cat >"$report/result.json" <<EOF
{"status":"pass","passes":$passes,"executions":$((passes*100)),"kernel_alerts":$alerts,"max_cdsp_millic":$max_cdsp,"max_cpu_millic":$max_cpu,"min_battery_percent":$min_battery,"shmem_delta_kb":$delta_shmem,"elapsed_seconds":$(($(date +%s)-start_epoch))}
EOF
cat "$report/result.json"
