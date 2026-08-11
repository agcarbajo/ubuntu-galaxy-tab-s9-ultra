// SPDX-License-Identifier: GPL-2.0-only
/*
 * Silicon Mitus SM5714 charger + fuel gauge, as wired on the Samsung Galaxy
 * Tab S9 Ultra Wi-Fi (SM-X910).
 *
 * SM8550 boards normally report the battery through pmic_glink/qcom_battmgr,
 * but that path needs a "charger_pd" protection domain on the ADSP and this
 * device's firmware ships none (only root_pd, sensor_pd, audio_pd and the CDSP
 * root_pd).  Samsung drives the SM5714 from the AP instead, so do the same.
 *
 * The chip answers on three I2C addresses on the same bus: 0x49 for the
 * charger block (8-bit registers), 0x71 for the fuel gauge (16-bit registers,
 * with the interesting values behind an SRAM read window) and 0x25 for the
 * MUIC.  This driver binds the charger address and creates dummy clients for
 * the fuel gauge and MUIC.
 *
 * Samsung's shutdown path deliberately leaves ENQ4FET off and resets the
 * current limits.  Restore only the cable-dependent limits documented by its
 * downstream driver: SDP remains at 500 mA, CDP uses 1.5 A and DCP uses the
 * 1.8 A / 2.1 A values measured on this tablet.  No voltage, PD/PPS or
 * thermal setting is changed.  Register layout and the fixed-point
 * conversions come from Samsung's downstream sm5714_fuelgauge.c,
 * sm5714_charger.c and sm5714-muic.c.
 */

#include <linux/bitops.h>
#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/iio/consumer.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm.h>
#include <linux/power_supply.h>
#include <linux/workqueue.h>

#define SM5714_MUIC_I2C_ADDR		0x25
#define SM5714_FG_I2C_ADDR		0x71

/* Charger block (8-bit registers, at the address this driver binds). */
#define SM5714_CHG_REG_STATUS1		0x0d
#define  SM5714_CHG_STATUS1_VBUS_POK	BIT(0)
#define SM5714_CHG_REG_STATUS2		0x0e
#define  SM5714_CHG_STATUS2_CHG_ON	BIT(3)
#define  SM5714_CHG_STATUS2_TOPOFF	BIT(5)
#define SM5714_CHG_REG_CNTL1		0x13
#define  SM5714_CHG_CNTL1_ENQ4FET	BIT(3)
#define SM5714_CHG_REG_CNTL2		0x14
#define  SM5714_CHG_CNTL2_MODE_MASK	GENMASK(3, 0)
#define  SM5714_CHG_CNTL2_CHARGING	0x05
#define  SM5714_CHG_CNTL2_USB_OTG	0x07
#define SM5714_CHG_REG_VBUSCNTL		0x15
#define SM5714_CHG_REG_CHGCNTL2		0x18
#define SM5714_CHG_REG_BSTCNTL1		0x23
#define  SM5714_CHG_BSTCNTL1_OTG_MASK	(GENMASK(7, 6) | GENMASK(3, 0))
#define  SM5714_CHG_BSTCNTL1_5V1_900MA	0x46
/*
 * BSTCNTL1 bits 7:6 select the OTG current limit and bits 3:0 the boost
 * voltage, which is why 900 mA at 5.1 V spells 0x46 and 1500 mA at 5.1 V
 * spells 0xc6.  The limit itself comes from otg_ma; see the note there.
 */
#define  SM5714_CHG_BSTCNTL1_5V1	0x06
#define  SM5714_CHG_BSTCNTL1_MA_SHIFT	6
#define SM5714_CHG_REG_DEVICEID		0x50

/* MUIC block (8-bit registers, at SM5714_MUIC_I2C_ADDR). */
#define SM5714_MUIC_REG_CNTL		0x05
#define  SM5714_MUIC_CNTL_BC12OFF	BIT(1)
#define SM5714_MUIC_REG_MANUAL_SW	0x06
#define  SM5714_MUIC_MANUAL_SW_MANUAL	BIT(7)
#define  SM5714_MUIC_MANUAL_SW_PATH_MASK	GENMASK(5, 0)
#define  SM5714_MUIC_MANUAL_SW_USB	0x09
#define SM5714_MUIC_REG_DEVICE_ID	0x00
#define SM5714_MUIC_REG_DEVICE_TYPE1	0x07
#define  SM5714_MUIC_TYPE_DCD_OUT_SDP	BIT(0)
#define  SM5714_MUIC_TYPE_SDP		BIT(1)
#define  SM5714_MUIC_TYPE_DCP		BIT(2)
#define  SM5714_MUIC_TYPE_CDP		BIT(3)
#define  SM5714_MUIC_TYPE_U200		BIT(4)
#define  SM5714_MUIC_TYPE_AFC		BIT(5)
#define  SM5714_MUIC_TYPE_QC20		BIT(6)
#define  SM5714_MUIC_TYPE_LO_TA		BIT(7)

/* Fuel gauge block (16-bit registers, at SM5714_FG_I2C_ADDR). */
#define SM5714_FG_REG_DEVICE_ID		0x00
#define SM5714_FG_REG_SRAM_RADDR	0x8c
#define SM5714_FG_REG_SRAM_RDATA	0x8d

/* Fuel gauge SRAM window addresses. */
#define SM5714_FG_SRAM_SOC		0x00
#define SM5714_FG_SRAM_OCV		0x01
#define SM5714_FG_SRAM_VBAT		0x03
#define SM5714_FG_SRAM_CURRENT		0x05
#define SM5714_FG_SRAM_TEMPERATURE	0x07
#define SM5714_FG_SRAM_VBAT_AVG		0x08
#define SM5714_FG_SRAM_CURRENT_AVG	0x09

#define SM5714_POLL_INTERVAL_MS		1000
#define SM5714_CAPACITY_POLL_DIVIDER	10

enum sm5714_charge_thermal_state {
	SM5714_THERMAL_NORMAL,
	SM5714_THERMAL_REDUCED,
	SM5714_THERMAL_STOP,
};

struct sm5714_battery {
	struct device *dev;
	struct i2c_client *chg;
	struct i2c_client *fg;
	struct i2c_client *muic;
	struct iio_channel *battery_temp;
	/* Serialises the two-step SRAM read window on the fuel gauge. */
	struct mutex sram_lock;
	/* Serialises charger programming from polling and the TCPM callback. */
	struct mutex chg_lock;
	struct power_supply *psy_bat;
	struct power_supply *psy_usb;
	struct power_supply_battery_info *info;
	struct delayed_work poll_work;
	int last_status;
	int last_capacity;
	bool last_online;
	int last_usb_type;
	unsigned int poll_count;
	unsigned int typec_mv;
	unsigned int typec_ma;
	enum sm5714_charge_thermal_state thermal_state;
	bool direct_charging;
	bool otg_active;
};

static DEFINE_MUTEX(sm5714_global_lock);
static struct sm5714_battery *sm5714_primary;

static int sm5714_get_online_raw(struct sm5714_battery *sm);
static int sm5714_get_online(struct sm5714_battery *sm);
static int sm5714_get_temp(struct sm5714_battery *sm, int *val);
/*
 * OTG current limit, as the BSTCNTL1 selector: 0 = 500 mA, 1 = 900 mA,
 * 2 = 1200 mA, 3 = 1500 mA.
 *
 * Samsung uses 900 mA in every OTG row of its operating table, and this port
 * kept that until a bus-powered USB-C hub that a PC drives fine turned out
 * never to start here.  Everything else was measured and excluded — the
 * advertised Rp across all four values, the OTG data path, the interrupt
 * masks, a lost suspend event — and raising this to 1500 mA brought the hub and
 * its RTL8153 up on the first try.
 *
 * What makes it safe is that the two settings are independent.  This is a
 * ceiling, not a supply: the hub asks for 100 mA and the Ethernet for 180 mA
 * once enumerated.  What needed the headroom was the inrush while their
 * regulators and PHY start, and at 900 mA the charger's protection cut in
 * before the hub could signal attach — silently, which is why nothing ever
 * appeared in any log.  Meanwhile the Rp advertisement stays at the stock
 * value, so no device is *told* it may draw 1.5 A continuously.
 *
 * Set otg_ma=1 to go back to the vendor limit.
 */
static unsigned int otg_ma = 3;
module_param(otg_ma, uint, 0644);
MODULE_PARM_DESC(otg_ma,
		 "OTG current limit: 0=500mA, 1=900mA (vendor), 2=1200mA, 3=1500mA (default)");

int sm5714_battery_set_pd_contract(unsigned int mv, unsigned int ma);
int sm5714_battery_set_direct_charge(bool active);
int sm5714_battery_set_otg(bool active);
bool sm5714_battery_is_otg_active(void);

static int sm5714_chg_update_bits(struct sm5714_battery *sm, u8 reg,
				  u8 mask, u8 val)
{
	int old;
	u8 new;

	old = i2c_smbus_read_byte_data(sm->chg, reg);
	if (old < 0)
		return old;

	new = (old & ~mask) | (val & mask);
	if (new == old)
		return 0;

	return i2c_smbus_write_byte_data(sm->chg, reg, new);
}

/*
 * The SM5714 MUIC contains the physical D-/D+ switch between the connector
 * and the SoC.  Incoming VBUS lets its automatic BC1.2 state machine select
 * USB, which hid this dependency with a powered dock.  A bus-powered OTG
 * accessory has no incoming VBUS, so Samsung explicitly disables BC1.2 and
 * selects the USB path when it reports ATTACHED_DEV_OTG_MUIC.
 *
 * Restore automatic switching when the tablet stops sourcing VBUS so ordinary
 * sink/device charging and RNDIS continue to use the hardware detector.
 */
static int sm5714_muic_set_otg_path(struct sm5714_battery *sm, bool active)
{
	int old_cntl;
	int old;
	u8 new;
	int ret;

	if (active) {
		old_cntl = i2c_smbus_read_byte_data(sm->muic,
						    SM5714_MUIC_REG_CNTL);
		if (old_cntl < 0)
			return old_cntl;

		new = old_cntl | SM5714_MUIC_CNTL_BC12OFF;
		ret = i2c_smbus_write_byte_data(sm->muic,
						SM5714_MUIC_REG_CNTL, new);
		if (ret)
			return ret;

		old = i2c_smbus_read_byte_data(sm->muic,
					       SM5714_MUIC_REG_MANUAL_SW);
		if (old < 0)
			goto restore_bc12;

		new = (old & ~(SM5714_MUIC_MANUAL_SW_MANUAL |
			       SM5714_MUIC_MANUAL_SW_PATH_MASK)) |
		      SM5714_MUIC_MANUAL_SW_MANUAL |
		      SM5714_MUIC_MANUAL_SW_USB;
		ret = i2c_smbus_write_byte_data(sm->muic,
						SM5714_MUIC_REG_MANUAL_SW,
						new);
		if (!ret)
			return 0;

restore_bc12:
		i2c_smbus_write_byte_data(sm->muic, SM5714_MUIC_REG_CNTL,
					  old_cntl);
		return old < 0 ? old : ret;
	}

	old = i2c_smbus_read_byte_data(sm->muic,
				       SM5714_MUIC_REG_MANUAL_SW);
	if (old < 0)
		return old;

	new = old & ~(SM5714_MUIC_MANUAL_SW_MANUAL |
		      SM5714_MUIC_MANUAL_SW_PATH_MASK);
	ret = i2c_smbus_write_byte_data(sm->muic,
					SM5714_MUIC_REG_MANUAL_SW, new);
	if (ret)
		return ret;

	old = i2c_smbus_read_byte_data(sm->muic, SM5714_MUIC_REG_CNTL);
	if (old < 0)
		return old;

	return i2c_smbus_write_byte_data(sm->muic, SM5714_MUIC_REG_CNTL,
					 old & ~SM5714_MUIC_CNTL_BC12OFF);
}

static int sm5714_get_usb_type(struct sm5714_battery *sm)
{
	int online = sm5714_get_online(sm);
	int type;

	if (online <= 0)
		return online < 0 ? online : POWER_SUPPLY_USB_TYPE_UNKNOWN;

	if (READ_ONCE(sm->typec_mv) > 5000)
		return POWER_SUPPLY_USB_TYPE_PD;

	type = i2c_smbus_read_byte_data(sm->muic,
					SM5714_MUIC_REG_DEVICE_TYPE1);
	if (type < 0)
		return type;

	if (type & SM5714_MUIC_TYPE_CDP)
		return POWER_SUPPLY_USB_TYPE_CDP;
	if (type & (SM5714_MUIC_TYPE_SDP |
		    SM5714_MUIC_TYPE_DCD_OUT_SDP))
		return POWER_SUPPLY_USB_TYPE_SDP;
	if (type & (SM5714_MUIC_TYPE_DCP |
		    SM5714_MUIC_TYPE_U200 |
		    SM5714_MUIC_TYPE_AFC |
		    SM5714_MUIC_TYPE_QC20 |
		    SM5714_MUIC_TYPE_LO_TA))
		return POWER_SUPPLY_USB_TYPE_DCP;

	return POWER_SUPPLY_USB_TYPE_UNKNOWN;
}

static u8 sm5714_input_current_reg(unsigned int ma)
{
	return clamp_val((ma - 100) / 25, 0, 0x7f);
}

static u8 sm5714_fast_current_reg(unsigned int ma)
{
	unsigned int ua = ma * 1000;

	if (ua <= 109375)
		return 0x07;

	return clamp_val(7 + (ua - 109375) / 15625, 0x07, 0xe0);
}

static enum sm5714_charge_thermal_state
sm5714_charge_thermal_state(struct sm5714_battery *sm, int temp)
{
	/*
	 * The stock X910 battery data uses 50.0 C as the wired
	 * warm/overheat boundary.  Add a conservative reduced-current band from
	 * 46.0 C, matching the stock mixed-temperature threshold.  A hard stop
	 * recovers into that reduced band below 46.0 C; full current returns
	 * only below the stock warm/normal boundary of 42.0 C.
	 */
	if (sm->thermal_state == SM5714_THERMAL_STOP) {
		if (temp >= 460)
			return SM5714_THERMAL_STOP;
		if (temp > 420)
			return SM5714_THERMAL_REDUCED;
	}
	if (sm->thermal_state == SM5714_THERMAL_REDUCED && temp > 420) {
		if (temp >= 500)
			return SM5714_THERMAL_STOP;
		return SM5714_THERMAL_REDUCED;
	}

	if (temp >= 500)
		return SM5714_THERMAL_STOP;
	if (temp >= 460)
		return SM5714_THERMAL_REDUCED;
	return SM5714_THERMAL_NORMAL;
}

static int sm5714_configure_charging(struct sm5714_battery *sm)
{
	unsigned int input_ma, fast_ma;
	unsigned int typec_mv, typec_ma;
	enum sm5714_charge_thermal_state thermal_state;
	int usb_type;
	int temp;
	int ret;

	mutex_lock(&sm->chg_lock);
	if (READ_ONCE(sm->otg_active)) {
		ret = -EBUSY;
		goto out_unlock;
	}

	typec_mv = sm->typec_mv;
	typec_ma = sm->typec_ma;
	usb_type = sm5714_get_usb_type(sm);
	if (usb_type < 0) {
		ret = usb_type;
		goto out_unlock;
	}

	thermal_state = sm->thermal_state;
	if (!sm5714_get_temp(sm, &temp)) {
		thermal_state = sm5714_charge_thermal_state(sm, temp);
		sm->thermal_state = thermal_state;
	}

	if (thermal_state == SM5714_THERMAL_STOP) {
		ret = sm5714_chg_update_bits(sm, SM5714_CHG_REG_CNTL1,
					     SM5714_CHG_CNTL1_ENQ4FET, 0);
		if (!ret)
			dev_warn(sm->dev,
				 "charging suspended at battery temperature %d.%d C\n",
				 temp / 10, abs(temp % 10));
		goto out_unlock;
	}

	if (typec_mv >= 5000 && typec_ma >= 500) {
		/*
		 * Stock board data allows 3 A input, 3150 mA battery current and
		 * 9 V on the switching charger.  The 15 W fixed-PD path uses
		 * 9 V / 1.66 A; a Type-C Rp=3 A fallback may use 5 V / 3 A.
		 */
		input_ma = min(typec_ma, typec_mv > 5000 ? 1660U : 3000U);
		fast_ma = 2800;

	} else switch (usb_type) {
	case POWER_SUPPLY_USB_TYPE_DCP:
		input_ma = 1800;
		/* 2100 mA maps to the stock bootloader's CHGCNTL2=0x86. */
		fast_ma = 2100;
		break;
	case POWER_SUPPLY_USB_TYPE_CDP:
		input_ma = 1500;
		fast_ma = 1500;
		break;
	case POWER_SUPPLY_USB_TYPE_SDP:
	default:
		/* Unknown sources must never be treated as high-current ports. */
		input_ma = 500;
		fast_ma = 500;
		break;
	}

	if (thermal_state == SM5714_THERMAL_REDUCED) {
		/*
		 * Keep the fixed-PD input budget available: the panel/GPU can
		 * consume most of a 9 W cap by themselves.  The stock switching
		 * charger uses 2.1 A battery current on this board, so use that
		 * well-tested value in the warm band and reserve the hard cutoff
		 * for 50 C.
		 */
		fast_ma = min(fast_ma, 2100U);
	}

	/*
	 * Match chg_set_enq4fet(): lower the input limit before closing Q4,
	 * then restore the limit advertised by the MUIC classification.
	 */
	ret = i2c_smbus_write_byte_data(sm->chg, SM5714_CHG_REG_VBUSCNTL,
					sm5714_input_current_reg(500));
	if (ret)
		goto out_unlock;

	ret = i2c_smbus_write_byte_data(sm->chg, SM5714_CHG_REG_CHGCNTL2,
					sm5714_fast_current_reg(fast_ma));
	if (ret)
		goto out_unlock;

	if (input_ma > 500)
		usleep_range(DIV_ROUND_UP(input_ma - 500, 250) * 1000,
			     DIV_ROUND_UP(input_ma - 500, 250) * 1000 + 1000);

	ret = sm5714_chg_update_bits(sm, SM5714_CHG_REG_CNTL1,
				     SM5714_CHG_CNTL1_ENQ4FET,
				     SM5714_CHG_CNTL1_ENQ4FET);
	if (ret)
		goto out_unlock;

	ret = i2c_smbus_write_byte_data(sm->chg, SM5714_CHG_REG_VBUSCNTL,
					sm5714_input_current_reg(input_ma));
	if (!ret)
		dev_info(sm->dev,
			 "enabled charging for USB type %d at %u mV "
			 "(%u mA input, %u mA fast)\n",
			 usb_type, typec_mv ?: 5000, input_ma, fast_ma);

out_unlock:
	mutex_unlock(&sm->chg_lock);
	return ret;
}

/*
 * TCPM calls this only after it has selected a Type-C current limit or a PD
 * contract.  Keep the board-specific charger coupling here rather than in the
 * transport driver: the SM5714 USB-PD block is on a different I2C adapter.
 */
int sm5714_battery_set_pd_contract(unsigned int mv, unsigned int ma)
{
	struct sm5714_battery *sm;
	int ret = 0;

	if ((mv && (mv < 5000 || mv > 9000)) || ma > 3000)
		return -ERANGE;

	mutex_lock(&sm5714_global_lock);
	sm = sm5714_primary;
	if (!sm) {
		ret = -EPROBE_DEFER;
		goto out;
	}

	WRITE_ONCE(sm->typec_mv, mv);
	WRITE_ONCE(sm->typec_ma, ma);
	if (mv && ma && sm5714_get_online(sm) > 0 &&
	    !READ_ONCE(sm->direct_charging))
		ret = sm5714_configure_charging(sm);

	power_supply_changed(sm->psy_usb);
	power_supply_changed(sm->psy_bat);
out:
	mutex_unlock(&sm5714_global_lock);
	return ret;
}
EXPORT_SYMBOL_GPL(sm5714_battery_set_pd_contract);

/*
 * Hand the battery path to the board's SM5440 2:1 charge pump.  Keeping this
 * arbitration in the SM5714 driver prevents its one-second recovery poll (or
 * a later TCPM PPS update) from closing Q4 behind the direct charger.
 */
int sm5714_battery_set_direct_charge(bool active)
{
	struct sm5714_battery *sm;
	int temp;
	int ret = 0;

	mutex_lock(&sm5714_global_lock);
	sm = sm5714_primary;
	if (!sm) {
		ret = -EPROBE_DEFER;
		goto out;
	}

	if (active) {
		ret = sm5714_get_temp(sm, &temp);
		if (ret)
			goto out;
		if (temp < 100 || temp >= 420) {
			ret = -ERANGE;
			goto out;
		}

		WRITE_ONCE(sm->direct_charging, true);
		mutex_lock(&sm->chg_lock);
		ret = sm5714_chg_update_bits(sm, SM5714_CHG_REG_CNTL1,
					     SM5714_CHG_CNTL1_ENQ4FET, 0);
		mutex_unlock(&sm->chg_lock);
		if (ret)
			WRITE_ONCE(sm->direct_charging, false);
	} else {
		WRITE_ONCE(sm->direct_charging, false);
		if (sm5714_get_online(sm) > 0)
			ret = sm5714_configure_charging(sm);
	}

	power_supply_changed(sm->psy_usb);
	power_supply_changed(sm->psy_bat);
out:
	mutex_unlock(&sm5714_global_lock);
	return ret;
}
EXPORT_SYMBOL_GPL(sm5714_battery_set_direct_charge);

/*
 * Feed VBUS while TCPM owns the source role.  Samsung's downstream charger
 * driver uses mode 0x7 with a 5.1 V / 900 mA boost setting on this exact
 * board.  Keep that conservative stock limit: it is sufficient for keyboards,
 * storage and self-powered docks without inventing a larger board budget.
 *
 * Q4 must remain open while the boost drives the connector.  Conversely, do
 * not enable the boost if an external source is already present, and restore
 * the ordinary switching-charger mode before accepting a sink attachment.
 */
int sm5714_battery_set_otg(bool active)
{
	struct sm5714_battery *sm;
	bool restore_charging = false;
	int online;
	int ret = 0;

	mutex_lock(&sm5714_global_lock);
	sm = sm5714_primary;
	if (!sm) {
		ret = -EPROBE_DEFER;
		goto out_global;
	}

	if (active == READ_ONCE(sm->otg_active))
		goto out_notify;

	if (active) {
		if (READ_ONCE(sm->direct_charging)) {
			ret = -EBUSY;
			goto out_global;
		}

		online = sm5714_get_online_raw(sm);
		if (online < 0) {
			ret = online;
			goto out_global;
		}
		if (online) {
			ret = -EBUSY;
			goto out_global;
		}

		mutex_lock(&sm->chg_lock);
		/*
		 * Route D-/D+ before enabling VBUS.  Samsung handles the MUIC
		 * explicitly for every OTG attachment; coordinating it with
		 * the boost here ensures that TCPM exposes the USB host only
		 * after the physical USB2 path is connected.
		 */
		ret = sm5714_muic_set_otg_path(sm, true);
		if (!ret)
			ret = sm5714_chg_update_bits(sm, SM5714_CHG_REG_CNTL1,
						     SM5714_CHG_CNTL1_ENQ4FET,
						     0);
		if (!ret)
			ret = sm5714_chg_update_bits(
				sm, SM5714_CHG_REG_BSTCNTL1,
				SM5714_CHG_BSTCNTL1_OTG_MASK,
				SM5714_CHG_BSTCNTL1_5V1 |
				((otg_ma & 3) <<
				 SM5714_CHG_BSTCNTL1_MA_SHIFT));
		if (!ret)
			ret = sm5714_chg_update_bits(
				sm, SM5714_CHG_REG_CNTL2,
				SM5714_CHG_CNTL2_MODE_MASK,
				SM5714_CHG_CNTL2_USB_OTG);
		if (!ret)
			WRITE_ONCE(sm->otg_active, true);
		else
			sm5714_muic_set_otg_path(sm, false);
		mutex_unlock(&sm->chg_lock);

		if (!ret)
			dev_info(sm->dev,
				 "enabled USB OTG boost at 5.1 V / %u mA\n",
				 (const unsigned int []){ 500, 900, 1200,
							  1500 }[otg_ma & 3]);
	} else {
		mutex_lock(&sm->chg_lock);
		ret = sm5714_chg_update_bits(
			sm, SM5714_CHG_REG_CNTL2,
			SM5714_CHG_CNTL2_MODE_MASK,
			SM5714_CHG_CNTL2_CHARGING);
		if (!ret) {
			WRITE_ONCE(sm->otg_active, false);
			ret = sm5714_muic_set_otg_path(sm, false);
		}
		mutex_unlock(&sm->chg_lock);

		if (!ret) {
			restore_charging = sm5714_get_online_raw(sm) > 0;
			dev_info(sm->dev, "disabled USB OTG boost\n");
		}
	}

out_notify:
	power_supply_changed(sm->psy_usb);
	power_supply_changed(sm->psy_bat);
out_global:
	mutex_unlock(&sm5714_global_lock);

	/*
	 * configure_charging() takes chg_lock and consults the exported state;
	 * run it after dropping the global lock used by TCPM callbacks.
	 */
	if (!ret && restore_charging)
		ret = sm5714_configure_charging(sm);

	return ret;
}
EXPORT_SYMBOL_GPL(sm5714_battery_set_otg);

bool sm5714_battery_is_otg_active(void)
{
	struct sm5714_battery *sm;
	bool active = false;

	mutex_lock(&sm5714_global_lock);
	sm = sm5714_primary;
	if (sm)
		active = READ_ONCE(sm->otg_active);
	mutex_unlock(&sm5714_global_lock);

	return active;
}
EXPORT_SYMBOL_GPL(sm5714_battery_is_otg_active);

/*
 * The fuel gauge exposes its measurements through an SRAM read window: point
 * RADDR at the word of interest, then read RDATA.
 */
static int sm5714_fg_read_sram(struct sm5714_battery *sm, u8 addr)
{
	int ret;

	mutex_lock(&sm->sram_lock);

	ret = i2c_smbus_write_word_data(sm->fg, SM5714_FG_REG_SRAM_RADDR, addr);
	if (ret < 0)
		goto out;

	ret = i2c_smbus_read_word_data(sm->fg, SM5714_FG_REG_SRAM_RDATA);
out:
	mutex_unlock(&sm->sram_lock);
	if (ret < 0)
		dev_dbg(sm->dev, "SRAM read 0x%02x failed: %d\n", addr, ret);
	return ret;
}

/*
 * Current and temperature are legitimately negative when the battery is
 * discharging or cold, so these helpers report the value through *val and keep
 * the return code purely for I/O errors.  Folding the two together would make a
 * discharging battery look like a failing I2C transfer.
 */

/* State of charge arrives as an unsigned Q8.8 percentage. */
static int sm5714_get_capacity(struct sm5714_battery *sm, int *val)
{
	int raw = sm5714_fg_read_sram(sm, SM5714_FG_SRAM_SOC);

	if (raw < 0)
		return raw;

	*val = clamp(((raw * 10) >> 8) / 10, 0, 100);
	return 0;
}

/* Battery voltage is offset from 2700 mV in units of 10/109 mV. */
static int sm5714_get_voltage(struct sm5714_battery *sm, u8 sram_addr, int *val)
{
	int raw = sm5714_fg_read_sram(sm, sram_addr);
	int mv;

	if (raw < 0)
		return raw;

	if (raw & 0x8000)
		mv = 2700 - (((raw & 0x7fff) * 10) / 109);
	else
		mv = ((raw * 10) / 109) + 2700;

	*val = mv * 1000;
	return 0;
}

static int sm5714_get_ocv(struct sm5714_battery *sm, int *val)
{
	int raw = sm5714_fg_read_sram(sm, SM5714_FG_SRAM_OCV);

	if (raw < 0)
		return raw;

	*val = ((raw * 1000) >> 11) * 1000;
	return 0;
}

/*
 * Current is a sign-magnitude value in units of 1/2044 A.  Bit 15 marks a
 * discharge, which matches the power supply class convention of negative
 * current flowing out of the battery.
 */
static int sm5714_get_current(struct sm5714_battery *sm, u8 sram_addr, int *val)
{
	int raw = sm5714_fg_read_sram(sm, sram_addr);
	int ma;

	if (raw < 0)
		return raw;

	ma = ((raw & 0x7fff) * 1000) / 2044;
	if (raw & 0x8000)
		ma = -ma;

	*val = ma * 1000;
	return 0;
}

static int sm5714_get_temp(struct sm5714_battery *sm, int *val)
{
	int temp_mc;
	int raw;
	int temp;

	/*
	 * The stock X910 policy uses the external pack thermistor.  The SM5714
	 * SRAM value is the fuel-gauge die temperature and rises/falls by several
	 * degrees as Q4 switches, so it is not a valid battery safety signal.
	 */
	if (sm->battery_temp) {
		temp = iio_read_channel_processed(sm->battery_temp, &temp_mc);
		if (!temp) {
			temp = DIV_ROUND_CLOSEST(temp_mc, 100);
			if (temp >= -200 && temp <= 900) {
				*val = temp;
				return 0;
			}
			dev_warn_ratelimited(sm->dev,
					     "pack thermistor returned implausible %d mC\n",
					     temp_mc);
		}
	}

	raw = sm5714_fg_read_sram(sm, SM5714_FG_SRAM_TEMPERATURE);
	if (raw < 0)
		return raw;

	temp = (((raw & 0x7fff) * 10) * 2989) >> 11 >> 8;
	if (raw & 0x8000)
		temp = -temp;

	*val = temp;
	return 0;
}

static int sm5714_get_online_raw(struct sm5714_battery *sm)
{
	int ret = i2c_smbus_read_byte_data(sm->chg, SM5714_CHG_REG_STATUS1);

	if (ret < 0)
		return ret;

	return !!(ret & SM5714_CHG_STATUS1_VBUS_POK);
}

static int sm5714_get_online(struct sm5714_battery *sm)
{
	if (READ_ONCE(sm->otg_active))
		return 0;

	return sm5714_get_online_raw(sm);
}

static int sm5714_get_status(struct sm5714_battery *sm)
{
	int st1, st2;

	if (READ_ONCE(sm->otg_active))
		return POWER_SUPPLY_STATUS_DISCHARGING;

	st1 = i2c_smbus_read_byte_data(sm->chg, SM5714_CHG_REG_STATUS1);
	if (st1 < 0)
		return st1;
	st2 = i2c_smbus_read_byte_data(sm->chg, SM5714_CHG_REG_STATUS2);
	if (st2 < 0)
		return st2;

	if (st2 & SM5714_CHG_STATUS2_TOPOFF)
		return POWER_SUPPLY_STATUS_FULL;
	if (READ_ONCE(sm->direct_charging) &&
	    (st1 & SM5714_CHG_STATUS1_VBUS_POK))
		return POWER_SUPPLY_STATUS_CHARGING;
	if (st2 & SM5714_CHG_STATUS2_CHG_ON)
		return POWER_SUPPLY_STATUS_CHARGING;
	if (st1 & SM5714_CHG_STATUS1_VBUS_POK)
		return POWER_SUPPLY_STATUS_NOT_CHARGING;

	return POWER_SUPPLY_STATUS_DISCHARGING;
}

static int sm5714_bat_get_property(struct power_supply *psy,
				   enum power_supply_property psp,
				   union power_supply_propval *val)
{
	struct sm5714_battery *sm = power_supply_get_drvdata(psy);
	int ret;

	switch (psp) {
	case POWER_SUPPLY_PROP_STATUS:
		ret = sm5714_get_status(sm);
		if (ret < 0)
			return ret;
		val->intval = ret;
		return 0;
	case POWER_SUPPLY_PROP_PRESENT:
		val->intval = 1;
		return 0;
	case POWER_SUPPLY_PROP_TECHNOLOGY:
		val->intval = POWER_SUPPLY_TECHNOLOGY_LION;
		return 0;
	case POWER_SUPPLY_PROP_CAPACITY:
		ret = sm5714_get_capacity(sm, &val->intval);
		break;
	case POWER_SUPPLY_PROP_VOLTAGE_NOW:
		ret = sm5714_get_voltage(sm, SM5714_FG_SRAM_VBAT, &val->intval);
		break;
	case POWER_SUPPLY_PROP_VOLTAGE_AVG:
		ret = sm5714_get_voltage(sm, SM5714_FG_SRAM_VBAT_AVG,
					 &val->intval);
		break;
	case POWER_SUPPLY_PROP_VOLTAGE_OCV:
		ret = sm5714_get_ocv(sm, &val->intval);
		break;
	case POWER_SUPPLY_PROP_CURRENT_NOW:
		ret = sm5714_get_current(sm, SM5714_FG_SRAM_CURRENT,
					 &val->intval);
		break;
	case POWER_SUPPLY_PROP_CURRENT_AVG:
		ret = sm5714_get_current(sm, SM5714_FG_SRAM_CURRENT_AVG,
					 &val->intval);
		break;
	case POWER_SUPPLY_PROP_TEMP:
		ret = sm5714_get_temp(sm, &val->intval);
		break;
	case POWER_SUPPLY_PROP_CHARGE_FULL_DESIGN:
		if (!sm->info ||
		    sm->info->charge_full_design_uah < 0)
			return -ENODATA;
		val->intval = sm->info->charge_full_design_uah;
		return 0;
	case POWER_SUPPLY_PROP_VOLTAGE_MAX_DESIGN:
		if (!sm->info ||
		    sm->info->voltage_max_design_uv < 0)
			return -ENODATA;
		val->intval = sm->info->voltage_max_design_uv;
		return 0;
	case POWER_SUPPLY_PROP_VOLTAGE_MIN_DESIGN:
		if (!sm->info ||
		    sm->info->voltage_min_design_uv < 0)
			return -ENODATA;
		val->intval = sm->info->voltage_min_design_uv;
		return 0;
	default:
		return -EINVAL;
	}

	return ret;
}

static int sm5714_usb_get_property(struct power_supply *psy,
				   enum power_supply_property psp,
				   union power_supply_propval *val)
{
	struct sm5714_battery *sm = power_supply_get_drvdata(psy);
	int ret;

	switch (psp) {
	case POWER_SUPPLY_PROP_ONLINE:
		ret = sm5714_get_online(sm);
		break;
	case POWER_SUPPLY_PROP_USB_TYPE:
		ret = sm5714_get_usb_type(sm);
		if (ret < 0)
			return ret;
		val->intval = ret;
		return 0;
	case POWER_SUPPLY_PROP_VOLTAGE_MAX:
		val->intval = (READ_ONCE(sm->typec_mv) ?: 5000) * 1000;
		return 0;
	case POWER_SUPPLY_PROP_CURRENT_MAX:
		val->intval = READ_ONCE(sm->typec_ma) * 1000;
		return 0;
	default:
		return -EINVAL;
	}

	if (ret < 0)
		return ret;

	val->intval = ret;
	return 0;
}

static enum power_supply_property sm5714_bat_props[] = {
	POWER_SUPPLY_PROP_STATUS,
	POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_TECHNOLOGY,
	POWER_SUPPLY_PROP_CAPACITY,
	POWER_SUPPLY_PROP_VOLTAGE_NOW,
	POWER_SUPPLY_PROP_VOLTAGE_AVG,
	POWER_SUPPLY_PROP_VOLTAGE_OCV,
	POWER_SUPPLY_PROP_VOLTAGE_MAX_DESIGN,
	POWER_SUPPLY_PROP_VOLTAGE_MIN_DESIGN,
	POWER_SUPPLY_PROP_CURRENT_NOW,
	POWER_SUPPLY_PROP_CURRENT_AVG,
	POWER_SUPPLY_PROP_CHARGE_FULL_DESIGN,
	POWER_SUPPLY_PROP_TEMP,
};

static enum power_supply_property sm5714_usb_props[] = {
	POWER_SUPPLY_PROP_ONLINE,
	POWER_SUPPLY_PROP_USB_TYPE,
	POWER_SUPPLY_PROP_VOLTAGE_MAX,
	POWER_SUPPLY_PROP_CURRENT_MAX,
};

static const struct power_supply_desc sm5714_bat_desc = {
	.name		= "sm5714-battery",
	.type		= POWER_SUPPLY_TYPE_BATTERY,
	.properties	= sm5714_bat_props,
	.num_properties	= ARRAY_SIZE(sm5714_bat_props),
	.get_property	= sm5714_bat_get_property,
};

static const struct power_supply_desc sm5714_usb_desc = {
	.name		= "sm5714-usb",
	.type		= POWER_SUPPLY_TYPE_USB,
	.properties	= sm5714_usb_props,
	.num_properties	= ARRAY_SIZE(sm5714_usb_props),
	.get_property	= sm5714_usb_get_property,
	.usb_types	= BIT(POWER_SUPPLY_USB_TYPE_UNKNOWN) |
			  BIT(POWER_SUPPLY_USB_TYPE_SDP) |
			  BIT(POWER_SUPPLY_USB_TYPE_CDP) |
			  BIT(POWER_SUPPLY_USB_TYPE_DCP) |
			  BIT(POWER_SUPPLY_USB_TYPE_PD),
};

/*
 * The charger interrupt is shared with the MUIC and fuel-gauge blocks.  Until
 * that MFD interrupt domain is implemented, poll VBUS and charging state once
 * per second so desktop indication follows a cable event promptly.  Capacity
 * still changes slowly and is sampled only every ten passes.
 */
static void sm5714_poll_work(struct work_struct *work)
{
	struct sm5714_battery *sm = container_of(to_delayed_work(work),
						 struct sm5714_battery,
						 poll_work);
	int status = sm5714_get_status(sm);
	int online = sm5714_get_online(sm);
	int usb_type = sm5714_get_usb_type(sm);
	int capacity = sm->last_capacity;
	enum sm5714_charge_thermal_state old_thermal_state;
	int temp;
	int cntl1;

	if (sm->poll_count++ % SM5714_CAPACITY_POLL_DIVIDER == 0 &&
	    sm5714_get_capacity(sm, &capacity))
		capacity = sm->last_capacity;

	old_thermal_state = sm->thermal_state;
	if (online > 0 && !sm5714_get_temp(sm, &temp))
		sm->thermal_state = sm5714_charge_thermal_state(sm, temp);
	if (online > 0 && sm->thermal_state != old_thermal_state) {
		dev_info(sm->dev, "charging thermal state %d -> %d at %d.%d C\n",
			 old_thermal_state, sm->thermal_state,
			 temp / 10, abs(temp % 10));
		sm5714_configure_charging(sm);
		status = sm5714_get_status(sm);
	}

	/*
	 * Samsung's shutdown leaves Q4 open.  Recover it at boot or after a
	 * cable insertion, but do not override thermal/full-charge decisions
	 * when the charging path is already enabled.
	 */
	if (online > 0 && !READ_ONCE(sm->direct_charging) &&
	    status == POWER_SUPPLY_STATUS_NOT_CHARGING &&
	    sm->thermal_state != SM5714_THERMAL_STOP) {
		cntl1 = i2c_smbus_read_byte_data(sm->chg, SM5714_CHG_REG_CNTL1);
		if (cntl1 >= 0 && !(cntl1 & SM5714_CHG_CNTL1_ENQ4FET) &&
		    !sm5714_configure_charging(sm))
			status = sm5714_get_status(sm);
	}

	if (status >= 0 &&
	    (status != sm->last_status || capacity != sm->last_capacity)) {
		sm->last_status = status;
		sm->last_capacity = capacity;
		power_supply_changed(sm->psy_bat);
	}

	if (online >= 0 && !!online != sm->last_online) {
		sm->last_online = online;
		if (!online)
			sm5714_chg_update_bits(sm, SM5714_CHG_REG_CNTL1,
					       SM5714_CHG_CNTL1_ENQ4FET, 0);
		power_supply_changed(sm->psy_usb);
		/*
		 * UPower keeps a separate battery object.  Wake it as well when
		 * external power changes, even if STATUS2 has not yet moved from
		 * NOT_CHARGING to CHARGING.
		 */
		power_supply_changed(sm->psy_bat);
	}

	if (usb_type >= 0 && usb_type != sm->last_usb_type) {
		sm->last_usb_type = usb_type;
		power_supply_changed(sm->psy_usb);
	}

	schedule_delayed_work(&sm->poll_work,
			      msecs_to_jiffies(SM5714_POLL_INTERVAL_MS));
}

static void sm5714_cancel_poll(void *data)
{
	struct sm5714_battery *sm = data;

	cancel_delayed_work_sync(&sm->poll_work);
}

static void sm5714_clear_primary(void *data)
{
	struct sm5714_battery *sm = data;

	mutex_lock(&sm5714_global_lock);
	if (sm5714_primary == sm)
		sm5714_primary = NULL;
	mutex_unlock(&sm5714_global_lock);
}

static int sm5714_suspend(struct device *dev)
{
	struct sm5714_battery *sm = dev_get_drvdata(dev);

	cancel_delayed_work_sync(&sm->poll_work);
	return 0;
}

static int sm5714_resume(struct device *dev)
{
	struct sm5714_battery *sm = dev_get_drvdata(dev);

	schedule_delayed_work(&sm->poll_work, 0);
	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(sm5714_pm_ops, sm5714_suspend, sm5714_resume);

static int sm5714_probe(struct i2c_client *client)
{
	struct power_supply_config psy_cfg = {};
	struct device *dev = &client->dev;
	struct sm5714_battery *sm;
	int ret;

	if (!i2c_check_functionality(client->adapter,
				     I2C_FUNC_SMBUS_BYTE_DATA |
				     I2C_FUNC_SMBUS_WORD_DATA))
		return -EOPNOTSUPP;

	sm = devm_kzalloc(dev, sizeof(*sm), GFP_KERNEL);
	if (!sm)
		return -ENOMEM;

	sm->dev = dev;
	sm->chg = client;
	i2c_set_clientdata(client, sm);

	sm->battery_temp = devm_iio_channel_get(dev, "battery-temp");
	if (IS_ERR(sm->battery_temp))
		return dev_err_probe(dev, PTR_ERR(sm->battery_temp),
				     "cannot get battery thermistor\n");

	ret = devm_mutex_init(dev, &sm->sram_lock);
	if (ret)
		return ret;
	ret = devm_mutex_init(dev, &sm->chg_lock);
	if (ret)
		return ret;

	ret = i2c_smbus_read_byte_data(client, SM5714_CHG_REG_DEVICEID);
	if (ret < 0)
		return dev_err_probe(dev, ret, "no charger at 0x%02x\n",
				     client->addr);
	dev_info(dev, "SM5714 charger device id 0x%02x\n", ret);

	sm->fg = devm_i2c_new_dummy_device(dev, client->adapter,
					   SM5714_FG_I2C_ADDR);
	if (IS_ERR(sm->fg))
		return dev_err_probe(dev, PTR_ERR(sm->fg),
				     "cannot claim fuel gauge at 0x%02x\n",
				     SM5714_FG_I2C_ADDR);

	ret = i2c_smbus_read_word_data(sm->fg, SM5714_FG_REG_DEVICE_ID);
	if (ret < 0)
		return dev_err_probe(dev, ret, "no fuel gauge at 0x%02x\n",
				     SM5714_FG_I2C_ADDR);
	dev_info(dev, "SM5714 fuel gauge device id 0x%04x\n", ret);

	sm->muic = devm_i2c_new_dummy_device(dev, client->adapter,
					     SM5714_MUIC_I2C_ADDR);
	if (IS_ERR(sm->muic))
		return dev_err_probe(dev, PTR_ERR(sm->muic),
				     "cannot claim MUIC at 0x%02x\n",
				     SM5714_MUIC_I2C_ADDR);

	ret = i2c_smbus_read_byte_data(sm->muic, SM5714_MUIC_REG_DEVICE_ID);
	if (ret < 0)
		return dev_err_probe(dev, ret, "no MUIC at 0x%02x\n",
				     SM5714_MUIC_I2C_ADDR);
	dev_info(dev, "SM5714 MUIC device id 0x%02x\n", ret);

	psy_cfg.drv_data = sm;
	psy_cfg.fwnode = dev_fwnode(dev);

	sm->psy_bat = devm_power_supply_register(dev, &sm5714_bat_desc,
						 &psy_cfg);
	if (IS_ERR(sm->psy_bat))
		return dev_err_probe(dev, PTR_ERR(sm->psy_bat),
				     "cannot register battery\n");

	sm->psy_usb = devm_power_supply_register(dev, &sm5714_usb_desc,
						 &psy_cfg);
	if (IS_ERR(sm->psy_usb))
		return dev_err_probe(dev, PTR_ERR(sm->psy_usb),
				     "cannot register charger\n");

	ret = 0;
	mutex_lock(&sm5714_global_lock);
	if (sm5714_primary)
		ret = -EBUSY;
	else
		sm5714_primary = sm;
	mutex_unlock(&sm5714_global_lock);
	if (ret)
		return dev_err_probe(dev, ret, "only one SM5714 is supported\n");
	ret = devm_add_action_or_reset(dev, sm5714_clear_primary, sm);
	if (ret)
		return ret;

	/* Design capacity is board data; absent monitored-battery, skip it. */
	if (power_supply_get_battery_info(sm->psy_bat, &sm->info))
		sm->info = NULL;

	sm->last_status = sm5714_get_status(sm);
	if (sm5714_get_capacity(sm, &sm->last_capacity))
		sm->last_capacity = -1;
	sm->last_online = sm5714_get_online(sm) > 0;
	sm->last_usb_type = sm5714_get_usb_type(sm);

	if (sm->last_online &&
	    sm->last_status == POWER_SUPPLY_STATUS_NOT_CHARGING) {
		ret = sm5714_configure_charging(sm);
		if (ret)
			dev_warn(dev, "cannot restore charging state: %d\n", ret);
		else
			sm->last_status = sm5714_get_status(sm);
	}

	INIT_DELAYED_WORK(&sm->poll_work, sm5714_poll_work);
	ret = devm_add_action_or_reset(dev, sm5714_cancel_poll, sm);
	if (ret)
		return ret;
	schedule_delayed_work(&sm->poll_work,
			      msecs_to_jiffies(SM5714_POLL_INTERVAL_MS));

	return 0;
}

static const struct of_device_id sm5714_of_match[] = {
	{ .compatible = "siliconmitus,sm5714" },
	{ }
};
MODULE_DEVICE_TABLE(of, sm5714_of_match);

static const struct i2c_device_id sm5714_i2c_id[] = {
	{ "sm5714" },
	{ }
};
MODULE_DEVICE_TABLE(i2c, sm5714_i2c_id);

static struct i2c_driver sm5714_driver = {
	.driver = {
		.name = "sm5714-battery",
		.of_match_table = sm5714_of_match,
		.pm = pm_sleep_ptr(&sm5714_pm_ops),
	},
	.probe = sm5714_probe,
	.id_table = sm5714_i2c_id,
};
module_i2c_driver(sm5714_driver);

MODULE_DESCRIPTION("Silicon Mitus SM5714 charger and fuel gauge");
MODULE_LICENSE("GPL");
