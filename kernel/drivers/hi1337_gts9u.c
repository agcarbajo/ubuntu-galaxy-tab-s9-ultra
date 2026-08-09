// SPDX-License-Identifier: GPL-2.0
/* Hynix HI1337 support for the Samsung Galaxy Tab S9 Ultra (SM-X910). */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/regulator/consumer.h>
#include <linux/unaligned.h>

#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>
#include <media/v4l2-fwnode.h>

#define HI1337_MCLK                    19200000
#define HI1337_LINK_FREQ               360200000ULL
#define HI1337_PIXEL_RATE              288160000ULL
#define HI1337_DATA_LANES              4
#define HI1337_BITS_PER_PIXEL          10

#define HI1337_REG_MODEL_ID            0x0716
#define HI1337_REG_VENDOR_ID           0x0714
#define HI1337_MODEL_ID                0x1336
#define HI1337_VENDOR_ID               0x2000
#define HI1337_REG_MODE_SELECT         0x0b00
#define HI1337_MODE_STANDBY            0x0000
#define HI1337_MODE_STREAMING          0x0100
#define HI1337_REG_FRAME_LENGTH        0x020e
#define HI1337_REG_EXPOSURE            0x020a
#define HI1337_REG_ANALOGUE_GAIN       0x0213
#define HI1337_FRAME_LENGTH_MAX        0x7fff
#define HI1337_EXPOSURE_MIN            4
#define HI1337_EXPOSURE_MARGIN         4

struct hi1337_reg {
	u16 address;
	u16 value;
};

#include "hi1337_gts9u_tables.h"

struct hi1337_mode {
	u32 width;
	u32 height;
	u32 frame_length;
	const struct hi1337_reg *regs;
	unsigned int num_regs;
	const char *name;
};

struct hi1337_variant {
	struct hi1337_mode mode;
};

static const struct hi1337_variant hi1337_rear = {
	.mode = {
		.width = 4128,
		.height = 3096,
		.frame_length = 0x0cc0,
		.regs = hi1337_rear_4128x3096_regs,
		.num_regs = ARRAY_SIZE(hi1337_rear_4128x3096_regs),
		.name = "rear-main",
	},
};

static const struct hi1337_variant hi1337_front = {
	.mode = {
		.width = 3408,
		.height = 2556,
		.frame_length = 0x0a96,
		.regs = hi1337_front_3408x2556_regs,
		.num_regs = ARRAY_SIZE(hi1337_front_3408x2556_regs),
		.name = "front-main",
	},
};

static const struct hi1337_variant hi1337_front_uw = {
	.mode = {
		.width = 4000,
		.height = 3000,
		.frame_length = 0x0c54,
		.regs = hi1337_front_uw_4000x3000_regs,
		.num_regs = ARRAY_SIZE(hi1337_front_uw_4000x3000_regs),
		.name = "front-ultrawide",
	},
};

struct hi1337 {
	struct device *dev;
	struct clk *clk;
	struct regulator_bulk_data supplies[2];
	struct gpio_desc *enable_gpio;
	struct gpio_desc *reset_gpio;
	const struct hi1337_variant *variant;

	struct v4l2_subdev sd;
	struct media_pad pad;
	struct v4l2_ctrl_handler ctrl_handler;
	struct v4l2_ctrl *link_freq;
	struct v4l2_ctrl *pixel_rate;
	struct v4l2_ctrl *vblank;
	struct v4l2_ctrl *hblank;
	struct v4l2_ctrl *exposure;
	struct mutex mutex;
	bool streaming;
};

#define to_hi1337(sd) container_of(sd, struct hi1337, sd)

static int hi1337_read_reg(struct hi1337 *sensor, u16 reg, u16 *value)
{
	struct i2c_client *client = v4l2_get_subdevdata(&sensor->sd);
	struct i2c_msg messages[2];
	u8 address[2];
	u8 data[2];
	int ret;

	put_unaligned_be16(reg, address);
	messages[0].addr = client->addr;
	messages[0].flags = 0;
	messages[0].len = sizeof(address);
	messages[0].buf = address;
	messages[1].addr = client->addr;
	messages[1].flags = I2C_M_RD;
	messages[1].len = sizeof(data);
	messages[1].buf = data;

	ret = i2c_transfer(client->adapter, messages, ARRAY_SIZE(messages));
	if (ret != ARRAY_SIZE(messages))
		return ret < 0 ? ret : -EIO;

	*value = get_unaligned_be16(data);
	return 0;
}

static int hi1337_write_reg(struct hi1337 *sensor, u16 reg, u16 value)
{
	struct i2c_client *client = v4l2_get_subdevdata(&sensor->sd);
	u8 data[4];
	int ret;

	put_unaligned_be16(reg, data);
	put_unaligned_be16(value, data + 2);
	ret = i2c_master_send(client, data, sizeof(data));
	return ret == sizeof(data) ? 0 : (ret < 0 ? ret : -EIO);
}

static int hi1337_write_table(struct hi1337 *sensor,
			      const struct hi1337_reg *regs,
			      unsigned int num_regs)
{
	unsigned int index;
	int ret;

	for (index = 0; index < num_regs; index++) {
		ret = hi1337_write_reg(sensor, regs[index].address,
				       regs[index].value);
		if (ret) {
			dev_err_ratelimited(sensor->dev,
				"failed to write register 0x%04x: %d\n",
				regs[index].address, ret);
			return ret;
		}
	}

	return 0;
}

static int hi1337_power_on(struct hi1337 *sensor)
{
	int ret;

	ret = regulator_bulk_enable(ARRAY_SIZE(sensor->supplies),
				    sensor->supplies);
	if (ret)
		return ret;
	/* The stock sequence gives VIO and VDIG one millisecond each. */
	usleep_range(2000, 2500);

	/*
	 * The front module-enable line is multiplexed with the internal DMIC.
	 * Hold camera GPIOs only while the sensor is actually powered so an
	 * idle, registered camera cannot regress audio capture.
	 */
	sensor->enable_gpio = gpiod_get_optional(sensor->dev, "enable",
					 GPIOD_OUT_LOW);
	if (IS_ERR(sensor->enable_gpio)) {
		ret = PTR_ERR(sensor->enable_gpio);
		sensor->enable_gpio = NULL;
		goto disable_regulators;
	}
	sensor->reset_gpio = gpiod_get(sensor->dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(sensor->reset_gpio)) {
		ret = PTR_ERR(sensor->reset_gpio);
		sensor->reset_gpio = NULL;
		goto release_enable;
	}

	if (sensor->enable_gpio)
		gpiod_set_value_cansleep(sensor->enable_gpio, 1);
	usleep_range(1000, 1500);

	ret = clk_prepare_enable(sensor->clk);
	if (ret)
		goto disable_module;

	/* Stock keeps MCLK stable for 10 ms before releasing reset. */
	usleep_range(10000, 11000);
	gpiod_set_value_cansleep(sensor->reset_gpio, 0);
	usleep_range(12000, 13000);
	return 0;

disable_module:
	if (sensor->enable_gpio)
		gpiod_set_value_cansleep(sensor->enable_gpio, 0);
	gpiod_put(sensor->reset_gpio);
	sensor->reset_gpio = NULL;
release_enable:
	if (sensor->enable_gpio)
		gpiod_put(sensor->enable_gpio);
	sensor->enable_gpio = NULL;
disable_regulators:
	regulator_bulk_disable(ARRAY_SIZE(sensor->supplies), sensor->supplies);
	return ret;
}

static void hi1337_power_off(struct hi1337 *sensor)
{
	if (!sensor->reset_gpio)
		return;

	gpiod_set_value_cansleep(sensor->reset_gpio, 1);
	clk_disable_unprepare(sensor->clk);
	if (sensor->enable_gpio)
		gpiod_set_value_cansleep(sensor->enable_gpio, 0);
	gpiod_put(sensor->reset_gpio);
	sensor->reset_gpio = NULL;
	if (sensor->enable_gpio)
		gpiod_put(sensor->enable_gpio);
	sensor->enable_gpio = NULL;
	regulator_bulk_disable(ARRAY_SIZE(sensor->supplies), sensor->supplies);
}

static int hi1337_identify(struct hi1337 *sensor)
{
	u16 model = 0;
	u16 vendor = 0;
	int model_ret;
	int vendor_ret;

	model_ret = hi1337_read_reg(sensor, HI1337_REG_MODEL_ID, &model);
	vendor_ret = hi1337_read_reg(sensor, HI1337_REG_VENDOR_ID, &vendor);
	if (model_ret && vendor_ret) {
		dev_err(sensor->dev,
			"identity reads failed: model=%d vendor=%d\n",
			model_ret, vendor_ret);
		return model_ret;
	}

	if (model != HI1337_MODEL_ID && model != 0x1337 &&
	    vendor != HI1337_VENDOR_ID) {
		dev_err(sensor->dev,
			"unexpected sensor identity model=0x%04x vendor=0x%04x\n",
			model, vendor);
		return -ENXIO;
	}

	dev_info(sensor->dev, "%s model=0x%04x vendor=0x%04x\n",
		 sensor->variant->mode.name, model, vendor);
	return 0;
}

static int hi1337_set_ctrl(struct v4l2_ctrl *ctrl)
{
	struct hi1337 *sensor = container_of(ctrl->handler, struct hi1337,
					     ctrl_handler);
	s64 exposure_max;

	if (ctrl->id == V4L2_CID_VBLANK) {
		exposure_max = sensor->variant->mode.height + ctrl->val -
			       HI1337_EXPOSURE_MARGIN;
		__v4l2_ctrl_modify_range(sensor->exposure,
					 HI1337_EXPOSURE_MIN,
					 exposure_max, 1,
					 min_t(s64, sensor->exposure->val,
					       exposure_max));
	}

	if (!sensor->streaming)
		return 0;

	switch (ctrl->id) {
	case V4L2_CID_EXPOSURE:
		return hi1337_write_reg(sensor, HI1337_REG_EXPOSURE,
					ctrl->val);
	case V4L2_CID_ANALOGUE_GAIN:
		return hi1337_write_reg(sensor, HI1337_REG_ANALOGUE_GAIN,
					ctrl->val & 0xff);
	case V4L2_CID_VBLANK:
		return hi1337_write_reg(sensor, HI1337_REG_FRAME_LENGTH,
					sensor->variant->mode.height + ctrl->val);
	default:
		return 0;
	}
}

static const struct v4l2_ctrl_ops hi1337_ctrl_ops = {
	.s_ctrl = hi1337_set_ctrl,
};

static int hi1337_init_controls(struct hi1337 *sensor)
{
	const struct hi1337_mode *mode = &sensor->variant->mode;
	struct v4l2_fwnode_device_properties props;
	static const s64 link_freq_menu[] = { HI1337_LINK_FREQ };
	u32 vblank = mode->frame_length - mode->height;
	int ret;

	ret = v4l2_ctrl_handler_init(&sensor->ctrl_handler, 8);
	if (ret)
		return ret;

	sensor->ctrl_handler.lock = &sensor->mutex;
	sensor->link_freq = v4l2_ctrl_new_int_menu(&sensor->ctrl_handler,
		&hi1337_ctrl_ops, V4L2_CID_LINK_FREQ, 0, 0, link_freq_menu);
	if (sensor->link_freq)
		sensor->link_freq->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	sensor->pixel_rate = v4l2_ctrl_new_std(&sensor->ctrl_handler,
		&hi1337_ctrl_ops, V4L2_CID_PIXEL_RATE,
		HI1337_PIXEL_RATE, HI1337_PIXEL_RATE, 1, HI1337_PIXEL_RATE);
	sensor->vblank = v4l2_ctrl_new_std(&sensor->ctrl_handler,
		&hi1337_ctrl_ops, V4L2_CID_VBLANK, vblank,
		HI1337_FRAME_LENGTH_MAX - mode->height, 1, vblank);
	sensor->hblank = v4l2_ctrl_new_std(&sensor->ctrl_handler,
		&hi1337_ctrl_ops, V4L2_CID_HBLANK, 0, 0, 1, 0);
	if (sensor->hblank)
		sensor->hblank->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	sensor->exposure = v4l2_ctrl_new_std(&sensor->ctrl_handler,
		&hi1337_ctrl_ops, V4L2_CID_EXPOSURE, HI1337_EXPOSURE_MIN,
		mode->frame_length - HI1337_EXPOSURE_MARGIN, 1,
		mode->frame_length - HI1337_EXPOSURE_MARGIN);
	v4l2_ctrl_new_std(&sensor->ctrl_handler, &hi1337_ctrl_ops,
			  V4L2_CID_ANALOGUE_GAIN, 0, 240, 1, 0);

	/* Export the DT rotation and front/back location to libcamera. */
	ret = v4l2_fwnode_device_parse(sensor->dev, &props);
	if (ret)
		return ret;
	ret = v4l2_ctrl_new_fwnode_properties(&sensor->ctrl_handler,
					       &hi1337_ctrl_ops, &props);
	if (ret)
		return ret;

	if (sensor->ctrl_handler.error)
		return sensor->ctrl_handler.error;
	sensor->sd.ctrl_handler = &sensor->ctrl_handler;
	return 0;
}

static void hi1337_fill_format(struct hi1337 *sensor,
			       struct v4l2_mbus_framefmt *format)
{
	format->width = sensor->variant->mode.width;
	format->height = sensor->variant->mode.height;
	format->code = MEDIA_BUS_FMT_SGRBG10_1X10;
	format->field = V4L2_FIELD_NONE;
	format->colorspace = V4L2_COLORSPACE_RAW;
}

static int hi1337_start_streaming(struct hi1337 *sensor)
{
	const struct hi1337_mode *mode = &sensor->variant->mode;
	int ret;

	ret = hi1337_write_table(sensor, hi1337_global_regs,
				 ARRAY_SIZE(hi1337_global_regs));
	if (ret)
		return ret;
	ret = hi1337_write_table(sensor, mode->regs, mode->num_regs);
	if (ret)
		return ret;

	sensor->streaming = true;
	ret = __v4l2_ctrl_handler_setup(&sensor->ctrl_handler);
	if (ret)
		goto clear_streaming;
	ret = hi1337_write_reg(sensor, HI1337_REG_MODE_SELECT,
			       HI1337_MODE_STREAMING);
	if (ret)
		goto clear_streaming;
	return 0;

clear_streaming:
	sensor->streaming = false;
	return ret;
}

static int hi1337_set_stream(struct v4l2_subdev *sd, int enable)
{
	struct hi1337 *sensor = to_hi1337(sd);
	int ret = 0;

	mutex_lock(&sensor->mutex);
	if (sensor->streaming == !!enable)
		goto unlock;

	if (enable) {
		ret = hi1337_power_on(sensor);
		if (ret)
			goto unlock;
		ret = hi1337_start_streaming(sensor);
		if (ret)
			hi1337_power_off(sensor);
	} else {
		ret = hi1337_write_reg(sensor, HI1337_REG_MODE_SELECT,
				       HI1337_MODE_STANDBY);
		sensor->streaming = false;
		hi1337_power_off(sensor);
	}

unlock:
	mutex_unlock(&sensor->mutex);
	return ret;
}

static int hi1337_get_format(struct v4l2_subdev *sd,
			     struct v4l2_subdev_state *state,
			     struct v4l2_subdev_format *format)
{
	struct hi1337 *sensor = to_hi1337(sd);

	if (format->which == V4L2_SUBDEV_FORMAT_TRY)
		format->format = *v4l2_subdev_state_get_format(state,
								format->pad);
	else
		hi1337_fill_format(sensor, &format->format);
	return 0;
}

static int hi1337_set_format(struct v4l2_subdev *sd,
			     struct v4l2_subdev_state *state,
			     struct v4l2_subdev_format *format)
{
	struct hi1337 *sensor = to_hi1337(sd);

	hi1337_fill_format(sensor, &format->format);
	if (format->which == V4L2_SUBDEV_FORMAT_TRY)
		*v4l2_subdev_state_get_format(state, format->pad) =
			format->format;
	return 0;
}

static int hi1337_enum_mbus_code(struct v4l2_subdev *sd,
				 struct v4l2_subdev_state *state,
				 struct v4l2_subdev_mbus_code_enum *code)
{
	if (code->index)
		return -EINVAL;
	code->code = MEDIA_BUS_FMT_SGRBG10_1X10;
	return 0;
}

static int hi1337_enum_frame_size(struct v4l2_subdev *sd,
				  struct v4l2_subdev_state *state,
				  struct v4l2_subdev_frame_size_enum *size)
{
	struct hi1337 *sensor = to_hi1337(sd);

	if (size->index || size->code != MEDIA_BUS_FMT_SGRBG10_1X10)
		return -EINVAL;
	size->min_width = sensor->variant->mode.width;
	size->max_width = size->min_width;
	size->min_height = sensor->variant->mode.height;
	size->max_height = size->min_height;
	return 0;
}

static int hi1337_get_selection(struct v4l2_subdev *sd,
				struct v4l2_subdev_state *state,
				struct v4l2_subdev_selection *selection)
{
	struct hi1337 *sensor = to_hi1337(sd);

	if (selection->pad)
		return -EINVAL;

	switch (selection->target) {
	case V4L2_SEL_TGT_CROP:
	case V4L2_SEL_TGT_CROP_DEFAULT:
	case V4L2_SEL_TGT_CROP_BOUNDS:
	case V4L2_SEL_TGT_NATIVE_SIZE:
		selection->r.left = 0;
		selection->r.top = 0;
		selection->r.width = sensor->variant->mode.width;
		selection->r.height = sensor->variant->mode.height;
		return 0;
	default:
		return -EINVAL;
	}
}

static int hi1337_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
	hi1337_fill_format(to_hi1337(sd),
			   v4l2_subdev_state_get_format(fh->state, 0));
	return 0;
}

static const struct v4l2_subdev_video_ops hi1337_video_ops = {
	.s_stream = hi1337_set_stream,
};

static const struct v4l2_subdev_pad_ops hi1337_pad_ops = {
	.get_fmt = hi1337_get_format,
	.set_fmt = hi1337_set_format,
	.enum_mbus_code = hi1337_enum_mbus_code,
	.enum_frame_size = hi1337_enum_frame_size,
	.get_selection = hi1337_get_selection,
};

static const struct v4l2_subdev_ops hi1337_subdev_ops = {
	.video = &hi1337_video_ops,
	.pad = &hi1337_pad_ops,
};

static const struct v4l2_subdev_internal_ops hi1337_internal_ops = {
	.open = hi1337_open,
};

static const struct media_entity_operations hi1337_entity_ops = {
	.link_validate = v4l2_subdev_link_validate,
};

static int hi1337_check_hwcfg(struct device *dev)
{
	struct v4l2_fwnode_endpoint endpoint = {
		.bus_type = V4L2_MBUS_CSI2_DPHY,
	};
	struct fwnode_handle *fwnode_endpoint;
	bool found_frequency = false;
	unsigned int index;
	int ret;

	fwnode_endpoint = fwnode_graph_get_next_endpoint(dev_fwnode(dev), NULL);
	if (!fwnode_endpoint)
		return -ENXIO;
	ret = v4l2_fwnode_endpoint_alloc_parse(fwnode_endpoint, &endpoint);
	fwnode_handle_put(fwnode_endpoint);
	if (ret)
		return ret;

	if (endpoint.bus.mipi_csi2.num_data_lanes != HI1337_DATA_LANES) {
		ret = -EINVAL;
		goto free_endpoint;
	}
	for (index = 0; index < endpoint.nr_of_link_frequencies; index++)
		if (endpoint.link_frequencies[index] == HI1337_LINK_FREQ)
			found_frequency = true;
	ret = found_frequency ? 0 : -EINVAL;

free_endpoint:
	v4l2_fwnode_endpoint_free(&endpoint);
	return ret;
}

static int hi1337_probe(struct i2c_client *client)
{
	struct hi1337 *sensor;
	unsigned long clock_rate;
	int ret;

	sensor = devm_kzalloc(&client->dev, sizeof(*sensor), GFP_KERNEL);
	if (!sensor)
		return -ENOMEM;
	sensor->dev = &client->dev;
	sensor->variant = device_get_match_data(sensor->dev);
	if (!sensor->variant)
		return -EINVAL;

	sensor->clk = devm_v4l2_sensor_clk_get(sensor->dev, NULL);
	if (IS_ERR(sensor->clk))
		return dev_err_probe(sensor->dev, PTR_ERR(sensor->clk),
				     "failed to get MCLK\n");
	clock_rate = clk_get_rate(sensor->clk);
	if (clock_rate != HI1337_MCLK)
		return dev_err_probe(sensor->dev, -EINVAL,
				     "unsupported MCLK %lu\n", clock_rate);

	sensor->supplies[0].supply = "vddio";
	sensor->supplies[1].supply = "vdig";
	ret = devm_regulator_bulk_get(sensor->dev,
				      ARRAY_SIZE(sensor->supplies),
				      sensor->supplies);
	if (ret)
		return dev_err_probe(sensor->dev, ret,
				     "failed to get regulators\n");
	ret = hi1337_check_hwcfg(sensor->dev);
	if (ret)
		return dev_err_probe(sensor->dev, ret,
				     "invalid CSI-2 endpoint\n");

	v4l2_i2c_subdev_init(&sensor->sd, client, &hi1337_subdev_ops);
	ret = hi1337_power_on(sensor);
	if (ret)
		return dev_err_probe(sensor->dev, ret,
				     "failed to power module\n");
	ret = hi1337_identify(sensor);
	if (ret)
		goto power_off;

	mutex_init(&sensor->mutex);
	ret = hi1337_init_controls(sensor);
	if (ret)
		goto destroy_mutex;

	sensor->sd.internal_ops = &hi1337_internal_ops;
	sensor->sd.flags |= V4L2_SUBDEV_FL_HAS_DEVNODE;
	sensor->sd.entity.ops = &hi1337_entity_ops;
	sensor->sd.entity.function = MEDIA_ENT_F_CAM_SENSOR;
	sensor->pad.flags = MEDIA_PAD_FL_SOURCE;
	ret = media_entity_pads_init(&sensor->sd.entity, 1, &sensor->pad);
	if (ret)
		goto free_controls;
	ret = v4l2_async_register_subdev_sensor(&sensor->sd);
	if (ret)
		goto cleanup_entity;
	hi1337_power_off(sensor);
	return 0;

cleanup_entity:
	media_entity_cleanup(&sensor->sd.entity);
free_controls:
	v4l2_ctrl_handler_free(&sensor->ctrl_handler);
destroy_mutex:
	mutex_destroy(&sensor->mutex);
power_off:
	hi1337_power_off(sensor);
	return ret;
}

static void hi1337_remove(struct i2c_client *client)
{
	struct v4l2_subdev *sd = i2c_get_clientdata(client);
	struct hi1337 *sensor = to_hi1337(sd);

	v4l2_async_unregister_subdev(sd);
	media_entity_cleanup(&sd->entity);
	v4l2_ctrl_handler_free(&sensor->ctrl_handler);
	if (sensor->streaming)
		hi1337_power_off(sensor);
	mutex_destroy(&sensor->mutex);
}

static const struct of_device_id hi1337_of_match[] = {
	{ .compatible = "hynix,hi1337-gts9u-rear", .data = &hi1337_rear },
	{ .compatible = "hynix,hi1337-gts9u-front", .data = &hi1337_front },
	{ .compatible = "hynix,hi1337-gts9u-front-uw", .data = &hi1337_front_uw },
	{ }
};
MODULE_DEVICE_TABLE(of, hi1337_of_match);

static struct i2c_driver hi1337_i2c_driver = {
	.driver = {
		.name = "hi1337-gts9u",
		.of_match_table = hi1337_of_match,
	},
	.probe = hi1337_probe,
	.remove = hi1337_remove,
};
module_i2c_driver(hi1337_i2c_driver);

MODULE_AUTHOR("Antonio García Carbajo");
MODULE_DESCRIPTION("Hynix HI1337 driver for Samsung SM-X910 camera modules");
MODULE_LICENSE("GPL");
