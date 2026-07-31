// SPDX-License-Identifier: GPL-2.0-only
/*
 * Parade PS5169 USB 3.x / DisplayPort Type-C redriver.
 *
 * The register sequence comes from Samsung's GPL-2.0 downstream PS5169 driver
 * for the Galaxy Tab S9 Ultra (SM-X910).  This implementation deliberately
 * uses the mainline Type-C switch/retimer graph instead of Samsung's global
 * notifier and sysfs interfaces.
 */

#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/regmap.h>
#include <linux/usb/role.h>
#include <linux/usb/typec_dp.h>
#include <linux/usb/typec_mux.h>
#include <linux/usb/typec_retimer.h>

#define PS5169_REG_MODE			0x40
#define PS5169_REG_USB_DIRECTION	0x04
#define PS5169_REG_EQ0			0x52
#define PS5169_REG_EQ1			0x5e
#define PS5169_REG_CHIP_ID2		0xac
#define PS5169_REG_CHIP_ID1		0xad

struct ps5169 {
	struct device *dev;
	struct regmap *regmap;
	struct mutex lock;
	struct typec_switch_dev *sw;
	struct typec_retimer *retimer;
	struct typec_switch *typec_switch;
	struct typec_mux *typec_mux;
	struct usb_role_switch *role_switch;
	enum typec_orientation orientation;
	unsigned long mode;
	unsigned int svid;
	u8 reg50;
	u8 reg51;
	u8 reg54;
	u8 reg5d;
};

static int ps5169_write_sequence(struct ps5169 *ps,
				  const struct reg_sequence *sequence,
				  int count)
{
	return regmap_multi_reg_write(ps->regmap, sequence, count);
}

static int ps5169_set_safe(struct ps5169 *ps)
{
	static const struct reg_sequence sequence[] = {
		{ PS5169_REG_EQ0, 0x20 },
		{ PS5169_REG_EQ1, 0x06 },
		{ PS5169_REG_MODE, 0x80 },
		{ 0xa0, 0x02 },
		{ 0xa1, 0x00 },
		{ PS5169_REG_USB_DIRECTION, 0x00 },
		{ 0x8d, 0x00 },
		{ 0x90, 0x00 },
	};

	return ps5169_write_sequence(ps, sequence, ARRAY_SIZE(sequence));
}

static int ps5169_program(struct ps5169 *ps)
{
	bool reverse = ps->orientation == TYPEC_ORIENTATION_REVERSE;
	enum usb_role role = USB_ROLE_NONE;
	u8 mode;
	int ret;

	if (ps->orientation == TYPEC_ORIENTATION_NONE ||
	    ps->mode == TYPEC_STATE_SAFE)
		return ps5169_set_safe(ps);

	if (ps->role_switch)
		role = usb_role_switch_get_role(ps->role_switch);

	switch (ps->mode) {
	case TYPEC_STATE_USB:
		mode = reverse ? 0xd0 : 0xc0;
		ret = regmap_write(ps->regmap, PS5169_REG_MODE, mode);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, 0xa0, 0x02);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, PS5169_REG_USB_DIRECTION,
				   role == USB_ROLE_HOST ? 0x00 : 0x44);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, 0x8d, 0x01);
		if (ret)
			return ret;
		return regmap_write(ps->regmap, 0x90, 0x01);

	case TYPEC_DP_STATE_C:
	case TYPEC_DP_STATE_E:
		if (ps->svid != USB_TYPEC_DP_SID)
			return -EINVAL;
		mode = reverse ? 0xb0 : 0xa0;
		ret = regmap_write(ps->regmap, PS5169_REG_MODE, mode);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, 0xa0, 0x00);
		if (ret)
			return ret;
		return regmap_write(ps->regmap, 0xa1, 0x04);

	case TYPEC_DP_STATE_D:
	case TYPEC_DP_STATE_F:
		if (ps->svid != USB_TYPEC_DP_SID)
			return -EINVAL;
		mode = reverse ? 0xf0 : 0xe0;
		ret = regmap_write(ps->regmap, PS5169_REG_MODE, mode);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, 0xa0, 0x00);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, 0xa1, 0x04);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, PS5169_REG_USB_DIRECTION, 0x00);
		if (ret)
			return ret;
		ret = regmap_write(ps->regmap, 0x8d, 0x01);
		if (ret)
			return ret;
		return regmap_write(ps->regmap, 0x90, 0x01);

	default:
		return -EOPNOTSUPP;
	}
}

static int ps5169_switch_set(struct typec_switch_dev *sw,
			      enum typec_orientation orientation)
{
	struct ps5169 *ps = typec_switch_get_drvdata(sw);
	int ret;

	ret = typec_switch_set(ps->typec_switch, orientation);
	if (ret)
		return ret;

	mutex_lock(&ps->lock);
	ps->orientation = orientation;
	ret = ps5169_program(ps);
	mutex_unlock(&ps->lock);
	return ret;
}

static int ps5169_retimer_set(struct typec_retimer *retimer,
			       struct typec_retimer_state *state)
{
	struct ps5169 *ps = typec_retimer_get_drvdata(retimer);
	struct typec_mux_state mux_state = {
		.alt = state->alt,
		.data = state->data,
		.mode = state->mode,
	};
	int ret;

	mutex_lock(&ps->lock);
	ps->mode = state->mode;
	ps->svid = state->alt ? state->alt->svid : 0;
	ret = ps5169_program(ps);
	mutex_unlock(&ps->lock);
	if (ret)
		return ret;

	return typec_mux_set(ps->typec_mux, &mux_state);
}

static int ps5169_hw_init(struct ps5169 *ps)
{
	struct reg_sequence sequence[] = {
		{ PS5169_REG_MODE, 0x80 }, { 0xa0, 0x02 },
		{ 0x51, ps->reg51 }, { 0x50, ps->reg50 },
		{ 0x54, ps->reg54 }, { 0x5d, ps->reg5d },
		{ 0x55, 0x00 }, { 0x56, 0x00 }, { 0x57, 0x00 },
		{ 0x58, 0x00 }, { 0x59, 0x00 }, { 0x5a, 0x00 },
		{ 0x5b, 0x00 }, { 0x5f, 0x00 }, { 0x60, 0x00 },
		{ 0x61, 0x03 }, { 0x65, 0x40 }, { 0x66, 0x00 },
		{ 0x67, 0x03 }, { PS5169_REG_EQ0, 0x20 },
		{ PS5169_REG_EQ1, 0x06 },
		{ PS5169_REG_USB_DIRECTION, 0x00 },
	};
	unsigned int id1, id2;
	int ret;

	usleep_range(10000, 10100);
	ret = regmap_write(ps->regmap, 0x9d, 0x80);
	if (ret)
		return ret;
	usleep_range(10000, 10100);
	ret = regmap_write(ps->regmap, 0x9d, 0x00);
	if (ret)
		return ret;
	ret = ps5169_write_sequence(ps, sequence, ARRAY_SIZE(sequence));
	if (ret)
		return ret;

	usleep_range(10000, 10100);
	ret = regmap_read(ps->regmap, PS5169_REG_CHIP_ID1, &id1);
	if (ret)
		return ret;
	ret = regmap_read(ps->regmap, PS5169_REG_CHIP_ID2, &id2);
	if (ret)
		return ret;
	dev_info(ps->dev, "PS5169 redriver detected (chip id %02x:%02x)\n",
		 id1, id2);
	return 0;
}

static const struct regmap_config ps5169_regmap_config = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = PS5169_REG_CHIP_ID1,
	.cache_type = REGCACHE_NONE,
};

static int ps5169_probe(struct i2c_client *client)
{
	struct typec_retimer_desc retimer_desc = { };
	struct typec_switch_desc switch_desc = { };
	struct device *dev = &client->dev;
	struct ps5169 *ps;
	u32 value;
	int ret;

	ps = devm_kzalloc(dev, sizeof(*ps), GFP_KERNEL);
	if (!ps)
		return -ENOMEM;
	ps->dev = dev;
	ps->regmap = devm_regmap_init_i2c(client, &ps5169_regmap_config);
	if (IS_ERR(ps->regmap))
		return dev_err_probe(dev, PTR_ERR(ps->regmap),
				     "failed to allocate regmap\n");

	mutex_init(&ps->lock);
	ps->orientation = TYPEC_ORIENTATION_NONE;
	ps->mode = TYPEC_STATE_SAFE;
	ps->reg50 = 0x10;
	ps->reg51 = 0x70;
	ps->reg54 = 0x02;
	ps->reg5d = 0x40;
	if (!device_property_read_u32(dev, "parade,reg50", &value))
		ps->reg50 = value;
	if (!device_property_read_u32(dev, "parade,reg51", &value))
		ps->reg51 = value;
	if (!device_property_read_u32(dev, "parade,reg54", &value))
		ps->reg54 = value;
	if (!device_property_read_u32(dev, "parade,reg5d", &value))
		ps->reg5d = value;

	ps->typec_switch = fwnode_typec_switch_get(dev_fwnode(dev));
	if (IS_ERR(ps->typec_switch))
		return dev_err_probe(dev, PTR_ERR(ps->typec_switch),
				     "failed to acquire downstream orientation switch\n");
	ps->typec_mux = fwnode_typec_mux_get(dev_fwnode(dev));
	if (IS_ERR(ps->typec_mux)) {
		ret = dev_err_probe(dev, PTR_ERR(ps->typec_mux),
				    "failed to acquire downstream mode switch\n");
		goto put_switch;
	}
	ps->role_switch = fwnode_usb_role_switch_get(dev_fwnode(dev));
	if (IS_ERR(ps->role_switch)) {
		ret = dev_err_probe(dev, PTR_ERR(ps->role_switch),
				    "failed to acquire USB role switch\n");
		goto put_mux;
	}

	ret = ps5169_hw_init(ps);
	if (ret) {
		ret = dev_err_probe(dev, ret, "failed to initialise redriver\n");
		goto put_role;
	}

	switch_desc.drvdata = ps;
	switch_desc.fwnode = dev_fwnode(dev);
	switch_desc.set = ps5169_switch_set;
	ps->sw = typec_switch_register(dev, &switch_desc);
	if (IS_ERR(ps->sw)) {
		ret = dev_err_probe(dev, PTR_ERR(ps->sw),
				    "failed to register orientation switch\n");
		goto put_role;
	}

	retimer_desc.drvdata = ps;
	retimer_desc.fwnode = dev_fwnode(dev);
	retimer_desc.set = ps5169_retimer_set;
	ps->retimer = typec_retimer_register(dev, &retimer_desc);
	if (IS_ERR(ps->retimer)) {
		ret = dev_err_probe(dev, PTR_ERR(ps->retimer),
				    "failed to register retimer\n");
		goto unregister_switch;
	}

	i2c_set_clientdata(client, ps);
	return 0;

unregister_switch:
	typec_switch_unregister(ps->sw);
put_role:
	usb_role_switch_put(ps->role_switch);
put_mux:
	typec_mux_put(ps->typec_mux);
put_switch:
	typec_switch_put(ps->typec_switch);
	return ret;
}

static void ps5169_remove(struct i2c_client *client)
{
	struct ps5169 *ps = i2c_get_clientdata(client);

	typec_retimer_unregister(ps->retimer);
	typec_switch_unregister(ps->sw);
	usb_role_switch_put(ps->role_switch);
	typec_mux_put(ps->typec_mux);
	typec_switch_put(ps->typec_switch);
}

static const struct of_device_id ps5169_of_match[] = {
	{ .compatible = "parade,ps5169" },
	{ }
};
MODULE_DEVICE_TABLE(of, ps5169_of_match);

static struct i2c_driver ps5169_driver = {
	.driver = {
		.name = "ps5169",
		.of_match_table = ps5169_of_match,
	},
	.probe = ps5169_probe,
	.remove = ps5169_remove,
};
module_i2c_driver(ps5169_driver);

MODULE_DESCRIPTION("Parade PS5169 USB 3.x / DisplayPort Type-C redriver");
MODULE_LICENSE("GPL");
