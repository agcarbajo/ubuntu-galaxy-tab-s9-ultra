#!/bin/bash
# Import the kernel sources, device tree, patches and boot configuration from
# the frozen postmarketOS v1.71 port into this repository, recording the
# SHA-256 of every source file so future divergence is detectable.
#
# The postmarketOS checkout is treated as read-only: this script only reads.
set -euo pipefail

pmos=${PMOS_REPO:-'/mnt/c/Users/agcar/Desktop/Aplicaciones/Custom Roms/GALAXY TAB S9 ULTRA/Ubuntu Touch/PostmarketOS'}
here=$(cd "$(dirname "$0")/.." && pwd)

kpkg="$pmos/pmaports/device/testing/linux-samsung-gts9uwifi-mainline"
test -f "$kpkg/APKBUILD"

mkdir -p "$here/kernel/dts" "$here/kernel/drivers" "$here/kernel/patches" \
	"$here/kernel/config" "$here/configs/vendor_boot" "$here/configs/dtbo" \
	"$here/configs/twrp"

manifest=$(mktemp)
record() {
	printf '| `%s` | `%s` | `%s` |\n' \
		"$2" "${1#"$pmos"/}" "$(sha256sum "$1" | cut -d' ' -f1)" >> "$manifest"
}

copy() {
	install -m 0644 "$1" "$here/$2"
	record "$1" "$2"
}

copy "$kpkg/sm8550-samsung-gts9uwifi.dts" kernel/dts/sm8550-samsung-gts9uwifi.dts
copy "$kpkg/config-gts9uwifi.fragment"    kernel/config/config-gts9uwifi.fragment

# The device fragment is applied on top of the generic postmarketOS aarch64
# mainline config.  That base lives in the upstream pmaports checkout rather
# than in the port repository, so vendor it here to keep this build
# self-contained.
pmaports_checkout=${PMAPORTS_CHECKOUT:-/root/pmos-gts9u/pmaports}
base_config=$pmaports_checkout/device/main/linux-postmarketos-mainline/config-mainline.aarch64
if [ -f "$base_config" ]; then
	copy "$base_config" kernel/config/config-mainline.aarch64
elif [ -f "$here/kernel/config/config-mainline.aarch64" ]; then
	echo 'keeping the already vendored config-mainline.aarch64'
else
	echo "missing base config: $base_config" >&2
	echo 'set PMAPORTS_CHECKOUT to an upstream pmaports checkout' >&2
	exit 1
fi

for driver in panel-samsung-ana38407.c ps5169.c sm5440_direct.c \
	sm5714_battery.c sm5714_usbpd.c; do
	copy "$kpkg/$driver" "kernel/drivers/$driver"
done

for patch in "$kpkg"/*.patch; do
	copy "$patch" "kernel/patches/${patch##*/}"
done

copy "$pmos/configs/vendor_boot/cmdline.txt"    configs/vendor_boot/cmdline.txt
copy "$pmos/configs/vendor_boot/bootconfig.txt" configs/vendor_boot/bootconfig.txt
for dtbo in "$pmos"/configs/dtbo/*.dts; do
	copy "$dtbo" "configs/dtbo/${dtbo##*/}"
done

sort -o "$manifest" "$manifest"

python3 - "$here/kernel/PROVENANCE.md" "$manifest" <<'PY'
import sys, pathlib
target, manifest = (pathlib.Path(p) for p in sys.argv[1:3])
rows = manifest.read_text().rstrip("\n")
text = target.read_text()
head, sep, _ = text.partition("| Fichero | Origen en el port pmOS | SHA-256 de origen |")
target.write_text(
    head
    + sep
    + "\n|---|---|---|\n"
    + rows
    + "\n"
)
PY

echo "imported $(grep -c '^|' "$manifest") files"
rm -f "$manifest"
