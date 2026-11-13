#!/system/bin/sh
# Read-only Android comparison: only I2C writes to the STM32, no key events.
set -eu

[ "$(id -u)" -eq 0 ] || { echo 'Run as root' >&2; exit 1; }
trace_root=/sys/kernel/tracing
instance=$trace_root/instances/pogo-caps-led-android
out=/data/local/tmp/pogo-caps-led-android-$(date +%s)
[ ! -e "$instance" ] || { echo 'Tracing instance already exists' >&2; exit 1; }
[ ! -e "$out" ] || { echo 'Output directory already exists' >&2; exit 1; }
mkdir "$out"
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

mkdir "$instance"
created=1
printf 'adapter_nr == 67 && addr == 0x2a\n' \
    > "$instance/events/i2c/i2c_write/filter"
printf '0\n' > "$instance/tracing_on"
printf '\n' > "$instance/trace"
printf '1\n' > "$instance/events/i2c/i2c_write/enable"
printf '1\n' > "$instance/tracing_on"
echo "Capturing for 60 seconds: $out"
sleep 60
printf '0\n' > "$instance/tracing_on"
cat "$instance/trace" > "$out/i2c-write.log"
grep stm32_pogo_i2c /proc/interrupts > "$out/interrupts.txt" || :
sha256sum "$out/i2c-write.log" "$out/interrupts.txt" > "$out/sha256.txt"
echo "Capture complete: $out"
