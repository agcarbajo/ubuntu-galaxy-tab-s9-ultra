#!/bin/bash
# Banco de pruebas para la siembra de juegos de arranque del instalador.
#
# `seed_boot_sets` es la unica parte del instalador que escribe ficheros y que
# no se puede ejecutar de verdad sin reinstalar el aparato, porque solo tiene
# sentido en el instante en que las particiones todavia llevan Android y el
# rootfs nuevo ya esta escrito. Asi que aqui se le monta alrededor todo lo que
# necesita —cuatro particiones, un super con su build.prop, un rootfs recien
# hecho y un ZIP— con ficheros e imagenes de bucle.
#
# Se ejecuta con mksh a proposito: es el shell con el que TWRP corre el
# instalador, y su aritmetica de 32 bits ya ha roto cosas en este puerto antes.
#
# Necesita root (losetup, mount) y se ejecuta en la maquina de compilacion.
# No toca ningun aparato.
set -u

repo=$(cd "$(dirname "$0")/.." && pwd)
INSTALADOR="$repo/configs/twrp/ubuntu-update-binary"
[ -f "$INSTALADOR" ] || { echo "no encuentro el instalador"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "hace falta root para losetup y mount"; exit 1; }

W=$(mktemp -d /tmp/gts9u-siembra.XXXXXX)
fallos=0
ok()   { echo "  PASA  $1"; }
mal()  { echo "  FALLA $1"; fallos=$((fallos + 1)); }

limpia() {
    umount "$W/rootmnt" 2>/dev/null
    for l in $(losetup -j "$W/rootfs.img" -O NAME -n 2>/dev/null) \
             $(losetup -j "$W/pequeno.img" -O NAME -n 2>/dev/null) \
             $(losetup -j "$W/super.img" -O NAME -n 2>/dev/null); do
        losetup -d "$l" 2>/dev/null
    done
    rm -f /dev/block/mapper/system
    rm -rf "$W"
}
trap limpia EXIT

CMDLINE_SAMSUNG='video=vfb:640x400,bpp=32 firmware_class.path=/vendor/firmware_mnt/image'
CMDLINE_UBUNTU='root=LABEL=UBTS9U_UFS rootfstype=ext4 rootwait console=tty0'

prepara_particiones() {  # $1 = cmdline de vendor_boot
    mkdir -p "$W/parts"
    # Contenido aleatorio: si la siembra copiara otra cosa, los hashes no
    # coincidirian por casualidad.
    for spec in boot:100663296 init_boot:8388608 vendor_boot:100663296 dtbo:16777216; do
        n=${spec%%:*}; s=${spec##*:}
        dd if=/dev/urandom of="$W/parts/$n.img" bs=1M count=$((s / 1048576)) status=none
    done
    printf '%s' "$1" | dd of="$W/parts/vendor_boot.img" bs=1 seek=28 conv=notrunc status=none
}

prepara_zip() {
    mkdir -p "$W/zip"
    for p in boot init_boot vendor_boot dtbo; do
        dd if=/dev/urandom of="$W/zip/$p.img" bs=1M count=2 status=none
    done
}

prepara_super() {  # $1 = lineas de build.prop
    mkdir -p "$W/superfs/system" "$W/supermnt"
    printf '%s\n' "$1" > "$W/superfs/system/build.prop"
    dd if=/dev/zero of="$W/super.img" bs=1M count=32 status=none
    mkfs.ext4 -q -F "$W/super.img"
    mount -o loop "$W/super.img" "$W/supermnt"
    cp -a "$W/superfs/system" "$W/supermnt/"
    umount "$W/supermnt"
    loop=$(losetup --find --show "$W/super.img")
    mkdir -p /dev/block/mapper
    ln -sfn "$loop" /dev/block/mapper/system
}

prepara_rootfs() {  # $1 = fichero  $2 = MiB
    dd if=/dev/zero of="$1" bs=1M count="$2" status=none
    mkfs.ext4 -q -F -L UBTS9U_UFS "$1"
    losetup --find --show "$1"
}

# Lo que el resto del instalador tendria ya definido a estas alturas.
OUTFD=1
ZIPFILE="$W/fake.zip"
ROOTFS_MOUNT="$W/rootmnt"
ROOTFS_LABEL=UBTS9U_UFS
HAS_ROOTFS_IMAGE=1
ROOT_PART=linuxroot
mkdir -p "$ROOTFS_MOUNT"
ui_print()     { echo "  | $1"; }
resolve_part() { [ -f "$W/parts/$1.img" ] && echo "$W/parts/$1.img" || return 1; }
unzip()        { [ "$1" = "-p" ] && cat "$W/zip/$3"; }

# El bloque real del instalador, sin copiarlo: si alguien lo cambia, esto
# prueba lo nuevo y no una copia que envejece.
eval "$(sed -n '/^BOOT_SETS_DIR=/,/^fs_label()/p' "$INSTALADOR" | sed '$d')"

echo "== 1. instalacion sobre Android: siembra los dos juegos =="
prepara_particiones "$CMDLINE_SAMSUNG"
prepara_zip
prepara_super 'ro.build.version.oneui=80000
ro.build.version.release=16'
ROOTFS_LOOP=$(prepara_rootfs "$W/rootfs.img" 1024)
DATA_TARGET=$ROOTFS_LOOP
seed_boot_sets
mount "$ROOTFS_LOOP" "$ROOTFS_MOUNT"
B="$ROOTFS_MOUNT/var/lib/gts9u-boot-sets"

for p in boot init_boot vendor_boot dtbo; do
    if [ "$(sha256sum < "$W/parts/$p.img")" = "$(sha256sum < "$B/android/$p.img")" ]
    then ok "android/$p.img es la particion, byte a byte"
    else mal "android/$p.img no coincide con la particion"; fi
    if [ "$(sha256sum < "$W/zip/$p.img")" = "$(sha256sum < "$B/ubuntu/$p.img")" ]
    then ok "ubuntu/$p.img es la imagen del ZIP, byte a byte"
    else mal "ubuntu/$p.img no coincide con el ZIP"; fi
done
[ "$(cat "$B/android/name.txt")" = "One UI 8" ] \
    && ok "80000 se lee como One UI 8" || mal "nombre mal: $(cat "$B/android/name.txt")"
umount "$ROOTFS_MOUNT"; losetup -d "$ROOTFS_LOOP"

echo
echo "== 2. version con minor: 70100 es One UI 7.1 =="
rm -f /dev/block/mapper/system
losetup -d "$(losetup -j "$W/super.img" -O NAME -n)" 2>/dev/null
rm -f "$W/super.img"
prepara_super 'ro.build.version.oneui=70100'
ROOTFS_LOOP=$(prepara_rootfs "$W/rootfs.img" 1024)
DATA_TARGET=$ROOTFS_LOOP
seed_boot_sets >/dev/null
mount "$ROOTFS_LOOP" "$ROOTFS_MOUNT"
[ "$(cat "$ROOTFS_MOUNT/var/lib/gts9u-boot-sets/android/name.txt")" = "One UI 7.1" ] \
    && ok "70100 se lee como One UI 7.1" || mal "70100 mal leido"
umount "$ROOTFS_MOUNT"; losetup -d "$ROOTFS_LOOP"

echo
echo "== 3. reinstalacion sobre un dualboot: no inventa un Android =="
prepara_particiones "$CMDLINE_UBUNTU"
ROOTFS_LOOP=$(prepara_rootfs "$W/rootfs.img" 1024)
DATA_TARGET=$ROOTFS_LOOP
seed_boot_sets >/dev/null
mount "$ROOTFS_LOOP" "$ROOTFS_MOUNT"
[ -d "$ROOTFS_MOUNT/var/lib/gts9u-boot-sets/android" ] \
    && mal "ha guardado Ubuntu haciendolo pasar por Android" \
    || ok "no guarda un juego de Android que no existe"
[ -f "$ROOTFS_MOUNT/var/lib/gts9u-boot-sets/ubuntu/boot.img" ] \
    && ok "pero si siembra el de Ubuntu" || mal "tampoco ha sembrado Ubuntu"
umount "$ROOTFS_MOUNT"; losetup -d "$ROOTFS_LOOP"

echo
echo "== 4. sin sitio en el rootfs: se abstiene =="
prepara_particiones "$CMDLINE_SAMSUNG"
ROOTFS_LOOP=$(prepara_rootfs "$W/pequeno.img" 64)
DATA_TARGET=$ROOTFS_LOOP
seed_boot_sets >/dev/null
mount "$ROOTFS_LOOP" "$ROOTFS_MOUNT"
[ -d "$ROOTFS_MOUNT/var/lib/gts9u-boot-sets" ] \
    && mal "ha sembrado sin sitio" || ok "no siembra si no cabe"
umount "$ROOTFS_MOUNT"; losetup -d "$ROOTFS_LOOP"

echo
if [ "$fallos" -eq 0 ]; then echo "TODO CORRECTO"; else echo "$fallos FALLOS"; fi
exit "$fallos"
