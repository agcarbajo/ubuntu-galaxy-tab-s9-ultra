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

assert_libfprint_outranks_archive() {
    # One APT transaction installs the staged .deb together with the archive's
    # candidate, and refuses all of it as a downgrade if the local libfprint is
    # not the newer of the two.  The versions are compared before the install
    # so the reason is one line in the build log instead of mmdebstrap's PIPE
    # teardown noise, which is how it surfaced the last time the archive moved.
    local target=$1 staged='' version candidate entry
    # A glob, not `ls | head`: under `pipefail` a glob that matches nothing
    # makes the pipeline fail and `set -e` would take the build down here.
    for entry in "$target"/tmp/local-debs/libfprint-2-2_*.deb; do
        if [ -e "$entry" ]; then staged=$entry; break; fi
    done
    [ -n "$staged" ] || return 0
    version=$(dpkg-deb -f "$staged" Version) || return 1
    candidate=$(chroot "$target" apt-cache policy libfprint-2-2 2>/dev/null |
        awk '$1 == "Candidate:" { value = $2 } END { print value }') || candidate=''
    if [ -z "$candidate" ] || [ "$candidate" = '(none)' ]; then
        return 0
    fi
    if dpkg --compare-versions "$version" gt "$candidate"; then
        return 0
    fi
    # `apt-cache policy` names the installed version as the candidate when it
    # is the newer of the two, so a rootfs that already carries the local build
    # reports the staged version back here.  That is still refused: equal
    # versions leave APT free to install the archive's build, which has no
    # EL721 driver, and nothing in the log would say so.
    if [ "$version" = "$candidate" ]; then
        echo "the staged libfprint-2-2 ($version) has exactly APT's candidate" >&2
        echo "version, which leaves APT free to install the archive build, which" >&2
        echo "carries no EL721 driver.  Raise the gts9uN suffix in" >&2
        echo "scripts/build-libfprint-el721.sh -- or, if this rootfs already has" >&2
        echo "the local build installed, assemble the rootfs from scratch." >&2
        return 1
    fi
    echo "the staged libfprint-2-2 ($version) does not outrank the archive" >&2
    echo "candidate ($candidate), so APT would refuse the local transaction as" >&2
    echo "a downgrade.  Upstream's revision has moved on: rebase" >&2
    echo "packaging/libfprint and name the next revision in" >&2
    echo "scripts/build-libfprint-el721.sh." >&2
    return 1
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
