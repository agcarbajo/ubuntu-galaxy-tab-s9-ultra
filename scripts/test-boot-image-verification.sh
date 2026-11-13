#!/bin/bash
# Test bench for the installer's boot image read-back.
#
# `unzip -p "$ZIPFILE" boot.img | dd of=...` only ever checked dd's status,
# and dd reports success over a stream that never arrived: a member TWRP's
# ziptool cannot read, or a ZIP truncated in transfer, writes nothing, dd
# exits 0, and the installer used to print "Images written." over a partially
# written kernel.  These cases drive the real code from the installer -- the
# block between its verification markers, extracted and not copied, so a
# change to it is what gets tested -- against stand-in partition files.
#
# It runs under mksh on purpose: that is the shell TWRP gives the installer,
# and its 32-bit arithmetic has broken this port before.
#
# Needs no root, no device and no network.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
INSTALLER="$repo/configs/twrp/ubuntu-update-binary"
[ -f "$INSTALLER" ] || { echo "installer not found: $INSTALLER" >&2; exit 1; }
command -v mksh >/dev/null 2>&1 || { echo 'mksh is missing; apt install mksh' >&2; exit 1; }

W=$(mktemp -d /tmp/gts9u-bootverify.XXXXXX)
failures=0
ok()   { echo "  PASS  $1"; }
bad()  { echo "  FAIL  $1"; failures=$((failures + 1)); }
trap 'rm -rf "$W"' EXIT

# The real block, by its markers.  An installer that loses them fails here
# rather than silently losing its verification.
sed -n '/^# --- boot image verification/,/^# --- end boot image verification/p' \
	"$INSTALLER" > "$W/verification.sh"
grep -q '^verify_written_image()' "$W/verification.sh" || {
	echo 'the installer no longer carries the extractable verification block' >&2
	exit 1
}

# Everything the rest of the installer would have defined by now.
cat > "$W/prelude.sh" <<'PRELUDE'
abort() { echo "ABORTED: $1"; exit 9; }
PRELUDE

run_case() {  # $1 = partition name, $2 = device file
	cat "$W/prelude.sh" "$W/verification.sh" > "$W/driver.sh"
	printf 'verify_written_image "%s" "%s"\necho VERIFIED\n' "$1" "$2" >> "$W/driver.sh"
	BOOT_SUMS="$W/SHA256SUMS" mksh "$W/driver.sh" 2>&1
}

image() {  # $1 = file, $2 = bytes
	dd if=/dev/urandom of="$1" bs=1024 count=$(($2 / 1024)) status=none
}

# init_boot's real partition size, since the whole-device hash is only exact
# because every image is built to exactly that.
INIT_BOOT_BYTES=8388608

echo '== 1. a write that arrived verifies =='
image "$W/init_boot.img" "$INIT_BOOT_BYTES"
cp "$W/init_boot.img" "$W/part"
printf '%s  init_boot.img\n' "$(sha256sum "$W/init_boot.img" | cut -d' ' -f1)" \
	> "$W/SHA256SUMS"
out=$(run_case init_boot "$W/part")
case "$out" in
	*VERIFIED*) ok 'a partition holding the image passes' ;;
	*) bad "a good write was rejected: $out" ;;
esac

echo
echo '== 2. the failure that printed "Images written." =='
# dd over an empty stream: the partition keeps whatever it held, dd exits 0.
image "$W/part" "$INIT_BOOT_BYTES"
printf '' | dd of="$W/part" bs=4M conv=notrunc status=none
dd_status=$?
[ "$dd_status" -eq 0 ] && ok 'dd still reports success over an empty stream' \
	|| bad "dd reported $dd_status, so this is no longer the case under test"
out=$(run_case init_boot "$W/part")
case "$out" in
	*VERIFIED*) bad 'an unwritten partition was accepted' ;;
	*"reads back differently"*) ok 'an unwritten partition is caught' ;;
	*) bad "unexpected result: $out" ;;
esac

echo
echo '== 3. a truncated member =='
cp "$W/init_boot.img" "$W/part"
dd if=/dev/zero of="$W/part" bs=1024 count=16 conv=notrunc status=none
out=$(run_case init_boot "$W/part")
case "$out" in
	*"reads back differently"*) ok 'a partially written image is caught' ;;
	*) bad "unexpected result: $out" ;;
esac

echo
echo '== 4. one flipped byte =='
cp "$W/init_boot.img" "$W/part"
printf 'x' | dd of="$W/part" bs=1 seek=4194304 conv=notrunc status=none
out=$(run_case init_boot "$W/part")
case "$out" in
	*"reads back differently"*) ok 'a single changed byte is caught' ;;
	*) bad "unexpected result: $out" ;;
esac

echo
echo '== 5. a partition larger than the image =='
# The installer asserts every partition size against the image size before it
# writes anything.  If that ever stopped being true, the whole-device hash
# would be comparing different lengths, so it must not pass quietly.
cp "$W/init_boot.img" "$W/part"
dd if=/dev/zero of="$W/part" bs=1024 count=8 oflag=append conv=notrunc status=none
out=$(run_case init_boot "$W/part")
case "$out" in
	*"reads back differently"*) ok 'a partition longer than the image is caught' ;;
	*) bad "unexpected result: $out" ;;
esac

echo
echo '== 6. a manifest that does not mention the image =='
cp "$W/init_boot.img" "$W/part"
printf '%s  boot.img\n' "$(sha256sum "$W/init_boot.img" | cut -d' ' -f1)" \
	> "$W/SHA256SUMS"
out=$(run_case init_boot "$W/part")
case "$out" in
	*"no entry for init_boot.img"*) ok 'a missing manifest entry stops the install' ;;
	*VERIFIED*) bad 'a missing manifest entry was ignored' ;;
	*) bad "unexpected result: $out" ;;
esac

echo
echo '== 7. a malformed digest =='
printf 'deadbeef  init_boot.img\n' > "$W/SHA256SUMS"
out=$(run_case init_boot "$W/part")
case "$out" in
	*"malformed digest"*) ok 'a short digest stops the install' ;;
	*) bad "unexpected result: $out" ;;
esac

echo
echo '== 8. the manifest is matched by name, not by substring =='
# `init_boot.img` ends with `boot.img`; a sloppy match would hand the init_boot
# digest to boot, or the other way round, and both would then verify against
# the wrong image.
image "$W/boot.img" 1048576
{
	printf '%s  boot.img\n' "$(sha256sum "$W/boot.img" | cut -d' ' -f1)"
	printf '%s  init_boot.img\n' "$(sha256sum "$W/init_boot.img" | cut -d' ' -f1)"
} > "$W/SHA256SUMS"
cp "$W/boot.img" "$W/part"
out=$(run_case boot "$W/part")
case "$out" in
	*VERIFIED*) ok 'boot.img takes boot.img''s digest' ;;
	*) bad "boot.img was verified against the wrong entry: $out" ;;
esac
cp "$W/init_boot.img" "$W/part"
out=$(run_case init_boot "$W/part")
case "$out" in
	*VERIFIED*) ok 'init_boot.img takes its own digest' ;;
	*) bad "init_boot.img was verified against the wrong entry: $out" ;;
esac

echo
if [ "$failures" -eq 0 ]; then echo 'ALL CORRECT'; else echo "$failures FAILURES"; fi
exit "$failures"
