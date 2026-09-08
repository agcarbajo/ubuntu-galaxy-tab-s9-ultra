#!/bin/bash
# Narrow, audited boot-only trial deployment. Never modifies vendor_boot/init_boot.
set -euo pipefail
old=33643c8c9c4d26da8988d133b1c3b5af8e3999f02cd3e0d40e7fbf12bdfaf811
new=a48a7d1b81e27641683fc930b5f9c712990e3748121b09b1cc82bd33e5d9ac8f
backup=/var/lib/gts9u-kernel-backups/pre-fod-kernel8-20260908
unit=gts9u-fod-kernel8-rollback.service
device=/dev/disk/by-partlabel/boot
size=100663296
hash() { sha256sum "$1" | awk '{print $1}'; }
check_device() {
    test -b "$device"
    test "$(lsblk -dnro PARTLABEL "$(readlink -f "$device")")" = boot
    test "$(blockdev --getsize64 "$device")" = "$size"
}
test "$(id -u)" = 0
case "${1:-}" in
    rollback)
        # Runs on the next boot; gives the owner ten minutes to validate it.
        sleep 600
        check_device
        test "$(hash "$backup/boot.img")" = "$old"
        current=$(hash "$device")
        if test "$current" = "$old"; then
            systemctl disable "$unit"
            exit 0
        fi
        test "$current" = "$new" # Do not overwrite an unrelated later change.
        dd if="$backup/boot.img" of="$device" bs=4M conv=fsync status=none
        test "$(hash "$device")" = "$old"
        systemctl disable "$unit"
        sync
        systemctl reboot
        ;;
    install)
        candidate=${2:?Candidate image required}
        service_file=${3:?Rollback unit required}
        check_device
        test ! -e "$backup"
        test ! -e "/etc/systemd/system/$unit"
        test "$(stat -c %s "$candidate")" = "$size"
        test "$(hash "$candidate")" = "$new"
        test "$(hash "$device")" = "$old"
        install -d -m 0700 "$backup"
        dd if="$device" of="$backup/boot.img" bs=4M iflag=fullblock status=none
        test "$(hash "$backup/boot.img")" = "$old"
        # Stage a root-owned candidate; recheck it before the partition write.
        install -m 0600 "$candidate" "$backup/candidate.img"
        test "$(hash "$backup/candidate.img")" = "$new"
        install -m 0700 "$0" "$backup/deploy.sh"
        install -m 0644 "$service_file" "/etc/systemd/system/$unit"
        systemctl daemon-reload
        systemctl enable "$unit" # Do not start its countdown until reboot.
        if ! dd if="$backup/candidate.img" of="$device" bs=4M conv=fsync status=none ||
           test "$(hash "$device")" != "$new"; then
            dd if="$backup/boot.img" of="$device" bs=4M conv=fsync status=none
            test "$(hash "$device")" = "$old"
            systemctl disable "$unit"
            echo 'Write failed; previous boot restored. Do not reboot.' >&2
            exit 1
        fi
        sync
        echo "VERIFIED: kernel #8 staged; previous boot at $backup/boot.img"
        echo 'Ten-minute rollback enabled for next boot. Reboot is a separate action.'
        ;;
    *) echo 'Usage: install-fod-kernel8.sh install IMAGE UNIT | rollback' >&2; exit 2 ;;
esac
