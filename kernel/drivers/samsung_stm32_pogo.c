// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung STM32 pogo keyboard controller, mainline-oriented subset.
 *
 * The wire protocol and input packet layout are derived from Samsung's GPLv2
 * SM-X910 Android 16 source release.  The untouched files and their hashes are
 * kept in kernel/vendor/samsung-stm32-pogo/.  This driver deliberately omits
 * Android sec_class/MUIC notifiers, firmware flashing and the MAX77816 booster:
 * EF-DX920 uses the direct-keycode protocol and is not one of the two booster
 * models declared by Samsung's device tree.
 *
 * Copyright (C) 2019-2026 Samsung Electronics
 */

#include <linux/bitmap.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm_wakeup.h>
#include <linux/regulator/consumer.h>
#include <linux/unaligned.h>

#define POGO_EVENT_MCU		1
#define POGO_EVENT_TOUCHPAD	2
#define POGO_EVENT_KEYPAD	3
#define POGO_EVENT_HALL		4
#define POGO_EVENT_ACCESSORY	5

#define POGO_MAX_PAYLOAD	100
#define POGO_MODEL_EF_DX920	0xd6
#define POGO_HALL_LID_OPEN	2

struct samsung_pogo {
	struct i2c_client *client;
	struct regulator *vddo;
	struct gpio_desc *data_ready;
	struct gpio_desc *connected;
	struct gpio_desc *boot;
	struct gpio_desc *reset;
	struct input_dev *input;
	struct mutex lock;
	DECLARE_BITMAP(keys_down, KEY_MAX + 1);
	u8 model;
	u8 caps_request;
	bool lid_closed;
};

static void samsung_pogo_power_off(void *data)
{
	struct samsung_pogo *pogo = data;

	regulator_disable(pogo->vddo);
}

static int samsung_pogo_send_header(struct samsung_pogo *pogo)
{
	u8 header[] = { 3, 0, READ_ONCE(pogo->caps_request) };
	int ret;

	ret = i2c_master_send(pogo->client, header, sizeof(header));
	return ret == sizeof(header) ? 0 : ret < 0 ? ret : -EIO;
}

static int samsung_pogo_recv(struct samsung_pogo *pogo, void *buf, size_t len)
{
	int ret = i2c_master_recv(pogo->client, buf, len);

	return ret == len ? 0 : ret < 0 ? ret : -EIO;
}

static void samsung_pogo_release_keys(struct samsung_pogo *pogo)
{
	unsigned int code;
	bool changed = false;

	for_each_set_bit(code, pogo->keys_down, KEY_MAX + 1) {
		input_report_key(pogo->input, code, 0);
		changed = true;
	}
	bitmap_zero(pogo->keys_down, KEY_MAX + 1);
	if (changed)
		input_sync(pogo->input);
}

static void samsung_pogo_report_keys(struct samsung_pogo *pogo,
				     const u8 *payload, size_t len)
{
	size_t offset;

	for (offset = 0; offset + sizeof(u16) <= len; offset += sizeof(u16)) {
		u16 event = get_unaligned_le16(payload + offset);
		unsigned int code = event & GENMASK(14, 0);
		bool pressed = event & BIT(15);

		if (!code || code > KEY_MAX) {
			dev_warn_ratelimited(&pogo->client->dev,
				"invalid key event %#06x\n", event);
			continue;
		}

		if (pressed)
			__set_bit(code, pogo->keys_down);
		else
			__clear_bit(code, pogo->keys_down);
		input_report_key(pogo->input, code, pressed);
	}
	input_sync(pogo->input);
}

static void samsung_pogo_report_hall(struct samsung_pogo *pogo,
				     const u8 *payload, size_t len)
{
	bool closed;

	if (!len)
		return;

	closed = payload[0] != POGO_HALL_LID_OPEN;
	if (closed == pogo->lid_closed)
		return;

	pogo->lid_closed = closed;
	input_report_switch(pogo->input, SW_LID, closed);
	input_sync(pogo->input);
	dev_info(&pogo->client->dev, "keyboard cover %s\n",
		 closed ? "closed" : "open");
}

static int samsung_pogo_read_event(struct samsung_pogo *pogo)
{
	u8 header[3];
	u8 payload[POGO_MAX_PAYLOAD];
	u16 total;
	size_t payload_len;
	int ret;

	ret = samsung_pogo_send_header(pogo);
	if (ret)
		return ret;

	ret = samsung_pogo_recv(pogo, header, sizeof(header));
	if (ret)
		return ret;

	total = get_unaligned_le16(header);
	if (total <= sizeof(header) || total - sizeof(header) > sizeof(payload)) {
		/* Samsung uses this otherwise-invalid header as the attach/model event. */
		if (header[2] && header[2] != pogo->model) {
			pogo->model = header[2];
			dev_info(&pogo->client->dev,
				 "keyboard attached, model %#02x%s\n", pogo->model,
				 pogo->model == POGO_MODEL_EF_DX920 ? " (EF-DX920)" : "");
		}
		return 0;
	}

	payload_len = total - sizeof(header);
	ret = samsung_pogo_recv(pogo, payload, payload_len);
	if (ret)
		return ret;

	switch (header[2]) {
	case POGO_EVENT_TOUCHPAD:
		/* EF-DX920 is the Slim cover and has no touchpad. */
		dev_dbg(&pogo->client->dev, "ignored touchpad packet (%zu bytes)\n",
			payload_len);
		break;
	case POGO_EVENT_KEYPAD:
		samsung_pogo_report_keys(pogo, payload, payload_len);
		break;
	case POGO_EVENT_HALL:
		samsung_pogo_release_keys(pogo);
		samsung_pogo_report_hall(pogo, payload, payload_len);
		break;
	case POGO_EVENT_ACCESSORY:
		dev_dbg(&pogo->client->dev, "accessory packet (%zu bytes)\n",
			payload_len);
		break;
	case POGO_EVENT_MCU:
	default:
		dev_dbg(&pogo->client->dev, "event %u (%zu bytes)\n",
			header[2], payload_len);
		break;
	}

	return 0;
}

static irqreturn_t samsung_pogo_irq_thread(int irq, void *data)
{
	struct samsung_pogo *pogo = data;
	int ret;

	pm_wakeup_event(&pogo->client->dev, 1000);
	mutex_lock(&pogo->lock);
	ret = samsung_pogo_read_event(pogo);
	mutex_unlock(&pogo->lock);
	if (ret)
		dev_warn_ratelimited(&pogo->client->dev,
				     "event read failed: %d\n", ret);

	return IRQ_HANDLED;
}

static int samsung_pogo_input_event(struct input_dev *input,
				    unsigned int type, unsigned int code, int value)
{
	struct samsung_pogo *pogo = input_get_drvdata(input);

	if (type != EV_LED || code != LED_CAPSL)
		return -EINVAL;

	/* The vendor protocol puts the desired Caps LED state in the next poll. */
	WRITE_ONCE(pogo->caps_request, value ? 2 : 1);
	return 0;
}

static int samsung_pogo_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct samsung_pogo *pogo;
	unsigned int code;
	int irq;
	int ret;

	if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
		return -EOPNOTSUPP;

	pogo = devm_kzalloc(dev, sizeof(*pogo), GFP_KERNEL);
	if (!pogo)
		return -ENOMEM;

	pogo->client = client;
	pogo->caps_request = 1;
	mutex_init(&pogo->lock);
	i2c_set_clientdata(client, pogo);

	pogo->vddo = devm_regulator_get(dev, "vddo");
	if (IS_ERR(pogo->vddo))
		return dev_err_probe(dev, PTR_ERR(pogo->vddo), "failed to get VDDO\n");

	pogo->boot = devm_gpiod_get(dev, "boot", GPIOD_OUT_LOW);
	if (IS_ERR(pogo->boot))
		return dev_err_probe(dev, PTR_ERR(pogo->boot), "failed to get BOOT0\n");

	/* reset is active-low in DT; logical low means deasserted/high on the pin. */
	pogo->reset = devm_gpiod_get(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(pogo->reset))
		return dev_err_probe(dev, PTR_ERR(pogo->reset), "failed to get reset\n");

	pogo->data_ready = devm_gpiod_get(dev, "data-ready", GPIOD_IN);
	if (IS_ERR(pogo->data_ready))
		return dev_err_probe(dev, PTR_ERR(pogo->data_ready),
				     "failed to get data-ready GPIO\n");

	pogo->connected = devm_gpiod_get_optional(dev, "connected", GPIOD_IN);
	if (IS_ERR(pogo->connected))
		return dev_err_probe(dev, PTR_ERR(pogo->connected),
				     "failed to get connection GPIO\n");

	ret = regulator_enable(pogo->vddo);
	if (ret)
		return dev_err_probe(dev, ret, "failed to enable VDDO\n");
	ret = devm_add_action_or_reset(dev, samsung_pogo_power_off, pogo);
	if (ret)
		return ret;

	msleep(50);

	pogo->input = devm_input_allocate_device(dev);
	if (!pogo->input)
		return -ENOMEM;
	pogo->input->name = "Book Cover Keyboard Slim (EF-DX920)";
	pogo->input->phys = "samsung-pogo/input0";
	pogo->input->id.bustype = BUS_I2C;
	pogo->input->id.vendor = 0x04e8;
	pogo->input->id.product = 0xa035;
	pogo->input->event = samsung_pogo_input_event;
	input_set_drvdata(pogo->input, pogo);
	for (code = 1; code <= KEY_MAX; code++)
		input_set_capability(pogo->input, EV_KEY, code);
	input_set_capability(pogo->input, EV_LED, LED_CAPSL);
	input_set_capability(pogo->input, EV_SW, SW_LID);

	ret = input_register_device(pogo->input);
	if (ret)
		return dev_err_probe(dev, ret, "failed to register input device\n");

	irq = gpiod_to_irq(pogo->data_ready);
	if (irq < 0)
		return dev_err_probe(dev, irq, "failed to map data-ready IRQ\n");

	ret = devm_request_threaded_irq(dev, irq, NULL, samsung_pogo_irq_thread,
					IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
					dev_name(dev), pogo);
	if (ret)
		return dev_err_probe(dev, ret, "failed to request data-ready IRQ\n");

	device_init_wakeup(dev, true);
	dev_info(dev, "STM32 pogo controller ready (connected=%d, data-ready=%d)\n",
		 pogo->connected ? gpiod_get_value_cansleep(pogo->connected) : -1,
		 gpiod_get_value_cansleep(pogo->data_ready));

	/* Do not miss an attach packet that was already pending before IRQ setup. */
	/* The descriptor is active-low, so logical 1 means a physical low IRQ. */
	if (gpiod_get_value_cansleep(pogo->data_ready) > 0)
		samsung_pogo_irq_thread(irq, pogo);

	return 0;
}

static void samsung_pogo_remove(struct i2c_client *client)
{
	struct samsung_pogo *pogo = i2c_get_clientdata(client);

	samsung_pogo_release_keys(pogo);
	device_init_wakeup(&client->dev, false);
}

static const struct of_device_id samsung_pogo_of_match[] = {
	{ .compatible = "samsung,gts9u-stm32-pogo" },
	{ }
};
MODULE_DEVICE_TABLE(of, samsung_pogo_of_match);

static struct i2c_driver samsung_pogo_driver = {
	.driver = {
		.name = "samsung-gts9u-stm32-pogo",
		.of_match_table = samsung_pogo_of_match,
	},
	.probe = samsung_pogo_probe,
	.remove = samsung_pogo_remove,
};
module_i2c_driver(samsung_pogo_driver);

MODULE_DESCRIPTION("Samsung SM-X910 STM32 pogo keyboard controller");
MODULE_AUTHOR("Samsung Electronics; mainline adaptation by the gts9uwifi port");
MODULE_LICENSE("GPL");
