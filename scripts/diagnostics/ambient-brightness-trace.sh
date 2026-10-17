#!/bin/sh
# Record ambient light and panel brightness side by side, to diagnose a
# brightness that keeps rising and falling (issue #8).  Run it in the graphical
# session of the account whose desktop misbehaves; it only reads.
#
# Output: a TSV in the current directory with one line per 250 ms:
#   monotonic seconds, lux reported by iio-sensor-proxy, panel brightness,
#   GNOME's ambient-enabled setting.  Attach the file to the report together
#   with a description of the room light and of what was on screen.
set -eu

duration=${1:-60}
case "$duration" in
    *[!0-9]*|'') echo 'Duration must be 1-600 seconds' >&2; exit 2 ;;
esac
[ "$duration" -ge 1 ] && [ "$duration" -le 600 ] || {
    echo 'Duration must be 1-600 seconds' >&2
    exit 2
}
panel=/sys/class/backlight/ae94000.dsi.0
[ -f "$panel/brightness" ] || panel=$(ls -d /sys/class/backlight/* 2>/dev/null | head -1)
[ -n "$panel" ] && [ -f "$panel/brightness" ] || {
    echo 'No backlight device found' >&2
    exit 1
}
out=ambient-brightness-$(date +%Y%m%d-%H%M%S).tsv

lux() {
    # LightLevel is only live while a client (GNOME) has claimed the sensor.
    busctl --system get-property net.hadess.SensorProxy /net/hadess/SensorProxy \
        net.hadess.SensorProxy LightLevel 2>/dev/null | awk '{print $2}'
}
ambient=$(gsettings get org.gnome.settings-daemon.plugins.power ambient-enabled 2>/dev/null || echo unknown)
max=$(cat "$panel/max_brightness")
printf 'seconds\tlux\tbrightness(max %s)\tambient-enabled\n' "$max" > "$out"
echo "Recording $duration s to $out (panel $panel, ambient-enabled=$ambient)"
start=$(cut -d' ' -f1 /proc/uptime)
end=$(awk -v s="$start" -v d="$duration" 'BEGIN { print s + d }')
while :; do
    now=$(cut -d' ' -f1 /proc/uptime)
    awk -v n="$now" -v e="$end" 'BEGIN { exit !(n < e) }' || break
    printf '%s\t%s\t%s\t%s\n' "$now" "$(lux)" "$(cat "$panel/brightness")" "$ambient" >> "$out"
    sleep 0.25
done
lines=$(($(wc -l < "$out") - 1))
echo "Done: $lines samples in $out"
awk -F'\t' 'NR > 1 && $3 != "" { if (min == "" || $3 < min) min = $3; if ($3 > max) max = $3; n++; if (NR > 2 && $3 != prev) changes++; prev = $3 }
    END { if (n) printf "brightness min %s max %s, changed %d times in %d samples\n", min, max, changes, n }' "$out"
