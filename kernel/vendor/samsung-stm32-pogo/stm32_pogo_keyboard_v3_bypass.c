#include "stm32_pogo_keyboard_v3.h"

static void release_all_key_bypass(struct stm32_keypad_dev *stm32);
static int keypad_set_input_dev_bypass(struct stm32_keypad_dev *stm32, struct pogo_data_struct pogo_data);
static void pogo_kpd_event_bypass(struct stm32_keypad_dev *stm32, u16 *key_values, int len);

static struct stm32_keypad_dev_function bypass = {
	release_all_key_bypass,
	keypad_set_input_dev_bypass,
	pogo_kpd_event_bypass,
};

struct stm32_keypad_dev_function *setup_stm32_keypad_dev_bypass(void)
{
	return &bypass;
}

static void release_all_key_bypass(struct stm32_keypad_dev *stm32)
{
	int i;

	if (!stm32->input_dev)
		return;
	input_info(true, &stm32->pdev->dev, "%s\n", __func__);
	for (i = 0; i < STM32_KEY_MAX; i++) {
		if (stm32->key_state[i]) {
			input_report_key(stm32->input_dev, i, 0);
#if !IS_ENABLED(CONFIG_SAMSUNG_PRODUCT_SHIP)
			input_info(true, &stm32->pdev->dev, "RA code(%d)\n", i);
#else
			input_info(true, &stm32->pdev->dev, "RA\n");
#endif
		}
	}
	input_sync(stm32->input_dev);
}

static int keypad_set_input_dev_bypass(struct stm32_keypad_dev *stm32, struct pogo_data_struct pogo_data)
{
	struct input_dev *input_dev;
	int ret = 0;
	int i = 0;

	if (stm32->input_dev) {
		input_err(true, &stm32->pdev->dev, "%s input dev already exist.\n", __func__);
		return ret;
	}

	input_dev = input_allocate_device();
	if (!input_dev) {
		input_err(true, &stm32->pdev->dev, "%s: Failed to allocate memory for input device\n", __func__);
		return -ENOMEM;
	}

	stm32->input_dev = input_dev;
	stm32->input_dev->dev.parent = &stm32->pdev->dev;
	stm32->keyboard_model = pogo_data.keyboard_model;

	for (i = 0; i < KDB_SUPPORT_MODEL_CNT; i++) {
		if (stm32->keyboard_model == stm32->support_keyboard_model[i]) {
			stm32->input_dev->name = stm32->dtdata->input_name[i];
			break;
		}
	}

	if (!stm32->input_dev->name)
		stm32->input_dev->name = "Book Cover Keyboard";

	input_info(true, &stm32->pdev->dev, "%s: input_name: %s\n", __func__, stm32->input_dev->name);
	stm32->input_dev->id.bustype = BUS_I2C;
	stm32->input_dev->id.vendor = INPUT_VENDOR_ID_SAMSUNG;
	stm32->input_dev->id.product = INPUT_PRODUCT_ID_POGO_KEYBOARD;
	stm32->input_dev->flush = NULL;
	stm32->input_dev->event = stm32_caps_event;

	input_set_drvdata(stm32->input_dev, stm32);
	set_bit(EV_KEY, stm32->input_dev->evbit);
	__set_bit(EV_LED, stm32->input_dev->evbit);
	__set_bit(LED_CAPSL, stm32->input_dev->ledbit);

	for (i = 0; i < STM32_KEY_MAX; i++) {
		if ((i >= STM32_GAMEPAD_KEY_START && i <= STM32_GAMEPAD_KEY_END) || i == BTN_TOUCH)
			continue;
		if (i == KEY_AI_HOT) {
			if (!((stm32->keyboard_model >= 0xd1 && stm32->keyboard_model <= 0xd6) ||
					stm32->keyboard_model == 0x03 || stm32->keyboard_model == 0x51)) {
				input_info(true, &stm32->pdev->dev, "%s: skip keycode %d\n", __func__, KEY_AI_HOT);
				continue;
			}
		}
		set_bit(i, input_dev->keybit);
		stm32->key_state[i] = 0;
	}

	ret = input_register_device(stm32->input_dev);
	if (ret) {
		input_err(true, &stm32->pdev->dev, "%s: Failed to register input device\n", __func__);
		input_free_device(input_dev);
		stm32->input_dev = NULL;
		return -ENODEV;
	}

	input_info(true, &stm32->pdev->dev, "%s: done\n", __func__);
	return ret;
}

static void pogo_kpd_event_bypass(struct stm32_keypad_dev *stm32, u16 *key_values, int len)
{
	int i, event_count;

	if (!stm32->input_dev) {
		input_err(true, &stm32->pdev->dev, "%s: input dev is null\n", __func__);
		return;
	}

	if (!key_values || !len) {
		input_err(true, &stm32->pdev->dev, "%s: no event data\n", __func__);
		return;
	}

	event_count = len / sizeof(struct stm32_keyevent_data);
	for (i = 0; i < event_count; i++) {
		struct stm32_keyevent_data keydata;

		keydata.data = key_values[i];

#if !IS_ENABLED(CONFIG_SAMSUNG_PRODUCT_SHIP)
		input_info(true, &stm32->pdev->dev, "%s '%s' (%d)\n", __func__,
				keydata.press != STM32_KPC_DATA_PRESS ? "R" : "P", keydata.key_value);
#else
		input_info(true, &stm32->pdev->dev, "%s '%s'\n", __func__,
				keydata.press != STM32_KPC_DATA_PRESS ? "R" : "P");
#endif
		if (keydata.key_value < STM32_KEY_MAX) {
			if (keydata.press != STM32_KPC_DATA_PRESS)
				stm32->key_state[keydata.key_value] = 0;
			else
				stm32->key_state[keydata.key_value] = 1;
		}
		input_report_key(stm32->input_dev, keydata.key_value, keydata.press);
		input_sync(stm32->input_dev);
	}

	input_dbg(false, &stm32->pdev->dev, "%s--\n", __func__);
}
