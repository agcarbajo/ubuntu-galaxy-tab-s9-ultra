#!/bin/sh
# Temporary systemd-sleep hook for the lid/charger suspend investigation.
# Install as /usr/lib/systemd/system-sleep/gts9u-lid-charger-diagnostic.
set -u

log=/var/log/gts9u-lid-charger-suspend.log
umask 077
{
    printf '\n=== %s phase=%s state=%s boot=%s ===\n' \
        "$(date --iso-8601=seconds)" "${1:-unknown}" "${2:-unknown}" \
        "$(cat /proc/sys/kernel/random/boot_id)"
    printf 'uptime='; cat /proc/uptime
    printf 'mem_sleep='; cat /sys/power/mem_sleep
    for property in \
        sm5714-battery/capacity sm5714-battery/status \
        sm5714-usb/online sm5714-usb/usb_type \
        tcpm-source-psy-8-0033/online; do
        path=/sys/class/power_supply/$property
        if [ -r "$path" ]; then
            printf '%s=' "$property"
            cat "$path"
        fi
    done
    printf 'wakeup IRQs:\n'
    grep -iE 'wacom|sm5714|pmic|pwrkey|gpio-keys' /proc/interrupts || :
    printf 'root mount='; findmnt -no OPTIONS /
} >> "$log" 2>&1

# A hard reset may follow immediately: force this small record to disk before
# the system enters sleep.  Do not call journalctl --sync from a sleep hook:
# on the tablet the hook reached its marker but never returned from pre.
sync -f "$log"
logger -t gts9u-suspend-diagnostic "phase=${1:-unknown} state=${2:-unknown} boot=$(cat /proc/sys/kernel/random/boot_id)"
