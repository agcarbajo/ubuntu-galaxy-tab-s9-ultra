#!/bin/bash
# Enabled by default after kernel #11 hardware validation.
# Stage only; never changes running devices or sleep policy.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tree=${1:?usage: stage-gpu-recovery-experiment.sh KERNEL_TREE}
enabled=${GPU_FAULT_WAIT_EXPERIMENTAL:-1}
source_files=("$tree/drivers/gpu/drm/msm/adreno/a6xx_gmu.c"
              "$tree/drivers/gpu/drm/msm/adreno/a6xx_hfi.c")
patch_file=$repo/kernel/patches/msm-adreno-bound-fault-coredump-wait-gts9u.patch
case "$enabled" in
    0|1) ;;
    *) echo 'GPU_FAULT_WAIT_EXPERIMENTAL must be 0 or 1' >&2; exit 1 ;;
esac
for source_file in "${source_files[@]}"; do test -f "$source_file"; done
if grep -q 'SM-X910 experiment: bound the fault-capture wait' "${source_files[@]}"; then
    if [ "$enabled" = 0 ]; then
        echo 'Experimental GPU fault wait remains in this tree; use a fresh tree for a default build.' >&2
        exit 1
    fi
    # Reject a marker-only or partially edited candidate.
    patch --dry-run --reverse --force --fuzz=0 -d "$tree" -p1 < "$patch_file"
elif [ "$enabled" = 1 ]; then
    patch --dry-run --forward --batch --fuzz=0 -d "$tree" -p1 < "$patch_file"
    patch --forward --batch --fuzz=0 --no-backup-if-mismatch -d "$tree" -p1 < "$patch_file"
fi
