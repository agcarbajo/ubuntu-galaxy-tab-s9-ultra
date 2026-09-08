#!/bin/bash
# Check that the early overlay adds only the two intended operating points.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
baseline=${1:?usage: test-performance-overlay.sh VALIDATED_BASE_DTB}
stage=$(mktemp -d -t gts9u-perf-test.XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
fdtget -t s "$baseline" / compatible | grep -qw samsung,gts9uwifi
dtc -I dts -O dtb -o "$stage/perf.dtbo" "$repo/kernel/dts/gts9u-performance.dtso"
fdtoverlay -i "$baseline" -o "$stage/after.dtb" "$stage/perf.dtbo"
fdtoverlay -i "$stage/after.dtb" -o "$stage/twice.dtb" "$stage/perf.dtbo"
dtc -q -I dtb -O dts -s "$stage/after.dtb" > "$stage/after.dts"
dtc -q -I dtb -O dts -s "$stage/twice.dtb" > "$stage/twice.dts"
cmp "$stage/after.dts" "$stage/twice.dts"
cpu=/opp-table-cpu7/opp-3360000000
gpu=/soc@0/gpu@3d00000/opp-table/opp-719000000
test "$(fdtget -t u "$stage/after.dtb" "$cpu" opp-hz)" = '0 3360000000'
test "$(fdtget -t u "$stage/after.dtb" "$cpu" opp-peak-kBps)" = '14928000 14744000 54067200'
test "$(fdtget -t u "$stage/after.dtb" "$gpu" opp-hz)" = '0 719000000'
test "$(fdtget -t u "$stage/after.dtb" "$gpu" opp-level)" = 224
test "$(fdtget -t u "$stage/after.dtb" "$gpu" opp-peak-kBps)" = 16500000
test "$(fdtget -t x "$stage/after.dtb" "$gpu" qcom,opp-acd-level)" = 882e5ffd
cp "$baseline" "$stage/before.dtb"
# If the source DT already includes the OPPs, compare after removing them from
# both sides. Otherwise deleting them from the baseline is unnecessary.
for node in "$cpu" "$gpu"; do
    fdtput -r "$stage/after.dtb" "$node"
    if fdtget -p "$stage/before.dtb" "$node" >/dev/null 2>&1; then
        fdtput -r "$stage/before.dtb" "$node"
    fi
done
dtc -q -I dtb -O dts -s "$stage/before.dtb" > "$stage/before.dts"
dtc -q -I dtb -O dts -s "$stage/after.dtb" > "$stage/reverted.dts"
cmp "$stage/before.dts" "$stage/reverted.dts"
mkdir -p "$stage/tree/drivers/soc/qcom"
touch "$stage/tree/drivers/soc/qcom/Makefile"
bash "$repo/scripts/stage-performance-overlay.sh" "$stage/tree"
cp "$stage/tree/drivers/soc/qcom/gts9u-performance-overlay.h" "$stage/header-first"
bash "$repo/scripts/stage-performance-overlay.sh" "$stage/tree"
cmp "$stage/header-first" "$stage/tree/drivers/soc/qcom/gts9u-performance-overlay.h"
test "$(grep -c 'gts9u-performance.o' "$stage/tree/drivers/soc/qcom/Makefile")" = 1
echo 'PASS: OPP values, idempotent application/staging, all other DT content preserved'
