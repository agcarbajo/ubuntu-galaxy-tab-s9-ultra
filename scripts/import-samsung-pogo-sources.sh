#!/bin/bash
# Import the GPLv2 STM32 pogo-keyboard sources from Samsung's official SM-X910
# source release.  No proprietary firmware is imported by this script.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
archive=${SAMSUNG_OSRC_ZIP:-"$repo/../SM-X910_EUR_16_Opensource.zip"}
expected=e793bc22715b5ca020a5f0b2481e314f3a331609e5e9c798f7d76fe18b2dcb8e
destination=$repo/kernel/vendor/samsung-stm32-pogo

test -f "$archive" || { echo "missing Samsung source archive: $archive" >&2; exit 1; }
actual=$(sha256sum "$archive" | cut -d' ' -f1)
test "$actual" = "$expected" || {
	echo "unexpected Samsung source archive hash: $actual" >&2
	exit 1
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
unzip -p "$archive" Kernel.tar.gz > "$tmp/Kernel.tar.gz"

prefix=./kernel_platform/msm-kernel/drivers/input/sec_input/stm32
members=(
	"$prefix/Kconfig"
	"$prefix/Makefile"
	"$prefix/kbd_max77816_i2c.c"
	"$prefix/pogo_notifier_v3.h"
	"$prefix/stm32_pogo_cmd_v3.c"
	"$prefix/stm32_pogo_core_v3.c"
	"$prefix/stm32_pogo_fn_v3.c"
	"$prefix/stm32_pogo_fw.c"
	"$prefix/stm32_pogo_i2c_v3.c"
	"$prefix/stm32_pogo_interrupt_v3.c"
	"$prefix/stm32_pogo_keyboard_v3.c"
	"$prefix/stm32_pogo_keyboard_v3.h"
	"$prefix/stm32_pogo_keyboard_v3_bypass.c"
	"$prefix/stm32_pogo_keyboard_v3_common.c"
	"$prefix/stm32_pogo_keyboard_v3_row.c"
	"$prefix/stm32_pogo_notifier_v3.c"
	"$prefix/stm32_pogo_touchpad_v3.c"
	"$prefix/stm32_pogo_v3.h"
	"$prefix/stm32_pogo_voting_v3.c"
)

tar -xzf "$tmp/Kernel.tar.gz" -C "$tmp" "${members[@]}"
rm -rf "$destination"
mkdir -p "$destination"
for member in "${members[@]}"; do
	install -m 0644 "$tmp/${member#./}" "$destination/${member##*/}"
done

(
	cd "$destination"
	sha256sum $(find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' | sort) \
		> SHA256SUMS
)

echo "Imported ${#members[@]} GPLv2 files into $destination"

