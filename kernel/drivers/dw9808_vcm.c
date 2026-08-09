// SPDX-License-Identifier: GPL-2.0-only
/* Dongwoon DW9808 VCM support for the Galaxy Tab S9 Ultra. */

#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/pm_runtime.h>
#include <linux/regulator/consumer.h>
#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>

#define DW9808_MAX_FOCUS_POS	1023
#define DW9808_CTRL_STEPS	16
#define DW9808_CTRL_DELAY_US	1000
#define DW9808_MAX_RETRIES	10

#define DW9808_REG_CONTROL	0x02
#define DW9808_REG_POSITION_MSB	0x03
#define DW9808_REG_POSITION_LSB	0x04
#define DW9808_REG_STATUS	0x05

struct dw9808_device {
	struct v4l2_ctrl_handler controls;
	struct v4l2_subdev subdev;
	struct regulator *vcc;
	u16 position;
};

static inline struct dw9808_device *to_dw9808(struct v4l2_subdev *subdev)
{
	return container_of(subdev, struct dw9808_device, subdev);
}

static int dw9808_status(struct i2c_client *client)
{
	return i2c_smbus_read_byte_data(client, DW9808_REG_STATUS);
}

static int dw9808_write(struct i2c_client *client, u8 reg, u8 value)
{
	int ret = i2c_smbus_write_byte_data(client, reg, value);

	if (ret < 0)
		dev_err(&client->dev, "register 0x%02x write failed: %d\n",
			reg, ret);
	return ret;
}

static int dw9808_init(struct i2c_client *client)
{
	/* Exact sequence from Samsung's dw9808 CamX actuatorDriver data. */
	static const struct {
		u8 reg;
		u8 value;
	} sequence[] = {
		{ 0x02, 0x01 }, { 0x02, 0x00 },
		{ 0x06, 0x60 }, { 0x07, 0x05 },
		{ 0x03, 0x00 }, { 0x04, 0xaf },
		{ 0x03, 0x00 }, { 0x04, 0xfa },
		{ 0x03, 0x01 }, { 0x04, 0x18 },
		{ 0x03, 0x01 }, { 0x04, 0x2b },
		{ 0x02, 0x02 },
	};
	unsigned int i;
	int ret;

	for (i = 0; i < ARRAY_SIZE(sequence); i++) {
		ret = dw9808_write(client, sequence[i].reg, sequence[i].value);
		if (ret)
			return ret;
	}
	usleep_range(5000, 5100);
	return 0;
}

static int dw9808_set_position(struct i2c_client *client, u16 position)
{
	u8 data[] = {
		DW9808_REG_POSITION_MSB,
		(position >> 8) & 0x03,
		position & 0xff,
	};
	int ret, status;

	ret = readx_poll_timeout(dw9808_status, client, status, status <= 0,
				 DW9808_CTRL_DELAY_US,
				 DW9808_MAX_RETRIES * DW9808_CTRL_DELAY_US);
	if (ret || status < 0)
		return ret ? -EBUSY : status;

	ret = i2c_master_send(client, data, sizeof(data));
	if (ret < 0)
		return ret;
	return ret == sizeof(data) ? 0 : -EIO;
}

static int dw9808_set_control(struct v4l2_ctrl *control)
{
	struct dw9808_device *dw9808 = container_of(control->handler,
						    struct dw9808_device,
						    controls);
	struct i2c_client *client = v4l2_get_subdevdata(&dw9808->subdev);
	int ret;

	if (control->id != V4L2_CID_FOCUS_ABSOLUTE)
		return -EINVAL;

	dw9808->position = control->val;
	ret = pm_runtime_get_if_in_use(&client->dev);
	if (ret <= 0)
		return ret < 0 ? ret : 0;
	ret = dw9808_set_position(client, dw9808->position);
	pm_runtime_put(&client->dev);
	return ret;
}

static const struct v4l2_ctrl_ops dw9808_control_ops = {
	.s_ctrl = dw9808_set_control,
};

static int dw9808_open(struct v4l2_subdev *subdev,
			struct v4l2_subdev_fh *fh)
{
	return pm_runtime_resume_and_get(subdev->dev);
}

static int dw9808_close(struct v4l2_subdev *subdev,
			 struct v4l2_subdev_fh *fh)
{
	pm_runtime_put(subdev->dev);
	return 0;
}

static const struct v4l2_subdev_internal_ops dw9808_internal_ops = {
	.open = dw9808_open,
	.close = dw9808_close,
};

static const struct v4l2_subdev_ops dw9808_subdev_ops = {};

static int dw9808_suspend(struct device *dev)
{
	struct i2c_client *client = to_i2c_client(dev);
	struct v4l2_subdev *subdev = i2c_get_clientdata(client);
	struct dw9808_device *dw9808 = to_dw9808(subdev);
	int position, ret = 0;

	for (position = dw9808->position & ~(DW9808_CTRL_STEPS - 1);
	     position >= 0; position -= DW9808_CTRL_STEPS) {
		int step_ret = dw9808_set_position(client, position);

		if (step_ret && !ret)
			ret = step_ret;
		usleep_range(DW9808_CTRL_DELAY_US, DW9808_CTRL_DELAY_US + 100);
	}
	if (dw9808_write(client, DW9808_REG_CONTROL, 0x01) && !ret)
		ret = -EIO;
	regulator_disable(dw9808->vcc);
	return ret;
}

static int dw9808_resume(struct device *dev)
{
	struct i2c_client *client = to_i2c_client(dev);
	struct v4l2_subdev *subdev = i2c_get_clientdata(client);
	struct dw9808_device *dw9808 = to_dw9808(subdev);
	int position, ret;

	ret = regulator_enable(dw9808->vcc);
	if (ret)
		return ret;
	usleep_range(1000, 1100);

	ret = dw9808_init(client);
	if (ret)
		goto disable;

	for (position = dw9808->position % DW9808_CTRL_STEPS;
	     position < dw9808->position + DW9808_CTRL_STEPS;
	     position += DW9808_CTRL_STEPS) {
		ret = dw9808_set_position(client,
					 min(position, (int)dw9808->position));
		if (ret)
			goto disable;
		usleep_range(DW9808_CTRL_DELAY_US, DW9808_CTRL_DELAY_US + 100);
	}
	return 0;

disable:
	regulator_disable(dw9808->vcc);
	return ret;
}

static const struct dev_pm_ops dw9808_pm_ops = {
	SET_SYSTEM_SLEEP_PM_OPS(pm_runtime_force_suspend, pm_runtime_force_resume)
	SET_RUNTIME_PM_OPS(dw9808_suspend, dw9808_resume, NULL)
};

static int dw9808_probe(struct i2c_client *client)
{
	struct dw9808_device *dw9808;
	int ret;

	dw9808 = devm_kzalloc(&client->dev, sizeof(*dw9808), GFP_KERNEL);
	if (!dw9808)
		return -ENOMEM;

	dw9808->vcc = devm_regulator_get(&client->dev, "vcc");
	if (IS_ERR(dw9808->vcc))
		return dev_err_probe(&client->dev, PTR_ERR(dw9808->vcc),
				     "failed to get VCC supply\n");

	v4l2_i2c_subdev_init(&dw9808->subdev, client, &dw9808_subdev_ops);
	dw9808->subdev.flags |= V4L2_SUBDEV_FL_HAS_DEVNODE;
	dw9808->subdev.internal_ops = &dw9808_internal_ops;
	dw9808->subdev.entity.function = MEDIA_ENT_F_LENS;

	v4l2_ctrl_handler_init(&dw9808->controls, 1);
	v4l2_ctrl_new_std(&dw9808->controls, &dw9808_control_ops,
			  V4L2_CID_FOCUS_ABSOLUTE, 0,
			  DW9808_MAX_FOCUS_POS, 1, 512);
	dw9808->subdev.ctrl_handler = &dw9808->controls;
	if (dw9808->controls.error) {
		ret = dw9808->controls.error;
		goto free_controls;
	}
	dw9808->position = 512;

	ret = media_entity_pads_init(&dw9808->subdev.entity, 0, NULL);
	if (ret)
		goto free_controls;

	ret = v4l2_async_register_subdev(&dw9808->subdev);
	if (ret)
		goto clean_entity;

	pm_runtime_set_suspended(&client->dev);
	pm_runtime_enable(&client->dev);
	return 0;

clean_entity:
	media_entity_cleanup(&dw9808->subdev.entity);
free_controls:
	v4l2_ctrl_handler_free(&dw9808->controls);
	return ret;
}

static void dw9808_remove(struct i2c_client *client)
{
	struct v4l2_subdev *subdev = i2c_get_clientdata(client);
	struct dw9808_device *dw9808 = to_dw9808(subdev);

	pm_runtime_disable(&client->dev);
	v4l2_async_unregister_subdev(subdev);
	v4l2_ctrl_handler_free(&dw9808->controls);
	media_entity_cleanup(&subdev->entity);
}

static const struct of_device_id dw9808_of_match[] = {
	{ .compatible = "dongwoon,dw9808-vcm" },
	{}
};
MODULE_DEVICE_TABLE(of, dw9808_of_match);

static struct i2c_driver dw9808_driver = {
	.driver = {
		.name = "dw9808-vcm",
		.of_match_table = dw9808_of_match,
		.pm = &dw9808_pm_ops,
	},
	.probe = dw9808_probe,
	.remove = dw9808_remove,
};
module_i2c_driver(dw9808_driver);

MODULE_DESCRIPTION("Dongwoon DW9808 VCM driver");
MODULE_LICENSE("GPL");
