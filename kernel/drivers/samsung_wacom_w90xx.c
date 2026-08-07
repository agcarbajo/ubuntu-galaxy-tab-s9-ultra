// SPDX-License-Identifier: GPL-2.0-only
/*
 * Wacom W90xx EMR digitiser (Samsung "wez01") on the Galaxy Tab S9 Ultra.
 *
 * Mainline already carries two Wacom I2C drivers and neither can drive this
 * part.  wacom_i2c reads a 19-byte query little-endian from offsets 3, 5 and
 * 11; this controller answers big-endian with its record starting at offset 17,
 * so the query fails -- silently, because that driver returns the error without
 * logging it.  wacom_w9000 only knows the W9002 and W9007A.
 *
 * Everything below was measured on the hardware rather than ported, because no
 * source for this part is public.  The query decode was cross-checked against
 * Samsung's own device tree, which states max_pressure 0xfff, max_tilt 0x3f
 * 0x3f, max_height 0xff, module_ver 2 and boot_addr 9: all five appear in the
 * reply at the offsets used here.  The reported x_max and y_max give a ratio of
 * 0.6243, and the panel is 1848 x 2960, which is 0.6243.
 *
 * The input report was decoded from 5200 captured frames.  Pressure is
 * non-zero in exactly the frames whose status byte has bit 4 set and zero in
 * all 5059 others, which is what makes the tip bit and the pressure field
 * certain rather than plausible.
 */

#include <linux/bits.h>
#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/input/touchscreen.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>
#include <linux/slab.h>
#include <linux/unaligned.h>

/*
 * Status byte of an input report.  Bit 0 is set in every frame this device has
 * ever produced, including the ones that carry no pen, so it is not a tool bit
 * and is deliberately not interpreted.
 */
#define WACOM_STATUS_IN_RANGE	BIT(7)
#define WACOM_STATUS_BARREL	BIT(5)
#define WACOM_STATUS_TIP	BIT(4)
#define WACOM_STATUS_VALID	BIT(0)

#define WACOM_REPORT_SIZE	16

/*
 * Between pen reports the controller also hands out a short status header
 * whose first byte is 0x0d.  It is not a pen frame and must not be read as
 * one: treating it as "no pen" is what made the cursor drop out seventy-five
 * times in a fifteen-minute session, always while the pen was moving fastest
 * and reads were most likely to land between updates.
 */
#define WACOM_STATUS_HEADER	0x0d

/*
 * Leaving range is inferred from a bit going away rather than announced, so a
 * single stray frame is indistinguishable from a real lift.  Three in a row at
 * 40 Hz is 75 ms: too short to see, long enough that no isolated torn read can
 * fake it.
 */
#define WACOM_OUT_OF_RANGE_FRAMES	3

/* Field offsets within an input report. */
#define WACOM_REPORT_STATUS	0
#define WACOM_REPORT_X		1
#define WACOM_REPORT_Y		3
#define WACOM_REPORT_PRESSURE	5
#define WACOM_REPORT_TILT_X	7
#define WACOM_REPORT_TILT_Y	8
#define WACOM_REPORT_DISTANCE	9

/*
 * Bit 15 of the pressure word is set in every frame, with or without contact,
 * so it marks the field rather than scaling it.  The device tree caps pressure
 * at 4095, which fits comfortably in the remaining fifteen bits.
 */
#define WACOM_PRESSURE_MASK	GENMASK(14, 0)

/*
 * The controller powers up at its slowest rate and stays there: measured, the
 * gap between reports was 25.0 ms to three figures, which is the 40 Hz of
 * Samsung's own COM_SAMPLERATE_40.  Their constants are single-byte commands,
 * and sending 0x31 took the measured rate to about 440 Hz of genuinely
 * distinct positions: 5385 fresh X values across 5637 packets, so the extra
 * reports carry data rather than repeats.
 *
 * The rate does not stick.  It falls back to 40 Hz on its own, which is what
 * wez01 means by "samplerate state is %d, need to recovery", so it has to be
 * re-sent rather than set once.
 */
#define WACOM_CMD_SAMPLERATE_MAX	0x31

/* Feature report 3, the same request shape mainline's wacom_i2c uses. */
static const u8 wacom_query_cmd[] = { 0x04, 0x00, 0x33, 0x02, 0x05, 0x00 };

/*
 * The reply is 16 bytes of input-report space followed by the query record.
 * Reading both in one transfer is what revealed the layout, and keeping it that
 * way means the offsets below are the ones that were measured.
 */
#define WACOM_QUERY_SIZE	32
#define WACOM_QUERY_TRIES	10
#define WACOM_QUERY_BASE	17
#define WACOM_QUERY_X		(WACOM_QUERY_BASE + 0)
#define WACOM_QUERY_Y		(WACOM_QUERY_BASE + 2)
#define WACOM_QUERY_PRESSURE	(WACOM_QUERY_BASE + 4)
#define WACOM_QUERY_MODULE_VER	(WACOM_QUERY_BASE + 9)
#define WACOM_QUERY_TILT_X	(WACOM_QUERY_BASE + 10)
#define WACOM_QUERY_TILT_Y	(WACOM_QUERY_BASE + 11)
#define WACOM_QUERY_DISTANCE	(WACOM_QUERY_BASE + 12)

struct samsung_wacom {
	struct i2c_client *client;
	struct input_dev *input;
	struct touchscreen_properties props;
	bool in_range;
	unsigned int out_of_range;
};

struct samsung_wacom_features {
	u16 x_max;
	u16 y_max;
	u16 pressure_max;
	u8 tilt_x_max;
	u8 tilt_y_max;
	u8 distance_max;
	u8 module_ver;
};

static int samsung_wacom_query(struct i2c_client *client,
			       struct samsung_wacom_features *features)
{
	u8 data[WACOM_QUERY_SIZE];
	struct i2c_msg msgs[] = {
		{
			.addr = client->addr,
			.flags = 0,
			.len = sizeof(wacom_query_cmd),
			.buf = (u8 *)wacom_query_cmd,
		},
		{
			.addr = client->addr,
			.flags = I2C_M_RD,
			.len = sizeof(data),
			.buf = data,
		},
	};
	int ret;

	ret = i2c_transfer(client->adapter, msgs, ARRAY_SIZE(msgs));
	if (ret < 0)
		return ret;
	if (ret != ARRAY_SIZE(msgs))
		return -EIO;

	features->x_max = get_unaligned_be16(&data[WACOM_QUERY_X]);
	features->y_max = get_unaligned_be16(&data[WACOM_QUERY_Y]);
	features->pressure_max = get_unaligned_be16(&data[WACOM_QUERY_PRESSURE]);
	features->module_ver = data[WACOM_QUERY_MODULE_VER];
	features->tilt_x_max = data[WACOM_QUERY_TILT_X];
	features->tilt_y_max = data[WACOM_QUERY_TILT_Y];
	features->distance_max = data[WACOM_QUERY_DISTANCE];

	/*
	 * A controller that is powered but idle answers with zeros.  Refusing
	 * that here is what separates "no digitiser" from "digitiser with an
	 * unexpected layout", which cost a session to tell apart by hand.
	 */
	if (!features->x_max || !features->y_max || !features->pressure_max)
		return -ENODEV;

	return 0;
}

static void samsung_wacom_set_max_rate(struct samsung_wacom *wacom)
{
	static const u8 cmd = WACOM_CMD_SAMPLERATE_MAX;
	int ret;

	ret = i2c_master_send(wacom->client, &cmd, sizeof(cmd));
	if (ret != sizeof(cmd))
		dev_dbg(&wacom->client->dev,
			"could not raise the sample rate: %d\n", ret);
}

static irqreturn_t samsung_wacom_irq(int irq, void *dev_id)
{
	struct samsung_wacom *wacom = dev_id;
	struct input_dev *input = wacom->input;
	u8 data[WACOM_REPORT_SIZE];
	unsigned int pressure;
	bool in_range, tip, barrel;
	int ret;

	ret = i2c_master_recv(wacom->client, data, sizeof(data));
	if (ret != sizeof(data))
		return IRQ_HANDLED;

	/*
	 * Anything that is not a pen frame says nothing about the pen.  Both
	 * the status header and a read that landed mid-update have to be
	 * dropped rather than believed, or every one of them becomes a
	 * momentary loss of the cursor.
	 */
	if (data[WACOM_REPORT_STATUS] == WACOM_STATUS_HEADER ||
	    !(data[WACOM_REPORT_STATUS] & WACOM_STATUS_VALID))
		return IRQ_HANDLED;

	in_range = data[WACOM_REPORT_STATUS] & WACOM_STATUS_IN_RANGE;
	if (!in_range) {
		/*
		 * Leaving range is reported by the bit going away, not by a
		 * distinct packet, so the release has to be synthesised.  It
		 * takes several consecutive frames to believe it, and it is
		 * only emitted on the transition: this device keeps sending
		 * frames when idle, and reporting each one would flood the
		 * input layer.
		 */
		if (wacom->in_range &&
		    ++wacom->out_of_range >= WACOM_OUT_OF_RANGE_FRAMES) {
			wacom->in_range = false;
			wacom->out_of_range = 0;
			input_report_key(input, BTN_TOUCH, 0);
			input_report_key(input, BTN_STYLUS, 0);
			input_report_key(input, BTN_TOOL_PEN, 0);
			input_report_abs(input, ABS_PRESSURE, 0);
			input_sync(input);
		}
		return IRQ_HANDLED;
	}

	wacom->out_of_range = 0;
	if (!wacom->in_range) {
		/*
		 * Entering range is where the rate has reverted, so this is
		 * where it has to be asked for again.  One byte, and only on
		 * the transition, so it costs nothing while drawing.
		 */
		samsung_wacom_set_max_rate(wacom);
	}
	tip = data[WACOM_REPORT_STATUS] & WACOM_STATUS_TIP;
	barrel = data[WACOM_REPORT_STATUS] & WACOM_STATUS_BARREL;
	pressure = get_unaligned_be16(&data[WACOM_REPORT_PRESSURE]) &
		   WACOM_PRESSURE_MASK;

	wacom->in_range = true;

	touchscreen_report_pos(input, &wacom->props,
			       get_unaligned_be16(&data[WACOM_REPORT_X]),
			       get_unaligned_be16(&data[WACOM_REPORT_Y]),
			       false);
	input_report_abs(input, ABS_PRESSURE, pressure);
	input_report_abs(input, ABS_TILT_X, (s8)data[WACOM_REPORT_TILT_X]);
	input_report_abs(input, ABS_TILT_Y, (s8)data[WACOM_REPORT_TILT_Y]);
	input_report_abs(input, ABS_DISTANCE, data[WACOM_REPORT_DISTANCE]);
	input_report_key(input, BTN_TOOL_PEN, 1);
	input_report_key(input, BTN_TOUCH, tip);
	input_report_key(input, BTN_STYLUS, barrel);
	input_sync(input);

	return IRQ_HANDLED;
}

static int samsung_wacom_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct samsung_wacom_features features;
	struct samsung_wacom *wacom;
	struct input_dev *input;
	int attempt;
	int error;

	if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
		return dev_err_probe(dev, -EIO, "adapter lacks plain I2C\n");

	if (!client->irq)
		return dev_err_probe(dev, -EINVAL, "no interrupt\n");

	/*
	 * The rail is shared with the panel's VCI, and leaving it to the panel
	 * is not good enough: the display comes up long after this probe, and
	 * the first attempt at this driver was answered with a NACK at 3.9 s
	 * for exactly that reason.  Holding a reference of our own also keeps
	 * the digitiser alive once the screen blanks, which is what hover has
	 * to survive.
	 */
	error = devm_regulator_get_enable(dev, "avdd");
	if (error)
		return dev_err_probe(dev, error, "cannot enable AVDD\n");

	/*
	 * A controller that has just been given power needs a moment before it
	 * answers, and one NACK at probe would otherwise cost the whole device
	 * until the next reboot.
	 */
	for (attempt = 0; attempt < WACOM_QUERY_TRIES; attempt++) {
		if (attempt)
			msleep(20);
		error = samsung_wacom_query(client, &features);
		if (!error)
			break;
	}
	if (error)
		return dev_err_probe(dev, error,
				     "digitiser did not answer in %d tries\n",
				     WACOM_QUERY_TRIES);

	wacom = devm_kzalloc(dev, sizeof(*wacom), GFP_KERNEL);
	if (!wacom)
		return -ENOMEM;

	input = devm_input_allocate_device(dev);
	if (!input)
		return -ENOMEM;

	wacom->client = client;
	wacom->input = input;

	input->name = "Wacom EMR Digitizer";
	input->id.bustype = BUS_I2C;
	input->id.vendor = 0x056a;	/* Wacom */
	input->id.version = features.module_ver;

	/*
	 * The digitiser sits under the panel, so its coordinates are screen
	 * coordinates.  Saying so is not decoration: without INPUT_PROP_DIRECT
	 * libinput files a stylus under external graphics tablets, which are
	 * mapped to the whole desktop and deliberately do not follow the output
	 * orientation.  The visible symptom was the pen staying put while the
	 * screen rotated, ending up ninety degrees out in portrait.  The Goodix
	 * touchscreen next to it sets the same bit, which is why touch rotated
	 * correctly all along.
	 */
	__set_bit(INPUT_PROP_DIRECT, input->propbit);

	input_set_capability(input, EV_KEY, BTN_TOOL_PEN);
	input_set_capability(input, EV_KEY, BTN_TOUCH);
	input_set_capability(input, EV_KEY, BTN_STYLUS);
	input_set_abs_params(input, ABS_X, 0, features.x_max, 0, 0);
	input_set_abs_params(input, ABS_Y, 0, features.y_max, 0, 0);
	input_set_abs_params(input, ABS_PRESSURE, 0, features.pressure_max, 0, 0);
	input_set_abs_params(input, ABS_DISTANCE, 0, features.distance_max, 0, 0);
	input_set_abs_params(input, ABS_TILT_X, -features.tilt_x_max,
			     features.tilt_x_max, 0, 0);
	input_set_abs_params(input, ABS_TILT_Y, -features.tilt_y_max,
			     features.tilt_y_max, 0, 0);
	input_abs_set_res(input, ABS_X, features.x_max / 155);
	input_abs_set_res(input, ABS_Y, features.y_max / 248);

	/*
	 * The digitiser grid runs the other way round from the panel, exactly
	 * as the Goodix touchscreen's does, so the same device tree properties
	 * describe both and userspace sees one orientation.
	 */
	touchscreen_parse_properties(input, false, &wacom->props);

	input_set_drvdata(input, wacom);

	error = devm_request_threaded_irq(dev, client->irq, NULL,
					  samsung_wacom_irq,
					  IRQF_ONESHOT, dev_name(dev), wacom);
	if (error)
		return dev_err_probe(dev, error, "cannot claim the interrupt\n");

	error = input_register_device(input);
	if (error)
		return dev_err_probe(dev, error, "cannot register input\n");

	samsung_wacom_set_max_rate(wacom);

	dev_info(dev,
		 "Wacom EMR digitiser: %u x %u, pressure %u, tilt +/-%u/%u, module %u\n",
		 features.x_max, features.y_max, features.pressure_max,
		 features.tilt_x_max, features.tilt_y_max, features.module_ver);

	return 0;
}

static const struct of_device_id samsung_wacom_of_match[] = {
	{ .compatible = "samsung,gts9u-wacom-w90xx" },
	{ }
};
MODULE_DEVICE_TABLE(of, samsung_wacom_of_match);

static struct i2c_driver samsung_wacom_driver = {
	.driver = {
		.name = "samsung-wacom-w90xx",
		.of_match_table = samsung_wacom_of_match,
	},
	.probe = samsung_wacom_probe,
};
module_i2c_driver(samsung_wacom_driver);

MODULE_DESCRIPTION("Wacom W90xx EMR digitiser on the Samsung SM-X910");
MODULE_LICENSE("GPL");
