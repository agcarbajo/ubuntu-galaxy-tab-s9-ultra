#!/bin/bash
# Check that the early overlays change only what they are meant to: the two
# operating points, and the UFS inline crypto engine clock that the UFS OPPs
# scale.  Each is applied on its own in the kernel, so each is checked alone
# as well as together.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
baseline=${1:?usage: test-performance-overlay.sh VALIDATED_BASE_DTB}
stage=$(mktemp -d -t gts9u-perf-test.XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
fdtget -t s "$baseline" / compatible | grep -qw samsung,gts9uwifi
overlays=(gts9u-performance gts9u-ufs-ice)
for overlay in "${overlays[@]}"; do
	dtc -I dts -O dtb -o "$stage/$overlay.dtbo" "$repo/kernel/dts/$overlay.dtso"
done
apply() {
	# apply SOURCE.dtb RESULT.dtb OVERLAY...: the overlays, in order
	local src=$1 dst=$2 overlay
	shift 2
	cp "$src" "$stage/apply.dtb"
	for overlay in "$@"; do
		fdtoverlay -i "$stage/apply.dtb" -o "$stage/apply.next.dtb" "$stage/$overlay.dtbo"
		mv "$stage/apply.next.dtb" "$stage/apply.dtb"
	done
	mv "$stage/apply.dtb" "$dst"
}
sorted() { dtc -q -I dtb -O dts -s "$1"; }
apply "$baseline" "$stage/after.dtb" "${overlays[@]}"
apply "$stage/after.dtb" "$stage/twice.dtb" "${overlays[@]}"
sorted "$stage/after.dtb" > "$stage/after.dts"
sorted "$stage/twice.dtb" > "$stage/twice.dts"
cmp "$stage/after.dts" "$stage/twice.dts"
# The kernel applies them as separate transactions; neither may need the
# other, and the order must not matter.
apply "$baseline" "$stage/reversed.dtb" gts9u-ufs-ice gts9u-performance
sorted "$stage/reversed.dtb" > "$stage/reversed.dts"
cmp "$stage/after.dts" "$stage/reversed.dts"
cpu=/opp-table-cpu7/opp-3360000000
gpu=/soc@0/gpu@3d00000/opp-table/opp-719000000
ufs=/soc@0/ufshc@1d84000
# UFS OPP: the ICE core clock rate it adds.  gcc-kalama.c's VDD_LOWER and
# VDD_LOW corners; the 403 MHz one is deliberately absent.
ufs_opps=(75000000:100000000 150000000:201500000 300000000:201500000)
# props NODE: its property names, sorted; added nodes must have exactly these
# and no children, since the comparison below deletes them whole.
props() { fdtget -p "$stage/after.dtb" "$1" | sort | tr '\n' ' '; }
nstrings() { fdtget -t bx "$1" "$ufs" clock-names | tr ' ' '\n' | grep -cx 0; }
test "$(fdtget -t u "$stage/after.dtb" "$cpu" opp-hz)" = '0 3360000000'
test "$(fdtget -t u "$stage/after.dtb" "$cpu" opp-peak-kBps)" = '14928000 14744000 54067200'
test "$(props "$cpu")" = 'opp-hz opp-peak-kBps '
test -z "$(fdtget -l "$stage/after.dtb" "$cpu")"
test "$(fdtget -t u "$stage/after.dtb" "$gpu" opp-hz)" = '0 719000000'
test "$(fdtget -t u "$stage/after.dtb" "$gpu" opp-level)" = 224
test "$(fdtget -t u "$stage/after.dtb" "$gpu" opp-peak-kBps)" = 16500000
test "$(fdtget -t x "$stage/after.dtb" "$gpu" qcom,opp-acd-level)" = 882e5ffd
test "$(props "$gpu")" = 'opp-hz opp-level opp-peak-kBps qcom,opp-acd-level '
test -z "$(fdtget -l "$stage/after.dtb" "$gpu")"
# GCC_UFS_PHY_ICE_CORE_CLK (141) joins the UFS clocks, after the others, and
# is the clock the inline crypto engine's own node already names.
gcc=$(fdtget -t u "$baseline" /soc@0/clock-controller@100000 phandle)
test "$(fdtget -t u "$stage/after.dtb" "$ufs" clocks)" = \
	"$(fdtget -t u "$baseline" "$ufs" clocks) $gcc 141"
test "$(fdtget -t s "$stage/after.dtb" "$ufs" clock-names)" = \
	"$(fdtget -t s "$baseline" "$ufs" clock-names) ice_core_clk"
# fdtget -t s joins with spaces; count the NUL-terminated strings too.
test "$(nstrings "$stage/after.dtb")" = "$(( $(nstrings "$baseline") + 1 ))"
ice=$(fdtget -t u "$baseline" "$ufs" qcom,ice)
ice_node=$(fdtget -t s "$baseline" /__symbols__ ice)
test "$(fdtget -t u "$baseline" "$ice_node" phandle)" = "$ice"
test "$(fdtget -t u "$baseline" "$ice_node" clocks | cut -d' ' -f1-2)" = "$gcc 141"
# One rate per clock: every OPP must end up with as many 64-bit values as
# the controller has clocks, or the OPP core rejects the table and the
# tablet has no root device.
nclocks=$(nstrings "$stage/after.dtb")
for opp in "${ufs_opps[@]}"; do
	node=$ufs/opp-table/opp-${opp%:*}
	# opp-hz is 64-bit: fdtget prints each rate as two cells, high first.
	test "$(fdtget -t u "$stage/after.dtb" "$node" opp-hz)" = \
		"$(fdtget -t u "$baseline" "$node" opp-hz) 0 ${opp#*:}"
	test "$(fdtget -t u "$stage/after.dtb" "$node" opp-hz | wc -w)" = "$(( nclocks * 2 ))"
done
test "$(fdtget -l "$stage/after.dtb" "$ufs/opp-table" | wc -l)" = "${#ufs_opps[@]}"
cp "$baseline" "$stage/before.dtb"
# If the source DT already includes the OPPs, compare after removing them from
# both sides. Otherwise deleting them from the baseline is unnecessary.
for node in "$cpu" "$gpu"; do
    fdtput -r "$stage/after.dtb" "$node"
    if fdtget -p "$stage/before.dtb" "$node" >/dev/null 2>&1; then
        fdtput -r "$stage/before.dtb" "$node"
    fi
done
# The UFS properties the overlay rewrites go back to the baseline's.
# shellcheck disable=SC2046 # one fdtput argument per cell or string
fdtput -t u "$stage/after.dtb" "$ufs" clocks $(fdtget -t u "$baseline" "$ufs" clocks)
# shellcheck disable=SC2046
fdtput -t s "$stage/after.dtb" "$ufs" clock-names $(fdtget -t s "$baseline" "$ufs" clock-names)
for opp in "${ufs_opps[@]}"; do
	node=$ufs/opp-table/opp-${opp%:*}
	# shellcheck disable=SC2046
	fdtput -t u "$stage/after.dtb" "$node" opp-hz $(fdtget -t u "$baseline" "$node" opp-hz)
done
sorted "$stage/before.dtb" > "$stage/before.dts"
sorted "$stage/after.dtb" > "$stage/reverted.dts"
cmp "$stage/before.dts" "$stage/reverted.dts"
mkdir -p "$stage/tree/drivers/soc/qcom"
touch "$stage/tree/drivers/soc/qcom/Makefile"
bash "$repo/scripts/stage-performance-overlay.sh" "$stage/tree"
header=$stage/tree/drivers/soc/qcom/gts9u-performance-overlay.h
for symbol in gts9u_performance_overlay gts9u_ufs_ice_overlay; do
	grep -qx "static const unsigned char $symbol\[\] __initconst __aligned(8) = {" "$header"
	# The helper must apply exactly the blobs the header carries.
	grep -q "$symbol, *sizeof($symbol)\|($symbol,\$" "$repo/kernel/drivers/gts9u-performance.c"
done
cp "$header" "$stage/header-first"
bash "$repo/scripts/stage-performance-overlay.sh" "$stage/tree"
cmp "$stage/header-first" "$header"
test "$(grep -c 'gts9u-performance.o' "$stage/tree/drivers/soc/qcom/Makefile")" = 1
echo "PASS: ${overlays[*]}: OPP and UFS ICE values, order-independent and idempotent application/staging, all other DT content preserved"
