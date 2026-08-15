#!/bin/bash
# Swap the four boot partitions between Ubuntu and One UI, over ADB, with the
# tablet sitting in TWRP.
#
# Only boot, init_boot, vendor_boot and dtbo differ between the two systems.
# `vbmeta` is deliberately not in that list: One UI was measured to run fine
# with the unsigned flags=2 vbmeta that Ubuntu needs, and rewriting vbmeta
# invalidates the key Android derives for its metadata-encrypted /data, which
# costs a full data wipe every time.  Leaving it alone is what makes switching
# systems cheap.
#
# It inspects and reports by default.  Writing requires --write, and every
# image is verified by size and by reading the partition back afterwards.
set -uo pipefail

adb=${ADB:-/mnt/c/Users/agcar/ADB/platform-tools/adb.exe}
sets_dir=${BOOT_SETS_DIR:-/mnt/d/gts9u-backup}
target=""
do_write=0
stage=/tmp/lr/_swap

# Sizes are fixed by the partition table, so a wrong or truncated file is
# caught before anything is written.
declare -A want=( [boot]=100663296 [vendor_boot]=100663296 [init_boot]=8388608 [dtbo]=16777216 )

usage() {
	cat <<'EOF'
Usage:
  swap-boot-set.sh --to ubuntu           inspect and report the plan
  swap-boot-set.sh --to oneui --write    write the One UI boot set

Options:
  --to ubuntu|oneui   which system should boot next
  --write             actually write the four partitions

Reads the images from $BOOT_SETS_DIR/{ubuntu,oneui}-boot-set/ (default
/mnt/d/gts9u-backup).  The tablet must be in TWRP.
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
		--to) target=$2; shift 2 ;;
		--write) do_write=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown argument: $1" >&2; usage; exit 2 ;;
	esac
done

case "$target" in
	ubuntu) src=$sets_dir/ubuntu-boot-set ;;
	oneui)  src=$sets_dir/oneui-boot-set ;;
	*) echo '--to must be ubuntu or oneui' >&2; usage; exit 2 ;;
esac

sh_() { "$adb" shell "$@" 2>/dev/null | tr -d '\r'; }
die() { echo "ABORTADO: $*" >&2; exit 1; }

echo '=== el aparato ==='
count=$("$adb" devices 2>&1 | tr -d '\r' | grep -cE '[[:space:]]recovery$')
[ "$count" -eq 1 ] || die 'necesito exactamente un aparato en TWRP.'
twrp=$(sh_ 'getprop ro.twrp.version')
[ -n "$twrp" ] || die 'el aparato no esta en TWRP.'
codename=$(sh_ 'getprop ro.product.device')
case "$codename" in gts9u|gts9uwifi) ;; *) die "esto no es un SM-X910 ('$codename')." ;; esac
printf 'TWRP %s en %s\n' "$twrp" "$codename"

echo
echo "=== juego de origen: $src ==="
for p in boot vendor_boot init_boot dtbo; do
	f=$src/$p.img
	[ -f "$f" ] || die "falta $f"
	sz=$(stat -c %s "$f")
	[ "$sz" = "${want[$p]}" ] || die "$p mide $sz y deberia medir ${want[$p]}"
	printf '  %-12s %10s bytes  %s\n' "$p" "$sz" "$(sha256sum "$f" | cut -d' ' -f1)"
done

echo
echo '=== lo que hay ahora en el aparato ==='
for p in boot vendor_boot init_boot dtbo; do
	printf '  %-12s %s\n' "$p" "$(sh_ "sha256sum /dev/block/by-name/$p" | cut -d' ' -f1)"
done

if [ "$do_write" -eq 0 ]; then
	echo
	echo "Solo inspeccion. Nada se ha escrito. Anade --write para pasar a $target."
	exit 0
fi

echo
echo "=== escribiendo el juego de $target ==="
# linuxroot is the staging area: TWRP's /tmp is a small ramdisk and Android's
# /data cannot be decrypted here.
sh_ "mkdir -p /tmp/lr; mountpoint -q /tmp/lr || mount -t ext4 /dev/block/sda35 /tmp/lr" >/dev/null
sh_ 'mountpoint -q /tmp/lr && echo si' | grep -q si || die 'no pude montar linuxroot para hacer sitio.'
sh_ "mkdir -p $stage" >/dev/null

fail=0
for p in boot vendor_boot init_boot dtbo; do
	f=$src/$p.img
	expect=$(sha256sum "$f" | cut -d' ' -f1)

	"$adb" push "$(wslpath -w "$f")" "$stage/$p.img" >/dev/null 2>&1 || die "no pude enviar $p"
	[ "$(sh_ "sha256sum $stage/$p.img" | cut -d' ' -f1)" = "$expect" ] || \
		die "$p llego corrupto; nada se ha escrito en esa particion"

	sh_ "dd if=$stage/$p.img of=/dev/block/by-name/$p bs=4M 2>/dev/null; sync" >/dev/null
	got=$(sh_ "sha256sum /dev/block/by-name/$p" | cut -d' ' -f1)
	if [ "$got" = "$expect" ]; then
		printf '  %-12s escrita y releida OK\n' "$p"
	else
		printf '  %-12s NO COINCIDE al releer: %s\n' "$p" "$got"
		fail=1
	fi
done

sh_ "rm -rf $stage; umount /tmp/lr" >/dev/null

[ "$fail" -eq 0 ] || die 'alguna particion no coincide; no reinicies sin revisarlo.'

echo
echo "Hecho. El aparato arrancara en $target al reiniciar."
