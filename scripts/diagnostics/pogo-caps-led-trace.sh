#!/bin/sh
# Capture only STM32 I2C writes and LED state during one Caps Lock toggle.
# No input events or key codes are recorded.
set -eu

[ "$(id -u)" -eq 0 ] || { echo 'Run as root' >&2; exit 1; }
duration=${1:-20}
case "$duration" in
    *[!0-9]*|'') echo 'Duration must be 1-120 seconds' >&2; exit 2 ;;
esac
[ "$duration" -ge 1 ] && [ "$duration" -le 120 ] || {
    echo 'Duration must be 1-120 seconds' >&2
    exit 2
}
trace_root=/sys/kernel/tracing
instance=$trace_root/instances/pogo-caps-led
out=$(mktemp -d /var/lib/gts9u-diagnostics/pogo-caps-led-XXXXXXXX)
chmod 0700 "$out"
created=0
cleanup()
{
    if [ "$created" -eq 1 ]; then
        printf '0\n' > "$instance/tracing_on" || :
        printf '0\n' > "$instance/events/i2c/i2c_write/enable" || :
        rmdir "$instance" || :
    fi
}
trap cleanup EXIT HUP INT TERM

[ ! -e "$instance" ] || { echo 'Tracing instance already exists' >&2; exit 1; }
mkdir "$instance"
created=1
device=$(find /sys/bus/i2c/drivers/samsung-gts9u-stm32-pogo -maxdepth 1 \
    -type l -name '*-002a' -print -quit)
[ -n "$device" ] || { echo 'STM32 keyboard device not found' >&2; exit 1; }
adapter=$(basename "$device")
adapter=${adapter%-*}
led=$(find "$device/input" -maxdepth 3 -type d -name '*::capslock' -print -quit)
[ -n "$led" ] || { echo 'Caps Lock LED not found' >&2; exit 1; }

printf 'adapter_nr == %s && addr == 0x2a\n' "$adapter" \
    > "$instance/events/i2c/i2c_write/filter"
printf '0\n' > "$instance/tracing_on"
printf '\n' > "$instance/trace"
printf '1\n' > "$instance/events/i2c/i2c_write/enable"
printf '1\n' > "$instance/tracing_on"

echo "Capturing for $duration seconds: $out"
end=$(($(date +%s) + duration))
while [ "$(date +%s)" -lt "$end" ]; do
    timestamp=$(date +%s.%N)
    brightness=$(cat "$led/brightness")
    diagnostics=$(cat "$device/diagnostics")
    caps=$(printf '%s\n' "$diagnostics" | sed -n 's/.* caps=\([^ ]*\).*/\1/p')
    data_irq=$(printf '%s\n' "$diagnostics" | sed -n 's/.* data_irq=\([^ ]*\).*/\1/p')
    printf '%s led=%s caps=%s data_irq=%s\n' \
        "$timestamp" "$brightness" "$caps" "$data_irq" >> "$out/state.log"
    sleep 0.1
done

printf '0\n' > "$instance/tracing_on"
cat "$instance/trace" > "$out/i2c-write.log"
sha256sum "$out/state.log" "$out/i2c-write.log" > "$out/sha256.txt"
echo "Capture complete: $out"
