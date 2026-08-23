// SPDX-License-Identifier: GPL-2.0-only
/*
 * Turn on the EL721's 3.3 V rail from outside the driver.
 *
 * The stock device node powers the reader from a PMIC rail it names
 * VDD_BTP_3P3 and carries no etspi-ldoPin, so the GPIO this port drives as an
 * LDO enable is not what feeds the sensor.  Until the built-in driver is
 * rebuilt to claim "vdd" itself, this module claims it on the same device and
 * enables it, which is enough to tell whether the reader coming up changes
 * what TrustZone can read over the secure SPI.
 *
 * It only enables a regulator the device tree already assigns to that device.
 */

#include <linux/device.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/regulator/consumer.h>

static struct regulator *vdd;
static struct device *target;

static int fpvdd_match(struct device *dev, const void *data)
{
	return dev_name(dev) && !strcmp(dev_name(dev), "egis-el721");
}

static int __init fpvdd_init(void)
{
	int ret;

	target = bus_find_device(&platform_bus_type, NULL, NULL, fpvdd_match);
	if (!target) {
		pr_err("gts9u-fpvdd: no egis-el721 platform device\n");
		return -ENODEV;
	}

	/*
	 * The device this port registers for the reader is synthetic and has no
	 * device-tree node, so its "vdd" resolves to a dummy.  Ask for the rail
	 * by the name the device tree gives it instead.
	 */
	vdd = regulator_get(NULL, "vreg_l2b_3p3");
	if (IS_ERR(vdd))
		vdd = regulator_get(target, "vdd");
	if (IS_ERR(vdd)) {
		ret = PTR_ERR(vdd);
		vdd = NULL;
		put_device(target);
		target = NULL;
		pr_err("gts9u-fpvdd: cannot get the vdd supply (%d)\n", ret);
		return ret;
	}

	ret = regulator_set_voltage(vdd, 3300000, 3300000);
	if (ret)
		pr_warn("gts9u-fpvdd: cannot set 3.3 V (%d)\n", ret);
	ret = regulator_enable(vdd);
	if (ret) {
		pr_err("gts9u-fpvdd: cannot enable the vdd supply (%d)\n", ret);
		regulator_put(vdd);
		vdd = NULL;
		put_device(target);
		target = NULL;
		return ret;
	}

	pr_info("gts9u-fpvdd: sensor supply enabled at %d uV\n",
		regulator_get_voltage(vdd));
	return 0;
}

static void __exit fpvdd_exit(void)
{
	if (vdd) {
		regulator_disable(vdd);
		regulator_put(vdd);
	}
	if (target)
		put_device(target);
}

module_init(fpvdd_init);
module_exit(fpvdd_exit);

MODULE_DESCRIPTION("Enable the SM-X910 fingerprint sensor supply for testing");
MODULE_AUTHOR("Ubuntu Galaxy Tab S9 Ultra port contributors");
MODULE_LICENSE("GPL");
