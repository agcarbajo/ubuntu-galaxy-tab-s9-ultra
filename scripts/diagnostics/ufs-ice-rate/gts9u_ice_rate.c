// SPDX-License-Identifier: GPL-2.0-only
/*
 * Experiment only: ask the clock framework for another UFS ICE core clock
 * rate on a running tablet, to measure what the 19.2 MHz the bootloader
 * leaves costs.  Nothing is restored on unload; a reboot does that.
 */
#include <linux/clk.h>
#include <linux/module.h>
#include <linux/of.h>

static unsigned long rate = 100000000;
module_param(rate, ulong, 0444);

static int __init gts9u_ice_rate_init(void)
{
	struct device_node *np;
	unsigned long before;
	struct clk *clk;
	long rounded;
	int ret;

	np = of_find_compatible_node(NULL, NULL, "qcom,inline-crypto-engine");
	if (!np)
		return -ENODEV;
	clk = of_clk_get(np, 0);
	of_node_put(np);
	if (IS_ERR(clk))
		return PTR_ERR(clk);

	before = clk_get_rate(clk);
	rounded = clk_round_rate(clk, rate);
	ret = clk_set_rate(clk, rate);
	pr_info("gts9u-ice-rate: %lu Hz -> asked %lu, rounds to %ld, set returned %d, now %lu Hz\n",
		before, rate, rounded, ret, clk_get_rate(clk));
	clk_put(clk);
	return ret;
}

static void __exit gts9u_ice_rate_exit(void)
{
}

module_init(gts9u_ice_rate_init);
module_exit(gts9u_ice_rate_exit);
MODULE_DESCRIPTION("Galaxy Tab S9 Ultra UFS ICE clock rate experiment");
MODULE_LICENSE("GPL");
