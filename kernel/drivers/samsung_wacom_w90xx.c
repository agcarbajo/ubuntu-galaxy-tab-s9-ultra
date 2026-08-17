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

#include <linux/atomic.h>
#include <linux/bits.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/input/touchscreen.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/power_supply.h>
#include <linux/regulator/consumer.h>
#include <linux/samsung_wacom.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>
#include <linux/timer.h>
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

/*
 * And the frames may simply stop.  When the pen is taken away the controller
 * can fall silent without ever sending the out-of-range frames the counter
 * above waits for, and then nothing clears BTN_TOOL_PEN: measured on the
 * device, 0 interrupts in five seconds with the tool still reported in range
 * and ABS_DISTANCE frozen at its last value.
 *
 * That is not cosmetic.  libinput groups this digitiser with the Goodix
 * touchscreen, so a tool it believes is in proximity makes it arbitrate touch
 * away around the last pen position: new contacts inside that rectangle are
 * dropped while contacts already in progress are not, which reads as a part of
 * the screen that answers the pen but not a finger, unless the finger is
 * dragged in from outside.  It lasts until the next reboot.
 *
 * So silence has to count as leaving too.  Idle reports arrive every 25 ms, so
 * a quarter of a second is ten missed frames: far too long to fire while the
 * pen is really there, far too short to be noticed when it is not.
 */
#define WACOM_PROXIMITY_TIMEOUT_MS	250

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

/* Samsung's garage/docking protocol, verified against the X910 source drop. */
#define WACOM_CMD_GARAGE_STATUS		0xee
#define WACOM_CMD_BLE_CHARGE_ENABLE	0xe9
#define WACOM_CMD_BLE_PAIR_RESET	0xea
#define WACOM_CMD_BLE_CHARGE_START	0xeb
#define WACOM_CMD_BLE_CHARGE_KEEP_ON	0xec
#define WACOM_CMD_BLE_CHARGE_KEEP_OFF	0xed
#define WACOM_CHARGE_START_DELAY_MS	1000
#define WACOM_CHARGE_STATUS_PERIOD_MS	30000
#define WACOM_PACKET_ID_MASK		GENMASK(3, 0)
#define WACOM_PACKET_REPLY		0x0e
#define WACOM_REPLY_GARAGE_CHARGE	0x06
#define WACOM_GARAGE_DIRECTION_UP	0x01
#define WACOM_GARAGE_DIRECTION_DOWN	0x02

/*
 * The book cover arrives here and nowhere else.  The tablet's own Hall sensor
 * (TLMM 107, wired as gpio-keys SW_LID) answers the plain Book Cover, but the
 * keyboard folio's magnet never reaches it: measured with the cover shut, that
 * line reads inactive and its interrupt count stays at zero for a whole boot,
 * and a sweep of all 207 pins finds nothing that holds a level either.
 *
 * The digitiser is what notices, which makes sense because its grid spans the
 * whole panel.  Samsung's driver decodes exactly this (wacom_i2c.c: NOTI_PACKET
 * 13, COVER_DETECT_PACKET 10, status in bit 7 of data[3]) and reports it as
 * SW_FLIP, which is 0x10 -- the code mainline calls SW_MACHINE_COVER.
 *
 * Captured off the i2c tracepoints on this tablet, closing then opening:
 *   [0d-0a-10-80-13-...]   bit 7 set   -> closed
 *   [0d-0a-10-00-13-...]   bit 7 clear -> open
 * The controller volunteers these with no survey mode asked for, so all that
 * was missing is reading them: the frame is not a pen report, so it used to be
 * dropped with everything else that is not.
 */
#define WACOM_PACKET_NOTI		0x0d
#define WACOM_NOTI_COVER_DETECT		0x0a
#define WACOM_COVER_CLOSED		BIT(7)

enum samsung_wacom_charge_state {
	WACOM_CHARGE_OFF = 0,
	WACOM_CHARGE_START,
	WACOM_CHARGE_TRANSIT,
	WACOM_CHARGE_RESET,
	WACOM_CHARGE_AFTER_START,
	WACOM_CHARGE_AFTER_RESET,
	WACOM_CHARGE_ON_KEEP_1,
	WACOM_CHARGE_OFF_KEEP_1,
	WACOM_CHARGE_ON_KEEP_2,
	WACOM_CHARGE_OFF_KEEP_2,
	WACOM_CHARGE_FULL,
};

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
	struct gpio_desc *pdct;
	struct power_supply *pen_supply;
	struct delayed_work charge_work;
	struct mutex command_lock;
	struct mutex option_lock;
	struct touchscreen_properties props;
	/* Guards in_range and out_of_range against the proximity timer. */
	spinlock_t lock;
	struct timer_list prox_timer;
	bool in_range;
	bool docked;
	bool cover_closed;
	bool disable_when_docked;
	bool pen_irq_disabled;
	u8 garage_direction;
	u8 charge_stage;
	int charge_status;
	unsigned int out_of_range;
};

static atomic_t samsung_wacom_pen_proximity = ATOMIC_INIT(0);
static atomic_t samsung_wacom_touch_suppression = ATOMIC_INIT(1);

bool samsung_wacom_should_suppress_touch(void)
{
	return atomic_read(&samsung_wacom_touch_suppression) &&
	       atomic_read(&samsung_wacom_pen_proximity);
}
EXPORT_SYMBOL_GPL(samsung_wacom_should_suppress_touch);

static enum power_supply_property samsung_wacom_pen_properties[] = {
	POWER_SUPPLY_PROP_STATUS,
	POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_CAPACITY,
	POWER_SUPPLY_PROP_SCOPE,
	POWER_SUPPLY_PROP_MODEL_NAME,
};

static int samsung_wacom_pen_get_property(struct power_supply *psy,
					  enum power_supply_property property,
					  union power_supply_propval *value)
{
	struct samsung_wacom *wacom = power_supply_get_drvdata(psy);

	switch (property) {
	case POWER_SUPPLY_PROP_STATUS:
		value->intval = wacom->charge_status;
		return 0;
	case POWER_SUPPLY_PROP_PRESENT:
		value->intval = wacom->docked;
		return 0;
	case POWER_SUPPLY_PROP_CAPACITY:
		if (wacom->charge_status != POWER_SUPPLY_STATUS_FULL)
			return -ENODATA;
		value->intval = 100;
		return 0;
	case POWER_SUPPLY_PROP_SCOPE:
		value->intval = POWER_SUPPLY_SCOPE_DEVICE;
		return 0;
	case POWER_SUPPLY_PROP_MODEL_NAME:
		value->strval = "Samsung S Pen";
		return 0;
	default:
		return -EINVAL;
	}
}

static const struct power_supply_desc samsung_wacom_pen_supply = {
	.name = "gts9u-spen",
	.type = POWER_SUPPLY_TYPE_BATTERY,
	.properties = samsung_wacom_pen_properties,
	.num_properties = ARRAY_SIZE(samsung_wacom_pen_properties),
	.get_property = samsung_wacom_pen_get_property,
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

	mutex_lock(&wacom->command_lock);
	ret = i2c_master_send(wacom->client, &cmd, sizeof(cmd));
	mutex_unlock(&wacom->command_lock);
	if (ret != sizeof(cmd))
		dev_dbg(&wacom->client->dev,
			"could not raise the sample rate: %d\n", ret);
}

static int samsung_wacom_charge_status(u8 state)
{
	switch (state) {
	case WACOM_CHARGE_FULL:
		return POWER_SUPPLY_STATUS_FULL;
	case WACOM_CHARGE_START:
	case WACOM_CHARGE_TRANSIT:
	case WACOM_CHARGE_RESET:
	case WACOM_CHARGE_AFTER_START:
	case WACOM_CHARGE_AFTER_RESET:
	case WACOM_CHARGE_ON_KEEP_1:
	case WACOM_CHARGE_ON_KEEP_2:
		return POWER_SUPPLY_STATUS_CHARGING;
	case WACOM_CHARGE_OFF:
	case WACOM_CHARGE_OFF_KEEP_1:
	case WACOM_CHARGE_OFF_KEEP_2:
		return POWER_SUPPLY_STATUS_NOT_CHARGING;
	default:
		return POWER_SUPPLY_STATUS_UNKNOWN;
	}
}

static void samsung_wacom_notify_garage(struct samsung_wacom *wacom)
{
	sysfs_notify(&wacom->client->dev.kobj, NULL, "pen_docked");
	sysfs_notify(&wacom->client->dev.kobj, NULL, "pen_orientation");
	sysfs_notify(&wacom->client->dev.kobj, NULL, "pen_charging");
	if (wacom->pen_supply)
		power_supply_changed(wacom->pen_supply);
}

static bool samsung_wacom_leave_range(struct samsung_wacom *wacom);
static void samsung_wacom_update_digitizer(struct samsung_wacom *wacom);

static int samsung_wacom_send_command(struct samsung_wacom *wacom, u8 cmd)
{
	int ret;

	mutex_lock(&wacom->command_lock);
	ret = i2c_master_send(wacom->client, &cmd, sizeof(cmd));
	mutex_unlock(&wacom->command_lock);

	return ret == sizeof(cmd) ? 0 : (ret < 0 ? ret : -EIO);
}

static void samsung_wacom_charge_work(struct work_struct *work)
{
	struct samsung_wacom *wacom = container_of(to_delayed_work(work),
						    struct samsung_wacom,
						    charge_work);
	int ret;

	if (!READ_ONCE(wacom->docked)) {
		wacom->charge_stage = 0;
		ret = samsung_wacom_send_command(wacom,
					       WACOM_CMD_BLE_CHARGE_KEEP_OFF);
		if (ret)
			dev_dbg(&wacom->client->dev,
				"could not stop S Pen charging: %d\n", ret);
		return;
	}

	if (wacom->charge_stage == 0) {
		ret = samsung_wacom_send_command(wacom,
					       WACOM_CMD_BLE_CHARGE_ENABLE);
		if (!ret) {
			usleep_range(20000, 25000);
			ret = samsung_wacom_send_command(wacom,
						       WACOM_CMD_BLE_CHARGE_START);
		}
		if (ret) {
			dev_warn(&wacom->client->dev,
				 "could not start S Pen charging: %d\n", ret);
			mod_delayed_work(system_wq, &wacom->charge_work,
					 msecs_to_jiffies(WACOM_CHARGE_START_DELAY_MS));
			return;
		}

		wacom->charge_stage = 1;
		WRITE_ONCE(wacom->charge_status, POWER_SUPPLY_STATUS_CHARGING);
		samsung_wacom_notify_garage(wacom);
		dev_info(&wacom->client->dev, "S Pen charging started\n");
		mod_delayed_work(system_wq, &wacom->charge_work,
				 msecs_to_jiffies(WACOM_CHARGE_START_DELAY_MS));
		return;
	}

	if (wacom->charge_stage == 1) {
		ret = samsung_wacom_send_command(wacom,
					       WACOM_CMD_BLE_CHARGE_KEEP_ON);
		if (ret) {
			dev_warn(&wacom->client->dev,
				 "could not keep S Pen charging: %d\n", ret);
			mod_delayed_work(system_wq, &wacom->charge_work,
					 msecs_to_jiffies(WACOM_CHARGE_START_DELAY_MS));
			return;
		}
		wacom->charge_stage = 2;
	}

	ret = samsung_wacom_send_command(wacom, WACOM_CMD_GARAGE_STATUS);
	if (ret)
		dev_warn(&wacom->client->dev,
			 "could not query S Pen orientation/charge: %d\n", ret);
	mod_delayed_work(system_wq, &wacom->charge_work,
			 msecs_to_jiffies(WACOM_CHARGE_STATUS_PERIOD_MS));
}

static bool samsung_wacom_handle_garage_reply(struct samsung_wacom *wacom,
					       const u8 *data)
{
	u8 direction;
	u8 charge_state;

	if ((data[0] & WACOM_PACKET_ID_MASK) != WACOM_PACKET_REPLY ||
	    data[1] != WACOM_REPLY_GARAGE_CHARGE)
		return false;

	charge_state = data[2] & WACOM_PACKET_ID_MASK;
	direction = data[5];
	WRITE_ONCE(wacom->charge_status,
		   samsung_wacom_charge_status(charge_state));
	if (direction == WACOM_GARAGE_DIRECTION_UP ||
	    direction == WACOM_GARAGE_DIRECTION_DOWN)
		WRITE_ONCE(wacom->garage_direction, direction);

	dev_info(&wacom->client->dev,
		 "S Pen garage reply: docked=%u direction=%u charge-state=%u\n",
		 READ_ONCE(wacom->docked), READ_ONCE(wacom->garage_direction),
		 charge_state);
	samsung_wacom_notify_garage(wacom);
	return true;
}

static bool samsung_wacom_handle_cover_noti(struct samsung_wacom *wacom,
					    const u8 *data)
{
	bool closed;

	if ((data[0] & WACOM_PACKET_ID_MASK) != WACOM_PACKET_NOTI ||
	    data[1] != WACOM_NOTI_COVER_DETECT)
		return false;

	closed = data[3] & WACOM_COVER_CLOSED;
	/*
	 * Claim the frame either way: it is a cover notification and never a pen
	 * report, so passing it on would only get it dropped further down.
	 */
	if (closed == READ_ONCE(wacom->cover_closed))
		return true;

	WRITE_ONCE(wacom->cover_closed, closed);
	/*
	 * SW_MACHINE_COVER is what the hardware means and what stock reports.
	 * SW_LID goes out with it because that is the one logind and GNOME act
	 * on, and blanking the screen when the cover shuts is the whole point;
	 * gpio-keys keeps reporting SW_LID for the plain cover, and the two
	 * never contradict each other because each answers a different lid.
	 */
	input_report_switch(wacom->input, SW_MACHINE_COVER, closed);
	input_report_switch(wacom->input, SW_LID, closed);
	input_sync(wacom->input);
	dev_info(&wacom->client->dev, "book cover %s\n",
		 closed ? "closed" : "open");

	return true;
}

static irqreturn_t samsung_wacom_pdct_irq(int irq, void *dev_id)
{
	struct samsung_wacom *wacom = dev_id;
	bool docked = gpiod_get_value_cansleep(wacom->pdct) > 0;

	/* Both edges share the threaded line; ignore duplicate level reports. */
	if (docked == READ_ONCE(wacom->docked))
		return IRQ_HANDLED;

	WRITE_ONCE(wacom->docked, docked);
	wacom->charge_stage = 0;
	/* Never expose the orientation reported for a previous insertion. */
	WRITE_ONCE(wacom->garage_direction, 0);
	if (!docked) {
		WRITE_ONCE(wacom->charge_status,
			   POWER_SUPPLY_STATUS_NOT_CHARGING);
	}

	input_report_switch(wacom->input, SW_PEN_INSERTED, docked);
	input_sync(wacom->input);
	samsung_wacom_update_digitizer(wacom);
	samsung_wacom_notify_garage(wacom);
	dev_info(&wacom->client->dev, "S Pen %s\n",
		 docked ? "docked" : "undocked");

	mod_delayed_work(system_wq, &wacom->charge_work, 0);

	return IRQ_HANDLED;
}

static ssize_t pen_docked_show(struct device *dev,
			       struct device_attribute *attribute, char *buf)
{
	struct samsung_wacom *wacom = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", READ_ONCE(wacom->docked));
}
static DEVICE_ATTR_RO(pen_docked);

static ssize_t pen_orientation_show(struct device *dev,
				    struct device_attribute *attribute,
				    char *buf)
{
	struct samsung_wacom *wacom = dev_get_drvdata(dev);
	const char *orientation = "unknown";

	if (READ_ONCE(wacom->garage_direction) == WACOM_GARAGE_DIRECTION_UP)
		orientation = "upside";
	else if (READ_ONCE(wacom->garage_direction) == WACOM_GARAGE_DIRECTION_DOWN)
		orientation = "downside";

	return sysfs_emit(buf, "%s\n", orientation);
}
static DEVICE_ATTR_RO(pen_orientation);

static ssize_t pen_charging_show(struct device *dev,
				 struct device_attribute *attribute, char *buf)
{
	struct samsung_wacom *wacom = dev_get_drvdata(dev);
	const char *status = "unknown";

	switch (READ_ONCE(wacom->charge_status)) {
	case POWER_SUPPLY_STATUS_CHARGING:
		status = "charging";
		break;
	case POWER_SUPPLY_STATUS_FULL:
		status = "full";
		break;
	case POWER_SUPPLY_STATUS_NOT_CHARGING:
		status = "not-charging";
		break;
	}

	return sysfs_emit(buf, "%s\n", status);
}
static DEVICE_ATTR_RO(pen_charging);

static ssize_t pen_ble_reset_store(struct device *dev,
				   struct device_attribute *attribute,
				   const char *buf, size_t count)
{
	struct samsung_wacom *wacom = dev_get_drvdata(dev);
	bool reset;
	int ret;

	ret = kstrtobool(buf, &reset);
	if (ret)
		return ret;
	if (!reset)
		return -EINVAL;
	if (!READ_ONCE(wacom->docked))
		return -ENODEV;

	/*
	 * This is the command used by Samsung's "Reset S Pen" flow.  Unlike the
	 * normal START pattern, RESET clears the pen's previous BLE bond and makes
	 * it advertise for a new host while it remains on the charging garage.
	 * Keep it explicit: issuing it on every dock would destroy a valid bond.
	 */
	cancel_delayed_work_sync(&wacom->charge_work);
	ret = samsung_wacom_send_command(wacom, WACOM_CMD_BLE_PAIR_RESET);
	if (ret) {
		mod_delayed_work(system_wq, &wacom->charge_work, 0);
		return ret;
	}

	wacom->charge_stage = 1;
	WRITE_ONCE(wacom->charge_status, POWER_SUPPLY_STATUS_CHARGING);
	samsung_wacom_notify_garage(wacom);
	mod_delayed_work(system_wq, &wacom->charge_work,
			 msecs_to_jiffies(WACOM_CHARGE_START_DELAY_MS));
	dev_info(dev, "S Pen BLE pairing reset requested\n");

	return count;
}
static DEVICE_ATTR_WO(pen_ble_reset);

static ssize_t ignore_finger_while_hovering_show(
	struct device *dev, struct device_attribute *attribute, char *buf)
{
	return sysfs_emit(buf, "%u\n",
			  atomic_read(&samsung_wacom_touch_suppression));
}

static ssize_t ignore_finger_while_hovering_store(
	struct device *dev, struct device_attribute *attribute,
	const char *buf, size_t count)
{
	bool enabled;
	int ret;

	ret = kstrtobool(buf, &enabled);
	if (ret)
		return ret;
	atomic_set(&samsung_wacom_touch_suppression, enabled);
	return count;
}
static DEVICE_ATTR_RW(ignore_finger_while_hovering);

static ssize_t disable_digitizer_when_docked_show(
	struct device *dev, struct device_attribute *attribute, char *buf)
{
	struct samsung_wacom *wacom = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", READ_ONCE(wacom->disable_when_docked));
}

static ssize_t disable_digitizer_when_docked_store(
	struct device *dev, struct device_attribute *attribute,
	const char *buf, size_t count)
{
	struct samsung_wacom *wacom = dev_get_drvdata(dev);
	bool enabled;
	int ret;

	ret = kstrtobool(buf, &enabled);
	if (ret)
		return ret;
	WRITE_ONCE(wacom->disable_when_docked, enabled);
	samsung_wacom_update_digitizer(wacom);
	return count;
}
static DEVICE_ATTR_RW(disable_digitizer_when_docked);

static struct attribute *samsung_wacom_attrs[] = {
	&dev_attr_pen_docked.attr,
	&dev_attr_pen_orientation.attr,
	&dev_attr_pen_charging.attr,
	&dev_attr_pen_ble_reset.attr,
	&dev_attr_ignore_finger_while_hovering.attr,
	&dev_attr_disable_digitizer_when_docked.attr,
	NULL,
};

static const struct attribute_group samsung_wacom_group = {
	.attrs = samsung_wacom_attrs,
};

/*
 * Leaving range is synthesised, never announced, so it is emitted from two
 * places -- the frame counter and the silence timer -- and lives here once.
 */
static void samsung_wacom_report_leave(struct samsung_wacom *wacom)
{
	struct input_dev *input = wacom->input;

	input_report_key(input, BTN_TOUCH, 0);
	input_report_key(input, BTN_STYLUS, 0);
	input_report_key(input, BTN_TOOL_PEN, 0);
	input_report_abs(input, ABS_PRESSURE, 0);
	input_sync(input);
}

/* Returns true if this call is the one that took the pen out of range. */
static bool samsung_wacom_leave_range(struct samsung_wacom *wacom)
{
	unsigned long flags;
	bool leaving;

	spin_lock_irqsave(&wacom->lock, flags);
	leaving = wacom->in_range;
	wacom->in_range = false;
	wacom->out_of_range = 0;
	spin_unlock_irqrestore(&wacom->lock, flags);
	atomic_set(&samsung_wacom_pen_proximity, 0);

	if (leaving)
		samsung_wacom_report_leave(wacom);

	return leaving;
}

static void samsung_wacom_update_digitizer(struct samsung_wacom *wacom)
{
	bool disable = READ_ONCE(wacom->disable_when_docked) &&
		       READ_ONCE(wacom->docked);

	mutex_lock(&wacom->option_lock);
	if (disable == wacom->pen_irq_disabled)
		goto out;

	if (disable) {
		wacom->pen_irq_disabled = true;
		timer_delete_sync(&wacom->prox_timer);
		samsung_wacom_leave_range(wacom);
		dev_info(&wacom->client->dev,
			 "digitiser disabled while S Pen is docked\n");
	} else {
		wacom->pen_irq_disabled = false;
		dev_info(&wacom->client->dev, "digitiser enabled\n");
	}
out:
	mutex_unlock(&wacom->option_lock);
}

static void samsung_wacom_prox_timeout(struct timer_list *t)
{
	struct samsung_wacom *wacom = timer_container_of(wacom, t, prox_timer);

	if (samsung_wacom_leave_range(wacom))
		dev_dbg(&wacom->client->dev,
			"no report in %u ms; synthesising proximity out\n",
			WACOM_PROXIMITY_TIMEOUT_MS);
}

static irqreturn_t samsung_wacom_irq(int irq, void *dev_id)
{
	struct samsung_wacom *wacom = dev_id;
	struct input_dev *input = wacom->input;
	u8 data[WACOM_REPORT_SIZE];
	unsigned int pressure;
	unsigned long flags;
	bool in_range, tip, barrel, first;
	unsigned int missed;
	int ret;

	ret = i2c_master_recv(wacom->client, data, sizeof(data));
	if (ret != sizeof(data))
		return IRQ_HANDLED;
	if (samsung_wacom_handle_garage_reply(wacom, data))
		return IRQ_HANDLED;
	/*
	 * Ahead of the docked check on purpose: the pen normally lives in its
	 * silo, and that is exactly when pen reporting is suppressed, so a cover
	 * notification tested any later would be thrown away in the common case.
	 */
	if (samsung_wacom_handle_cover_noti(wacom, data))
		return IRQ_HANDLED;
	/*
	 * Garage replies share this IRQ with coordinate packets.  Keep the line
	 * enabled while docked and suppress only pen coordinates, otherwise a
	 * fresh orientation/charge reply cannot be received after insertion.
	 */
	if (READ_ONCE(wacom->pen_irq_disabled))
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
		spin_lock_irqsave(&wacom->lock, flags);
		missed = wacom->in_range ? ++wacom->out_of_range : 0;
		spin_unlock_irqrestore(&wacom->lock, flags);

		if (missed >= WACOM_OUT_OF_RANGE_FRAMES) {
			timer_delete(&wacom->prox_timer);
			samsung_wacom_leave_range(wacom);
		}
		return IRQ_HANDLED;
	}

	/*
	 * A frame arrived, so the pen is here: push the silence deadline out
	 * again.  Doing it on every frame rather than on the transition is what
	 * makes the timer measure silence instead of dwell time.
	 */
	mod_timer(&wacom->prox_timer,
		  jiffies + msecs_to_jiffies(WACOM_PROXIMITY_TIMEOUT_MS));

	spin_lock_irqsave(&wacom->lock, flags);
	first = !wacom->in_range;
	wacom->in_range = true;
	wacom->out_of_range = 0;
	spin_unlock_irqrestore(&wacom->lock, flags);
	atomic_set(&samsung_wacom_pen_proximity, 1);

	if (first) {
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

static void samsung_wacom_stop_timer(void *data)
{
	struct samsung_wacom *wacom = data;

	timer_shutdown_sync(&wacom->prox_timer);
}

static void samsung_wacom_cancel_charge_work(void *data)
{
	struct samsung_wacom *wacom = data;

	cancel_delayed_work_sync(&wacom->charge_work);
}

static int samsung_wacom_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct samsung_wacom_features features;
	struct power_supply_config supply_config = {};
	struct samsung_wacom *wacom;
	struct input_dev *input;
	int pdct_irq;
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
		/*
		 * The panel is another consumer of this rail and can finish its own
		 * startup after the Wacom I2C device is first enumerated.  A hard
		 * timeout left the digitiser permanently unbound for that boot.  Put
		 * it on the deferred-probe list so the core retries once the remaining
		 * display suppliers have settled.
		 */
		return dev_err_probe(dev, -EPROBE_DEFER,
				     "digitiser is not powered yet (%d after %d tries)\n",
				     error, WACOM_QUERY_TRIES);

	wacom = devm_kzalloc(dev, sizeof(*wacom), GFP_KERNEL);
	if (!wacom)
		return -ENOMEM;

	input = devm_input_allocate_device(dev);
	if (!input)
		return -ENOMEM;

	wacom->client = client;
	wacom->input = input;
	wacom->pdct = devm_gpiod_get(dev, "pdct", GPIOD_IN);
	if (IS_ERR(wacom->pdct))
		return dev_err_probe(dev, PTR_ERR(wacom->pdct),
				     "cannot claim S Pen dock detect\n");
	wacom->docked = gpiod_get_value_cansleep(wacom->pdct) > 0;
	wacom->charge_status = POWER_SUPPLY_STATUS_UNKNOWN;
	mutex_init(&wacom->command_lock);
	mutex_init(&wacom->option_lock);
	INIT_DELAYED_WORK(&wacom->charge_work, samsung_wacom_charge_work);
	spin_lock_init(&wacom->lock);
	timer_setup(&wacom->prox_timer, samsung_wacom_prox_timeout, 0);
	i2c_set_clientdata(client, wacom);

	/*
	 * Registered before the interrupt so that teardown runs the other way
	 * round: the handler that arms the timer goes first, then the timer.
	 */
	error = devm_add_action_or_reset(dev, samsung_wacom_stop_timer, wacom);
	if (error)
		return error;
	error = devm_add_action_or_reset(dev, samsung_wacom_cancel_charge_work,
					 wacom);
	if (error)
		return error;

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
	input_set_capability(input, EV_SW, SW_PEN_INSERTED);
	input_set_capability(input, EV_SW, SW_MACHINE_COVER);
	input_set_capability(input, EV_SW, SW_LID);
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

	input_report_switch(input, SW_PEN_INSERTED, wacom->docked);
	input_sync(input);

	pdct_irq = gpiod_to_irq(wacom->pdct);
	if (pdct_irq < 0)
		return dev_err_probe(dev, pdct_irq,
				     "cannot map S Pen dock interrupt\n");
	error = devm_request_threaded_irq(dev, pdct_irq, NULL,
					  samsung_wacom_pdct_irq,
					  IRQF_ONESHOT | IRQF_TRIGGER_RISING |
					  IRQF_TRIGGER_FALLING,
					  "gts9u-spen-dock", wacom);
	if (error)
		return dev_err_probe(dev, error,
				     "cannot claim S Pen dock interrupt\n");

	supply_config.drv_data = wacom;
	supply_config.fwnode = dev_fwnode(dev);
	wacom->pen_supply = devm_power_supply_register(dev,
						       &samsung_wacom_pen_supply,
						       &supply_config);
	if (IS_ERR(wacom->pen_supply))
		return dev_err_probe(dev, PTR_ERR(wacom->pen_supply),
				     "cannot register S Pen power supply\n");

	error = devm_device_add_group(dev, &samsung_wacom_group);
	if (error)
		return dev_err_probe(dev, error,
				     "cannot expose S Pen dock state\n");

	samsung_wacom_set_max_rate(wacom);
	if (wacom->docked)
		mod_delayed_work(system_wq, &wacom->charge_work, 0);

	dev_info(dev,
		 "Wacom EMR digitiser: %u x %u, pressure %u, tilt +/-%u/%u, module %u, docked=%u\n",
		 features.x_max, features.y_max, features.pressure_max,
		 features.tilt_x_max, features.tilt_y_max, features.module_ver,
		 wacom->docked);

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
