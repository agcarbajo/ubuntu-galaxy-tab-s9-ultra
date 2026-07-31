// SPDX-License-Identifier: GPL-2.0-only
/*
 * Silicon Mitus SM5714 USB Type-C / USB-PD controller.
 *
 * This is a clean TCPM transport driver based on the register-level behaviour
 * documented by Samsung's GPL downstream driver.  The policy engine remains
 * Linux TCPM; none of Samsung's private notifier, battery or altmode framework
 * is copied here.
 */

#include <linux/bitops.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/regmap.h>
#include <linux/usb/pd.h>
#include <linux/usb/tcpm.h>
#include <linux/workqueue.h>

#define SM5714_REG_INT1			0x01
#define SM5714_REG_MASK1		0x06
#define SM5714_REG_STATUS1		0x0b
#define  SM5714_INT1_VBUS_POK		BIT(0)
#define  SM5714_INT1_ATTACH		BIT(3)
#define  SM5714_INT1_DETACH		BIT(4)
#define  SM5714_INT2_SRC_ADV		BIT(4)
#define  SM5714_INT2_VBUS_0V		BIT(5)
#define  SM5714_INT4_RX_DONE		BIT(0)
#define  SM5714_INT4_TX_DONE		BIT(1)
#define  SM5714_INT4_TX_SOP_ERR	BIT(2)
#define  SM5714_INT4_PRL_RST_DONE	BIT(4)
#define  SM5714_INT4_HRST_RX		BIT(5)
#define  SM5714_INT4_HCRST_DONE	BIT(6)
#define  SM5714_INT4_TX_DISCARD	BIT(7)

#define SM5714_REG_CORR_CNTL4		0x23
#define SM5714_REG_CORR_CNTL5		0x24
#define SM5714_REG_CC_STATUS		0x28
#define  SM5714_CC_ATTACH_MASK		GENMASK(2, 0)
#define  SM5714_CC_ATTACH_SOURCE	1
#define  SM5714_CC_ATTACH_SINK		2
#define  SM5714_CC_ATTACH_AUDIO	3
#define  SM5714_CC_RP_MASK		GENMASK(4, 3)
#define  SM5714_CC_FLIPPED		BIT(5)
#define  SM5714_CC_POWERED_CABLE	BIT(6)
#define SM5714_REG_CC_CNTL1		0x29
#define SM5714_REG_CC_CNTL3		0x2b
#define SM5714_REG_CC_CNTL5		0x2d
#define SM5714_REG_CC_CNTL7		0x2f
#define SM5714_REG_PD_CNTL1		0x38
#define SM5714_REG_PD_CNTL2		0x39
#define SM5714_REG_PD_CNTL4		0x3b
#define  SM5714_PD_HARD_RESET		BIT(2)
#define SM5714_REG_RX_SRC		0x41
#define SM5714_REG_RX_HEADER		0x42
#define SM5714_REG_RX_PAYLOAD		0x44
#define SM5714_REG_RX_BUF		0x5e
#define SM5714_REG_RX_BUF_ST		0x5f
#define SM5714_REG_TX_HEADER		0x60
#define SM5714_REG_TX_PAYLOAD		0x62
#define SM5714_REG_TX_REQ		0x7e
#define SM5714_REG_PD_STATE3		0xd8

/* Implemented by the companion charger/fuel-gauge driver on this board. */
int sm5714_battery_set_pd_contract(unsigned int mv, unsigned int ma);
int sm5714_battery_set_otg(bool active);
bool sm5714_battery_is_otg_active(void);

struct sm5714_usbpd {
	struct device *dev;
	struct regmap *regmap;
	struct mutex lock;
	struct tcpc_dev tcpc;
	struct tcpm_port *port;
	struct fwnode_handle *connector;
	struct delayed_work cc_resync_work;
	struct delayed_work otg_det_work;
	struct gpio_desc *otg_det_gpio;
	enum typec_cc_polarity polarity;
	bool pr_swap_src_to_snk;
	bool pr_swap_snk_to_src;
	bool retained_sink_dfp;
	bool retained_dock_reset;
	unsigned int negotiated_mv;
	unsigned int negotiated_ma;
};

static const struct regmap_config sm5714_usbpd_regmap_config = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = 0xff,
	.cache_type = REGCACHE_NONE,
};

static inline struct sm5714_usbpd *tcpc_to_sm5714(struct tcpc_dev *tcpc)
{
	return container_of(tcpc, struct sm5714_usbpd, tcpc);
}

static int sm5714_usbpd_set_cc_hold(struct sm5714_usbpd *sm, u8 hold)
{
	return regmap_update_bits(sm->regmap, SM5714_REG_CC_CNTL3,
				  GENMASK(5, 4), hold);
}

static void sm5714_usbpd_cc_resync_work(struct work_struct *work)
{
	struct sm5714_usbpd *sm =
		container_of(to_delayed_work(work), struct sm5714_usbpd,
			     cc_resync_work);
	unsigned int cc;

	if (IS_ERR_OR_NULL(sm->port))
		return;

	if (!regmap_read(sm->regmap, SM5714_REG_CC_STATUS, &cc))
		dev_info(sm->dev, "resynchronizing TCPM, CC status 0x%02x\n",
			 cc);
	tcpm_cc_change(sm->port);
	tcpm_vbus_change(sm->port);
}

static void sm5714_usbpd_otg_det_work(struct work_struct *work)
{
	struct sm5714_usbpd *sm =
		container_of(to_delayed_work(work), struct sm5714_usbpd,
			     otg_det_work);

	gpiod_set_value_cansleep(sm->otg_det_gpio, 0);
}

static int sm5714_usbpd_init(struct tcpc_dev *tcpc)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	unsigned int state3;
	u8 pending[5];
	static const u8 masks[5] = {
		0xe6, /* VBUS valid, attach and detach */
		0xcf, /* advertised current and VBUS 0 V */
		0xff,
		0x08, /* all PD transport events; bit 3 is unused */
		0xff,
	};
	int ret;

	mutex_lock(&sm->lock);

	/* Match the non-water-detection part of Samsung's register init. */
	ret = regmap_write(sm->regmap, SM5714_REG_CORR_CNTL5, 0x00);
	if (ret)
		goto out;
	ret = regmap_write(sm->regmap, SM5714_REG_CORR_CNTL4, 0x00);
	if (ret)
		goto out;
	ret = regmap_read(sm->regmap, SM5714_REG_PD_STATE3, &state3);
	if (ret)
		goto out;
	/*
	 * The controller and a powered partner can both retain PD state across
	 * an AP reboot.  Flush any partial message and protocol event left in
	 * the RX window before resetting the protocol layer.  Without this, a
	 * retained-dock CC reset can deliver Source_Capabilities but then expose
	 * a stale hard reset before TCPM has transmitted its Request.
	 *
	 * This is the same RX-buffer flush used by Samsung's
	 * sm5714_protocol_layer_reset().
	 */
	ret = regmap_write(sm->regmap, SM5714_REG_RX_BUF_ST, 0x10);
	if (ret)
		goto out;
	if (state3 & 0x06) {
		ret = regmap_write(sm->regmap, SM5714_REG_PD_CNTL4, 0x01);
		if (ret)
			goto out;
	}

	/* Reading the interrupt block clears stale edge latches. */
	ret = regmap_bulk_read(sm->regmap, SM5714_REG_INT1,
			       pending, sizeof(pending));
	if (ret)
		goto out;
	ret = regmap_bulk_write(sm->regmap, SM5714_REG_MASK1,
				masks, sizeof(masks));
out:
	mutex_unlock(&sm->lock);
	return ret;
}

static int sm5714_usbpd_get_vbus(struct tcpc_dev *tcpc)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	unsigned int status;
	int ret;

	ret = regmap_read(sm->regmap, SM5714_REG_STATUS1, &status);
	if (ret)
		return ret;

	/*
	 * STATUS1.VBUS_POK reports an external source but stays low while the
	 * companion charger supplies VBUS from its OTG boost.  Returning false
	 * in that state makes TCPM tear a valid source attachment down after
	 * tSrcTurnOn (480 ms), before a bus-powered hub can enumerate.
	 */
	return !!(status & SM5714_INT1_VBUS_POK) ||
	       sm5714_battery_is_otg_active();
}

static enum typec_cc_status sm5714_usbpd_rp_status(unsigned int cc)
{
	switch (cc & SM5714_CC_RP_MASK) {
	case 0x08:
		return TYPEC_CC_RP_1_5;
	case 0x10:
	case 0x18:
		return TYPEC_CC_RP_3_0;
	default:
		return TYPEC_CC_RP_DEF;
	}
}

static int sm5714_usbpd_get_current_limit(struct tcpc_dev *tcpc)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	unsigned int cc;
	int ret;

	ret = regmap_read(sm->regmap, SM5714_REG_CC_STATUS, &cc);
	if (ret)
		return ret;

	switch (sm5714_usbpd_rp_status(cc)) {
	case TYPEC_CC_RP_3_0:
		return 3000;
	case TYPEC_CC_RP_1_5:
		return 1500;
	default:
		return 500;
	}
}

static int sm5714_usbpd_get_cc(struct tcpc_dev *tcpc,
			       enum typec_cc_status *cc1,
			       enum typec_cc_status *cc2)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	enum typec_cc_status active = TYPEC_CC_OPEN;
	enum typec_cc_status inactive = TYPEC_CC_OPEN;
	unsigned int cc;
	bool flipped;
	int ret;

	ret = regmap_read(sm->regmap, SM5714_REG_CC_STATUS, &cc);
	if (ret)
		return ret;

	switch (cc & SM5714_CC_ATTACH_MASK) {
	case SM5714_CC_ATTACH_SOURCE:
		active = sm5714_usbpd_rp_status(cc);
		break;
	case SM5714_CC_ATTACH_SINK:
		active = TYPEC_CC_RD;
		/*
		 * Samsung calls bit 6 CABLE_TYPE.  In source/host mode it
		 * denotes Ra on the unused CC pin and the downstream driver
		 * immediately enables VCONN.  Report Ra to TCPM so its normal
		 * policy requests VCONN through sm5714_usbpd_set_vconn().
		 */
		if (cc & SM5714_CC_POWERED_CABLE)
			inactive = TYPEC_CC_RA;
		break;
	case SM5714_CC_ATTACH_AUDIO:
		*cc1 = TYPEC_CC_RA;
		*cc2 = TYPEC_CC_RA;
		return 0;
	default:
		break;
	}

	flipped = cc & SM5714_CC_FLIPPED;
	*cc1 = flipped ? inactive : active;
	*cc2 = flipped ? active : inactive;
	return 0;
}

static int sm5714_usbpd_set_cc(struct tcpc_dev *tcpc,
			       enum typec_cc_status cc)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	unsigned int role;
	unsigned int status;
	int ret;

	mutex_lock(&sm->lock);
	switch (cc) {
	case TYPEC_CC_OPEN:
		sm->pr_swap_src_to_snk = false;
		sm->pr_swap_snk_to_src = false;
		sm5714_usbpd_set_cc_hold(sm, 0);
		ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL3, 0x88);
		break;
	case TYPEC_CC_RD:
		ret = regmap_read(sm->regmap, SM5714_REG_CC_STATUS,
				  &status);
		if (ret)
			break;
		if ((status & SM5714_CC_ATTACH_MASK) ==
		    SM5714_CC_ATTACH_SOURCE)
			break;
		if (sm->pr_swap_src_to_snk) {
			/*
			 * Apply an in-place Source -> Sink PR_SWAP.  Forcing
			 * CC_CNTL1/3 here briefly opens both CC pins and the
			 * powered dock disappears before TCPM can complete the
			 * swap.  Samsung's driver toggles bit 0 of CC_CNTL7 for
			 * both PR_SWAP directions; the SM5714 then changes the
			 * pull while preserving the existing attachment.
			 */
			ret = sm5714_usbpd_set_cc_hold(sm, 0x10);
			if (!ret)
				ret = regmap_read(sm->regmap,
						  SM5714_REG_CC_CNTL7, &role);
			if (!ret)
				ret = regmap_write(sm->regmap,
						   SM5714_REG_CC_CNTL7,
						   role ^ BIT(0));
			if (!ret)
				dev_info(sm->dev,
					 "Source-to-Sink PR_SWAP: CC hold applied\n");
			break;
		}

		/* No natural DRP attachment exists: force sink/UFP. */
		ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL1, 0x45);
		if (!ret)
			ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL3,
					   0x82);
		break;
	case TYPEC_CC_RP_DEF:
	case TYPEC_CC_RP_1_5:
	case TYPEC_CC_RP_3_0:
		/*
		 * Force source/DFP mode with the board's stock Rp advertisement.
		 *
		 * TCPM derives its initial Rp from the source PDO and asks for
		 * RP_1_5 for the 900 mA OTG supply.  On this SM5714, however,
		 * CC_CNTL1=0x59 repeatedly drops an attached passive OTG dongle.
		 * Samsung's X910 driver explicitly changes PLUG_CTRL_RP180 back
		 * to PLUG_CTRL_RP80 (CC_CNTL1=0x49) on source attachment, before
		 * enabling VBUS.  Keep that hardware-specific behaviour here.
		 * PD-capable partners still learn the real 900 mA limit from the
		 * source PDO; non-PD accessories see the safe default USB current.
		 */
		ret = regmap_read(sm->regmap, SM5714_REG_CC_STATUS,
				  &status);
		if (ret)
			break;
		if ((status & SM5714_CC_ATTACH_MASK) ==
		    SM5714_CC_ATTACH_SINK) {
			/*
			 * The autonomous DRP engine already owns this natural
			 * attachment.  Samsung leaves mode 0x40/0x80 intact
			 * and only changes the Rp selection in bits 5:4.
			 * Forcing 0x49/0x81 here generates an immediate DETACH.
			 */
			ret = regmap_update_bits(sm->regmap,
						 SM5714_REG_CC_CNTL1,
						 GENMASK(5, 4), 0);
			break;
		}
		if (sm->pr_swap_snk_to_src) {
			/* Apply the inverse Sink -> Source PR_SWAP in place. */
			ret = regmap_read(sm->regmap, SM5714_REG_CC_CNTL7,
					  &role);
			if (!ret)
				ret = regmap_write(sm->regmap,
						   SM5714_REG_CC_CNTL7,
						   role ^ BIT(0));
			if (!ret)
				dev_info(sm->dev,
					 "Sink-to-Source PR_SWAP: Rp applied\n");
			break;
		}

		/* No natural DRP attachment exists: force source/DFP. */
		ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL1, 0x49);
		if (!ret)
			ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL3,
					   0x81);
		break;
	default:
		ret = -EOPNOTSUPP;
		break;
	}
	mutex_unlock(&sm->lock);

	return ret;
}

static int sm5714_usbpd_start_toggling(struct tcpc_dev *tcpc,
				       enum typec_port_type port_type,
				       enum typec_cc_status cc)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	unsigned int val = 0x40;
	int ret;

	/*
	 * The SM5714 has an autonomous DRP state machine.  Samsung's NORMAL_DRP
	 * configuration selects it with CC_CNTL1=0x40; bits 5:4 retain the Rp
	 * advertisement requested by TCPM.  Using the hardware state machine is
	 * not merely an optimisation: software toggling would keep issuing I2C
	 * transfers after the QUP controller has suspended.
	 */
	if (port_type == TYPEC_PORT_SRC)
		return sm5714_usbpd_set_cc(tcpc, cc);
	if (port_type == TYPEC_PORT_SNK)
		return sm5714_usbpd_set_cc(tcpc, TYPEC_CC_RD);

	/*
	 * Use the same default Rp while the autonomous DRP engine toggles.
	 * See sm5714_usbpd_set_cc(): the stock X910 policy does not retain
	 * Rp 1.5 A after detecting a source/host attachment.
	 */

	mutex_lock(&sm->lock);
	sm->pr_swap_src_to_snk = false;
	sm->pr_swap_snk_to_src = false;
	sm5714_usbpd_set_cc_hold(sm, 0);
	ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL1, val);
	/*
	 * set_cc(OPEN) disables both CC comparators with CC_CNTL3=0x88.
	 * Merely selecting NORMAL_DRP in CC_CNTL1 does not clear that latch,
	 * leaving TCPM permanently unattached.  Samsung's downstream
	 * sm5714_check_cc_state() restores CC operation with 0x80.
	 */
	if (!ret)
		ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL3, 0x80);
	mutex_unlock(&sm->lock);

	return ret;
}

static int sm5714_usbpd_set_polarity(struct tcpc_dev *tcpc,
				     enum typec_cc_polarity polarity)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);

	sm->polarity = polarity;
	return 0;
}

static int sm5714_usbpd_set_vconn(struct tcpc_dev *tcpc, bool on)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	u8 val;

	if (!on)
		val = 0x18;
	else
		val = sm->polarity == TYPEC_POLARITY_CC1 ? 0x19 : 0x1a;

	return regmap_write(sm->regmap, SM5714_REG_CC_CNTL5, val);
}

static int sm5714_usbpd_set_vbus(struct tcpc_dev *tcpc, bool on, bool charge)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	int ret;

	/*
	 * Samsung freezes the detected CC state before removing VBUS in a
	 * Source-to-Sink PR_SWAP.  TCPM already supplies the stock 25 ms and
	 * 350 ms timing windows; without this SM5714-specific latch the powered
	 * dock electrically detaches while it is taking over as the new source.
	 */
	if (!on && sm->pr_swap_src_to_snk) {
		mutex_lock(&sm->lock);
		ret = sm5714_usbpd_set_cc_hold(sm, 0x20);
		mutex_unlock(&sm->lock);
		if (ret)
			return ret;
		dev_info(sm->dev,
			 "Source-to-Sink PR_SWAP: CC state frozen\n");
	}

	/*
	 * The X910 stock driver pulses usbpd,otg_det high for 130 ms on every
	 * source attachment.  This board signal is distinct from the SM5714
	 * boost controls: without it the PTN3222 reaches host Connect Detect,
	 * but never observes the downstream USB2 pull-up.
	 */
	if (on && sm->otg_det_gpio) {
		gpiod_set_value_cansleep(sm->otg_det_gpio, 1);
		mod_delayed_work(system_dfl_wq, &sm->otg_det_work,
				 msecs_to_jiffies(130));
	}

	ret = sm5714_battery_set_otg(on);
	if (!ret && on && sm->pr_swap_snk_to_src) {
		sm->pr_swap_snk_to_src = false;
		dev_info(sm->dev,
			 "Sink-to-Source PR_SWAP: VBUS source enabled\n");
	}
	if (ret || !on) {
		cancel_delayed_work(&sm->otg_det_work);
		if (sm->otg_det_gpio)
			gpiod_set_value_cansleep(sm->otg_det_gpio, 0);
	}

	return ret;
}

static int sm5714_usbpd_set_current_limit(struct tcpc_dev *tcpc,
					  u32 max_ma, u32 mv)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	int ret;

	ret = sm5714_battery_set_pd_contract(mv, max_ma);
	if (ret)
		return ret;

	sm->negotiated_mv = mv;
	sm->negotiated_ma = max_ma;
	dev_info(sm->dev, "USB-PD contract: %u mV, %u mA\n", mv, max_ma);
	return 0;
}

static int sm5714_usbpd_set_pd_rx(struct tcpc_dev *tcpc, bool on)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);

	return regmap_write(sm->regmap, SM5714_REG_PD_CNTL1,
			    on ? 0x08 : 0x00);
}

static bool sm5714_usbpd_consume_retained_sink_dfp(struct tcpc_dev *tcpc)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	bool retained = sm->retained_sink_dfp;

	sm->retained_sink_dfp = false;
	return retained;
}

static int sm5714_usbpd_set_roles(struct tcpc_dev *tcpc, bool attached,
				  enum typec_role role,
				  enum typec_data_role data)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	unsigned int val;
	int ret;

	ret = regmap_read(sm->regmap, SM5714_REG_PD_CNTL2, &val);
	if (ret)
		return ret;

	if (role == TYPEC_SOURCE)
		val |= BIT(1);
	else
		val &= ~BIT(1);
	if (data == TYPEC_HOST)
		val |= BIT(0);
	else
		val &= ~BIT(0);

	return regmap_write(sm->regmap, SM5714_REG_PD_CNTL2, val);
}

static int sm5714_usbpd_transmit(struct tcpc_dev *tcpc,
				 enum tcpm_transmit_type type,
				 const struct pd_message *msg,
				 unsigned int negotiated_rev)
{
	struct sm5714_usbpd *sm = tcpc_to_sm5714(tcpc);
	unsigned int count;
	u8 request;
	int ret;

	mutex_lock(&sm->lock);

	if (type == TCPC_TX_HARD_RESET) {
		ret = regmap_update_bits(sm->regmap, SM5714_REG_PD_CNTL4,
					 SM5714_PD_HARD_RESET,
					 SM5714_PD_HARD_RESET);
		goto out;
	}

	switch (type) {
	case TCPC_TX_SOP:
		request = 0x07;
		break;
	case TCPC_TX_SOP_PRIME:
		request = 0x17;
		break;
	case TCPC_TX_SOP_PRIME_PRIME:
		request = 0x27;
		break;
	default:
		ret = -EOPNOTSUPP;
		goto out;
	}

	count = pd_header_cnt_le(msg->header);
	ret = regmap_bulk_write(sm->regmap, SM5714_REG_TX_HEADER,
				&msg->header, sizeof(msg->header));
	if (ret)
		goto out;
	if (count) {
		ret = regmap_bulk_write(sm->regmap, SM5714_REG_TX_PAYLOAD,
					msg->payload,
					count * sizeof(msg->payload[0]));
		if (ret)
			goto out;
	}
	ret = regmap_write(sm->regmap, SM5714_REG_TX_REQ, request);
out:
	mutex_unlock(&sm->lock);
	return ret;
}

static void sm5714_usbpd_receive(struct sm5714_usbpd *sm)
{
	struct pd_message msg = {};
	enum tcpm_transmit_type sop;
	unsigned int origin;
	unsigned int status;
	unsigned int count;
	u8 type;
	int ret;

	ret = regmap_bulk_read(sm->regmap, SM5714_REG_RX_HEADER,
			       &msg.header, sizeof(msg.header));
	if (ret)
		return;
	count = pd_header_cnt_le(msg.header);
	if (count > PD_MAX_PAYLOAD)
		goto acknowledge;
	if (count) {
		ret = regmap_bulk_read(sm->regmap, SM5714_REG_RX_PAYLOAD,
				       msg.payload,
				       count * sizeof(msg.payload[0]));
		if (ret)
			goto acknowledge;
	}
	ret = regmap_read(sm->regmap, SM5714_REG_RX_SRC, &origin);
	if (ret)
		goto acknowledge;

	switch (origin & 0x0f) {
	case 0:
		sop = TCPC_TX_SOP;
		break;
	case 1:
		sop = TCPC_TX_SOP_PRIME;
		break;
	case 2:
		sop = TCPC_TX_SOP_PRIME_PRIME;
		break;
	default:
		goto acknowledge;
	}

	type = pd_header_type_le(msg.header);
	if (sop == TCPC_TX_SOP && !count && type == PD_CTRL_PR_SWAP) {
		ret = regmap_read(sm->regmap, SM5714_REG_CC_STATUS, &status);
		if (!ret) {
			if ((status & SM5714_CC_ATTACH_MASK) ==
			    SM5714_CC_ATTACH_SINK)
				sm->pr_swap_src_to_snk = true;
			else if ((status & SM5714_CC_ATTACH_MASK) ==
				 SM5714_CC_ATTACH_SOURCE)
				sm->pr_swap_snk_to_src = true;
		}
	}
	if (sop == TCPC_TX_SOP && !count && type == PD_CTRL_PS_RDY &&
	    sm->pr_swap_src_to_snk) {
		ret = sm5714_usbpd_set_cc_hold(sm, 0);
		if (!ret) {
			sm->pr_swap_src_to_snk = false;
			dev_info(sm->dev,
				 "Source-to-Sink PR_SWAP: CC hold released\n");
		}
	}
	tcpm_pd_receive(sm->port, &msg, sop);

acknowledge:
	regmap_write(sm->regmap, SM5714_REG_RX_BUF, 0x80);
}

static irqreturn_t sm5714_usbpd_irq(int irq, void *data)
{
	struct sm5714_usbpd *sm = data;
	u8 intr[5];
	int ret;

	mutex_lock(&sm->lock);
	ret = regmap_bulk_read(sm->regmap, SM5714_REG_INT1,
			       intr, sizeof(intr));
	if (ret) {
		mutex_unlock(&sm->lock);
		return IRQ_NONE;
	}

	if (intr[3] & SM5714_INT4_RX_DONE)
		sm5714_usbpd_receive(sm);
	if (intr[3] & SM5714_INT4_TX_DONE)
		tcpm_pd_transmit_complete(sm->port, TCPC_TX_SUCCESS);
	else if (intr[3] & SM5714_INT4_TX_DISCARD)
		tcpm_pd_transmit_complete(sm->port, TCPC_TX_DISCARDED);
	else if (intr[3] & SM5714_INT4_TX_SOP_ERR)
		tcpm_pd_transmit_complete(sm->port, TCPC_TX_FAILED);
	if (intr[3] & SM5714_INT4_HRST_RX)
		tcpm_pd_hard_reset(sm->port);

	mutex_unlock(&sm->lock);

	if (intr[0] & (SM5714_INT1_ATTACH | SM5714_INT1_DETACH) ||
	    intr[1] & SM5714_INT2_SRC_ADV)
		tcpm_cc_change(sm->port);
	if (intr[0] & SM5714_INT1_VBUS_POK ||
	    intr[1] & SM5714_INT2_VBUS_0V)
		tcpm_vbus_change(sm->port);

	return IRQ_HANDLED;
}

static int sm5714_usbpd_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct sm5714_usbpd *sm;
	unsigned int cc;
	unsigned int retained_roles;
	int ret;

	sm = devm_kzalloc(dev, sizeof(*sm), GFP_KERNEL);
	if (!sm)
		return -ENOMEM;

	sm->dev = dev;
	sm->regmap = devm_regmap_init_i2c(client,
					  &sm5714_usbpd_regmap_config);
	if (IS_ERR(sm->regmap))
		return PTR_ERR(sm->regmap);
	mutex_init(&sm->lock);
	INIT_DELAYED_WORK(&sm->cc_resync_work, sm5714_usbpd_cc_resync_work);
	INIT_DELAYED_WORK(&sm->otg_det_work, sm5714_usbpd_otg_det_work);
	i2c_set_clientdata(client, sm);

	sm->otg_det_gpio = devm_gpiod_get_optional(dev, "otg-det",
						   GPIOD_OUT_LOW);
	if (IS_ERR(sm->otg_det_gpio))
		return dev_err_probe(dev, PTR_ERR(sm->otg_det_gpio),
				     "failed to acquire OTG-detect GPIO\n");

	sm->connector = device_get_named_child_node(dev, "connector");
	if (!sm->connector)
		return dev_err_probe(dev, -EINVAL,
				     "missing usb-c-connector child\n");

	/*
	 * A powered dock and the SM5714 both survive a warm tablet reboot.  Save
	 * the controller's old local data role before tcpm_register_port()
	 * clears it while constructing the new unattached state.  CC must still
	 * describe a source attachment, so a previous PC/device connection can
	 * never seed DFP here.
	 */
	ret = regmap_read(sm->regmap, SM5714_REG_PD_CNTL2, &retained_roles);
	if (ret)
		goto put_fwnode;
	ret = regmap_read(sm->regmap, SM5714_REG_CC_STATUS, &cc);
	if (ret)
		goto put_fwnode;
	sm->retained_sink_dfp =
		(retained_roles & BIT(0)) &&
		((cc & SM5714_CC_ATTACH_MASK) == SM5714_CC_ATTACH_SOURCE);
	if (sm->retained_sink_dfp) {
		dev_info(dev, "retained Sink/DFP role detected\n");
		/*
		 * Keeping the data role is sufficient for USB host, but some
		 * powered docks retain their old PD/DisplayPort state and never
		 * send Source_Capabilities after the tablet reboots.  Present Rp
		 * briefly to create a real CC detach at the still-powered Source,
		 * then leave both pins open.  TCPM subsequently starts normal DRP
		 * toggling and the dock negotiates power, USB and altmodes from
		 * scratch exactly as it does after a physical reconnect.
		 */
		ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL1, 0x49);
		if (ret)
			goto put_fwnode;
		ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL3, 0x81);
		if (ret)
			goto put_fwnode;
		msleep(200);
		ret = regmap_write(sm->regmap, SM5714_REG_CC_CNTL3, 0x88);
		if (ret)
			goto put_fwnode;
		msleep(50);
		sm->retained_sink_dfp = false;
		sm->retained_dock_reset = true;
		dev_info(dev,
			 "reset retained dock with a CC detach before TCPM\n");
	}

	sm->tcpc.fwnode = sm->connector;
	/*
	 * A powered USB-C dock stays Source/UFP across an X910 reboot.  It is
	 * the power source but the USB data peripheral, so recover as
	 * Sink/DFP when its retained role appears in the first PD reply.
	 */
	sm->tcpc.adopt_retained_source_ufp = true;
	sm->tcpc.consume_retained_sink_dfp =
		sm5714_usbpd_consume_retained_sink_dfp;
	sm->tcpc.init = sm5714_usbpd_init;
	sm->tcpc.get_vbus = sm5714_usbpd_get_vbus;
	sm->tcpc.get_current_limit = sm5714_usbpd_get_current_limit;
	sm->tcpc.set_cc = sm5714_usbpd_set_cc;
	sm->tcpc.get_cc = sm5714_usbpd_get_cc;
	sm->tcpc.set_polarity = sm5714_usbpd_set_polarity;
	sm->tcpc.set_vconn = sm5714_usbpd_set_vconn;
	sm->tcpc.set_vbus = sm5714_usbpd_set_vbus;
	sm->tcpc.set_current_limit = sm5714_usbpd_set_current_limit;
	sm->tcpc.set_pd_rx = sm5714_usbpd_set_pd_rx;
	sm->tcpc.set_roles = sm5714_usbpd_set_roles;
	sm->tcpc.start_toggling = sm5714_usbpd_start_toggling;
	sm->tcpc.pd_transmit = sm5714_usbpd_transmit;

	sm->port = tcpm_register_port(dev, &sm->tcpc);
	if (IS_ERR(sm->port)) {
		ret = PTR_ERR(sm->port);
		goto put_fwnode;
	}

	ret = devm_request_threaded_irq(dev, client->irq, NULL,
					sm5714_usbpd_irq,
					IRQF_ONESHOT | IRQF_TRIGGER_LOW,
					dev_name(dev), sm);
	if (ret)
		goto unregister_port;

	device_init_wakeup(dev, true);
	enable_irq_wake(client->irq);
	/*
	 * CC comparators settle after the autonomous DRP machine is enabled.
	 * tcpm_register_port() can see Rp before the charger has raised VBUS:
	 * TCPM then spends about 1.02 seconds in PORT_RESET/PORT_RESET_WAIT_OFF.
	 * An earlier 250 ms resync was consumed inside that reset and left TCPM
	 * in TOGGLING forever when the physical attach edge predated the IRQ
	 * registration.  Wait until both that reset and VBUS ramp have finished.
	 *
	 * This remains deliberately scheduled only once: re-arming it from
	 * start_toggling() feeds back through tcpm_cc_change() and oscillates
	 * between host and unattached.
	 */
	/*
	 * A retained-dock reset creates a fresh physical CC/VBUS edge after the
	 * IRQ is registered.  Its first Source_Capabilities can still be in
	 * flight at 1.5 s, so do not let the fallback resync interrupt that
	 * negotiation.  Keep the fallback, but move it beyond the normal PD and
	 * altmode discovery window.
	 */
	mod_delayed_work(system_dfl_wq, &sm->cc_resync_work,
			 msecs_to_jiffies(sm->retained_dock_reset ? 3000 :
					  1500));
	dev_info(dev, "SM5714 USB Type-C/PD controller registered\n");
	return 0;

unregister_port:
	tcpm_unregister_port(sm->port);
put_fwnode:
	fwnode_handle_put(sm->connector);
	return ret;
}

static void sm5714_usbpd_remove(struct i2c_client *client)
{
	struct sm5714_usbpd *sm = i2c_get_clientdata(client);

	cancel_delayed_work_sync(&sm->cc_resync_work);
	cancel_delayed_work_sync(&sm->otg_det_work);
	if (sm->otg_det_gpio)
		gpiod_set_value_cansleep(sm->otg_det_gpio, 0);
	disable_irq_wake(client->irq);
	tcpm_unregister_port(sm->port);
	fwnode_handle_put(sm->connector);
}

static const struct of_device_id sm5714_usbpd_of_match[] = {
	{ .compatible = "siliconmitus,sm5714-usbpd" },
	{ }
};
MODULE_DEVICE_TABLE(of, sm5714_usbpd_of_match);

static struct i2c_driver sm5714_usbpd_driver = {
	.driver = {
		.name = "sm5714-usbpd",
		.of_match_table = sm5714_usbpd_of_match,
	},
	.probe = sm5714_usbpd_probe,
	.remove = sm5714_usbpd_remove,
};
module_i2c_driver(sm5714_usbpd_driver);

MODULE_DESCRIPTION("Silicon Mitus SM5714 USB Type-C and PD controller");
MODULE_LICENSE("GPL");
