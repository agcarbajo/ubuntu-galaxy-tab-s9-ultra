#!/bin/bash
# Banco de pruebas del ZIP de reparticionado, sobre un disco falso.
#
# El aparato de desarrollo ya esta partido, asi que el camino bueno no se
# puede probar en el sin costar los datos de One UI. Aqui se monta un fichero
# disperso del tamano de la UFS de 1 TB en un bucle de 4096 bytes, con el GUID
# de disco real y las entradas 19 y 34 en su sitio, y se ejecuta el instalador
# con mksh, que es el shell de TWRP.
#
# Necesita root (losetup, mkfs) y no toca ningun aparato.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
INSTALADOR="$repo/configs/twrp/repartition-update-binary"
[ -f "$INSTALADOR" ] || { echo "no encuentro el instalador"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "hace falta root"; exit 1; }

W=$(mktemp -d /tmp/gts9u-fmt.XXXXXX)
LOOP=""
fallos=0
ok()  { echo "  PASA  $1"; }
mal() { echo "  FALLA $1"; fallos=$((fallos + 1)); }

limpia() {
    [ -n "$LOOP" ] && { partx -d "$LOOP" 2>/dev/null; losetup -d "$LOOP" 2>/dev/null; }
    rm -f /dev/block/sda /dev/block/by-name/userdata /dev/block/by-name/metadata
    rm -rf "$W" /external_sd
}
trap limpia EXIT

mkdir -p "$W/bin" /external_sd /dev/block/by-name
cat > "$W/bin/getprop" <<'G'
#!/bin/sh
case "$1" in
  ro.product.device) echo gts9uwifi ;;
  ro.boot.em.model)  echo SM-X910 ;;
  *) echo "" ;;
esac
G
cat > "$W/bin/unzip" <<'U'
#!/bin/sh
[ "$1" = "-p" ] || exit 1
case "$3" in
  ANDROID-PERCENT) echo 40 ;;
  BUNDLE-LABEL)    echo "prueba" ;;
  *) exit 1 ;;
esac
U
chmod +x "$W/bin"/*
export PATH="$W/bin:$PATH"

truncate -s $((249720832 * 4096)) "$W/ufs.img"
LOOP=$(losetup --find --show -b 4096 -P "$W/ufs.img")
sgdisk --zap-all "$LOOP" >/dev/null 2>&1
sgdisk --disk-guid=98101B32-BBE2-4BF2-A06E-2BB33D000C20 \
    --new=19:96128:104319 --change-name=19:metadata \
    --new=34:3626496:0 \
    --typecode=34:1B81E7E6-F50D-419B-A739-2AEEF8DA3335 \
    --partition-guid=34:1B81E7E6-F50D-419B-A739-2AEEF8DA3335 \
    --change-name=34:userdata "$LOOP" >/dev/null
partx -a "$LOOP" 2>/dev/null
ln -sfn "$LOOP" /dev/block/sda
ln -sfn "${LOOP}p34" /dev/block/by-name/userdata
ln -sfn "${LOOP}p19" /dev/block/by-name/metadata
dd if=/dev/urandom of="${LOOP}p34" bs=1M count=8 status=none 2>/dev/null

cp "$INSTALADOR" "$W/update-binary"

echo "== 1. parte la UFS y rehace los datos de Android =="
mksh "$W/update-binary" dummy 1 /external_sd/split.zip > "$W/run1.log" 2>&1
grep -q "userdata is f2fs again" "$W/run1.log" \
    && ok "dice haber formateado" || { mal "no formateo"; tail -5 "$W/run1.log"; }
partx -u "$LOOP" 2>/dev/null; sleep 1

MAGIC=$(dd if="${LOOP}p34" bs=1 skip=1024 count=4 2>/dev/null | od -An -tx1 | tr -d ' \n')
[ "$MAGIC" = "1020f5f2" ] && ok "la firma f2fs esta puesta" || mal "firma '$MAGIC'"
[ "$(blkid -s TYPE -o value "${LOOP}p34" 2>/dev/null)" = f2fs ] \
    && ok "userdata es f2fs" || mal "userdata no es f2fs"
[ "$(blkid -s TYPE -o value "${LOOP}p19" 2>/dev/null)" = ext4 ] \
    && ok "metadata vuelve vacia en ext4" || mal "metadata no es ext4"

# El kernel de WSL no trae f2fs y no se puede montar, pero fsck valida la
# estructura sin montarla, que para esto vale igual.
if command -v fsck.f2fs >/dev/null 2>&1; then
    fsck.f2fs -a "${LOOP}p34" >"$W/fsck.log" 2>&1 \
        && ok "fsck.f2fs lo da por bueno" || { mal "fsck.f2fs se queja"; tail -3 "$W/fsck.log"; }
fi

REAL=$(blockdev --getsize64 "${LOOP}p34")
ESP=$(awk 'BEGIN { printf "%d", 98437632 * 4096 }')
[ "$REAL" = "$ESP" ] && ok "userdata mide el 40% pedido" || mal "mide $REAL, esperaba $ESP"

echo
echo "== 2. flasheado otra vez: no puede tocar un Android que funciona =="
# Un testigo en crudo, muy dentro de la zona de datos. Aqui esta el peligro de
# verdad: en un aparato ya partido y en uso, formatear seria borrarle a alguien
# su Android, y nada en la particion distingue "recien acortada" de "sana y
# cifrada" — con cifrado de metadatos las dos son ruido.
OFF=$((200 * 1048576))
printf 'TESTIGO-DE-ANDROID' | dd of="${LOOP}p34" bs=1 seek=$OFF conv=notrunc status=none
mksh "$W/update-binary" dummy 1 /external_sd/split.zip > "$W/run2.log" 2>&1
rc=$?
[ "$rc" = 0 ] && ok "sale con bien, no como error" || mal "rc=$rc"
grep -q "Nothing to do" "$W/run2.log" \
    && ok "reconoce que ya estaba partida" || mal "no la reconoce"
[ "$(dd if="${LOOP}p34" bs=1 skip=$OFF count=18 2>/dev/null)" = "TESTIGO-DE-ANDROID" ] \
    && ok "los datos de Android siguen intactos" \
    || mal "ha formateado un Android que funcionaba"

echo
[ "$fallos" -eq 0 ] && echo "TODO CORRECTO" || echo "$fallos FALLOS"
exit "$fallos"
