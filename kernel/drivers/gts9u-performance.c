// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung's bootloader needs the byte-identical, validated base DTB. Add the
 * SM8550-AC OPPs after that handoff, before either OPP consumer can probe.
 * The CPU driver still checks its hardware LUT and supplies the real voltage;
 * the GPU entry comes from the X910's stock power-level table, not an OC.
 */
#include <linux/init.h>
#include <linux/of.h>
#include <linux/printk.h>

#include "gts9u-performance-overlay.h"

static int __init gts9u_performance_init(void)
{
	int overlay_id, ret;

	if (!of_machine_is_compatible("samsung,gts9uwifi"))
		return 0;

	ret = of_overlay_fdt_apply(gts9u_performance_overlay,
				  sizeof(gts9u_performance_overlay),
				  &overlay_id, NULL);
	if (ret) {
		pr_err("gts9u-performance: cannot add Galaxy OPPs: %d\n", ret);
		return ret;
	}

	pr_info("gts9u-performance: registered Galaxy 3.36 GHz CPU and 719 MHz GPU OPPs\n");
	return 0;
}
/* qcom-cpufreq-hw registers at postcore; OF platform devices appear later. */
core_initcall(gts9u_performance_init);
