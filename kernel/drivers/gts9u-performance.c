// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung's bootloader needs the byte-identical, validated base DTB. Add the
 * SM8550-AC OPPs and the UFS ICE clock after that handoff, before any of
 * their consumers can probe.
 * The CPU driver still checks its hardware LUT and supplies the real voltage;
 * the GPU entry comes from the X910's stock power-level table, not an OC.
 */
#include <linux/init.h>
#include <linux/of.h>
#include <linux/printk.h>
#include <linux/types.h>

#include "gts9u-performance-overlay.h"

static int __init gts9u_apply(const unsigned char *fdt, u32 size,
			      const char *what)
{
	int overlay_id, ret;

	ret = of_overlay_fdt_apply(fdt, size, &overlay_id, NULL);
	if (ret)
		pr_err("gts9u-performance: cannot add %s: %d\n", what, ret);
	return ret;
}

static int __init gts9u_performance_init(void)
{
	int ret, err;

	if (!of_machine_is_compatible("samsung,gts9uwifi"))
		return 0;

	/*
	 * The overlays are independent and each is applied as one transaction,
	 * so a failing one must not cost the board the other.
	 */
	ret = gts9u_apply(gts9u_performance_overlay,
			  sizeof(gts9u_performance_overlay), "Galaxy OPPs");
	if (!ret)
		pr_info("gts9u-performance: registered Galaxy 3.36 GHz CPU and 719 MHz GPU OPPs\n");

	err = gts9u_apply(gts9u_ufs_ice_overlay, sizeof(gts9u_ufs_ice_overlay),
			  "UFS ICE clock scaling");
	if (!err)
		pr_info("gts9u-performance: UFS OPPs now scale the ICE core clock\n");
	return ret ?: err;
}
/* qcom-cpufreq-hw registers at postcore; OF platform devices appear later. */
core_initcall(gts9u_performance_init);
