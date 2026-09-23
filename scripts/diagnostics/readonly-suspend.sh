#!/bin/sh
set -eu
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
state=/run/gts9u-readonly-suspend
root_label=/dev/disk/by-partlabel/linuxroot

root_options() { findmnt -no OPTIONS /; }
readonly_root() {
    case ",$(root_options)," in *,ro,*) return 0;; *) return 1;; esac
}
check() {
    test "$(tr -d '\000' < /proc/device-tree/model)" = 'Samsung Galaxy Tab S9 Ultra Wi-Fi'
    test "$(readlink -f "$(findmnt -no SOURCE /)")" = "$(readlink -f "$root_label")"
    test "$(blockdev --getro "$root_label")" = 0
    test "$(cat /sys/class/power_supply/sm5714-battery/capacity)" -ge 20
    test "$(cat /sys/power/mem_sleep)" = 's2idle [deep]'
    case ",$(root_options)," in *,rw,*) ;; *) return 1;; esac
    python3 -c 'import json,subprocess; assert json.loads(subprocess.check_output(["gts9u-update", "--status"]))["state"] == "complete"'
    test "$(swapon --show=NAME,USED --noheadings --raw | awk '$1 == "/swapfile" { print $2 }')" = 0B
    other_mounts=$(findmnt -rn -o SOURCE,TARGET,OPTIONS | awk '$1 ~ "^/dev/" && $2 != "/" && $3 ~ "(^|,)rw(,|$)" { print $2 }')
    if [ -n "$other_mounts" ]; then
        printf 'Writable external mounts must be safely unmounted first: %s\n' "$other_mounts" >&2
        return 1
    fi
    systemctl is-active --quiet gdm3.service
    test ! -e "$state"
}
rollback() {
    trap - EXIT INT TERM
    if readonly_root; then
        mount -o remount,rw / || exit 1
    fi
    if ! swapon --show=NAME --noheadings --raw | awk '$1 == "/swapfile" { found=1 } END { exit !found }'; then
        swapon /swapfile || exit 1
    fi
    systemctl start gdm3.service
    printf 'restored\n' > "$state/status"
}
prepare() {
    check
    mkdir -m 700 "$state"
    trap rollback EXIT INT TERM
    systemctl stop gdm3.service
    swapoff /swapfile
    sync
    mount -o remount,ro /
    readonly_root
    timeout 25 dd if="$root_label" of="$state/reference" bs=1M count=8 iflag=direct status=none
    cat /sys/power/suspend_stats/fail > "$state/fail-before"
    printf 'prepared\n' > "$state/status"
    trap - EXIT INT TERM
}
probe() {
    test "$(cat "$state/status")" = prepared
    readonly_root
    timeout 25 dd if="$root_label" of="$state/after" bs=1M count=8 iflag=direct status=none
    cmp "$state/reference" "$state/after"
    test "$(cat /sys/power/suspend_stats/fail)" = "$(cat "$state/fail-before")"
    printf 'PM wake IRQ: '
    cat /sys/power/pm_wakeup_irq
    printf 'Root remains read-only; uncached storage read matched.\n'
}
case "${1:-}" in
    preflight) check && printf 'PASS: suitable for a supervised read-only suspend preparation\n' ;;
    prepare) prepare ;;
    probe) probe ;;
    restore) test -d "$state" && rollback ;;
    *) printf 'Usage: %s preflight|prepare|probe|restore\n' "$0" >&2; exit 2 ;;
esac
