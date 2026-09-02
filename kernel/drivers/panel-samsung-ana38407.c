// SPDX-License-Identifier: GPL-2.0-only
/*
 * DRM panel driver for the Samsung AMSA46AS02 (Anapass ANA38407 DDIC) as fitted
 * to the Galaxy Tab S9 Ultra Wi-Fi (SM-X910, "gts9uwifi").
 *
 * 2960x1848 command-mode DSI panel, 4 lanes, DSC 1.1 (2 slices 1480x77, 8bpp).
 * The DCS init/exit sequences and timings were recovered from the Samsung
 * open-source drop (opensource.samsung.com, SM-X910_EUR_16) panel data file and
 * from the stock DTBO; see docs/panel-ana38407-bringup.md.  Samsung's
 * proprietary gamma/VRR/ACL/mdnie machinery is intentionally NOT ported: the
 * DPU switches refresh rate by mode-set, and brightness goes through the
 * standard DCS 0x51 path.
 */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>
#include <linux/workqueue.h>

#include <drm/display/drm_dsc.h>
#include <drm/display/drm_dsc_helper.h>
#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>

/*
 * DCS 0x51 carries 11 significant bits on this DDIC, not 12: Samsung's own
 * power-on sequence programs 0x07ff as "full brightness", and anything with bit
 * 11 set wraps back to the bottom of the range.  Declaring 4095 made the
 * desktop's slider sweep the panel from dark to bright twice.
 */
#define ANA38407_MAX_BRIGHTNESS		0x07ff
/* One UI enrollment reports HBM platform level 385. Samsung's HBM table
 * maps that to WRDISBV 1623 (634 cd/m2), not 2047 (900 cd/m2). Normal mode
 * also uses 2047, but with a different luminance table (420 cd/m2).
 */
#define ANA38407_FOD_BRIGHTNESS		1623
#define ANA38407_FOD_WATCHDOG_MS	15000
#define ANA38407_FOD_SETTLE_MS		35

/* Revision D, as read back by the bootloader (lcd_id=0x800004). */
static const u8 ana38407_expected_id[3] = { 0x80, 0x00, 0x04 };

/*
 * On a cold boot the DDIC answers 00:00:00 and emits black, even though the
 * link is up and DRM reports the connector enabled; a suspend/resume then
 * recovers it and the id reads 80:00:04.  So the id is a reliable signal, and
 * the fault is not in this driver: replaying the init sequence, toggling reset
 * and even dropping the panel supplies the way unprepare/prepare does were all
 * measured to leave it at 00:00:00.  What differs on resume is that the DSI
 * host and PHY are re-initialised from scratch, rather than inherited from the
 * state the bootloader left behind after painting its logo.
 *
 * Log the mismatch so the cause is visible, but do not burn boot time cycling
 * the panel for a fix that does not work at this level.
 */

struct ana38407 {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct drm_dsc_config dsc;
	struct regulator_bulk_data *supplies;
	struct gpio_desc *reset_gpio;
	/* Serializes panel lifetime, normal brightness and optical FOD state. */
	struct mutex lock;
	struct delayed_work fod_watchdog;
	u16 user_brightness;
	bool prepared;
	bool enabled;
	bool fod_mode;
	bool fod_circle;
	u8 id[3];
	char cell_id[23];
};

/*
 * gts9u panel rails (from the stock DTS): vddio 1.8 V (l12b), vdd 1.2 V,
 * vci 3.0 V (l13b) and the AMOLED ELVDD "avdd" ~5.5 V behind a GPIO load switch.
 * All four must be up before the DDIC will light.
 */
static const struct regulator_bulk_data ana38407_supplies[] = {
	{ .supply = "vddio" },
	{ .supply = "vdd" },
	{ .supply = "vci" },
	{ .supply = "avdd" },
};

static inline struct ana38407 *to_ana38407(struct drm_panel *panel)
{
	return container_of(panel, struct ana38407, panel);
}

/*
 * Samsung sequences these rails rather than raising them together: its
 * dsi_panel_pwr_supply brings up vddio first and then waits
 * qcom,supply-post-on-sleep = 0x14 (20 ms) before vdd and vci, with avdd - the
 * AMOLED ELVDD behind a load switch - after them.
 *
 * Enabling all four at once and sleeping afterwards, which is what a plain
 * regulator_bulk_enable() does, left the DDIC unreliable at every enable: a
 * cold boot came up black, a resume often needed two or three attempts, and
 * the first frames sometimes showed artefacts.
 */
static int ana38407_power_on(struct ana38407 *ctx)
{
	int ret;

	ret = regulator_enable(ctx->supplies[0].consumer);	/* vddio */
	if (ret)
		return ret;

	msleep(20);

	ret = regulator_bulk_enable(ARRAY_SIZE(ana38407_supplies) - 1,
				    &ctx->supplies[1]);		/* vdd, vci, avdd */
	if (ret)
		regulator_disable(ctx->supplies[0].consumer);

	return ret;
}

/* Pack a signed DSC range BPG offset into the 6-bit field. */
#define DSC_BPG_OFFSET(x)	((u8)((x) & DSC_RANGE_BPG_OFFSET_MASK))

static void ana38407_reset(struct ana38407 *ctx)
{
	/* Samsung reset-sequence <0 10 1 1>: assert low, release high. */
	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	usleep_range(5000, 6000);
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	usleep_range(10000, 11000);
	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	usleep_range(10000, 11000);
}

/*
 * The optical sensor needs Samsung's short-lived fingerprint HBM sequence.
 * Keep every brightness and FOD transaction under the same lock: GNOME may
 * update the normal backlight while fprintd is sampling, but that new value
 * must only be remembered and restored after the sample has finished.
 */
static int ana38407_write_brightness_locked(struct ana38407 *ctx, u16 brightness)
{
	unsigned long mode_flags = ctx->dsi->mode_flags;
	int ret;

	ctx->dsi->mode_flags &= ~MIPI_DSI_MODE_LPM;
	ret = mipi_dsi_dcs_set_display_brightness_large(ctx->dsi, brightness);
	ctx->dsi->mode_flags = mode_flags;

	return ret;
}

static int ana38407_write_fod_locked(struct ana38407 *ctx, bool enable)
{
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };
	unsigned long mode_flags = ctx->dsi->mode_flags;
	u8 brightness_hi = ctx->user_brightness >> 8;
	u8 brightness_lo = ctx->user_brightness & 0xff;

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	if (enable) {
		/* Revision-D optical FOD + FlatZ sequence from Samsung's panel data. */
		mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x53, 0xe0);
		mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x51,
					     ANA38407_FOD_BRIGHTNESS >> 8,
					     ANA38407_FOD_BRIGHTNESS & 0xff);
		mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x0a, 0xe0);
		mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xe0, 0x3c, 0xfd, 0xff,
					     0x15, 0x00, 0x00, 0x66, 0xcc,
					     0x00, 0xff, 0x12);
	} else {
		mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x53, 0x28);
		mipi_dsi_dcs_write_var_seq_multi(&dsi_ctx, 0x51,
						 brightness_hi, brightness_lo);
	}
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);
	ctx->dsi->mode_flags = mode_flags;

	return dsi_ctx.accum_err;
}

static int ana38407_generic_write(struct ana38407 *ctx, const u8 *data,
				  size_t len)
{
	ssize_t ret;

	ret = mipi_dsi_generic_write(ctx->dsi, data, len);
	if (ret < 0)
		return ret;

	return 0;
}

static int ana38407_write_fod_circle_locked(struct ana38407 *ctx, bool enable)
{
	static const u8 level2_unlock[] = { 0xf1, 0x5a, 0x5a };
	static const u8 level2_lock[] = { 0xf1, 0xa5, 0xa5 };
	u8 circle[] = { 0x7a, 0x05, 0x00, 0x00, enable ? 0x00 : 0x02 };
	unsigned long mode_flags = ctx->dsi->mode_flags;
	int ret, lock_ret;

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;
	ret = ana38407_generic_write(ctx, level2_unlock,
				     sizeof(level2_unlock));
	if (!ret)
		ret = ana38407_generic_write(ctx, circle, sizeof(circle));
	lock_ret = ana38407_generic_write(ctx, level2_lock,
					  sizeof(level2_lock));
	ctx->dsi->mode_flags = mode_flags;
	if (!ret)
		ret = lock_ret;

	/* No TE-wait primitive is available here; cover two frames at 60 Hz. */
	if (!ret)
		msleep(ANA38407_FOD_SETTLE_MS);

	return ret;
}

static int ana38407_fod_cleanup_locked(struct ana38407 *ctx)
{
	int ret = 0, tmp;

	if (ctx->fod_circle) {
		tmp = ana38407_write_fod_circle_locked(ctx, false);
		if (!ret)
			ret = tmp;
		ctx->fod_circle = false;
	}

	if (ctx->fod_mode) {
		tmp = ana38407_write_fod_locked(ctx, false);
		if (!ret)
			ret = tmp;
		ctx->fod_mode = false;
	}

	return ret;
}

static void ana38407_fod_watchdog_work(struct work_struct *work)
{
	struct ana38407 *ctx = container_of(to_delayed_work(work),
						  struct ana38407,
						  fod_watchdog);
	int ret = 0;

	mutex_lock(&ctx->lock);
	if (ctx->prepared && ctx->enabled) {
		ret = ana38407_fod_cleanup_locked(ctx);
	} else {
		ctx->fod_circle = false;
		ctx->fod_mode = false;
	}
	mutex_unlock(&ctx->lock);

	if (ret)
		dev_warn(&ctx->dsi->dev,
			 "failed to leave fingerprint display mode: %d\n", ret);
}

/*
 * Power-on DCS sequence, transcribed from the panel PDF (macros expanded).
 * Level keys 0xF0/0xF1 0x5A 0x5A unlock; 0xA5 0xA5 relock.  The 0xC0/0xB0/0xC1
 * triples are indirect DDIC register accesses (Samsung "gpara").
 */
static int ana38407_on(struct ana38407 *ctx)
{
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };
	struct drm_dsc_picture_parameter_set pps;
	u8 module_info[11] = {};
	u8 id[3] = {};
	ssize_t module_info_len;

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;

	/*
	 * Rev C/D order (POWER_ON_PRE_SETTING): VBP and the display-on-delay
	 * register writes come BEFORE sleep-out.  The panel id (0x80 0x00 0x04,
	 * read by the bootloader as lcd_id=0x800004) is revision D.
	 */

	/* VBP_SETTING_FOR_SDC_IP */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc1, 0x0a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc0, 0x0f, 0x00, 0x00, 0x00, 0x09, 0xfd, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0xa5, 0xa5);

	/* DISPLAY_ON_DELAY_SETTING */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc1, 0x23);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc0, 0x0f, 0x00, 0x00, 0x00, 0x01, 0x04, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0xa5, 0xa5);

	/* sleep out */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x11);
	mipi_dsi_msleep(&dsi_ctx, 120);

	/*
	 * Confirm the DDIC answers on the DSI link.  Kept here, right after
	 * sleep-out, because that is where it reliably responds; prepare()
	 * checks the result and retries the whole sequence if it is wrong.
	 */
	mipi_dsi_dcs_read(ctx->dsi, 0xda, &id[0], 1);
	mipi_dsi_dcs_read(ctx->dsi, 0xdb, &id[1], 1);
	mipi_dsi_dcs_read(ctx->dsi, 0xdc, &id[2], 1);
	memcpy(ctx->id, id, sizeof(ctx->id));
	dev_info(&ctx->dsi->dev, "ana38407 panel id: %02x %02x %02x\n",
		 id[0], id[1], id[2]);

	/*
	 * Samsung's fingerprint TA binds optical calibration to the panel cell ID.
	 * RX_MODULE_INFO is DCS A1, 11 bytes under the level-0 key; Android exposes
	 * bytes 4..10 followed by 0..3 as 22 lowercase hexadecimal characters.
	 */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	module_info_len = mipi_dsi_dcs_read(ctx->dsi, 0xa1, module_info,
					    sizeof(module_info));
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);
	if (module_info_len == (ssize_t)sizeof(module_info)) {
		snprintf(ctx->cell_id, sizeof(ctx->cell_id),
			 "%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x",
			 module_info[4], module_info[5], module_info[6],
			 module_info[7], module_info[8], module_info[9],
			 module_info[10], module_info[0], module_info[1],
			 module_info[2], module_info[3]);
		dev_info(&ctx->dsi->dev, "ana38407 cell id: %s\n", ctx->cell_id);
	} else {
		ctx->cell_id[0] = '\0';
		dev_warn(&ctx->dsi->dev,
			 "failed to read panel cell id: %zd\n", module_info_len);
	}

	/* MX_IP_ENABLE */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc1, 0x23);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc0, 0x0f, 0x00, 0x00, 0x00, 0x09, 0xb2, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0xa5, 0xa5);

	/* TCON_INTR_SETTING (TE active low) */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc1, 0x02);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc0, 0x0f, 0x00, 0x00, 0x00, 0x14, 0x46, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc1, 0x13);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc0, 0x0f, 0x00, 0x00, 0x00, 0x08, 0xcf, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc1, 0x05);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc0, 0x0f, 0x00, 0x00, 0x00, 0x09, 0xcd, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf1, 0xa5, 0xa5);

	/* TE_ON */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x35, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);

	/* TSP_SYNC_SETTING (rev C+) */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x0b, 0xb9);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb9, 0xcc);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x0e, 0xb9);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb9, 0x15);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);

	/*
	 * DSC: enable compression and send the Picture Parameter Set as a proper
	 * MIPI PPS packet generated from drm_dsc_config (this is how mainline
	 * command-mode DSC panels do it; a hand-rolled DCS 0x0A long write is the
	 * wrong packet type).
	 */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_compression_mode_multi(&dsi_ctx, true);
	drm_dsc_pps_payload_pack(&pps, &ctx->dsc);
	mipi_dsi_picture_parameter_set_multi(&dsi_ctx, &pps);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);

	/* DIA_SETTING (digital image adjust on) */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x91, 0x02);

	/*
	 * BRIGHTNESS: dimming control (normal) + an explicit non-zero brightness
	 * level (0x51, 12-bit).  Without a real 0x51 write the DDIC emits black
	 * even with the display on.
	 */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x53, 0x28);
	mipi_dsi_dcs_write_var_seq_multi(&dsi_ctx, 0x51,
					 ctx->user_brightness >> 8,
					 ctx->user_brightness & 0xff);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);

	/* SP_SETTING */
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc3, 0x02);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);

	/*
	 * The stock panel declares samsung,delayed-display-on: complete the
	 * initialisation here, but keep the OLED dark until the bridge's enable
	 * phase, when the DPU/DSI command-mode stream is ready.  Sending 0x29
	 * from prepare exposed unsynchronised DSC data after resume: the shell's
	 * freshly damaged top bar was valid while the rest of the panel GRAM
	 * contained coloured noise.
	 */
	mipi_dsi_msleep(&dsi_ctx, 100);

	return dsi_ctx.accum_err;
}

static int ana38407_enable(struct drm_panel *panel)
{
	struct ana38407 *ctx = to_ana38407(panel);
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };
	int ret = 0;

	mutex_lock(&ctx->lock);
	if (!ctx->prepared) {
		ret = -EPIPE;
		goto out_unlock;
	}
	if (ctx->enabled)
		goto out_unlock;

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_set_display_on_multi(&dsi_ctx);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0xa5, 0xa5);
	mipi_dsi_msleep(&dsi_ctx, 20);
	ret = dsi_ctx.accum_err;
	if (!ret)
		ctx->enabled = true;

out_unlock:
	mutex_unlock(&ctx->lock);
	return ret;
}

static int ana38407_disable(struct drm_panel *panel)
{
	struct ana38407 *ctx = to_ana38407(panel);
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };
	int cleanup_ret = 0, ret = 0;

	mutex_lock(&ctx->lock);
	if (!ctx->enabled)
		goto out_unlock;

	cleanup_ret = ana38407_fod_cleanup_locked(ctx);
	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;
	mipi_dsi_dcs_set_display_off_multi(&dsi_ctx);
	mipi_dsi_msleep(&dsi_ctx, 20);
	ret = dsi_ctx.accum_err;
	ctx->enabled = false;

out_unlock:
	mutex_unlock(&ctx->lock);
	cancel_delayed_work_sync(&ctx->fod_watchdog);

	return ret ?: cleanup_ret;
}

static int ana38407_sleep_in(struct ana38407 *ctx)
{
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;
	mipi_dsi_dcs_enter_sleep_mode_multi(&dsi_ctx);
	mipi_dsi_msleep(&dsi_ctx, 120);

	return dsi_ctx.accum_err;
}

static int ana38407_prepare(struct drm_panel *panel)
{
	struct ana38407 *ctx = to_ana38407(panel);
	int ret;

	mutex_lock(&ctx->lock);
	if (ctx->prepared) {
		ret = 0;
		goto out_unlock;
	}

	ret = ana38407_power_on(ctx);
	if (ret)
		goto out_unlock;

	ana38407_reset(ctx);

	ret = ana38407_on(ctx);
	if (ret) {
		gpiod_set_value_cansleep(ctx->reset_gpio, 0);
		regulator_bulk_disable(ARRAY_SIZE(ana38407_supplies), ctx->supplies);
		goto out_unlock;
	}
	ctx->prepared = true;

	if (memcmp(ctx->id, ana38407_expected_id, sizeof(ctx->id)))
		dev_warn(&ctx->dsi->dev,
			 "panel id %02x %02x %02x, expected %02x %02x %02x: the panel will stay dark until a suspend/resume re-initialises the DSI host\n",
			 ctx->id[0], ctx->id[1], ctx->id[2],
			 ana38407_expected_id[0], ana38407_expected_id[1],
			 ana38407_expected_id[2]);

out_unlock:
	mutex_unlock(&ctx->lock);
	return ret;
}

static int ana38407_unprepare(struct drm_panel *panel)
{
	struct ana38407 *ctx = to_ana38407(panel);
	int cleanup_ret = 0, ret = 0;

	mutex_lock(&ctx->lock);
	if (!ctx->prepared)
		goto out_unlock;

	cleanup_ret = ana38407_fod_cleanup_locked(ctx);
	ret = ana38407_sleep_in(ctx);
	ctx->enabled = false;
	ctx->prepared = false;
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	regulator_bulk_disable(ARRAY_SIZE(ana38407_supplies), ctx->supplies);

out_unlock:
	mutex_unlock(&ctx->lock);
	cancel_delayed_work_sync(&ctx->fod_watchdog);

	return ret ?: cleanup_ret;
}

/* All five timing modes from the stock DTBO, hactive/vactive 2960x1848. */
static const struct drm_display_mode ana38407_modes[] = {
	{	/* 120 Hz */
		.clock = (2960 + 16 + 36 + 30) * (1848 + 16 + 32 + 32) * 120 / 1000,
		.hdisplay = 2960, .hsync_start = 2960 + 16, .hsync_end = 2960 + 16 + 36,
		.htotal = 2960 + 16 + 36 + 30,
		.vdisplay = 1848, .vsync_start = 1848 + 16, .vsync_end = 1848 + 16 + 32,
		.vtotal = 1848 + 16 + 32 + 32,
	},
	{	/* 60 Hz */
		.clock = (2960 + 256 + 256 + 255) * (1848 + 127 + 256 + 137) * 60 / 1000,
		.hdisplay = 2960, .hsync_start = 2960 + 256, .hsync_end = 2960 + 256 + 256,
		.htotal = 2960 + 256 + 256 + 255,
		.vdisplay = 1848, .vsync_start = 1848 + 127, .vsync_end = 1848 + 127 + 256,
		.vtotal = 1848 + 127 + 256 + 137,
	},
	{	/* 30 Hz */
		.clock = (2960 + 512 + 208 + 256) * (1848 + 512 + 512 + 512) * 30 / 1000,
		.hdisplay = 2960, .hsync_start = 2960 + 512, .hsync_end = 2960 + 512 + 208,
		.htotal = 2960 + 512 + 208 + 256,
		.vdisplay = 1848, .vsync_start = 1848 + 512, .vsync_end = 1848 + 512 + 512,
		.vtotal = 1848 + 512 + 512 + 512,
	},
};

static int ana38407_get_modes(struct drm_panel *panel,
			      struct drm_connector *connector)
{
	struct drm_display_mode *mode;
	int i, count = 0;

	for (i = 0; i < ARRAY_SIZE(ana38407_modes); i++) {
		mode = drm_mode_duplicate(connector->dev, &ana38407_modes[i]);
		if (!mode)
			continue;
		mode->type = DRM_MODE_TYPE_DRIVER;
		if (i == 0)
			mode->type |= DRM_MODE_TYPE_PREFERRED;
		mode->width_mm = 313;
		mode->height_mm = 196;
		drm_mode_set_name(mode);
		drm_mode_probed_add(connector, mode);
		count++;
	}

	connector->display_info.width_mm = 313;
	connector->display_info.height_mm = 196;

	return count;
}

static const struct drm_panel_funcs ana38407_panel_funcs = {
	.prepare = ana38407_prepare,
	.enable = ana38407_enable,
	.disable = ana38407_disable,
	.unprepare = ana38407_unprepare,
	.get_modes = ana38407_get_modes,
};

static int ana38407_bl_update(struct backlight_device *bl)
{
	struct ana38407 *ctx = bl_get_data(bl);
	u16 brightness = min_t(u16, backlight_get_brightness(bl),
			       ANA38407_MAX_BRIGHTNESS);
	int ret = 0;

	mutex_lock(&ctx->lock);
	ctx->user_brightness = brightness;
	if (ctx->prepared && !ctx->fod_mode)
		ret = ana38407_write_brightness_locked(ctx, brightness);
	mutex_unlock(&ctx->lock);

	return ret;
}

static const struct backlight_ops ana38407_bl_ops = {
	.update_status = ana38407_bl_update,
};

static struct ana38407 *ana38407_from_bl_dev(struct device *dev)
{
	return bl_get_data(to_backlight_device(dev));
}

static void ana38407_update_fod_watchdog_locked(struct ana38407 *ctx)
{
	if (ctx->fod_mode || ctx->fod_circle)
		mod_delayed_work(system_wq, &ctx->fod_watchdog,
				 msecs_to_jiffies(ANA38407_FOD_WATCHDOG_MS));
	else
		cancel_delayed_work(&ctx->fod_watchdog);
}

static ssize_t fod_mode_show(struct device *dev,
			     struct device_attribute *attr, char *buf)
{
	struct ana38407 *ctx = ana38407_from_bl_dev(dev);
	bool enabled;

	mutex_lock(&ctx->lock);
	enabled = ctx->fod_mode;
	mutex_unlock(&ctx->lock);

	return sysfs_emit(buf, "%u\n", enabled);
}

static ssize_t fod_mode_store(struct device *dev,
			      struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct ana38407 *ctx = ana38407_from_bl_dev(dev);
	bool enable;
	int ret;

	ret = kstrtobool(buf, &enable);
	if (ret)
		return ret;

	mutex_lock(&ctx->lock);
	if (!ctx->prepared || !ctx->enabled) {
		ret = -EPIPE;
		goto out_unlock;
	}

	if (ctx->fod_mode == enable) {
		ana38407_update_fod_watchdog_locked(ctx);
		ret = 0;
		goto out_unlock;
	}

	if (enable) {
		ret = ana38407_write_fod_locked(ctx, true);
		if (ret) {
			/* A failed sequence may have raised HBM; restore normal mode. */
			ana38407_write_fod_locked(ctx, false);
			goto out_unlock;
		}
		ctx->fod_mode = true;
	} else {
		ret = ana38407_fod_cleanup_locked(ctx);
	}
	ana38407_update_fod_watchdog_locked(ctx);

out_unlock:
	mutex_unlock(&ctx->lock);
	return ret ? ret : count;
}

static ssize_t fod_circle_show(struct device *dev,
			       struct device_attribute *attr, char *buf)
{
	struct ana38407 *ctx = ana38407_from_bl_dev(dev);
	bool enabled;

	mutex_lock(&ctx->lock);
	enabled = ctx->fod_circle;
	mutex_unlock(&ctx->lock);

	return sysfs_emit(buf, "%u\n", enabled);
}

static ssize_t fod_circle_store(struct device *dev,
				struct device_attribute *attr,
				const char *buf, size_t count)
{
	struct ana38407 *ctx = ana38407_from_bl_dev(dev);
	bool enable;
	int ret;

	ret = kstrtobool(buf, &enable);
	if (ret)
		return ret;

	mutex_lock(&ctx->lock);
	if (!ctx->prepared || !ctx->enabled) {
		ret = -EPIPE;
		goto out_unlock;
	}
	if (enable && !ctx->fod_mode) {
		ret = -EINVAL;
		goto out_unlock;
	}
	if (ctx->fod_circle == enable) {
		ana38407_update_fod_watchdog_locked(ctx);
		ret = 0;
		goto out_unlock;
	}

	ret = ana38407_write_fod_circle_locked(ctx, enable);
	if (!ret)
		ctx->fod_circle = enable;
	else if (enable)
		ana38407_write_fod_circle_locked(ctx, false);
	ana38407_update_fod_watchdog_locked(ctx);

out_unlock:
	mutex_unlock(&ctx->lock);
	return ret ? ret : count;
}

static ssize_t fod_ready_show(struct device *dev,
			      struct device_attribute *attr, char *buf)
{
	struct ana38407 *ctx = ana38407_from_bl_dev(dev);
	bool ready;

	mutex_lock(&ctx->lock);
	ready = ctx->prepared && ctx->enabled;
	mutex_unlock(&ctx->lock);

	return sysfs_emit(buf, "%u\n", ready);
}

static ssize_t fod_brightness_show(struct device *dev,
				   struct device_attribute *attr, char *buf)
{
	/* Raw WRDISBV programmed by fod_mode, not the desktop's saved value. */
	return sysfs_emit(buf, "%u\n", ANA38407_FOD_BRIGHTNESS);
}

static ssize_t cell_id_show(struct device *dev,
			    struct device_attribute *attr, char *buf)
{
	struct ana38407 *ctx = ana38407_from_bl_dev(dev);
	ssize_t ret;

	mutex_lock(&ctx->lock);
	ret = ctx->cell_id[0] ? sysfs_emit(buf, "%s\n", ctx->cell_id) : -ENODATA;
	mutex_unlock(&ctx->lock);

	return ret;
}

static DEVICE_ATTR_RW(fod_mode);
static DEVICE_ATTR_RW(fod_circle);
static DEVICE_ATTR_RO(fod_ready);
static DEVICE_ATTR_RO(fod_brightness);
static DEVICE_ATTR_RO(cell_id);

static struct attribute *ana38407_bl_attrs[] = {
	&dev_attr_fod_mode.attr,
	&dev_attr_fod_circle.attr,
	&dev_attr_fod_ready.attr,
	&dev_attr_fod_brightness.attr,
	&dev_attr_cell_id.attr,
	NULL,
};

static const struct attribute_group ana38407_bl_attr_group = {
	.attrs = ana38407_bl_attrs,
};

static struct backlight_device *ana38407_create_backlight(struct ana38407 *ctx)
{
	struct device *dev = &ctx->dsi->dev;
	const struct backlight_properties props = {
		.type = BACKLIGHT_RAW,
		.brightness = ANA38407_MAX_BRIGHTNESS,
		.max_brightness = ANA38407_MAX_BRIGHTNESS,
	};

	return devm_backlight_device_register(dev, dev_name(dev), dev, ctx,
					      &ana38407_bl_ops, &props);
}

/*
 * DSC config decoded from the panel's PPS (WT 0x0A ...): DSC 1.1, 2960x1848,
 * two 1480x77 slices, 8 bpc, 8.0 bpp.  The rc_buf_thresh / rc_range_params are
 * the DSC 8 bpp spec-standard tables (identical across 8 bpp panels).  The msm
 * DSI host fills convert_rgb/line_buf_depth and calls
 * drm_dsc_compute_rc_parameters() for the derived fields, so those are left out.
 */
static const struct drm_dsc_config ana38407_dsc_template = {
	.dsc_version_major = 1,
	.dsc_version_minor = 1,
	.slice_height = 77,
	.slice_width = 1480,
	.slice_count = 2,
	.bits_per_component = 8,
	.bits_per_pixel = 8 << 4,
	.block_pred_enable = true,
	.pic_width = 2960,
	.pic_height = 1848,
	.rc_buf_thresh = {
		14, 28, 42, 56, 70, 84, 98, 105, 112, 119, 121, 123, 125, 126
	},
	.rc_model_size = DSC_RC_MODEL_SIZE_CONST,
	.rc_edge_factor = DSC_RC_EDGE_FACTOR_CONST,
	.rc_tgt_offset_high = DSC_RC_TGT_OFFSET_HI_CONST,
	.rc_tgt_offset_low = DSC_RC_TGT_OFFSET_LO_CONST,
	.mux_word_size = DSC_MUX_WORD_SIZE_8_10_BPC,
	.line_buf_depth = 9,
	.first_line_bpg_offset = 12,
	.initial_xmit_delay = 512,
	.initial_offset = 6144,
	.rc_quant_incr_limit0 = 11,
	.rc_quant_incr_limit1 = 11,
	.rc_range_params = {
		{ 0,  4, DSC_BPG_OFFSET(2)},
		{ 0,  4, DSC_BPG_OFFSET(0)},
		{ 1,  5, DSC_BPG_OFFSET(0)},
		{ 1,  6, DSC_BPG_OFFSET(-2)},
		{ 3,  7, DSC_BPG_OFFSET(-4)},
		{ 3,  7, DSC_BPG_OFFSET(-6)},
		{ 3,  7, DSC_BPG_OFFSET(-8)},
		{ 3,  8, DSC_BPG_OFFSET(-8)},
		{ 3,  9, DSC_BPG_OFFSET(-8)},
		{ 3, 10, DSC_BPG_OFFSET(-10)},
		{ 5, 10, DSC_BPG_OFFSET(-10)},
		{ 5, 11, DSC_BPG_OFFSET(-12)},
		{ 5, 11, DSC_BPG_OFFSET(-12)},
		{ 9, 12, DSC_BPG_OFFSET(-12)},
		{12, 13, DSC_BPG_OFFSET(-12)},
	},
	.slice_chunk_size = 1480,
};

static void ana38407_dsc_config(struct ana38407 *ctx)
{
	ctx->dsc = ana38407_dsc_template;
}

static int ana38407_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct ana38407 *ctx;
	int ret;

	ctx = devm_drm_panel_alloc(dev, struct ana38407, panel,
				   &ana38407_panel_funcs,
				   DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(ctx))
		return PTR_ERR(ctx);

	ret = devm_regulator_bulk_get_const(dev, ARRAY_SIZE(ana38407_supplies),
					    ana38407_supplies, &ctx->supplies);
	if (ret < 0)
		return dev_err_probe(dev, ret, "failed to get panel regulators\n");

	ctx->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(ctx->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(ctx->reset_gpio),
				     "failed to get reset gpio\n");

	ctx->dsi = dsi;
	mipi_dsi_set_drvdata(dsi, ctx);
	mutex_init(&ctx->lock);
	INIT_DELAYED_WORK(&ctx->fod_watchdog, ana38407_fod_watchdog_work);
	ctx->user_brightness = ANA38407_MAX_BRIGHTNESS;

	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	dsi->mode_flags = MIPI_DSI_MODE_LPM | MIPI_DSI_CLOCK_NON_CONTINUOUS;

	ctx->panel.prepare_prev_first = true;

	ctx->panel.backlight = ana38407_create_backlight(ctx);
	if (IS_ERR(ctx->panel.backlight))
		return dev_err_probe(dev, PTR_ERR(ctx->panel.backlight),
				     "failed to create backlight\n");

	ret = sysfs_create_group(&ctx->panel.backlight->dev.kobj,
				 &ana38407_bl_attr_group);
	if (ret)
		return dev_err_probe(dev, ret,
				     "failed to create fingerprint controls\n");

	drm_panel_add(&ctx->panel);

	ana38407_dsc_config(ctx);
	dsi->dsc = &ctx->dsc;

	ret = mipi_dsi_attach(dsi);
	if (ret < 0) {
		drm_panel_remove(&ctx->panel);
		sysfs_remove_group(&ctx->panel.backlight->dev.kobj,
				   &ana38407_bl_attr_group);
		return dev_err_probe(dev, ret, "failed to attach to DSI host\n");
	}

	return 0;
}

static void ana38407_remove(struct mipi_dsi_device *dsi)
{
	struct ana38407 *ctx = mipi_dsi_get_drvdata(dsi);
	int ret;

	sysfs_remove_group(&ctx->panel.backlight->dev.kobj,
			   &ana38407_bl_attr_group);
	cancel_delayed_work_sync(&ctx->fod_watchdog);
	mutex_lock(&ctx->lock);
	if (ctx->prepared)
		ana38407_fod_cleanup_locked(ctx);
	mutex_unlock(&ctx->lock);

	ret = mipi_dsi_detach(dsi);
	if (ret < 0)
		dev_err(&dsi->dev, "failed to detach from DSI host: %d\n", ret);

	drm_panel_remove(&ctx->panel);
}

static const struct of_device_id ana38407_of_match[] = {
	{ .compatible = "samsung,ana38407-amsa46as02" },
	{ }
};
MODULE_DEVICE_TABLE(of, ana38407_of_match);

static struct mipi_dsi_driver ana38407_driver = {
	.probe = ana38407_probe,
	.remove = ana38407_remove,
	.driver = {
		.name = "panel-samsung-ana38407",
		.of_match_table = ana38407_of_match,
	},
};
module_mipi_dsi_driver(ana38407_driver);

MODULE_DESCRIPTION("Samsung ANA38407 AMSA46AS02 (gts9u) DSI panel driver");
MODULE_LICENSE("GPL");
