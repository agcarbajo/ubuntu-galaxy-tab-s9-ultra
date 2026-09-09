# Executed by BootMaintenance under the same lock as partition switching.
# Only backup files are written. No dd destination is a block device.
set -eu
mountpoint=/mnt/gts9u-linuxroot
base=$mountpoint/var/lib/gts9u-boot-sets
backup=$mountpoint/var/lib/gts9u-boot-backups
# SET_ID, SYSTEM_NAME, EXPECTED and CHANGED are assigned by the caller.
case "$SET_ID" in ''|*[!a-zA-Z0-9_-]*) exit 1;; esac
case "$(getprop ro.product.device)" in gts9u|gts9uwifi) ;; *) exit 1;; esac
if grep " $mountpoint " /proc/mounts | grep -q noload; then
    echo "Android: Linux filesystem needs recovery; backup unchanged."
    exit 1
fi
old=$base/$SET_ID
previous=$backup/$SET_ID.previous
stage=$backup/$SET_ID.pending
scratch=/data/local/tmp/gts9u-boot-check
writable=0
cleanup() {
    result=$?
    set +e
    if [ "$writable" = 1 ] && [ ! -d "$old" ] && [ -d "$previous" ]; then mv "$previous" "$old"; fi
    sync
    if [ "$writable" = 1 ]; then mount -o remount,ro "$mountpoint" || result=1; fi
    rm -rf "$scratch"
    exit "$result"
}
trap cleanup EXIT
# Verify a changed kernel belongs to this running Android before trusting any
# unknown image, including images left by an interrupted external switch.
if [ "$CHANGED" = 1 ]; then
    mkdir -p "$scratch"
    (cd "$scratch"; /data/adb/magisk/magiskboot unpack /dev/block/by-name/boot >/dev/null 2>&1)
    grep -aFq "Linux version $(uname -r) " "$scratch/kernel"
fi
mount -o remount,rw "$mountpoint"
writable=1
mkdir -p "$backup"
# Recover a power loss between the two directory renames.
if [ ! -d "$old" ] && [ -d "$previous" ]; then mv "$previous" "$old"; fi
if [ "$CHANGED" = 1 ]; then
    rm -rf "$stage"
    mkdir "$stage"
    for part in boot init_boot vendor_boot dtbo; do
        case "$part" in
            boot|vendor_boot) bytes=100663296;;
            init_boot) bytes=8388608;;
            dtbo) bytes=16777216;;
        esac
        test "$(blockdev --getsize64 /dev/block/by-name/$part)" = "$bytes"
        dd if=/dev/block/by-name/$part of="$stage/$part.img" bs=4M 2>/dev/null
        test "$(stat -c %s "$stage/$part.img")" = "$bytes"
    done
    printf '%s\n' "$EXPECTED" > "$stage/expected"
    (cd "$stage"; sha256sum -c expected)
    # A concurrent OTA/root tool must not turn the snapshot into a mixed set.
    for part in boot init_boot vendor_boot dtbo; do
        test "$(sha256sum /dev/block/by-name/$part | cut -d ' ' -f1)" = "$(sha256sum "$stage/$part.img" | cut -d ' ' -f1)"
    done
    printf '%s\n' "$SYSTEM_NAME" > "$stage/name.txt"
    rm "$stage/expected"
    sync
    rm -rf "$previous"
    if [ -d "$old" ]; then mv "$old" "$previous"; fi
    mv "$stage" "$old"
    sync
    echo 'Android: backup updated and verified; previous copy retained.'
else
    printf '%s\n' "$SYSTEM_NAME" > "$old/name.txt.new"
    mv "$old/name.txt.new" "$old/name.txt"
    echo 'Android: backup label corrected.'
fi
