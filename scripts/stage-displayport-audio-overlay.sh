#!/bin/bash
# Linux applies this backend; Samsung ABL still gets the validated base DTB.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
target=${1:?usage: stage-displayport-audio-overlay.sh KERNEL_WORKTREE}/drivers/soc/qcom
test -f "$target/Makefile"
install -m0644 "$repo/kernel/drivers/gts9u-displayport-audio.c" "$target/"
dtc -@ -I dts -O dtb -o "$target/gts9u-displayport-audio.dtbo" \
    "$repo/kernel/dts/gts9u-displayport-audio.dtso"
python3 - "$target" <<'PY'
from pathlib import Path
import sys
target = Path(sys.argv[1])
data = (target / 'gts9u-displayport-audio.dtbo').read_bytes()
rows = ['/* Generated from kernel/dts/gts9u-displayport-audio.dtso. */',
        'static const unsigned char gts9u_displayport_audio_overlay[] __initconst __aligned(8) = {']
for offset in range(0, len(data), 12):
    rows.append('\t' + ', '.join(f'0x{b:02x}' for b in data[offset:offset+12]) + ',')
rows.append('};\n')
(target / 'gts9u-displayport-audio-overlay.h').write_text('\n'.join(rows))
PY
grep -q '^obj-$(CONFIG_OF_OVERLAY) += gts9u-displayport-audio.o$' "$target/Makefile" ||
    printf '\nobj-$(CONFIG_OF_OVERLAY) += gts9u-displayport-audio.o\n' >> "$target/Makefile"
