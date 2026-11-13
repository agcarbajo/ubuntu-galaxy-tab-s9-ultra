#!/bin/bash
# Test bench for the post-resume storage check.
#
# The states it has to recognise are taken from a real failure on the tablet,
# captured on 2026-11-13 while it was in it: the UFS PHY failed to calibrate
# on resume and the root filesystem was left mounted "rw,noatime,emergency_ro"
# -- rw in the option list, which is exactly why a plain read-only test is not
# enough and this bench exists.
#
# It runs the shipped hook under dash, which is what /bin/sh is on the tablet.
# No root, no device, no suspend.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
HOOK="$repo/packaging/ubuntu-gts9u-device/usr/lib/systemd/system-sleep/ubuntu-gts9u-storage-health"
[ -f "$HOOK" ] || { echo "not found: $HOOK" >&2; exit 1; }

W=$(mktemp -d /tmp/gts9u-storage.XXXXXX)
trap 'rm -rf "$W"' EXIT
failures=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; failures=$((failures + 1)); }

mounts() {  # $1 = the root mount options, with a clean error count
	printf '/dev/sda35 / ext4 %s 0 0\n' "$1" > "$W/mounts"
	printf 'tmpfs /run tmpfs rw,nosuid 0 0\n' >> "$W/mounts"
	errors 0
}

errors() {  # $1 = errors_count of the root filesystem
	mkdir -p "$W/ext4/sda35"
	printf '%s\n' "$1" > "$W/ext4/sda35/errors_count"
}

run() {  # $@ = the hook's arguments
	PATH="$W/bin:$PATH" \
	GTS9U_STORAGE_FLAG="$W/flag" \
	GTS9U_STORAGE_MOUNTS="$W/mounts" \
	GTS9U_STORAGE_EXT4="$W/ext4" \
	GTS9U_STORAGE_SESSIONS="$W/user" \
		dash "$HOOK" "$@" 2>&1
}

mkdir -p "$W/bin" "$W/user/1000"
# The hook addresses a session only through a real socket, as systemd leaves it.
python3 -c 'import socket, sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' 	"$W/user/1000/bus" || { echo 'cannot create a unix socket for the bench' >&2; exit 1; }
for command in logger setpriv notify-send; do
	printf '#!/bin/sh\nprintf "%%s %%s\\n" "%s" "$*" >> "%s/calls"\n' "$command" "$W" \
		> "$W/bin/$command"
	chmod +x "$W/bin/$command"
done

echo '== 1. a healthy resume says nothing =='
mounts 'rw,relatime'
: > "$W/calls"
run post > /dev/null
if [ -e "$W/flag" ]; then bad 'a healthy resume raised the flag'; else ok 'no flag after a healthy resume'; fi
[ -s "$W/calls" ] && bad 'a healthy resume notified the owner' || ok 'no notification after a healthy resume'

echo
echo '== 2. the real failure: rw in the list, emergency_ro beside it =='
mounts 'rw,noatime,emergency_ro'
: > "$W/calls"
run post > /dev/null
if grep -q 'emergency read-only' "$W/flag" 2>/dev/null; then
	ok 'emergency_ro is caught although the mount still says rw'
else
	bad "flag missing or wrong: $(cat "$W/flag" 2>/dev/null)"
fi
grep -q 'notify-send' "$W/calls" && ok 'the owner is told in their session' \
	|| bad 'nobody was notified'
grep -q 'logger' "$W/calls" && ok 'the reason reaches the journal' \
	|| bad 'nothing was logged'

echo
echo '== 3. a plainly read-only root =='
mounts 'ro,relatime'
run post > /dev/null
grep -q 'mounted read-only' "$W/flag" 2>/dev/null \
	&& ok 'a read-only root is caught' || bad 'a read-only root was missed'

echo
echo '== 4. ext4 counted errors while the mount still looks fine =='
mounts 'rw,relatime'
errors 7
run post > /dev/null
if grep -q 'recorded 7 errors on sda35' "$W/flag" 2>/dev/null; then
	ok 'the error count and its device are named'
else
	bad "flag missing or wrong: $(cat "$W/flag" 2>/dev/null)"
fi

echo
echo '== 5. a later healthy resume clears the flag =='
mounts 'rw,relatime'
run post > /dev/null
[ -e "$W/flag" ] && bad 'the stale flag survived a healthy resume' \
	|| ok 'the flag is cleared when storage is back'

echo
echo '== 6. it does nothing on the way into suspend =='
mounts 'rw,noatime,emergency_ro'
: > "$W/calls"
run pre > /dev/null
[ -e "$W/flag" ] && bad 'the pre hook wrote the flag' || ok 'the pre hook is a no-op'
[ -s "$W/calls" ] && bad 'the pre hook notified the owner' || ok 'the pre hook stays quiet'

echo
echo '== 7. a session that is not a real uid is skipped =='
mounts 'ro,relatime'
mkdir -p "$W/user/gdm"
: > "$W/calls"
run post > /dev/null
grep -q 'setpriv --reuid gdm' "$W/calls" && bad 'a non-numeric session was used' \
	|| ok 'only numeric sessions are addressed'

echo
if [ "$failures" -eq 0 ]; then echo 'ALL CORRECT'; else echo "$failures FAILURES"; fi
exit "$failures"
