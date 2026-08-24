// SPDX-License-Identifier: GPL-2.0-only
/*
 * Publish the EL721's 3.3 V rail into the live device tree, as a module.
 *
 * Samsung's ABL bootloops on any vendor_boot DTB whose structure moves, so the
 * rail the reader needs - the one the stock tree names VDD_BTP_3P3, mapped to
 * the PMIC's second LDO - cannot be described there.  Adding it from the kernel
 * is the way in, and this module is where that is tried before anything is
 * flashed: if the changeset is wrong, insmod fails and the tablet stays up.
 *
 * It adds a node and never removes or rewrites one.
 */

#include <linux/delay.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/machine.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/regulator/consumer.h>

#define RAIL_NAME "vreg_l2b_3p3"
/*
 * The stock overlay asks this rail for 3.3 V exactly, but mainline's PMIC5
 * p-type LDO steps 8 mV from 1.504 V, and 3.3 V is half a step off the grid:
 * constrain it to the two neighbouring points instead or the regulator cannot
 * be registered at all.
 */
#define RAIL_MICROVOLTS_MIN 3296000
#define RAIL_MICROVOLTS_MAX 3304000
/* Well above the phandles the board description itself uses. */
#define RAIL_PHANDLE 0x7000
/* Matches the modes the board description gives its other PMIC rails. */
#define RPMH_MODE_LPM 1
#define RPMH_MODE_HPM 3

static const u32 allowed_modes[] = { RPMH_MODE_LPM, RPMH_MODE_HPM };

static struct of_changeset ocs;
static bool applied;
static struct platform_device *consumer;
static struct regulator *vdd;

static bool power = true;
module_param(power, bool, 0444);
MODULE_PARM_DESC(power, "enable the rail once it is published (default yes)");

/*
 * The stock node powers the reader from the PMIC and declares no etspi-ldoPin,
 * so the only line Linux should drive is the sleep/reset one.  This port drives
 * a second GPIO as if it enabled an LDO; hold only the stock line here to see
 * what the TA makes of it.
 */
static bool enable_line;
module_param(enable_line, bool, 0444);
MODULE_PARM_DESC(enable_line, "drive the stock sleep/reset line high");

static struct gpio_desc *enable_desc;

static int settle_ms = 10;
module_param(settle_ms, int, 0444);
MODULE_PARM_DESC(settle_ms, "milliseconds to wait after the reset pulse");

static bool reset_pulse;
module_param(reset_pulse, bool, 0444);
MODULE_PARM_DESC(reset_pulse, "pulse the sleep line low before raising it");

static struct gpiod_lookup_table enable_lookup = {
	.dev_id = "gts9u-el721-supply",
	.table = {
		GPIO_LOOKUP("f100000.pinctrl", 155, "enable", GPIO_ACTIVE_HIGH),
		{ }
	},
};

static struct device_node *find_pmic_regulators(void)
{
	struct device_node *np = NULL;

	for_each_compatible_node(np, NULL, "qcom,pm8550-rpmh-regulators") {
		const char *id;

		if (!of_property_read_string(np, "qcom,pmic-id", &id) &&
		    !strcmp(id, "b"))
			return np;
	}

	return NULL;
}

static int __init fprail_init(void)
{
	struct device_node *regulators, *holder, *rail, *supply;
	struct platform_device *pdev;
	int attempt;
	int ret;

	regulators = find_pmic_regulators();
	if (!regulators) {
		pr_err("gts9u-fprail: no pm8550 regulator node\n");
		return -ENODEV;
	}

	rail = of_get_child_by_name(regulators, "ldo2");
	if (rail) {
		pr_info("gts9u-fprail: ldo2 already present\n");
		of_node_put(rail);
		of_node_put(regulators);
		return -EEXIST;
	}

	/*
	 * The RPMh regulator driver enumerates its children once, at probe, so a
	 * node added to the one already bound would never be registered.  Give
	 * the rail its own sibling node instead and create a device for it: the
	 * rails already up are never disturbed.
	 */
	of_changeset_init(&ocs);
	holder = of_changeset_create_node(&ocs, regulators->parent,
					  "regulators-el721");
	if (!holder) {
		ret = -ENOMEM;
		goto fail;
	}
	ret = of_changeset_add_prop_string(&ocs, holder, "compatible",
					   "qcom,pm8550-rpmh-regulators");
	if (!ret)
		ret = of_changeset_add_prop_string(&ocs, holder, "qcom,pmic-id",
						   "b");
	if (ret)
		goto fail;

	rail = of_changeset_create_node(&ocs, holder, "ldo2");
	if (!rail) {
		ret = -ENOMEM;
		goto fail;
	}
	ret = of_changeset_add_prop_string(&ocs, rail, "regulator-name",
					   RAIL_NAME);
	if (!ret)
		ret = of_changeset_add_prop_u32(&ocs, rail,
						"regulator-min-microvolt",
						RAIL_MICROVOLTS_MIN);
	if (!ret)
		ret = of_changeset_add_prop_u32(&ocs, rail,
						"regulator-max-microvolt",
						RAIL_MICROVOLTS_MAX);
	if (!ret)
		ret = of_changeset_add_prop_u32(&ocs, rail,
						"regulator-initial-mode",
						RPMH_MODE_HPM);
	if (!ret)
		ret = of_changeset_add_prop_u32_array(&ocs, rail,
						      "regulator-allowed-modes",
						      allowed_modes,
						      ARRAY_SIZE(allowed_modes));
	if (!ret)
		ret = of_changeset_add_prop_u32(&ocs, rail, "phandle",
						RAIL_PHANDLE);
	if (ret)
		goto fail;

	supply = of_changeset_create_node(&ocs, of_root, "el721-supply");
	if (!supply) {
		ret = -ENOMEM;
		goto fail;
	}
	ret = of_changeset_add_prop_u32(&ocs, supply, "vdd-supply",
					RAIL_PHANDLE);
	if (ret)
		goto fail;

	ret = of_changeset_apply(&ocs);
	if (ret)
		goto fail;

	applied = true;
	/*
	 * __of_attach_node() only picks the phandle up from nodes that already
	 * carry the property when they are attached, and a changeset adds it
	 * afterwards.  Publish it so vdd-supply can be resolved.
	 */
	rail->phandle = RAIL_PHANDLE;

	pdev = of_platform_device_create(holder, NULL, NULL);
	if (!pdev)
		pr_warn("gts9u-fprail: the rail node has no device yet\n");
	of_node_put(regulators);
	pr_info("gts9u-fprail: published %s and its consumer node\n", RAIL_NAME);

	if (!power)
		return 0;

	/* Give the consumer node a device so its vdd-supply resolves. */
	consumer = platform_device_alloc("gts9u-el721-supply", PLATFORM_DEVID_NONE);
	if (!consumer)
		return 0;
	device_set_node(&consumer->dev, of_fwnode_handle(supply));
	if (platform_device_add(consumer)) {
		platform_device_put(consumer);
		consumer = NULL;
		return 0;
	}

	/*
	 * The rail's own device was created a moment ago, so its driver may not
	 * have bound yet; the first attempts come back as probe deferrals.
	 */
	for (attempt = 0; attempt < 50; attempt++) {
		vdd = regulator_get(&consumer->dev, "vdd");
		if (!IS_ERR(vdd) || PTR_ERR(vdd) != -EPROBE_DEFER)
			break;
		msleep(20);
	}
	if (IS_ERR(vdd)) {
		pr_err("gts9u-fprail: cannot get the rail (%ld)\n", PTR_ERR(vdd));
		vdd = NULL;
		return 0;
	}
	/* Order matters, and it is the stock driver's: the rail comes up
	 * first and settles, and only then is the sleep line driven.
	 * Driving a signal pin into an unpowered part leaves it without a
	 * clean reset, and this module used to do exactly that. */
	if (regulator_enable(vdd))
		pr_err("gts9u-fprail: cannot enable the rail\n");
	else
		pr_info("gts9u-fprail: rail enabled at %d uV\n",
			regulator_get_voltage(vdd));
	usleep_range(2300, 2400);

	if (enable_line) {
		gpiod_add_lookup_table(&enable_lookup);
		enable_desc = gpiod_get(&consumer->dev, "enable", GPIOD_OUT_LOW);
		if (IS_ERR(enable_desc)) {
			pr_err("gts9u-fprail: cannot drive the sleep line (%ld)\n",
			       PTR_ERR(enable_desc));
			enable_desc = NULL;
			gpiod_remove_lookup_table(&enable_lookup);
		} else {
			if (reset_pulse)
				usleep_range(1050, 1100);
			gpiod_set_value_cansleep(enable_desc, 1);
			usleep_range(1100, 1200);
			usleep_range(5000, 5100);
			if (settle_ms > 0)
				msleep(settle_ms);
			pr_info("gts9u-fprail: sleep line high, settled %d ms\n",
				settle_ms);
		}
	}


	return 0;

fail:
	of_changeset_destroy(&ocs);
	of_node_put(regulators);
	pr_err("gts9u-fprail: cannot publish the rail (%d)\n", ret);

	return ret;
}

static void __exit fprail_exit(void)
{
	if (enable_desc) {
		gpiod_set_value_cansleep(enable_desc, 0);
		gpiod_put(enable_desc);
		gpiod_remove_lookup_table(&enable_lookup);
	}
	if (vdd) {
		regulator_disable(vdd);
		regulator_put(vdd);
	}
	if (consumer)
		platform_device_unregister(consumer);
	if (applied) {
		of_changeset_revert(&ocs);
		of_changeset_destroy(&ocs);
	}
}

module_init(fprail_init);
module_exit(fprail_exit);

MODULE_DESCRIPTION("Publish the SM-X910 fingerprint sensor rail into the live tree");
MODULE_AUTHOR("Ubuntu Galaxy Tab S9 Ultra port contributors");
MODULE_LICENSE("GPL");
