#!/bin/bash
# Stage only; never changes running devices or sleep policy.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tree=${1:?usage: stage-ufs-resume-experiment.sh KERNEL_TREE}
enabled=${UFS_PCS_RESET_EXPERIMENTAL:-0}
source_file=$tree/drivers/phy/qualcomm/phy-qcom-qmp-ufs.c
patch_file=$repo/kernel/patches/qmp-ufs-assert-pcs-reset-before-calibration-gts9u.patch
case "$enabled" in
    0|1) ;;
    *) echo 'UFS_PCS_RESET_EXPERIMENTAL must be 0 or 1' >&2; exit 1 ;;
esac
test -f "$source_file"
if grep -q 'SM-X910 experiment: assert PCS reset before calibration tables' "$source_file"; then
    if [ "$enabled" = 0 ]; then
        echo 'Experimental UFS reset remains in this tree; use a fresh tree for a default build.' >&2
        exit 1
    fi
    # Reject a marker-only or partially edited candidate.
    patch --dry-run --reverse --batch --fuzz=0 -d "$tree" -p1 < "$patch_file"
elif [ "$enabled" = 1 ]; then
    patch --dry-run --forward --batch --fuzz=0 -d "$tree" -p1 < "$patch_file"
    patch --forward --batch --fuzz=0 -d "$tree" -p1 < "$patch_file"
fi
