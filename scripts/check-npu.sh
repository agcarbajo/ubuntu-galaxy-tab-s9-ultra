#!/bin/bash
# Physical HTP validation. Does not activate CDSP or change system configuration.
set -euo pipefail
runtime=${1:-/opt/gts9u-npu-bionic}
if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [staged-runtime-directory]" >&2
    exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run as root to access the diagnostic FastRPC devices.' >&2
    exit 2
fi
umask 077
report=$(mktemp -d /tmp/gts9u-npu-check.XXXXXXXX)
echo "Report: $report"
cdsp=
for processor in /sys/class/remoteproc/remoteproc*; do
    if [ -r "$processor/name" ] && [ "$(cat "$processor/name")" = cdsp ]; then
        if [ -n "$cdsp" ]; then
            echo 'More than one CDSP device found; refusing an ambiguous test.' >&2
            exit 2
        fi
        cdsp=$processor
    fi
done
stats=/sys/module/gts9u_dsp_stats/parameters/snapshot
snapshot() {
    date -Is
    uname -r
    cat /proc/sys/kernel/random/boot_id
    if [ -n "$cdsp" ]; then
        echo "CDSP=$cdsp"
        cat "$cdsp/name" "$cdsp/state" "$cdsp/firmware"
    else
        echo 'CDSP=absent'
    fi
    if [ -r "$stats" ]; then cat "$stats"; fi
}
snapshot > "$report/before.txt"
if [ -z "$cdsp" ] || [ "$(cat "$cdsp/state")" != running ]; then
    echo 'NPU NOT VERIFIED: CDSP is absent or offline.' | tee "$report/result.txt"
    exit 2
fi
for device in /dev/fastrpc-cdsp /dev/dma_heap/system; do
    if [ ! -c "$device" ]; then
        echo "NPU NOT VERIFIED: missing $device" | tee "$report/result.txt"
        exit 2
    fi
done
if [ ! -x "$runtime/bin/test-htp" ]; then
    echo "NPU NOT VERIFIED: missing $runtime/bin/test-htp" | tee "$report/result.txt"
    exit 2
fi
set +e
timeout -k 5 150 "$runtime/bin/test-htp" 100 > "$report/htp.log" 2>&1
result=$?
set -e
snapshot > "$report/after.txt"
printf '%s\n' "$result" > "$report/process-exit.txt"
dmesg > "$report/kernel.log" 2>/dev/null || true
if [ "$result" -eq 0 ] &&
   grep -Eq '^PASS HTP MatMul\+Relu runs=100 elements=102400 max_quantized_error=[01] accel_cycles=[1-9][0-9]*$' "$report/htp.log"; then
    echo 'PASS: 100 HTP executions, numerical validation and accelerator cycles.' | tee "$report/result.txt"
    exit 0
fi
echo "FAIL: HTP validation did not pass (process exit $result)." | tee "$report/result.txt"
tail -20 "$report/htp.log"
exit 1
