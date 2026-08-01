#include "stm32_pogo_keyboard_v3.h"

static void release_all_key_row(struct stm32_keypad_dev *stm32);
static int keypad_set_input_dev_row(struct stm32_keypad_dev *stm32, struct pogo_data_struct pogo_data);
static void pogo_kpd_event_row(struct stm32_keypad_dev *stm32, u16 *key_values, int len);

static struct stm32_keypad_dev_function row = {
	release_all_key_row,
	keypad_set_input_dev_row,
	pogo_kpd_event_row,
};

struct stm32_keypad_dev_function *setup_stm32_keypad_dev_row(void)
{
	return &row;
}

static void release_all_key_row(struct stm32_keypad_dev *stm32)
{
	int i, j;

	if (!stm32->input_dev)
		return;

	input_info(true, &stm32->pdev->dev, "%s\n", __func__);

	for (i = 0; i < stm32->dtdata_row->num_row; i++) {
		if (!stm32->key_state[i])
			continue;

		for (j = 0; j < stm32->dtdata_row->num_column; j++) {
			if (stm32->key_state[i] & (1 << j)) {
				int code = MATRIX_SCAN_CODE(i, j, STM32_KPC_ROW_SHIFT);

				input_event(stm32->input_dev, EV_MSC, MSC_SCAN, code);
				input_report_key(stm32->input_dev, stm32->keycode[code], 0);
#if !IS_ENABLED(CONFIG_SAMSUNG_PRODUCT_SHIP)
				input_info(true, &stm32->pdev->dev, "RA code(0x%X|%d) R:C(%d:%d)\n",
						stm32->keycode[code], stm32->keycode[code], i, j);
#else
				input_info(true, &stm32->pdev->dev, "RA (%d:%d)\n", i, j);
#endif
				stm32->key_state[i] &= ~(1 << j);
			}
		}
	}
	input_sync(stm32->input_dev);
}

static int keypad_set_input_dev_row(struct stm32_keypad_dev *stm32, struct pogo_data_struct pogo_data)
{
	struct input_dev *input_dev;
	int ret = 0;

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

	stm32->input_dev->name = stm32->dtdata_row->input_name[pogo_data.module_id];

	input_info(true, &stm32->pdev->dev, "%s: input_name: %s\n", __func__, stm32->input_dev->name);
	stm32->input_dev->id.bustype = BUS_I2C;
	stm32->input_dev->id.vendor = INPUT_VENDOR_ID_SAMSUNG;
	stm32->input_dev->id.product = INPUT_PRODUCT_ID_POGO_KEYBOARD;
	stm32->input_dev->flush = NULL;
	stm32->input_dev->event = NULL;

	input_set_drvdata(stm32->input_dev, stm32);
	input_set_capability(stm32->input_dev, EV_MSC, MSC_SCAN);
	set_bit(EV_KEY, stm32->input_dev->evbit);
	if (pogo_data.module_id == 1) {
		matrix_keypad_build_keymap(stm32->dtdata_row->keymap_data2, NULL, stm32->dtdata_row->num_row,
						stm32->dtdata_row->num_column, stm32->keycode, stm32->input_dev);
	} else {
		matrix_keypad_build_keymap(stm32->dtdata_row->keymap_data1, NULL, stm32->dtdata_row->num_row,
						stm32->dtdata_row->num_column, stm32->keycode, stm32->input_dev);
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
static void pogo_kpd_event_row(struct stm32_keypad_dev *stm32, u16 *key_values, int len)
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
		struct stm32_keyevent_data_row keydata;
		int code;

		keydata.data[0] = key_values[i];
		code = MATRIX_SCAN_CODE(keydata.row, keydata.col, STM32_KPC_ROW_SHIFT);

		if (keydata.row >= stm32->dtdata_row->num_row || keydata.col >= stm32->dtdata_row->num_column)
			continue;

		if (keydata.press != STM32_KPC_DATA_PRESS) /* Release */
			stm32->key_state[keydata.row] &= ~(1 << keydata.col);
		else /* Press */
			stm32->key_state[keydata.row] |= (1 << keydata.col);

#if !IS_ENABLED(CONFIG_SAMSUNG_PRODUCT_SHIP)
		input_info(true, &stm32->pdev->dev, "%s '%s' 0x%02X(%d) R:C(%d:%d)\n",
				keydata.press != STM32_KPC_DATA_PRESS ? "R" : "P",
				stm32->key_name[stm32->keycode[code]], stm32->keycode[code],
				stm32->keycode[code], keydata.row, keydata.col);
#else
		input_info(true, &stm32->pdev->dev, "%s\n", keydata.press != STM32_KPC_DATA_PRESS ? "R" : "P");
#endif
		input_event(stm32->input_dev, EV_MSC, MSC_SCAN, code);
		input_report_key(stm32->input_dev, stm32->keycode[code], keydata.press);
		input_sync(stm32->input_dev);
	}
	input_dbg(false, &stm32->pdev->dev, "%s--\n", __func__);
}
