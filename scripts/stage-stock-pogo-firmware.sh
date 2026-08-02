#!/bin/bash
# Stage the proprietary X910 STM32 keyboard image without versioning it.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
source_root=${STOCK_VENDOR_ROOT:-/root/pmos-gts9u/stock-vendor-extracted}
firmware_dir=${FIRMWARE_DIR:-"$repo/../PostmarketOS/pmaports/device/testing/firmware-samsung-gts9uwifi"}
source=$source_root/firmware/keyboard_stm/stm32_gts9family.bin
target=$firmware_dir/stm32_gts9family.bin
expected=1b48d88c23523ae205cd960e6d42725268638a15a47d8a5e52854eb01108caa3

test -f "$source" || {
	echo "missing stock keyboard firmware: $source" >&2
	exit 1
}
actual=$(sha256sum "$source" | cut -d' ' -f1)
[ "$actual" = "$expected" ] || {
	echo "unexpected STM32 firmware hash: $actual" >&2
	exit 1
}
install -m 0644 "$source" "$target"
echo "staged $target ($actual)"
