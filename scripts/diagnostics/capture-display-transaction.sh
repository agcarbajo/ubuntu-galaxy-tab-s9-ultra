#!/bin/bash
set -euo pipefail
duration=${1:-180}
out=${2:-/home/$(id -un 1000)/display-transaction-capture}
case $duration in
    ''|*[!0-9]*) echo 'duration must be an integer' >&2; exit 2 ;;
esac
[ "$duration" -ge 10 ] && [ "$duration" -le 900 ] || {
    echo 'duration must be between 10 and 900 seconds' >&2
    exit 2
}
uid=$(loginctl list-sessions --no-legend | awk '$4 == "seat0" && $7 == "no" {print $2; exit}')
[ -n "$uid" ] || uid=$(awk -F: '$3 >= 1000 && $3 < 60000 {print $3; exit}' /etc/passwd)
user=$(getent passwd "$uid" | cut -d: -f1)
group=$(id -gn "$user")
test ! -e "$out"
install -d -m 0750 -o "$user" -g "$group" "$out"
debug=/sys/module/drm/parameters/debug
original=$(cat "$debug")
start=$(date +%s)
runuser -u "$user" -- env XDG_RUNTIME_DIR="/run/user/$uid" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
    timeout "$duration" dbus-monitor --session \
    "type='method_call',interface='org.gnome.Mutter.DisplayConfig'" \
    > "$out/dbus.log" 2>&1 &
dbus_pid=$!
timeout "$duration" udevadm monitor --kernel --property --subsystem-match=drm \
    > "$out/udev.log" 2>&1 &
udev_pid=$!
(
    end=$((SECONDS + duration))
    while [ "$SECONDS" -lt "$end" ]; do
        printf '%s ' "$(date +%s.%N)"
        cat /sys/class/backlight/ae94000.dsi.0/actual_brightness
        sleep 0.1
    done
) > "$out/brightness.log" 2>&1 &
brightness_pid=$!
(
    trap 'printf "%s" "$original" > "$debug"' EXIT INT TERM
    printf '%d\n' $((original | 0x114)) > "$debug"
    cat /sys/kernel/debug/dri/1/state > "$out/drm-before.txt"
    sleep "$duration"
    cat /sys/kernel/debug/dri/1/state > "$out/drm-after.txt"
    journalctl -b _TRANSPORT=kernel --since="@$start" --no-pager -o short-precise \
        > "$out/kernel.log"
    journalctl -b _UID="$uid" --since="@$start" --no-pager -o short-precise \
        > "$out/user.log"
    wait "$dbus_pid" "$udev_pid" "$brightness_pid" 2>/dev/null || true
    chown -R "$user:$group" "$out"
) > "$out/capture.log" 2>&1 &
printf 'capture_pid=%s\nout=%s\n' "$!" "$out"
