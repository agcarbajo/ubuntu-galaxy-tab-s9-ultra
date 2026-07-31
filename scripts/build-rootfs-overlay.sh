#!/bin/bash
# Assemble the microSD rootfs overlay that the TWRP ZIP installs: the isolated
# ath12k modules built alongside this kernel, plus the proprietary firmware
# staged from the device.
#
# Scope note: this covers Hito 1 and 2, that is, everything needed for the
# kernel to reach userspace with Wi-Fi and a working GPU/ADSP firmware set.
# The UCM profile, udev rules and recovery services of the reference port are
# added later, one at a time and only once the matching regression has been
# observed under Ubuntu.
#
# No proprietary blob is ever copied into this repository, and nothing is
# flashed here.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
kernel_out=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}
overlay=${OVERLAY_OUT_DIR:-$base/out/rootfs-overlay}
initramfs_overlay=${INITRAMFS_OVERLAY_OUT_DIR:-$base/out/initramfs-overlay}
# The staged blobs live in the reference port's firmware package directory,
# where scripts/stage-stock-*.sh puts them after verifying pinned checksums.
firmware=${FIRMWARE_DIR:-'/mnt/c/Users/agcar/Desktop/Aplicaciones/Custom Roms/GALAXY TAB S9 ULTRA/Ubuntu Touch/PostmarketOS/pmaports/device/testing/firmware-samsung-gts9uwifi'}

test -d "$kernel_out/modules-root" || {
	echo "missing kernel modules: $kernel_out/modules-root" >&2
	echo 'run scripts/build-mainline-kernel.sh first' >&2
	exit 1
}
test -d "$firmware" || {
	echo "missing staged firmware: $firmware" >&2
	echo 'run the reference port stage-stock-*.sh helpers first' >&2
	exit 1
}

for path in "$overlay" "$initramfs_overlay"; do
	case "$path" in
		"$base"/out/*) rm -rf -- "$path" ;;
		*) echo "unsafe overlay path: $path" >&2; exit 1 ;;
	esac
done

mkdir -p \
	"$overlay/etc/modules-load.d" \
	"$overlay/usr/lib/firmware/qcom/sm8550" \
	"$overlay/usr/lib/firmware/ath12k/WCN7850/hw2.0" \
	"$overlay/usr/lib/firmware/qca" \
	"$overlay/usr/share/qcom/sm8550/Samsung/gts9uwifi" \
	"$initramfs_overlay/usr/lib/firmware/qca"

# --- isolated ath12k modules ----------------------------------------------
# These and boot.img are one signed set under kernel lockdown: installing them
# from a different build makes modprobe fail with "Operation not permitted".
cp -a "$kernel_out/modules-root/." "$overlay/"
printf 'ath12k\n' > "$overlay/etc/modules-load.d/ath12k.conf"

# --- Adreno 740 -----------------------------------------------------------
for f in a740_zap.mdt a740_zap.b00 a740_zap.b01 a740_zap.b02 a740_sqe.fw \
	gmu_gen70200.bin; do
	install -m 0644 "$firmware/$f" "$overlay/usr/lib/firmware/qcom/$f"
done

# --- ADSP: Samsung's own signed image plus the mandatory adsp_dtb ----------
for f in "$firmware"/adsp.mdt "$firmware"/adsp.b* \
	"$firmware"/adsp_dtb.mdt "$firmware"/adsp_dtb.b*; do
	install -m 0644 "$f" "$overlay/usr/lib/firmware/qcom/sm8550/${f##*/}"
done
# pd-mapper reads /sys/class/remoteproc/*/firmware and scans that same
# directory, so the protection-domain maps must sit next to adsp.mdt.
for f in adspr.jsn adsps.jsn adspua.jsn cdspr.jsn; do
	install -m 0644 "$firmware/$f" "$overlay/usr/lib/firmware/qcom/sm8550/$f"
done
install -m 0644 "$firmware/Samsung-Galaxy-Tab-S9-Ultra-tplg.bin" \
	"$overlay/usr/lib/firmware/qcom/sm8550/Samsung-Galaxy-Tab-S9-Ultra-tplg.bin"

# --- Wi-Fi WCN7850 --------------------------------------------------------
# The official amss with the QRD board data, ELF wrapper intact. Samsung's own
# HMT.2.0 board file crashes this amss (MHI RDDM) and must not be substituted.
install -m 0644 "$firmware/amss.bin" \
	"$overlay/usr/lib/firmware/ath12k/WCN7850/hw2.0/amss.bin"
install -m 0644 "$firmware/m3.bin" \
	"$overlay/usr/lib/firmware/ath12k/WCN7850/hw2.0/m3.bin"
install -m 0644 "$firmware/board-2.bin" \
	"$overlay/usr/lib/firmware/ath12k/WCN7850/hw2.0/board-2.bin"
install -m 0644 "$firmware/regdb.bin" \
	"$overlay/usr/lib/firmware/ath12k/WCN7850/hw2.0/regdb.bin"

# --- Bluetooth ------------------------------------------------------------
for f in hmtbtfw20.tlv hmtnv20.b21; do
	install -m 0644 "$firmware/$f" "$overlay/usr/lib/firmware/qca/$f"
done
# hci_qca is built-in and probes long before the microSD is mounted, so the
# same two files also go into the vendor_boot ramdisk fragment.  They must be
# under /usr/lib, never /lib: in the initramfs lib is a symlink to usr/lib and
# creating a directory over it broke the boot of pmOS v0.69.
install -m 0644 "$firmware/hmtbtfw20.tlv" \
	"$initramfs_overlay/usr/lib/firmware/qca/hmtbtfw20.tlv"
install -m 0644 "$firmware/hmtnv20.b21" \
	"$initramfs_overlay/usr/lib/firmware/qca/hmtnv20.b21"

# --- sensors: HexagonFS tree ----------------------------------------------
if [ -f "$firmware/sensor-hexagonfs.tar.gz" ]; then
	tar -xzf "$firmware/sensor-hexagonfs.tar.gz" \
		-C "$overlay/usr/share/qcom/sm8550/Samsung/gts9uwifi"
else
	echo 'note: sensor-hexagonfs.tar.gz is absent; motion sensors will not work' >&2
fi

find "$overlay" -type f -exec chmod 0644 {} +
find "$overlay" -type f -name '*.ko*' -exec chmod 0644 {} +

echo '=== overlay ==='
du -sh "$overlay" "$initramfs_overlay"
find "$overlay" -type f | wc -l | sed 's/^/files: /'
