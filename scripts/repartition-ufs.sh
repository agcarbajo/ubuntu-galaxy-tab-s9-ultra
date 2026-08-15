#!/bin/bash
# Split the internal UFS `userdata` into an Android `userdata` and a Linux
# `linuxroot`, over ADB, with the tablet sitting in TWRP.
#
# It inspects and reports by default.  Repartitioning requires --write, and
# every guard below has to pass first.  Nothing but GPT entry 34 is ever
# touched: `super` keeps Android's system, and no other entry is read or moved.
#
# The split is a percentage, not a size, so the same numbers work on the 256 GB,
# 512 GB and 1 TB models.  All of the arithmetic happens here, in bash on the
# build machine; the tablet only ever receives literal sector numbers.  That is
# deliberate — TWRP's shell is mksh, whose arithmetic is 32-bit, and every
# sector count on a 1 TB device overflows it.
set -uo pipefail

adb=${ADB:-/mnt/c/Users/agcar/ADB/platform-tools/adb.exe}
disk=/dev/block/sda
percent=50
do_write=0
backup_dir=""

# Samsung gives `userdata` the same value for its type GUID and its unique GUID.
# Both are reproduced on the partition we recreate, so the entry comes back
# byte-identical apart from its size.
UD_GUID=1B81E7E6-F50D-419B-A739-2AEEF8DA3335
# 0FC63DAF-… is "Linux filesystem", which is what efs, bota, prism, optics and
# omr already use on this device.
LR_GUID=0FC63DAF-8483-4772-8E79-3D69D8477DE4
# The disk is 4096 bytes per logical sector, so 512 sectors is 2 MiB.
ALIGN=512
EXPECT_DISK_GUID=98101B32-BBE2-4BF2-A06E-2BB33D000C20
EXPECT_UD_START=3626496

usage() {
	cat <<'EOF'
Usage:
  repartition-ufs.sh                                inspect and print the plan
  repartition-ufs.sh --android-percent 40           plan a 40/60 split
  repartition-ufs.sh --android-percent 40 --write   do it, after all guards

Options:
  --android-percent N   share of the current userdata left to Android (default 50)
  --backup-dir DIR      pull the live GPT here before writing (default: required
                        with --write)
  --write               actually repartition

The tablet must be in TWRP, with USB debugging reachable.  It never runs while a
system is booted.
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
		--android-percent) percent=$2; shift 2 ;;
		--backup-dir) backup_dir=$2; shift 2 ;;
		--write) do_write=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown argument: $1" >&2; usage; exit 2 ;;
	esac
done

case "$percent" in
	''|*[!0-9]*) echo "--android-percent must be a whole number" >&2; exit 2 ;;
esac
if [ "$percent" -lt 5 ] || [ "$percent" -gt 95 ]; then
	echo "--android-percent must be between 5 and 95; got $percent" >&2
	exit 2
fi

# The Windows adb.exe terminates every line with CRLF, so anything anchored to
# end-of-line silently fails to match unless the carriage return is stripped.
sh_() { "$adb" shell "$@" 2>/dev/null | tr -d '\r'; }
adb_() { "$adb" "$@" 2>&1 | tr -d '\r'; }

die() { echo "ABORTADO: $*" >&2; exit 1; }

echo '=== adb ==='
count=$(adb_ devices | grep -cE '[[:space:]](device|recovery)$')
[ "$count" -eq 0 ] && die 'no llego al aparato. Ponlo en TWRP y conecta el USB.'
[ "$count" -gt 1 ] && { adb_ devices; die 'hay mas de un aparato conectado; no adivino.'; }
adb_ devices -l | grep -E '[[:space:]](device|recovery)[[:space:]]'

echo
echo '=== tiene que estar en TWRP, no en un sistema arrancado ==='
twrp=$(sh_ getprop ro.twrp.version)
codename=$(sh_ getprop ro.product.device)
printf 'twrp=%s codename=%s\n' "${twrp:-ninguno}" "${codename:-desconocido}"
case "$codename" in
	gts9u|gts9uwifi) ;;
	*) die "esto no es un SM-X910 (codename '$codename')." ;;
esac
[ -n "$twrp" ] || die 'no veo ro.twrp.version: el aparato no esta en TWRP.'
[ "$(sh_ id -u)" = "0" ] || die 'el shell de adb no es root.'

echo
echo '=== la herramienta ==='
sgdisk=$(sh_ 'command -v sgdisk')
[ -n "$sgdisk" ] || die 'este TWRP no trae sgdisk.'
echo "sgdisk: $sgdisk"

echo
echo '=== el disco es el que creemos ==='
disk_guid=$(sh_ "sgdisk --print $disk" | sed -n 's/^Disk identifier (GUID): //p')
echo "disk GUID: ${disk_guid:-ninguno}"
[ "$disk_guid" = "$EXPECT_DISK_GUID" ] || \
	die "el GUID del disco no es el esperado ($EXPECT_DISK_GUID). Esto no es la UFS interna de esta tablet."

info=$(sh_ "sgdisk --info=34 $disk")
ud_name=$(printf '%s\n' "$info" | sed -n "s/^Partition name: '\(.*\)'$/\1/p")
ud_type=$(printf '%s\n' "$info" | sed -n 's/^Partition GUID code: \([0-9A-Fa-f-]*\).*/\1/p')
ud_first=$(printf '%s\n' "$info" | sed -n 's/^First sector: \([0-9]*\).*/\1/p')
ud_last=$(printf '%s\n' "$info" | sed -n 's/^Last sector: \([0-9]*\).*/\1/p')

printf 'entrada 34: nombre=%s tipo=%s primer=%s ultimo=%s\n' \
	"${ud_name:-?}" "${ud_type:-?}" "${ud_first:-?}" "${ud_last:-?}"

[ "$ud_name" = userdata ] || die "la entrada 34 no se llama userdata, se llama '$ud_name'."
[ "$ud_type" = "$UD_GUID" ] || die "el tipo de la entrada 34 no es el esperado."
[ "$ud_first" = "$EXPECT_UD_START" ] || \
	die "userdata no empieza en $EXPECT_UD_START sino en $ud_first."
[ -n "$(sh_ "sgdisk --info=35 $disk" | sed -n 's/^Partition name.*/x/p')" ] && \
	die 'ya existe una entrada 35; esta tablet ya esta reparticionada.'

# --- the arithmetic, in 64-bit bash, never on the tablet ---------------------
total=$(( ud_last - ud_first + 1 ))
android=$(( total * percent / 100 ))
android=$(( android / ALIGN * ALIGN ))
ud_new_last=$(( ud_first + android - 1 ))
lr_first=$(( ud_new_last + 1 ))
lr_last=$ud_last
linux=$(( lr_last - lr_first + 1 ))

[ "$android" -gt 0 ] || die 'la parte de Android sale vacia.'
[ "$linux" -gt 0 ] || die 'la parte de Linux sale vacia.'
[ $(( android + linux )) -eq "$total" ] || die 'las cuentas no cuadran.'
[ $(( lr_first % ALIGN )) -eq 0 ] || die "linuxroot no queda alineada a $ALIGN sectores."

gib() { awk -v s="$1" 'BEGIN { printf "%.1f GiB", s * 4096 / 1073741824 }'; }

echo
echo "=== el plan ($percent% Android / $(( 100 - percent ))% Linux) ==="
printf 'ahora   34 userdata   %14d - %-14d %16d sectores  %s\n' \
	"$ud_first" "$ud_last" "$total" "$(gib "$total")"
echo '        ---'
printf 'despues 34 userdata   %14d - %-14d %16d sectores  %s\n' \
	"$ud_first" "$ud_new_last" "$android" "$(gib "$android")"
printf 'despues 35 linuxroot  %14d - %-14d %16d sectores  %s\n' \
	"$lr_first" "$lr_last" "$linux" "$(gib "$linux")"

if [ "$do_write" -eq 0 ]; then
	echo
	echo 'Solo inspeccion. Nada se ha escrito. Anade --write para hacerlo.'
	exit 0
fi

# --- from here on it writes --------------------------------------------------
[ -n "$backup_dir" ] || die '--write exige --backup-dir: la GPT viva se guarda antes de tocarla.'
mkdir -p "$backup_dir" || die "no puedo crear $backup_dir"
stamp=$(date +%Y%m%d-%H%M%S)
out="$backup_dir/gpt-sda-$stamp.bin"

echo
echo '=== respaldo de la GPT viva ==='
sh_ "sgdisk --backup=/tmp/gpt-live.bin $disk" || die 'sgdisk --backup fallo.'
# adb is the Windows binary even when this script runs under WSL, so the
# destination has to be handed over as a Windows path.  Passing it /mnt/d/...
# makes the pull fail, and the guard below then aborts before anything is
# written — which is the right outcome, but for the wrong reason.
case "$adb" in
	*.exe) out_host=$(wslpath -w "$out" 2>/dev/null || echo "$out") ;;
	*) out_host=$out ;;
esac
adb_ pull /tmp/gpt-live.bin "$out_host" >/dev/null || die 'no pude traerme el respaldo.'
[ -s "$out" ] || die 'el respaldo de la GPT vino vacio.'
echo "guardada en $out ($(stat -c %s "$out") bytes)"
echo "sha256 $(sha256sum "$out" | cut -d' ' -f1)"

echo
echo '=== reparticionando ==='
sh_ "sgdisk --delete=34 $disk" || die 'no pude borrar la entrada 34.'
sh_ "sgdisk --new=34:$ud_first:$ud_new_last --typecode=34:$UD_GUID --partition-guid=34:$UD_GUID --change-name=34:userdata $disk" \
	|| die 'no pude crear userdata.'
sh_ "sgdisk --new=35:$lr_first:$lr_last --typecode=35:$LR_GUID --change-name=35:linuxroot $disk" \
	|| die 'no pude crear linuxroot.'

echo
echo '=== como queda ==='
sh_ "sgdisk --print $disk" | tail -8

cat <<'EOF'

Hecho. El kernel todavia tiene en memoria la tabla antigua, asi que ahora:

  1. Reinicia a recovery desde el propio TWRP (Reboot -> Recovery).
  2. Comprueba los tamanos nuevos:
       adb shell blockdev --getsize64 /dev/block/sda34
       adb shell blockdev --getsize64 /dev/block/sda35
  3. En TWRP: Wipe -> Format Data.  Formatea userdata y metadata, que es lo que
     One UI necesita para regenerar las claves FBE y volver a arrancar.
  4. Crea el sistema de ficheros de Linux:
       adb shell mke2fs -t ext4 -L UBTS9U_UFS /dev/block/sda35
  5. Reboot -> System, y confirma que One UI arranca.
EOF
