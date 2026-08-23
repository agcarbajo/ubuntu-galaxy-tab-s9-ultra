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
#include <linux/interconnect.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_clk.h>
#include <linux/platform_device.h>

#define FP_SE_COMPATIBLE "qcom,geni-spi"
#define FP_SE_NODE "spi@a88000"
#define FP_MAX_CLOCKS 4

static struct clk *held[FP_MAX_CLOCKS];
static unsigned int held_count;

/*
 * The serial engine clock alone is not enough: a QUP moves data on its
 * wrapper's core clocks, and mainline drives those from the interconnect
 * "qup-core" vote rather than from a clocks property.  Android keeps engines in
 * this wrapper busy so the vote is always present; here nothing does, and
 * gcc_qupv3_wrap1_core_clk reads as disabled.  Vote for the paths the serial
 * engine's own node declares.
 */
static const char *const icc_names[] = { "qup-core", "qup-config", "qup-memory" };
static struct icc_path *paths[ARRAY_SIZE(icc_names)];
static struct platform_device *icc_pdev;

static void fpclk_vote_icc(struct device_node *np)
{
	unsigned int i;

	/*
	 * of_icc_get() needs a device carrying the node; the serial engine is
	 * disabled, so no platform device exists for it.  Create a bare one that
	 * borrows the node purely as a handle for the lookup.
	 */
	icc_pdev = platform_device_alloc("gts9u-fpclk-icc", PLATFORM_DEVID_NONE);
	if (!icc_pdev)
		return;
	device_set_node(&icc_pdev->dev, of_fwnode_handle(of_node_get(np)));
	if (platform_device_add(icc_pdev)) {
		platform_device_put(icc_pdev);
		icc_pdev = NULL;
		return;
	}

	for (i = 0; i < ARRAY_SIZE(icc_names); i++) {
		struct icc_path *path = of_icc_get(&icc_pdev->dev, icc_names[i]);

		if (IS_ERR_OR_NULL(path)) {
			pr_warn("gts9u-fpclk: no %s path (%ld)\n", icc_names[i],
				PTR_ERR(path));
			continue;
		}
		if (icc_set_bw(path, Bps_to_icc(1000), Bps_to_icc(1000))) {
			pr_warn("gts9u-fpclk: cannot vote %s\n", icc_names[i]);
			icc_put(path);
			continue;
		}
		pr_info("gts9u-fpclk: voted %s\n", icc_names[i]);
		paths[i] = path;
	}
}

static void fpclk_release_icc(void)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(icc_names); i++) {
		if (!paths[i])
			continue;
		icc_set_bw(paths[i], 0, 0);
		icc_put(paths[i]);
		paths[i] = NULL;
	}
	if (icc_pdev)
		platform_device_unregister(icc_pdev);
}

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

/*
 * The TA asks its SPI instance for 20 MHz, and this board's serial engine
 * source is parked at 5.12 MHz with the clock gated.  Offer the rate as a
 * parameter so the theory can be tested without reflashing.
 */
static unsigned int rate = 20000000;
module_param(rate, uint, 0444);
MODULE_PARM_DESC(rate, "serial engine clock rate in Hz, 0 to leave it alone");

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
		if (rate && !strcmp(what, "serial engine")) {
			int rc = clk_set_rate(clk, rate);

			if (rc)
				pr_warn("gts9u-fpclk: cannot set %s clock %d to %u Hz (%d)\n",
					what, i, rate, rc);
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
	fpclk_vote_icc(se);
	of_node_put(se);

	if (!held_count) {
		pr_err("gts9u-fpclk: no clock could be held\n");
		return -ENODEV;
	}
	return 0;
}

static void __exit fpclk_exit(void)
{
	fpclk_release_icc();
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
