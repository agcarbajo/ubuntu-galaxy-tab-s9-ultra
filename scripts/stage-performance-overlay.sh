#!/bin/bash
# Stage the early, built-in board overlays in a disposable kernel tree.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tree=${1:?usage: stage-performance-overlay.sh KERNEL_WORKTREE}
target=$tree/drivers/soc/qcom
test -f "$target/Makefile"
command -v dtc >/dev/null
command -v python3 >/dev/null
install -m0644 "$repo/kernel/drivers/gts9u-performance.c" "$target/gts9u-performance.c"
# One blob per overlay: the helper applies them as separate transactions.
for overlay in gts9u-performance gts9u-ufs-ice; do
    dtc -I dts -O dtb -o "$target/$overlay.dtbo" "$repo/kernel/dts/$overlay.dtso"
done
python3 - "$target" <<'PY'
from pathlib import Path
import sys
target = Path(sys.argv[1])
lines = []
for overlay in ('gts9u-performance', 'gts9u-ufs-ice'):
    data = (target / f'{overlay}.dtbo').read_bytes()
    symbol = overlay.replace('-', '_') + '_overlay'
    lines += [f'/* Generated from kernel/dts/{overlay}.dtso. */',
              f'static const unsigned char {symbol}[] __initconst __aligned(8) = {{']
    for offset in range(0, len(data), 12):
        lines.append('\t' + ', '.join(f'0x{b:02x}' for b in data[offset:offset+12]) + ',')
    lines.append('};\n')
(target / 'gts9u-performance-overlay.h').write_text('\n'.join(lines))
PY
# The port already enables OF_OVERLAY for Gunyah. Do not silently build this
# as a module: that would run after the CPU, the GPU and the UFS host have
# read the properties it changes.
grep -q '^obj-$(CONFIG_OF_OVERLAY) += gts9u-performance.o$' "$target/Makefile" ||
    printf '\nobj-$(CONFIG_OF_OVERLAY) += gts9u-performance.o\n' >> "$target/Makefile"
