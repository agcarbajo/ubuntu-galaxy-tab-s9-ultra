#!/bin/bash
# Build the mainline kernel, device tree and isolated ath12k modules for the
# SM-X910 from the sources vendored in this repository.
#
# Derived from scripts/build-mainline-kernel.sh of the postmarketOS gts9uwifi
# port (MIT). Only the source layout and output paths changed: the pinned
# upstream checkout stays pristine and every device source is applied here.
#
# Nothing is flashed and no device is touched.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
kernel_src=${KERNEL_SRC:-$base/linux-mainline}
kernel_tree=${KERNEL_WORKTREE:-$base/build/linux-src-gts9uwifi}
build_dir=${KERNEL_BUILD_DIR:-$base/build/linux-gts9uwifi}
out_dir=${KERNEL_OUT_DIR:-$base/out/kernel-gts9uwifi}

dts=$repo/kernel/dts
drv=$repo/kernel/drivers
pat=$repo/kernel/patches
cfg=$repo/kernel/config

test -d "$kernel_src/.git" || {
	echo "missing pinned kernel checkout: $kernel_src" >&2
	echo 'run scripts/fetch-mainline.sh first' >&2
	exit 1
}
test -f "$dts/sm8550-samsung-gts9uwifi.dts"
test -f "$cfg/config-mainline.aarch64"
test -f "$cfg/config-gts9uwifi.fragment"

mkdir -p "$(dirname "$kernel_tree")" "$build_dir" "$out_dir"

if [ ! -e "$kernel_tree/.git" ]; then
	git -C "$kernel_src" worktree add --detach "$kernel_tree" HEAD
fi

# ---------------------------------------------------------------------------
# Board device tree
# ---------------------------------------------------------------------------

install -m 0644 "$dts/sm8550-samsung-gts9uwifi.dts" \
	"$kernel_tree/arch/arm64/boot/dts/qcom/sm8550-samsung-gts9uwifi.dts"

if ! grep -q 'sm8550-samsung-gts9uwifi.dtb' \
	"$kernel_tree/arch/arm64/boot/dts/qcom/Makefile"; then
	patch -d "$kernel_tree" -p1 < "$pat/add-gts9uwifi-dtb.patch"
fi
# ABL's ufdt fork requires /__symbols__ in any DTB destined for vendor_boot.
if ! grep -q '^DTC_FLAGS_sm8550-samsung-gts9uwifi := -@$' \
	"$kernel_tree/arch/arm64/boot/dts/qcom/Makefile"; then
	sed -i '/sm8550-samsung-gts9uwifi\.dtb/a DTC_FLAGS_sm8550-samsung-gts9uwifi := -@' \
		"$kernel_tree/arch/arm64/boot/dts/qcom/Makefile"
fi

# ---------------------------------------------------------------------------
# Hardware patches, each guarded so re-running is idempotent
# ---------------------------------------------------------------------------

apply_unless() {
	# apply_unless <marker> <file> <patch>
	local marker=$1 file=$2 patch=$3
	if ! grep -q "$marker" "$kernel_tree/$file"; then
		patch -d "$kernel_tree" -p1 < "$pat/$patch"
	fi
}

if [ ! -f "$kernel_tree/drivers/soc/qcom/samsung-gts9uwifi-sec-log.c" ]; then
	patch -d "$kernel_tree" -p1 < "$pat/add-samsung-sec-log-console.patch"
fi
apply_unless 'previous_index, index' \
	drivers/soc/qcom/samsung-gts9uwifi-sec-log.c \
	keep-sec-log-previous-index-current.patch

# ignore-console-null.patch is deliberately NOT applied by default.  The
# postmarketOS v1.71 kernel that was physically validated came from the direct
# build, which never applied it; only the Alpine package did.  It is a
# diagnostic aid that lets tty0/ttyMSM0 survive the `console=null` that ABL can
# append, and it cannot show anything while the DDIC still reads 00 00 00.
# Keep the first Ubuntu kernel byte-comparable to the validated one; set
# APPLY_IGNORE_CONSOLE_NULL=1 only for an explicit diagnostic build.
if [ "${APPLY_IGNORE_CONSOLE_NULL:-0}" = 1 ]; then
	apply_unless 'ignore_console_null' \
		kernel/printk/printk.c ignore-console-null.patch
fi

apply_unless 'Match Samsung SM8550 sequencing' \
	drivers/phy/phy-snps-eusb2.c match-samsung-sm8550-eusb2-phy-init.patch
apply_unless 'PTN3222_MAX_INIT_CELLS' \
	drivers/phy/phy-nxp-ptn3222.c configure-nxp-ptn3222-from-dt.patch
apply_unless 'pwrseq_qcom_wcn_program_wlan_pdc' \
	drivers/power/sequencing/pwrseq-qcom-wcn.c \
	wcn7850-pwrseq-cold-reset-aop.patch
apply_unless 'default y if ARCH_QCOM' \
	drivers/pci/pwrctrl/Kconfig build-wcn-pcie-providers-in.patch
apply_unless 'clk_set_rate(qmp->pipe_clks\[0\].clk, ULONG_MAX)' \
	drivers/phy/qualcomm/phy-qcom-qmp-pcie.c unpark-pcie0-pipe-mux.patch
apply_unless 'Match the SM-X910 Samsung kernel at standard mode' \
	drivers/i2c/busses/i2c-qcom-geni.c \
	match-samsung-geni-i2c-100khz-timing.patch
apply_unless "Samsung's SM8550 driver cancels first" \
	drivers/i2c/busses/i2c-qcom-geni.c \
	qcom-geni-cancel-before-abort.patch
apply_unless 'sc8280xp_snd_startup' \
	sound/soc/qcom/sc8280xp.c set-mi2s-codec-dai-format.patch
apply_unless 'ret != -ENODEV && ret != -EPROBE_DEFER' \
	drivers/gpu/drm/msm/dp/dp_display.c \
	msm-dp-allow-unresolved-usbc-bridge.patch
apply_unless 'bridge->of_node = msm_dp_display->pdev->dev.of_node' \
	drivers/gpu/drm/msm/dp/dp_drm.c msm-dp-associate-bridge-of-node.patch
apply_unless 'defer_hpd_until_resume' \
	drivers/gpu/drm/msm/dp/dp_drm.h msm-dp-defer-oob-hpd-until-resume.patch
apply_unless 'adopt_retained_source_ufp' \
	include/linux/usb/tcpm.h tcpm-adopt-retained-source-ufp-role.patch
apply_unless 'consume_retained_sink_dfp' \
	include/linux/usb/tcpm.h tcpm-use-retained-sink-data-role.patch

# The Goodix patch has two variants: a full one for a pristine tree and an
# upgrade for a tree that already carries the partial Samsung decoder.
goodix=drivers/input/touchscreen/goodix_berlin_core.c
if ! grep -q 'forcing 16-byte Samsung events for firmware PID 6936' \
	"$kernel_tree/$goodix"; then
	if grep -q 'GOODIX_BERLIN_SAMSUNG_EVENT_ID_MASK' "$kernel_tree/$goodix"; then
		patch -d "$kernel_tree" -p1 \
			< "$pat/upgrade-partial-goodix-samsung-events.patch"
	else
		patch -d "$kernel_tree" -p1 \
			< "$pat/support-samsung-goodix-16-byte-events.patch"
	fi
fi

# Xorg only creates a PRIME GPU screen when MODE_GETRESOURCES succeeds.  Keep
# the split GPU/DPU topology, but expose an empty KMS resource list on Adreno.
# GNOME/Wayland does not need the Xorg side, but the empty resource list is
# also what lets the render-only Adreno node coexist with the DPU.
msm_drv=drivers/gpu/drm/msm/msm_drv.c
if sed -n '/static const struct drm_driver msm_gpu_driver/,/^};/p' \
	"$kernel_tree/$msm_drv" | grep -q 'DRIVER_FEATURES_GPU,$'; then
	patch -d "$kernel_tree" -p1 < "$pat/expose-separate-gpu-kms-resources.patch"
elif ! grep -q 'msm_gpu_mode_config_funcs' "$kernel_tree/$msm_drv"; then
	echo 'separate GPU framebuffer hook missing; refusing to build' >&2
	exit 1
fi

# ---------------------------------------------------------------------------
# Out-of-tree drivers, shipped into the pristine tree with their Kconfig and
# Makefile entries, exactly as the reference port does.
# ---------------------------------------------------------------------------

panel_dir=$kernel_tree/drivers/gpu/drm/panel
install -m 0644 "$drv/panel-samsung-ana38407.c" \
	"$panel_dir/panel-samsung-ana38407.c"
if ! grep -q 'DRM_PANEL_SAMSUNG_ANA38407' "$panel_dir/Kconfig"; then
	sed -i '/^endmenu$/i \
config DRM_PANEL_SAMSUNG_ANA38407\
\ttristate "Samsung ANA38407 AMSA46AS02 (gts9u) DSI command-mode panel"\
\tdepends on OF\
\tdepends on DRM_MIPI_DSI\
\tdepends on BACKLIGHT_CLASS_DEVICE\
\thelp\
\t  DSC command-mode DSI panel on the Galaxy Tab S9 Ultra Wi-Fi (SM-X910).\
' "$panel_dir/Kconfig"
fi
grep -q 'panel-samsung-ana38407.o' "$panel_dir/Makefile" || \
	printf 'obj-$(CONFIG_DRM_PANEL_SAMSUNG_ANA38407) += panel-samsung-ana38407.o\n' \
		>> "$panel_dir/Makefile"

supply_dir=$kernel_tree/drivers/power/supply
install -m 0644 "$drv/sm5714_battery.c" "$supply_dir/sm5714_battery.c"
if ! grep -q 'BATTERY_SM5714' "$supply_dir/Kconfig"; then
	sed -i '/^endif # POWER_SUPPLY$/i \
config BATTERY_SM5714\
\ttristate "Silicon Mitus SM5714 charger and fuel gauge"\
\tdepends on I2C\
\tdepends on IIO\
\thelp\
\t  Battery state of charge and charging status on boards that drive the\
\t  SM5714 combo PMIC from the AP, such as the Galaxy Tab S9 Ultra Wi-Fi.\
' "$supply_dir/Kconfig"
fi
grep -q 'sm5714_battery.o' "$supply_dir/Makefile" || \
	printf 'obj-$(CONFIG_BATTERY_SM5714)\t+= sm5714_battery.o\n' \
		>> "$supply_dir/Makefile"

install -m 0644 "$drv/sm5440_direct.c" "$supply_dir/sm5440_direct.c"
if ! grep -q 'CHARGER_SM5440_DIRECT' "$supply_dir/Kconfig"; then
	sed -i '/^endif # POWER_SUPPLY$/i \
config CHARGER_SM5440_DIRECT\
\ttristate "Silicon Mitus SM5440 direct charger for Samsung SM-X910"\
\tdepends on I2C\
\tdepends on BATTERY_SM5714\
\thelp\
\t  Conservative PPS-controlled 2:1 direct charging on the Galaxy Tab S9\
\t  Ultra Wi-Fi, with automatic fallback to the SM5714 switching charger.\
' "$supply_dir/Kconfig"
fi
grep -q 'sm5440_direct.o' "$supply_dir/Makefile" || \
	printf 'obj-$(CONFIG_CHARGER_SM5440_DIRECT)\t+= sm5440_direct.o\n' \
		>> "$supply_dir/Makefile"

tcpm_dir=$kernel_tree/drivers/usb/typec/tcpm
install -m 0644 "$drv/sm5714_usbpd.c" "$tcpm_dir/sm5714_usbpd.c"
if ! grep -q 'TYPEC_SM5714' "$tcpm_dir/Kconfig"; then
	sed -i '/^endif # TYPEC_TCPM$/i \
config TYPEC_SM5714\
\ttristate "Silicon Mitus SM5714 USB Type-C and PD controller"\
\tdepends on I2C\
\tdepends on TYPEC_TCPM\
\tdepends on BATTERY_SM5714\
\thelp\
\t  USB Type-C CC and USB-PD message transport for the SM5714 PDIC.\
' "$tcpm_dir/Kconfig"
fi
grep -q 'sm5714_usbpd.o' "$tcpm_dir/Makefile" || \
	printf 'obj-$(CONFIG_TYPEC_SM5714)\t+= sm5714_usbpd.o\n' \
		>> "$tcpm_dir/Makefile"

mux_dir=$kernel_tree/drivers/usb/typec/mux
install -m 0644 "$drv/ps5169.c" "$mux_dir/ps5169.c"
if ! grep -q 'TYPEC_MUX_PS5169' "$mux_dir/Kconfig"; then
	cat >> "$mux_dir/Kconfig" <<'EOF'

config TYPEC_MUX_PS5169
	tristate "Parade PS5169 Type-C redriver"
	depends on I2C
	depends on TYPEC
	depends on USB_ROLE_SWITCH
	help
	  USB 3.x and DisplayPort lane redriver used by the SM-X910.
EOF
fi
grep -q 'ps5169.o' "$mux_dir/Makefile" || \
	printf 'obj-$(CONFIG_TYPEC_MUX_PS5169)\t+= ps5169.o\n' >> "$mux_dir/Makefile"

keyboard_dir=$kernel_tree/drivers/input/keyboard
install -m 0644 "$drv/samsung_stm32_pogo.c" \
	"$keyboard_dir/samsung_stm32_pogo.c"
if ! grep -q 'KEYBOARD_SAMSUNG_STM32_POGO' "$keyboard_dir/Kconfig"; then
	cat >> "$keyboard_dir/Kconfig" <<'EOF'

config KEYBOARD_SAMSUNG_STM32_POGO
	tristate "Samsung SM-X910 STM32 pogo keyboard"
	depends on I2C
	depends on GPIOLIB
	depends on REGULATOR
	help
	  Mainline-oriented driver for the STM32 controller in Samsung's
	  EF-DX920 Book Cover Keyboard Slim for the Galaxy Tab S9 Ultra.
EOF
fi
grep -q 'samsung_stm32_pogo.o' "$keyboard_dir/Makefile" || \
	printf 'obj-$(CONFIG_KEYBOARD_SAMSUNG_STM32_POGO) += samsung_stm32_pogo.o\n' \
		>> "$keyboard_dir/Makefile"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

cp "$cfg/config-mainline.aarch64" "$build_dir/.config"

# Two fragments, applied in order: the hardware one inherited byte-for-byte
# from the reference port, then the Ubuntu desktop one this port adds.  Keeping
# them separate means the inherited file stays comparable to its origin.
# An array, not a space-separated string: this repository lives under a path
# that contains spaces, and word splitting turned it into nonexistent files.
fragments=("$cfg/config-gts9uwifi.fragment")
[ -f "$cfg/config-ubuntu-desktop.fragment" ] && \
	fragments+=("$cfg/config-ubuntu-desktop.fragment")

apply_fragment() {
	while IFS= read -r setting; do
		case "$setting" in
			CONFIG_*=y)
				symbol=${setting%%=*}
				"$kernel_tree/scripts/config" --file "$build_dir/.config" \
					--enable "${symbol#CONFIG_}" ;;
			CONFIG_*=m)
				symbol=${setting%%=*}
				"$kernel_tree/scripts/config" --file "$build_dir/.config" \
					--module "${symbol#CONFIG_}" ;;
			CONFIG_*=\"*)
				symbol=${setting%%=*}
				value=${setting#*=}
				value=${value#\"}
				value=${value%\"}
				"$kernel_tree/scripts/config" --file "$build_dir/.config" \
					--set-str "${symbol#CONFIG_}" "$value" ;;
			'# CONFIG_'*' is not set')
				symbol=${setting#\# CONFIG_}
				symbol=${symbol% is not set}
				"$kernel_tree/scripts/config" --file "$build_dir/.config" \
					--disable "$symbol" ;;
		esac
	done < "$1"
}

for fragment in "${fragments[@]}"; do
	echo "applying config fragment: ${fragment##*/}"
	apply_fragment "$fragment"
done

make -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 olddefconfig

# A fragment line naming a symbol that does not exist is dropped silently by
# olddefconfig: that is how the GPU once shipped with no clock controller.
# Assert every requested setting survived.  A =y that a select could only
# satisfy as =m is warned about; anything missing is fatal.
missing=
downgraded=
for fragment in "${fragments[@]}"; do
	while IFS= read -r setting; do
		case "$setting" in
			CONFIG_*=y|CONFIG_*=m)
				symbol=${setting%%=*}
				want=${setting##*=}
				if grep -qxF "$symbol=y" "$build_dir/.config"; then
					:
				elif grep -qxF "$symbol=m" "$build_dir/.config"; then
					[ "$want" = y ] && downgraded="$downgraded $symbol"
				else
					missing="$missing $symbol"
				fi ;;
			CONFIG_*=\"*)
				symbol=${setting%%=*}
				grep -q "^$symbol=" "$build_dir/.config" || \
					missing="$missing $symbol" ;;
		esac
	done < "$fragment"
done
[ -n "$downgraded" ] && \
	echo "warning: fragment asked =y, kconfig could only give =m:$downgraded" >&2
if [ -n "$missing" ]; then
	echo "config fragment symbols unknown or disabled:$missing" >&2
	exit 1
fi

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

# Two reasons to pin the build identity rather than let the kernel pick it up
# from the host:
#
#  - Privacy. Without this the banner embeds the builder's account and machine
#    name (it read "root@PC-ARTURO" during bring-up), and that string ships
#    inside every published boot.img.
#  - Reproducibility. UTS_VERSION carries the build counter and timestamp, and
#    a one-character change there ("#1" vs "#18") shifts the linked image, so
#    two builds of identical sources never match byte for byte.
#
# SOURCE_DATE_EPOCH defaults to the commit date of the pinned kernel, so it is
# a property of the sources rather than of when we happened to build.
export KBUILD_BUILD_USER=${KBUILD_BUILD_USER:-ubuntu}
export KBUILD_BUILD_HOST=${KBUILD_BUILD_HOST:-gts9uwifi}
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$kernel_tree" log -1 --format=%ct)}
export KBUILD_BUILD_TIMESTAMP=${KBUILD_BUILD_TIMESTAMP:-$(
	LC_ALL=C date -u -d "@$SOURCE_DATE_EPOCH" 2>/dev/null
)}
# The build counter lives in .version and increments on every link.
printf '0\n' > "$build_dir/.version"

make -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 -j"$(nproc)" \
	Image.gz qcom/sm8550-samsung-gts9uwifi.dtb

if [ "${BUILD_WIFI_MODULES:-1}" = 1 ]; then
	modules_root=$out_dir/modules-root
	case "$modules_root" in
		"$base"/out/*/modules-root) rm -rf -- "$modules_root" ;;
		*) echo "unsafe modules output path: $modules_root" >&2; exit 1 ;;
	esac

	# An isolated M= build needs the built-in export table under the
	# external-module name, and a clean O= tree lacks scripts/module.lds
	# until modules_prepare.
	module_tree=$kernel_tree/drivers/net/wireless/ath/ath12k
	make -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 modules_prepare
	cp "$build_dir/vmlinux.symvers" "$build_dir/Module.symvers"
	make -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 -j"$(nproc)" \
		M="$module_tree" modules
	make -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 \
		M="$module_tree" \
		INSTALL_MOD_PATH="$modules_root" INSTALL_MOD_STRIP=1 \
		DEPMOD=true modules_install

	release=$(make -s -C "$kernel_tree" O="$build_dir" ARCH=arm64 LLVM=1 \
		kernelrelease)
	release_dir=$modules_root/lib/modules/$release
	install -m 0644 "$build_dir/modules.builtin" \
		"$release_dir/modules.builtin"
	install -m 0644 "$build_dir/modules.builtin.modinfo" \
		"$release_dir/modules.builtin.modinfo"
	find "$release_dir/updates" -type f -name '*.ko*' -printf '%P\n' \
		| sed 's#^#updates/#' | sort > "$release_dir/modules.order"
	depmod -b "$modules_root" "$release"
	mkdir -p "$modules_root/usr/lib"
	mv "$modules_root/lib/modules" "$modules_root/usr/lib/modules"
	rmdir "$modules_root/lib"
	printf '%s\n' "$release" > "$out_dir/kernel.release"
fi

install -m 0644 "$build_dir/arch/arm64/boot/Image.gz" "$out_dir/Image.gz"
install -m 0644 \
	"$build_dir/arch/arm64/boot/dts/qcom/sm8550-samsung-gts9uwifi.dtb" \
	"$out_dir/sm8550-samsung-gts9uwifi.dtb"
install -m 0644 "$build_dir/.config" "$out_dir/config"

sha256sum "$out_dir/Image.gz" \
	"$out_dir/sm8550-samsung-gts9uwifi.dtb" \
	"$out_dir/config" > "$out_dir/SHA256SUMS"

cat "$out_dir/SHA256SUMS"
