// SPDX-License-Identifier: GPL-2.0-only
/*
 * Hold the fingerprint SPI clocks on so TrustZone can drive the bus.
 *
 * The EL721 hangs off QUP wrapper 1, serial engine 2 — the TA names its pads
 * qup1_se2_l0..l3, which are gpio36..gpio39, the range both this port and the
 * stock tree keep reserved from Linux.  Neither Linux enables that controller:
 * in the stock device tree qupv3_se2_spi stays disabled and the device overlay
 * never references it, exactly as here.  The secure world owns the bus.
 *
 * What Linux still owns is the clock tree, and mainline gates every clock that
 * has no consumer.  On this system gcc_qupv3_wrap1_s2_clk reads as disabled,
 * which would leave TrustZone programming an unclocked block — consistent with
 * the measurement that its transfers never reach the pads.
 *
 * This module takes a reference on that serial engine's clock (and the QUP
 * wrapper's AHB clocks) purely to test that theory without reflashing.  It
 * drives no pin and touches no register.
 */

#include <linux/clk.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_clk.h>

#define FP_SE_COMPATIBLE "qcom,geni-spi"
#define FP_SE_NODE "spi@a88000"
#define FP_MAX_CLOCKS 4

static struct clk *held[FP_MAX_CLOCKS];
static unsigned int held_count;

static struct device_node *fpclk_find_se(void)
{
	struct device_node *np = NULL;

	/*
	 * The node is disabled, so of_find_compatible_node() is the way in:
	 * a platform device never gets created for it.
	 */
	for_each_compatible_node(np, NULL, FP_SE_COMPATIBLE) {
		if (!strcmp(kbasename(of_node_full_name(np)), FP_SE_NODE))
			return np;
	}
	return NULL;
}

static int fpclk_hold(struct device_node *np, const char *what)
{
	int count = of_clk_get_parent_count(np);
	int i;

	if (count <= 0) {
		pr_warn("gts9u-fpclk: %s has no clocks\n", what);
		return 0;
	}
	for (i = 0; i < count && held_count < FP_MAX_CLOCKS; i++) {
		struct clk *clk = of_clk_get(np, i);
		int ret;

		if (IS_ERR(clk)) {
			pr_warn("gts9u-fpclk: %s clock %d unavailable (%ld)\n",
				what, i, PTR_ERR(clk));
			continue;
		}
		ret = clk_prepare_enable(clk);
		if (ret) {
			pr_warn("gts9u-fpclk: cannot enable %s clock %d (%d)\n",
				what, i, ret);
			clk_put(clk);
			continue;
		}
		pr_info("gts9u-fpclk: holding %s clock %d at %lu Hz\n", what, i,
			clk_get_rate(clk));
		held[held_count++] = clk;
	}
	return 0;
}

static int __init fpclk_init(void)
{
	struct device_node *se;
	struct device_node *qup;

	se = fpclk_find_se();
	if (!se) {
		pr_err("gts9u-fpclk: no %s node named %s\n", FP_SE_COMPATIBLE,
		       FP_SE_NODE);
		return -ENODEV;
	}
	pr_info("gts9u-fpclk: found %pOF\n", se);

	qup = of_get_parent(se);
	if (qup) {
		fpclk_hold(qup, "qup wrapper");
		of_node_put(qup);
	}
	fpclk_hold(se, "serial engine");
	of_node_put(se);

	if (!held_count) {
		pr_err("gts9u-fpclk: no clock could be held\n");
		return -ENODEV;
	}
	return 0;
}

static void __exit fpclk_exit(void)
{
	while (held_count--) {
		clk_disable_unprepare(held[held_count]);
		clk_put(held[held_count]);
	}
}

module_init(fpclk_init);
module_exit(fpclk_exit);

MODULE_DESCRIPTION("Hold the SM-X910 fingerprint SPI clocks on for TrustZone");
MODULE_AUTHOR("Ubuntu Galaxy Tab S9 Ultra port contributors");
MODULE_LICENSE("GPL");
