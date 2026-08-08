// SPDX-License-Identifier: GPL-2.0-only
/*
 * Silicon Mitus SM5440 2:1 direct charger for the Samsung SM-X910.
 *
 * This is a deliberately small mainline-first driver.  Linux TCPM owns USB-PD
 * policy; this driver only requests a conservative PPS operating point, hands
 * the battery path over from SM5714, and programs the board's charge pump using
 * the register sequence published in Samsung's GPL source.  Every failure
 * turns the pump off and restores the fixed-PD switching charger.
 */

#include <linux/bitops.h>
#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/power_supply.h>
#include <linux/workqueue.h>

#define SM5440_REG_STATUS1		0x08
#define SM5440_REG_STATUS3		0x0a
#define  SM5440_STATUS3_VBUSPOK		BIT(5)
#define SM5440_REG_CNTL1		0x0c
#define  SM5440_CNTL1_SW_RESET		BIT(0)
#define  SM5440_CNTL1_WDT_EN		BIT(7)
#define  SM5440_CNTL1_WDT_30S		(4 << 4)
#define SM5440_REG_CNTL2		0x0d
#define SM5440_REG_CNTL3		0x0e
#define SM5440_REG_CNTL4		0x0f
#define SM5440_REG_CNTL5		0x10
#define  SM5440_CNTL5_OP_MODE_MASK	GENMASK(3, 2)
#define  SM5440_CNTL5_CHG_ON		BIT(2)
#define SM5440_REG_CNTL6		0x11
#define SM5440_REG_CNTL7		0x12
#define SM5440_REG_VBUSCNTL		0x13
#define SM5440_REG_VBATCNTL		0x14
#define SM5440_REG_VOUTCNTL		0x15
#define SM5440_REG_IBUSCNTL		0x16
#define SM5440_REG_PRTNCNTL		0x19
#define SM5440_REG_THEMCNTL1		0x1a
#define SM5440_REG_ADCCNTL1		0x1c
#define  SM5440_ADCCNTL1_AVG_32		BIT(3)
#define  SM5440_ADCCNTL1_CONTINUOUS	BIT(1)
#define  SM5440_ADCCNTL1_ENABLE	BIT(0)
#define SM5440_REG_ADCCNTL2		0x1d
#define SM5440_REG_ADC_VBUS1		0x1e
#define SM5440_REG_ADC_IBUS1		0x22
#define SM5440_REG_ADC_DIETEMP		0x26
#define SM5440_REG_ADC_VBAT1		0x27
#define SM5440_REG_DEVICEID		0x2b

#define SM5440_POLL_MS			1000
#define SM5440_RETRY_MS			30000
#define SM5440_INITIAL_IBUS_MA		3000

/*
 * What the loop aims for at the pump's input; the pack gets about twice this.
 * The chip's own limit above is the hard ceiling and stays well clear of it.
 */
/*
 * 2200 mA in, about 4.4 A to the pack, is what has been measured stable: 18.8 W
 * at 28 % charge with no dropout, and 16.7 W still at 81 %, where a pack this
 * full would normally have tapered away.
 *
 * 3200 was tried and the bus collapsed to 4888 mV within 36 s, latching
 * VBUSUVLO and REVBLK and taking the PD contract down to a 5 V DCP fallback.
 * That is *not* established as a hard limit, and the value here is
 * conservatism rather than a measured ceiling.  Two things were wrong with the
 * test: the adapter had latched a protection that only a mains unplug cleared,
 * and iio-sensor-proxy was busy-looping on a full core, which both heats the
 * board and steals current that never reaches the pack.  With those cleared
 * the gap between the requested and the measured input fell from about 900 mV
 * at 1.3 A to about 230 mV at 2.4 A, so the series resistance that seemed to
 * cap everything was mostly an artefact of the degraded state.
 *
 * Re-testing higher is worthwhile, but only from a low pack, on a freshly
 * power-cycled adapter, with nothing pinning a core.
 */
#define SM5440_TARGET_IBUS_MA		2200
#define SM5440_IBUS_TOLERANCE_MA	150

/*
 * Finding the real ceiling means changing this and measuring, and with the
 * value baked in that is a kernel rebuild and a partition flash per step --
 * forty minutes for one data point, on a pack that is charging the whole time,
 * so the conditions have moved by the time the next step is ready.
 *
 * Expose it instead:
 *
 *	/sys/module/sm5440_direct/parameters/target_ibus_ma
 *
 * The bounds below are sanity, not policy.  Nothing here relaxes a guard: the
 * loop still refuses to ask for less than twice the pack, still stops at
 * 10.5 V, and still hands back to the switching charger on VBUSPOK, die
 * temperature, pack temperature or capacity.  Raising this only changes what
 * the loop aims for; whether the bus can deliver it is still measured.
 */
#define SM5440_TARGET_IBUS_MIN_MA	800
#define SM5440_TARGET_IBUS_MAX_MA	4000

static unsigned int target_ibus_ma = SM5440_TARGET_IBUS_MA;
module_param(target_ibus_ma, uint, 0644);
MODULE_PARM_DESC(target_ibus_ma,
		 "pump input current the PPS loop aims for, in mA (default 2200; the pack gets about twice this)");

static int sm5440_target_ibus(void)
{
	return clamp_t(int, target_ibus_ma, SM5440_TARGET_IBUS_MIN_MA,
		       SM5440_TARGET_IBUS_MAX_MA);
}

/*
 * One PPS step is 20 mV.  Two per second, so a full swing across the useful
 * range takes a few seconds: fast enough to follow a pack that is charging,
 * slow enough not to chase the ADC's own noise.
 */
#define SM5440_VSTEP_MV			40

/*
 * How far above twice the pack the loop may push.  A switched-capacitor
 * converter behaves like a resistor -- measured here at a very consistent
 * 0.17 ohm across four operating points -- so this bounds the current as well
 * as the ratio: 2000 mV of headroom is about 11 A, far past anything the
 * thermal limits would allow to persist.
 */
#define SM5440_MAX_HEADROOM_MV		2000
#define SM5440_INITIAL_PPS_MA		3000

/*
 * The operating current asked for in the PPS Request, and the real ceiling on
 * this board.  It was 3000, and that was the whole limit: the pump settled at
 * 2895 mA and stayed there whatever the regulation loop aimed for, because the
 * adapter was in current limit and pushing the voltage from there only made it
 * fold back.  The loop's own floor is about 700 mV above twice the pack, which
 * at the measured 0.17 ohm is around 4.1 A, so the driver already wanted more
 * than it was asking for.  TCPM adds no limit of its own -- it clamps the
 * request to what the source advertises, and this one advertises 5 A.
 *
 * Swept on the hardware at 41-44 % charge, 20 s per step, EP-T4510 and its
 * own cable:
 *
 *	contract  pack     ibus      vbus      die
 *	3000 mA   21.4 W   2601 mA   8556 mV   45.5 C
 *	3200 mA   22.8 W   2864 mA   8611 mV   46.5 C
 *	3400 mA   25.0 W   2960 mA   8652 mV   48.5 C
 *	3600 mA   24.2 W   3141 mA   8801 mV   54.0 C
 *	3800 mA   24.2 W   3128 mA   8780 mV   55.0 C
 *	4000 mA   24.2 W   3167 mA   8835 mV   55.0 C
 *
 * Above 3400 the input current still rises and the power delivered does not:
 * that is loss in the pump, and it shows up as six degrees of die temperature
 * bought for nothing.  3400 held 25.2-25.5 W for five minutes with the die
 * flat at 49.5 C and the pack at 36.4 C.
 *
 * At that setting the measured input current sits right around 3 A
 * (2950-3080), which is where an unmarked USB-C cable's rating ends.  It is
 * not beyond it, and the adapter this was measured with ships a 5 A cable, but
 * anyone reaching for more should note that the connector, not the silicon, is
 * what the next step puts at risk.  Hence the knob stays:
 *
 *	/sys/module/sm5440_direct/parameters/pps_op_curr_ma
 */
#define SM5440_PPS_OP_CURR_DEFAULT_MA	3400
#define SM5440_PPS_OP_CURR_MIN_MA	1000
#define SM5440_PPS_OP_CURR_MAX_MA	5000

static unsigned int pps_op_curr_ma = SM5440_PPS_OP_CURR_DEFAULT_MA;
module_param(pps_op_curr_ma, uint, 0644);
MODULE_PARM_DESC(pps_op_curr_ma,
		 "operating current requested in the PPS contract, in mA (default 3400, the measured optimum; only raise it with a cable rated for more)");

static int sm5440_pps_op_curr(void)
{
	return clamp_t(int, pps_op_curr_ma, SM5440_PPS_OP_CURR_MIN_MA,
		       SM5440_PPS_OP_CURR_MAX_MA);
}

/*
 * What to ask for in the Request, at a given bus voltage.  The knob decides,
 * but never below the current the 15 W floor needs at that voltage, rounded to
 * the 50 mA the PPS message can express.
 */
static int sm5440_request_ma(int target_mv)
{
	int floor_ma = DIV_ROUND_UP(DIV_ROUND_UP(15000000, target_mv), 50) * 50;

	return max(sm5440_pps_op_curr(), floor_ma);
}
/*
 * Headroom above twice the pack, and it has to survive the cable.  At 1.8 A the
 * adapter and lead give up about 400 mV, so a nominal 700 left roughly 290 mV
 * at the chip -- measured vbus 8291-8332 mV against a 4003 mV pack -- and any
 * further dip reversed the current and latched REVBLK, which is INT3 bit 1 and
 * exactly what the chip reported when it shut down.
 *
 * Raising the current is what exposed this: at 1 A the same nominal headroom
 * was ample, because the drop was half.
 */
#define SM5440_INITIAL_HEADROOM_MV	1100
#define SM5440_VBATREG_MV		4400
#define SM5440_FREQUENCY_KHZ		450

int sm5714_battery_set_direct_charge(bool active);

struct sm5440_direct {
	struct device *dev;
	struct i2c_client *client;
	struct power_supply *tcpm;
	struct power_supply *battery;
	struct delayed_work work;
	int target_mv;
	int target_ma;
	unsigned int pps_ticks;
	bool active;
};

static int sm5440_update_bits(struct sm5440_direct *sm, u8 reg, u8 mask,
			      u8 val)
{
	int old;

	old = i2c_smbus_read_byte_data(sm->client, reg);
	if (old < 0)
		return old;

	return i2c_smbus_write_byte_data(sm->client, reg,
					 (old & ~mask) | (val & mask));
}

static int sm5440_read_adc_pair(struct sm5440_direct *sm, u8 reg)
{
	int high, low;

	high = i2c_smbus_read_byte_data(sm->client, reg);
	if (high < 0)
		return high;
	low = i2c_smbus_read_byte_data(sm->client, reg + 1);
	if (low < 0)
		return low;

	return (high << 5) | (low >> 3);
}

static int sm5440_adc_vbus_mv(struct sm5440_direct *sm)
{
	int raw = sm5440_read_adc_pair(sm, SM5440_REG_ADC_VBUS1);

	return raw < 0 ? raw : 4096 + raw;
}

static int sm5440_adc_ibus_ma(struct sm5440_direct *sm)
{
	int raw = sm5440_read_adc_pair(sm, SM5440_REG_ADC_IBUS1);

	return raw < 0 ? raw : (raw * 625) / 1000;
}

static int sm5440_adc_vbat_mv(struct sm5440_direct *sm)
{
	int raw = sm5440_read_adc_pair(sm, SM5440_REG_ADC_VBAT1);

	return raw < 0 ? raw : 2048 + (raw * 500) / 1000;
}

static int sm5440_adc_die_temp(struct sm5440_direct *sm)
{
	int raw = i2c_smbus_read_byte_data(sm->client,
					   SM5440_REG_ADC_DIETEMP);

	return raw < 0 ? raw : 225 + raw * 5;
}

static int sm5440_psy_get(struct power_supply *psy,
			  enum power_supply_property prop)
{
	union power_supply_propval val;
	int ret;

	ret = power_supply_get_property(psy, prop, &val);
	return ret ? ret : val.intval;
}

static int sm5440_psy_set(struct power_supply *psy,
			  enum power_supply_property prop, int value)
{
	union power_supply_propval val = { .intval = value };

	return power_supply_set_property(psy, prop, &val);
}

static int sm5440_request_pps(struct sm5440_direct *sm, int mv, int ma)
{
	int ret;

	ret = sm5440_psy_set(sm->tcpm, POWER_SUPPLY_PROP_ONLINE, 2);
	if (ret)
		return ret;
	ret = sm5440_psy_set(sm->tcpm, POWER_SUPPLY_PROP_CURRENT_NOW,
			      ma * 1000);
	if (ret)
		goto fixed;
	ret = sm5440_psy_set(sm->tcpm, POWER_SUPPLY_PROP_VOLTAGE_NOW,
			      mv * 1000);
	if (!ret)
		return 0;

fixed:
	sm5440_psy_set(sm->tcpm, POWER_SUPPLY_PROP_ONLINE, 1);
	return ret;
}

static int sm5440_refresh_pps(struct sm5440_direct *sm)
{
	int ret;

	ret = sm5440_psy_set(sm->tcpm, POWER_SUPPLY_PROP_CURRENT_NOW,
			     sm->target_ma * 1000);
	if (ret)
		return ret;

	return sm5440_psy_set(sm->tcpm, POWER_SUPPLY_PROP_VOLTAGE_NOW,
			      sm->target_mv * 1000);
}

static void sm5440_restore_switching(struct sm5440_direct *sm)
{
	sm5440_update_bits(sm, SM5440_REG_CNTL5,
			   SM5440_CNTL5_OP_MODE_MASK, 0);
	sm5440_update_bits(sm, SM5440_REG_ADCCNTL1,
			   SM5440_ADCCNTL1_ENABLE, 0);
	sm5440_update_bits(sm, SM5440_REG_CNTL1,
			   SM5440_CNTL1_WDT_EN, 0);
	sm5440_psy_set(sm->tcpm, POWER_SUPPLY_PROP_ONLINE, 1);
	sm5714_battery_set_direct_charge(false);
	sm->pps_ticks = 0;
	sm->active = false;
}

static void sm5440_put_power_supply(void *data)
{
	power_supply_put(data);
}

static int sm5440_hw_init(struct sm5440_direct *sm)
{
	int reg;
	int ret;
	int i;

	ret = i2c_smbus_write_byte_data(sm->client, SM5440_REG_CNTL1,
					 SM5440_CNTL1_SW_RESET);
	if (ret)
		return ret;
	for (i = 0; i < 255; i++) {
		usleep_range(1000, 2000);
		reg = i2c_smbus_read_byte_data(sm->client, SM5440_REG_CNTL1);
		if (reg < 0)
			return reg;
		if (!(reg & SM5440_CNTL1_SW_RESET))
			break;
	}
	if (i == 255)
		return -ETIMEDOUT;

#define SM5440_WRITE(_reg, _val) do {					\
	ret = i2c_smbus_write_byte_data(sm->client, (_reg), (_val));	\
	if (ret)							\
		return ret;						\
} while (0)

	SM5440_WRITE(SM5440_REG_CNTL1, SM5440_CNTL1_WDT_30S);
	SM5440_WRITE(SM5440_REG_CNTL2, 0xf2);
	SM5440_WRITE(SM5440_REG_CNTL3, 0xb8);
	SM5440_WRITE(SM5440_REG_CNTL4, 0xff);
	SM5440_WRITE(SM5440_REG_CNTL6, 0x09);
	SM5440_WRITE(SM5440_REG_CNTL7,
		     (SM5440_FREQUENCY_KHZ - 250) / 50);
	SM5440_WRITE(SM5440_REG_VBUSCNTL, 0x07);
	SM5440_WRITE(SM5440_REG_VBATCNTL,
		     ((SM5440_VBATREG_MV - 3800) * 10) / 125);
	SM5440_WRITE(SM5440_REG_VOUTCNTL, 0x3f);
	SM5440_WRITE(SM5440_REG_IBUSCNTL, SM5440_INITIAL_IBUS_MA / 50);
	SM5440_WRITE(SM5440_REG_PRTNCNTL, 0xfe);
	SM5440_WRITE(SM5440_REG_THEMCNTL1, 0x0c);
	SM5440_WRITE(SM5440_REG_ADCCNTL1,
		     SM5440_ADCCNTL1_AVG_32 |
		     SM5440_ADCCNTL1_CONTINUOUS |
		     SM5440_ADCCNTL1_ENABLE);
	SM5440_WRITE(SM5440_REG_ADCCNTL2, 0xdf);
#undef SM5440_WRITE

	/* Reading the four interrupt latches clears stale bootloader events. */
	for (i = 0; i < 4; i++) {
		ret = i2c_smbus_read_byte_data(sm->client, i);
		if (ret < 0)
			return ret;
	}

	return 0;
}

/*
 * The input a 2:1 pump needs is twice the pack plus enough to cover the drop
 * across cable and switches.  Both numbers move while charging, which is why
 * this is computed rather than remembered.
 */
static int sm5440_target_mv(int battery_uv)
{
	int mv = DIV_ROUND_UP((battery_uv / 1000) * 2 +
			      SM5440_INITIAL_HEADROOM_MV, 20) * 20;

	return clamp(mv, 8200, 10500);
}

static int sm5440_start(struct sm5440_direct *sm)
{
	int battery_uv, target_mv, target_ma;
	int vbus_mv;
	int status3;
	int ret;
	int i;

	battery_uv = sm5440_psy_get(sm->battery,
				    POWER_SUPPLY_PROP_VOLTAGE_NOW);
	if (battery_uv < 0)
		return battery_uv;

	target_mv = sm5440_target_mv(battery_uv);
	target_ma = sm5440_request_ma(target_mv);

	/*
	 * Open the SM5714 switching path while VBUS is still at its safe fixed
	 * 9 V contract.  Only then may the direct charger request >9 V PPS.
	 */
	ret = sm5714_battery_set_direct_charge(true);
	if (ret)
		return ret;

	ret = sm5440_hw_init(sm);
	if (ret)
		goto restore;

	ret = sm5440_request_pps(sm, target_mv, target_ma);
	if (ret)
		goto restore;

	/*
	 * A PPS power_supply write completes before the adapter has necessarily
	 * reached the requested voltage.  Starting the 2:1 pump during that ramp
	 * loaded the still-9-V bus, made it collapse and latched REVBLK.  Let the
	 * SM5440 ADC prove that the physical bus is ready before enabling CHG_ON.
	 */
	for (i = 0; i < 30; i++) {
		msleep(100);
		vbus_mv = sm5440_adc_vbus_mv(sm);
		if (vbus_mv < 0) {
			ret = vbus_mv;
			goto restore;
		}
		if (vbus_mv >= target_mv - 500)
			break;
	}
	if (i == 30) {
		dev_warn(sm->dev,
			 "PPS bus did not settle: target=%dmV measured=%dmV\n",
			 target_mv, vbus_mv);
		ret = -ETIMEDOUT;
		goto restore;
	}

	ret = sm5440_update_bits(sm, SM5440_REG_CNTL5,
				 SM5440_CNTL5_OP_MODE_MASK,
				 SM5440_CNTL5_CHG_ON);
	if (ret)
		goto restore;
	ret = sm5440_update_bits(sm, SM5440_REG_CNTL1,
				 SM5440_CNTL1_WDT_EN,
				 SM5440_CNTL1_WDT_EN);
	if (ret)
		goto restore;

	msleep(100);
	status3 = i2c_smbus_read_byte_data(sm->client, SM5440_REG_STATUS3);
	if (status3 < 0) {
		ret = status3;
		goto restore;
	}
	if (!(status3 & SM5440_STATUS3_VBUSPOK)) {
		ret = -ENOLINK;
		goto restore;
	}

	sm->active = true;
	sm->target_mv = target_mv;
	sm->target_ma = target_ma;
	sm->pps_ticks = 0;
	dev_info(sm->dev, "direct charge started: PPS %d mV/%d mA\n",
		 target_mv, target_ma);
	return 0;

restore:
	sm5440_restore_switching(sm);
	return ret;
}

static bool sm5440_eligible(struct sm5440_direct *sm)
{
	int capacity, online, temp, voltage;

	online = sm5440_psy_get(sm->tcpm, POWER_SUPPLY_PROP_ONLINE);
	capacity = sm5440_psy_get(sm->battery, POWER_SUPPLY_PROP_CAPACITY);
	temp = sm5440_psy_get(sm->battery, POWER_SUPPLY_PROP_TEMP);
	voltage = sm5440_psy_get(sm->battery, POWER_SUPPLY_PROP_VOLTAGE_NOW);

	return online > 0 && capacity >= 5 && capacity < 90 &&
	       temp >= 100 && temp < 420 &&
	       voltage >= 3500000 && voltage < 4350000;
}

static void sm5440_work(struct work_struct *work)
{
	struct sm5440_direct *sm =
		container_of(to_delayed_work(work), struct sm5440_direct, work);
	unsigned long delay = msecs_to_jiffies(SM5440_POLL_MS);
	int capacity, die_temp, ibus, op_mode, pack_temp, status3;
	int vbat, vbus;
	int ret;

	if (!sm->active) {
		if (!sm5440_eligible(sm)) {
			delay = msecs_to_jiffies(SM5440_RETRY_MS);
			goto out;
		}
		ret = sm5440_start(sm);
		if (ret) {
			dev_warn(sm->dev, "direct-charge start failed: %d\n", ret);
			delay = msecs_to_jiffies(SM5440_RETRY_MS);
		}
		goto out;
	}

	/*
	 * PPS sources leave the programmable contract unless the sink refreshes
	 * its Request periodically. Samsung's downstream loop does this every
	 * 2.5 seconds; without it the EP-T4510 fell back after about five
	 * seconds and the resulting VBUS step tripped REVBLK.
	 */
	if (++sm->pps_ticks >= 2) {
		int want;

		sm->pps_ticks = 0;

		/*
		 * Re-aim at the pack before each refresh.  Sending the voltage
		 * chosen at start over and over is what made the current decay:
		 * the pack rises as it charges, the headroom above twice it
		 * shrinks, and the pump eventually cannot hold the ratio and
		 * drops out.  Measured on the way down: 1047 mA, 995, 1050, 775,
		 * then CHG_ON clear with the bus at 8334 mV against a 3840 mV
		 * pack.  Twenty millivolts is the adapter's own step size, so
		 * anything smaller would be asking for a change it cannot make.
		 */
		want = sm5440_psy_get(sm->battery, POWER_SUPPLY_PROP_VOLTAGE_NOW);
		if (want > 0) {
			int floor_mv = sm5440_target_mv(want);
			int ceil_mv = min((want / 1000) * 2 +
					  SM5440_MAX_HEADROOM_MV, 10500);
			int measured = sm5440_adc_ibus_ma(sm);

			/*
			 * Aim at the current, not the voltage.  The chip's VBUS ADC
			 * disagrees with what the adapter says it is producing by
			 * hundreds of millivolts, and the gap grows as the current
			 * falls, so it is not a cable drop and cannot be corrected
			 * with a constant.  The current reading needs no such trust:
			 * push the voltage until the current arrives.
			 */
			if (measured >= 0) {
				int target = sm5440_target_ibus();

				if (measured < target - SM5440_IBUS_TOLERANCE_MA)
					sm->target_mv += SM5440_VSTEP_MV;
				else if (measured > target +
						SM5440_IBUS_TOLERANCE_MA)
					sm->target_mv -= SM5440_VSTEP_MV;
			}

			/*
			 * The floor still tracks the pack: never ask for less than
			 * twice it plus the headroom that keeps REVBLK away, however
			 * little current the loop thinks it needs.
			 */
			sm->target_mv = clamp(sm->target_mv, floor_mv, ceil_mv);

			/*
			 * The Request carries the operating current too, and
			 * this is the only place it is re-sent.  Recomputing it
			 * here is what lets the knob take effect on a live
			 * session instead of only at the next start.
			 */
			sm->target_ma = sm5440_request_ma(sm->target_mv);
		}

		ret = sm5440_refresh_pps(sm);
		if (ret) {
			dev_warn(sm->dev, "failed to refresh PPS: %d\n", ret);
			sm5440_restore_switching(sm);
			delay = msecs_to_jiffies(SM5440_RETRY_MS);
			goto out;
		}
	}

	capacity = sm5440_psy_get(sm->battery, POWER_SUPPLY_PROP_CAPACITY);
	pack_temp = sm5440_psy_get(sm->battery, POWER_SUPPLY_PROP_TEMP);
	op_mode = i2c_smbus_read_byte_data(sm->client, SM5440_REG_CNTL5);
	status3 = i2c_smbus_read_byte_data(sm->client, SM5440_REG_STATUS3);
	vbus = sm5440_adc_vbus_mv(sm);
	ibus = sm5440_adc_ibus_ma(sm);
	vbat = sm5440_adc_vbat_mv(sm);
	die_temp = sm5440_adc_die_temp(sm);

	if (capacity < 0 || pack_temp < 0 || op_mode < 0 || status3 < 0 ||
	    vbus < 0 || ibus < 0 || vbat < 0 || die_temp < 0 ||
	    capacity >= 90 || pack_temp >= 450 ||
	    !(op_mode & SM5440_CNTL5_CHG_ON) ||
	    !(status3 & SM5440_STATUS3_VBUSPOK) ||
	    vbus > 10800 || vbat > 4450 || die_temp >= 1100) {
		/*
		 * The part clears CHG_ON on its own and the reason is latched in
		 * the interrupt registers, which until now were only read once at
		 * init.  Two stops with opposite electrics -- one at 1085 mA and
		 * one at zero -- are not going to be told apart by guessing, so
		 * read the latches here and say what the hardware complained
		 * about.  They clear on read, which is why this happens once, at
		 * the point of failure.
		 */
		int int1, int2, int3, int4, status1;

		int1 = i2c_smbus_read_byte_data(sm->client, 0x00);
		int2 = i2c_smbus_read_byte_data(sm->client, 0x01);
		int3 = i2c_smbus_read_byte_data(sm->client, 0x02);
		int4 = i2c_smbus_read_byte_data(sm->client, 0x03);
		status1 = i2c_smbus_read_byte_data(sm->client, SM5440_REG_STATUS1);

		dev_warn(sm->dev,
			 "stopping direct charge: cap=%d temp=%d mode=%#x "
			 "st1=%#x st3=%#x int=%#x/%#x/%#x/%#x "
			 "vbus=%d ibus=%d vbat=%d die=%d\n",
			 capacity, pack_temp, op_mode, status1, status3,
			 int1, int2, int3, int4,
			 vbus, ibus, vbat, die_temp);
		sm5440_restore_switching(sm);
		delay = msecs_to_jiffies(SM5440_RETRY_MS);
		goto out;
	}

	/* Rewriting CNTL1 services the hardware watchdog. */
	ret = sm5440_update_bits(sm, SM5440_REG_CNTL1,
				 SM5440_CNTL1_WDT_EN,
				 SM5440_CNTL1_WDT_EN);
	if (ret) {
		sm5440_restore_switching(sm);
		delay = msecs_to_jiffies(SM5440_RETRY_MS);
		goto out;
	}

	dev_info_ratelimited(sm->dev,
			     "direct: pack=%d.%dC vbus=%dmV ibus=%dmA "
			     "vbat=%dmV die=%d.%dC\n",
			     pack_temp / 10, abs(pack_temp % 10),
			     vbus, ibus, vbat,
			     die_temp / 10, abs(die_temp % 10));
out:
	schedule_delayed_work(&sm->work, delay);
}

static void sm5440_cancel_work(void *data)
{
	struct sm5440_direct *sm = data;

	cancel_delayed_work_sync(&sm->work);
	if (sm->active)
		sm5440_restore_switching(sm);
}

static int sm5440_probe(struct i2c_client *client)
{
	struct sm5440_direct *sm;
	int id;
	int ret;

	if (!i2c_check_functionality(client->adapter,
				     I2C_FUNC_SMBUS_BYTE_DATA))
		return -EOPNOTSUPP;

	sm = devm_kzalloc(&client->dev, sizeof(*sm), GFP_KERNEL);
	if (!sm)
		return -ENOMEM;
	sm->dev = &client->dev;
	sm->client = client;
	i2c_set_clientdata(client, sm);

	id = i2c_smbus_read_byte_data(client, SM5440_REG_DEVICEID);
	if (id < 0)
		return dev_err_probe(sm->dev, id, "cannot read device ID\n");
	if ((id & 0x0f) != 1)
		return dev_err_probe(sm->dev, -ENODEV,
				     "unexpected device ID %#x\n", id);

	sm->tcpm = devm_power_supply_get_by_reference(sm->dev,
						      "tcpm-power-supply");
	if (IS_ERR(sm->tcpm))
		return dev_err_probe(sm->dev, PTR_ERR(sm->tcpm),
				     "cannot get TCPM power supply\n");
	if (!sm->tcpm)
		return dev_err_probe(sm->dev, -EPROBE_DEFER,
				     "TCPM power supply is not ready\n");

	sm->battery = power_supply_get_by_name("sm5714-battery");
	if (!sm->battery)
		return dev_err_probe(sm->dev, -EPROBE_DEFER,
				     "battery power supply is not ready\n");
	ret = devm_add_action_or_reset(sm->dev, sm5440_put_power_supply,
				       sm->battery);
	if (ret)
		return ret;

	INIT_DELAYED_WORK(&sm->work, sm5440_work);
	ret = devm_add_action_or_reset(sm->dev, sm5440_cancel_work, sm);
	if (ret)
		return ret;
	schedule_delayed_work(&sm->work, msecs_to_jiffies(10000));

	dev_info(sm->dev, "SM5440 direct charger device ID %#x\n", id);
	return 0;
}

static int sm5440_suspend(struct device *dev)
{
	struct sm5440_direct *sm = dev_get_drvdata(dev);

	/*
	 * The poll loop talks I2C once a second, and system suspend tears the
	 * bus down underneath it.  Left running it produced "Transfer while
	 * suspended" on both this device and the PD controller next to it, and
	 * the failed transfers took the whole USB-PD contract with them: the
	 * port dropped to a 5 V DCP fallback and stayed there.  The panel's
	 * cold-boot recovery suspends at about 21 s into every boot, which is
	 * exactly when the charger is negotiating, so this was not a rare race.
	 *
	 * Handing the battery back to the switching charger first is the safe
	 * order.  The pump's own watchdog would drop it within thirty seconds
	 * anyway once nothing services it, and coming back through the normal
	 * eligibility check on resume is cheaper than trying to prove what the
	 * hardware did while nobody was watching.
	 */
	if (sm->active)
		sm5440_restore_switching(sm);
	cancel_delayed_work_sync(&sm->work);

	return 0;
}

static int sm5440_resume(struct device *dev)
{
	struct sm5440_direct *sm = dev_get_drvdata(dev);

	schedule_delayed_work(&sm->work, msecs_to_jiffies(SM5440_RETRY_MS));

	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(sm5440_pm_ops, sm5440_suspend, sm5440_resume);

static const struct of_device_id sm5440_of_match[] = {
	{ .compatible = "siliconmitus,sm5440" },
	{ }
};
MODULE_DEVICE_TABLE(of, sm5440_of_match);

static struct i2c_driver sm5440_driver = {
	.driver = {
		.name = "sm5440-direct",
		.of_match_table = sm5440_of_match,
		.pm = pm_sleep_ptr(&sm5440_pm_ops),
	},
	.probe = sm5440_probe,
};
module_i2c_driver(sm5440_driver);

MODULE_DESCRIPTION("Silicon Mitus SM5440 direct charger for Samsung SM-X910");
MODULE_LICENSE("GPL");
