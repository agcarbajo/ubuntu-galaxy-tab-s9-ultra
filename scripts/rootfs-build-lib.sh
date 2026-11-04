#!/bin/bash
# Build-host helpers only; these never operate on a tablet.

unmount_rootfs() {
    local rootfs=$1 relative target attempt
    [ -d "$rootfs" ] || return 0
    rootfs=$(cd "$rootfs" && pwd -P) || return 1
    if [ "$rootfs" = / ]; then
        echo 'refusing to unmount build paths under the host root' >&2
        return 1
    fi
    for relative in dev/pts dev sys proc; do
        target=$rootfs/$relative
        if [ -L "$target" ]; then
            echo "refusing a symlink at rootfs mount path: $target" >&2
            return 1
        fi
        for attempt in 1 2 3; do
            if ! mountpoint -q "$target"; then
                break
            fi
            umount -R "$target" || true
            if ! mountpoint -q "$target"; then
                break
            fi
            if [ "$attempt" -lt 3 ]; then sleep 1; fi
        done
        if mountpoint -q "$target"; then
            echo "rootfs still has a live mount: $target" >&2
            return 1
        fi
    done
}

normalize_image_root() {
    # Both tar streams contain './' and can replace the image root's metadata
    # with that of a staging directory owned by the build user.
    chown 0:0 "$1"
    chmod 0755 "$1"
}

verify_image_root() {
    local inode
    inode=$(LC_ALL=C debugfs -R 'stat <2>' "$1" 2>/dev/null) || return 1
    if ! printf '%s\n' "$inode" | grep -Eq 'Type: directory[[:space:]]+Mode:[[:space:]]+0*755([[:space:]]|$)' ||
       ! printf '%s\n' "$inode" | grep -Eq 'User:[[:space:]]+0[[:space:]]+Group:[[:space:]]+0([[:space:]]|$)'; then
        echo 'finished image root must be a directory owned by 0:0 with mode 0755' >&2
        return 1
    fi
}
