#!/bin/bash
# Statically validate a generated Android v4 bundle and its TWRP ZIP.
#
# Read-only by construction: it never opens a block device, never writes to a
# partition and never invokes fastboot, adb or TWRP.  Run it before asking
# anyone to flash anything.
set -uo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
bundle=${BUNDLE_OUT_DIR:-$base/out/bundle}
zip=${1:-}
kernel_out=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}

failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
info() { printf 'info  %s\n' "$1"; }

check_size() {
	local name=$1 expected=$2 actual
	actual=$(stat -c %s "$bundle/$name" 2>/dev/null || echo 0)
	if [ "$actual" -eq "$expected" ]; then
		pass "$name is exactly $expected bytes"
	else
		fail "$name is $actual bytes, expected $expected"
	fi
}

echo '=== partition-sized images ==='
check_size boot.img 100663296
check_size init_boot.img 8388608
check_size vendor_boot.img 100663296
check_size dtbo.img 16777216
check_size vbmeta.img 131072

echo
echo '=== boot.img: kernel plus appended DTB ==='
if head -c 8 "$bundle/boot.img" 2>/dev/null | grep -q ANDROID; then
	pass 'boot.img carries the Android boot magic'
else
	fail 'boot.img does not start with ANDROID!'
fi
# ABL only takes the appended-DTB fallback when it finds an FDT after the gzip
# payload.  Verify the DTB we built is present inside boot.img.
if [ -f "$kernel_out/sm8550-samsung-gts9uwifi.dtb" ]; then
	if grep -qc "$(head -c 4 "$kernel_out/sm8550-samsung-gts9uwifi.dtb" | \
		od -An -tx1 | tr -d ' \n')" /dev/null 2>/dev/null; then :; fi
	if python3 - "$bundle/boot.img" "$kernel_out/sm8550-samsung-gts9uwifi.dtb" <<'PY'
import sys, pathlib
boot = pathlib.Path(sys.argv[1]).read_bytes()
dtb = pathlib.Path(sys.argv[2]).read_bytes()
sys.exit(0 if dtb in boot else 1)
PY
	then
		pass 'the built DTB is appended inside boot.img'
	else
		fail 'boot.img does not contain the built DTB'
	fi
fi

echo
echo '=== init_boot.img: LZ4 legacy ramdisk ==='
if python3 - "$bundle/init_boot.img" <<'PY'
import sys, pathlib
data = pathlib.Path(sys.argv[1]).read_bytes()
sys.exit(0 if b"\x02\x21\x4c\x18" in data[:65536] else 1)
PY
then
	pass 'init_boot carries a legacy LZ4 stream'
else
	fail 'init_boot ramdisk is not LZ4 legacy; Linux will reject the initrd'
fi

echo
echo '=== dtbo.img: deliberately not an Android DT table ==='
if head -c 4 "$bundle/dtbo.img" 2>/dev/null | \
	od -An -tx1 | tr -d ' \n' | grep -q '^d7b7ab1e$'; then
	fail 'dtbo.img is a DT table; ABL will take the ufdt path and reject the DTB'
else
	pass 'dtbo.img is not a DT table, so ABL uses the appended-DTB fallback'
fi

echo
echo '=== vbmeta.img: AVB flags 2 ==='
flags=$(dd if="$bundle/vbmeta.img" bs=1 skip=120 count=4 2>/dev/null | \
	od -An -tx1 | tr -d ' \n')
if [ "$flags" = 00000002 ]; then
	pass 'vbmeta has verification and verity disabled (flags=2)'
else
	fail "vbmeta flags are $flags, expected 00000002"
fi

echo
echo '=== vendor_boot.img: DTB, cmdline and bootconfig ==='
python3 - "$bundle/vendor_boot.img" "$repo/configs/vendor_boot/cmdline.txt" \
	"$repo/configs/vendor_boot/bootconfig.txt" \
	"$kernel_out/sm8550-samsung-gts9uwifi.dtb" <<'PY'
import hashlib, pathlib, struct, sys

img, cmdline_src, bootconfig_src, dtb_src = (pathlib.Path(p) for p in sys.argv[1:5])
data = img.read_bytes()
if data[:8] != b"VNDRBOOT":
    print("FAIL  vendor_boot magic is missing")
    sys.exit(1)
hdrv, pagesize, _k, _r, ramdisk_size = struct.unpack_from("<IIIII", data, 8)
cmdline = data[28:28 + 2048].split(b"\0", 1)[0].decode()
off = 28 + 2048 + 4 + 16
header_size, dtb_size = struct.unpack_from("<II", data, off)
off += 8 + 8
table_size, _n, _e, bootconfig_size = struct.unpack_from("<IIII", data, off)

def rnd(x):
    return (x + pagesize - 1) // pagesize * pagesize

p = rnd(header_size) + rnd(ramdisk_size)
dtb = data[p:p + dtb_size]
p += rnd(dtb_size) + rnd(table_size)
bootconfig = data[p:p + bootconfig_size].split(b"\0", 1)[0].decode()

ok = True
print(f"info  header version {hdrv}, page size {pagesize}")

want_cmdline = " ".join(cmdline_src.read_text().split())
if cmdline.strip() == want_cmdline:
    print("PASS  vendor cmdline matches configs/vendor_boot/cmdline.txt")
else:
    print("FAIL  vendor cmdline differs from the repository source")
    ok = False

# root= is the one that would strand the boot in an emergency shell: unlike
# the postmarketOS initramfs, initramfs-tools does not look for its own
# partition. The label is UBTS9U_UFS and not UBTS9U_ROOT so that a microSD
# left over from an older release cannot win the lookup against the copy
# installed on the internal storage. rootwait matters because neither the UFS
# nor a card is necessarily enumerated when the kernel goes looking.
for token in ("root=LABEL=UBTS9U_UFS", "rootwait", "msm.separate_gpu_kms=1"):
    if token in cmdline:
        print(f"PASS  cmdline keeps {token}")
    else:
        print(f"FAIL  cmdline is missing {token}")
        ok = False

# A parameter for a patch this build does not apply is dead weight and a sign
# the cmdline was copied rather than written for this port.
if "ignore_console_null" in cmdline:
    print("FAIL  cmdline passes ignore_console_null, whose patch is not applied by default")
    ok = False
if "pmos." in cmdline:
    print("FAIL  cmdline still carries postmarketOS-specific parameters")
    ok = False

if bootconfig.strip() == bootconfig_src.read_text().strip():
    print("PASS  bootconfig matches configs/vendor_boot/bootconfig.txt")
else:
    print("FAIL  bootconfig differs from the repository source")
    ok = False

if dtb_src.is_file():
    if hashlib.sha256(dtb).hexdigest() == hashlib.sha256(dtb_src.read_bytes()).hexdigest():
        print("PASS  the packed DTB is the one we built")
    else:
        print("FAIL  the packed DTB differs from the built DTB")
        ok = False

# ABL's ufdt fork needs /__symbols__ in this DTB.
if b"__symbols__" in dtb:
    print("PASS  the DTB exports /__symbols__")
else:
    print("FAIL  the DTB has no /__symbols__; ABL will reject it")
    ok = False

sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] || failures=$((failures + 1))

if [ -n "$zip" ] && [ -f "$zip" ]; then
	echo
	echo '=== TWRP ZIP ==='
	# A missing tool must not be reportable as success.  The negative checks
	# below ("the installer never references ...") pass on empty input, so
	# without this guard an absent unzip would silently certify the ZIP.
	if ! command -v unzip >/dev/null 2>&1; then
		fail 'unzip is not installed; ZIP contents cannot be validated'
		echo 'install it with: apt install unzip' >&2
		echo
		echo "$failures check(s) failed. Do not flash this bundle."
		exit 1
	fi
	if unzip -t "$zip" >/dev/null 2>&1; then
		pass 'ZIP CRCs are valid'
	else
		fail 'ZIP failed its CRC check'
	fi
	for member in boot.img init_boot.img vendor_boot.img dtbo.img vbmeta.img \
		META-INF/com/google/android/update-binary SHA256SUMS; do
		if unzip -l "$zip" "$member" >/dev/null 2>&1; then
			pass "ZIP contains $member"
		else
			fail "ZIP is missing $member"
		fi
	done

	# A full-installation ZIP carries the root filesystem and the manifest the
	# installer verifies it against.  An update ZIP carries neither, and says
	# so here rather than looking like a truncated release.
	if unzip -l "$zip" rootfs.img >/dev/null 2>&1; then
		if unzip -l "$zip" ROOTFS-IMAGE >/dev/null 2>&1; then
			pass 'ZIP contains rootfs.img and its ROOTFS-IMAGE manifest'
		else
			fail 'ZIP carries rootfs.img with no ROOTFS-IMAGE manifest'
		fi
		rootfs_line=$(unzip -p "$zip" ROOTFS-IMAGE 2>/dev/null)
		rootfs_bytes=$(printf '%s\n' "$rootfs_line" | cut -d' ' -f2)
		rootfs_mib=$(printf '%s\n' "$rootfs_line" | cut -d' ' -f3)
		if [ "${rootfs_bytes:-0}" -gt 0 ] 2>/dev/null && \
			[ $((rootfs_bytes % 1048576)) -eq 0 ]; then
			pass "the root filesystem image is $((rootfs_bytes / 1048576)) whole MiB"
		else
			fail "the root filesystem image size '$rootfs_bytes' is not whole MiB"
		fi
		if [ "${rootfs_mib:-0}" -gt 0 ] 2>/dev/null && \
			[ "$rootfs_mib" -eq $((rootfs_bytes / 1048576)) ]; then
			pass "the manifest publishes the size in MiB as well as bytes"
		else
			fail "the manifest MiB field '$rootfs_mib' does not match the byte count"
		fi
	else
		info 'no rootfs.img: this is an update ZIP, not a full installation'
	fi
	installer=$(unzip -p "$zip" META-INF/com/google/android/update-binary 2>/dev/null)
	if [ -z "$installer" ]; then
		fail 'the packaged installer could not be read'
	else
		if printf '%s\n' "$installer" | \
			grep -q '^# GTS9U-INSTALLER-CONTRACT: writes boot init_boot vendor_boot dtbo vbmeta linuxroot userdata only$'; then
			pass 'the packaged installer declares the expected contract'
		else
			fail 'the packaged installer does not declare the expected contract'
		fi
		if printf '%s\n' "$installer" | grep -q 'e2fsck -p "\$DATA_TARGET"'; then
			pass 'the installer preens the Ubuntu rootfs before mounting it read-write'
		else
			fail 'the installer does not validate the Ubuntu rootfs with e2fsck'
		fi
		if printf '%s\n' "$installer" | grep -q 'WRITTEN_SHA" = "\$ROOTFS_SHA'; then
			pass 'the installer hashes back the root filesystem it wrote'
		else
			fail 'the installer does not verify the root filesystem it writes'
		fi
		if printf '%s\n' "$installer" | grep -q 'the ZIP is stored on the installation target'; then
			pass 'the installer refuses to run from the partition it overwrites'
		else
			fail 'the installer does not check where the ZIP itself is stored'
		fi

		# TWRP's unzip is AOSP ziptool, and `unzip -l ZIP MEMBER` exits 0 for a
		# member that is not there.  Every membership test written that way
		# silently succeeds, which is how a ZIP with no overlay was rejected
		# for carrying one.  The installer reads the listing once and asks awk;
		# more than one `unzip -l` means someone went back to the idiom that
		# cannot fail.
		listings=$(printf '%s\n' "$installer" | sed 's/#.*//' | \
			grep -c 'unzip -l' || true)
		if [ "$listings" -eq 1 ]; then
			pass 'the installer tests ZIP membership against a real listing'
		else
			fail "the installer runs 'unzip -l' $listings times; it cannot be used as a test"
		fi

		# TWRP runs the installer with mksh, whose arithmetic and test(1) are
		# 32-bit signed.  Any quantity above 2 GiB wraps to a negative number
		# there, and the symptom is an abort on a ZIP that is perfectly fine —
		# which is how v0.18 failed its first flash, on the image's own byte
		# count.  Sizes in the installer are therefore counted in MiB, and a
		# ten-digit literal is the cheapest sign that someone went back to
		# bytes.
		if printf '%s\n' "$installer" | sed 's/#.*//' | \
			grep -qE '[^0-9][0-9]{10,}'; then
			fail 'installer code has a literal above 2 GiB; mksh cannot compare it'
			printf '%s\n' "$installer" | sed 's/#.*//' | \
				grep -nE '[^0-9][0-9]{10,}' | head -3 | sed 's/^/      /'
		else
			pass 'installer code keeps every number inside 32-bit range'
		fi

		# Check executable code, not prose: the installer's own comments name
		# the partitions it promises never to touch, and grepping the whole
		# file would flag exactly the documentation that makes it safe.
		#
		# userdata left this list when the root filesystem moved into it, and
		# linuxroot joined it later as the preferred target on a tablet that
		# has been split.  They are the only two names that may be written.
		# What replaces the guarantee for them is the check below: no tool
		# that could alter the partition table may appear anywhere in the
		# installer, so choosing between the two can never become a change to
		# the GPT.
		code=$(printf '%s\n' "$installer" | sed 's/#.*//')

		# `super` is the one exception, and only for reading: the installer
		# mounts Android's system read-only to learn what that Android calls
		# itself, so the dual-boot entry says "One UI 8" instead of guessing.
		# Reading it is allowed; writing it is not, and the two are told apart
		# rather than lumped together — a blanket ban on the word would only
		# have been satisfied by renaming a variable, which protects nothing.
		super_lines=$(printf '%s\n' "$code" | grep -nE '\bsuper\b' || true)
		super_bad=$(printf '%s\n' "$super_lines" | \
			grep -vE 'SUPER_MOUNT|mount -o ro|umount|mapper/system' || true)
		if [ -n "$(printf '%s' "$super_bad" | tr -d '[:space:]')" ]; then
			fail 'installer names super outside a read-only mount'
			printf '%s\n' "$super_bad" | head -5 | sed 's/^/      /'
		else
			pass 'super is only ever mounted read-only'
		fi

		if printf '%s\n' "$code" | \
			grep -qE '\b(pit|efs|persist|modem|modemst|md5|sbl|xbl|abl)\b'; then
			fail 'installer code references a partition it must never touch'
			printf '%s\n' "$code" | \
				grep -nE '\b(pit|efs|persist|modem|modemst)\b' | \
				head -5 | sed 's/^/      /'
		else
			pass 'installer code never names PIT, EFS, persist or modem'
		fi

		# Whatever else changes, nothing may write into super.
		if printf '%s\n' "$code" | \
			grep -qE '(dd +of=[^ ]*super|mkfs[^ ]* [^ ]*super|> *[^ ]*super)'; then
			fail 'installer appears to write into super'
		else
			pass 'nothing in the installer writes into super'
		fi

		# The only writes must be dd into a resolved partition handle.  This is
		# what keeps writing into userdata from becoming a change to the
		# partition table: with no partitioner and no mkfs in the installer,
		# the GPT Samsung shipped cannot be touched, and Odin stays a one-step
		# way back.
		writes=$(printf '%s\n' "$code" | grep -cE '\bdd +(if|of)=' || true)
		if [ "$writes" -gt 0 ] && \
			! printf '%s\n' "$code" | \
			grep -qE '\b(mkfs|mke2fs|wipefs|sgdisk|gdisk|fdisk|sfdisk|parted|partx|format|fastboot)\b'; then
			pass 'the installer only writes with dd, and never formats or repartitions'
		else
			fail 'the installer contains a formatting or partitioning command'
		fi
	fi
	info "ZIP SHA-256: $(sha256sum "$zip" | cut -d' ' -f1)"
fi

echo
if [ "$failures" -eq 0 ]; then
	echo 'All static checks passed. Nothing was written to any device.'
	exit 0
fi
echo "$failures check(s) failed. Do not flash this bundle."
exit 1
