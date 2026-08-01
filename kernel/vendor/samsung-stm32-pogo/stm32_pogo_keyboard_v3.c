/******************** (C) COPYRIGHT 2019 Samsung Electronics ********************
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation.
 *
 * THE PRESENT SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES
 * OR CONDITIONS OF ANY KIND, EITHER EXPRESS OR IMPLIED, FOR THE SOLE
 * PURPOSE TO SUPPORT YOUR APPLICATION DEVELOPMENT.
 * AS A RESULT, STMICROELECTRONICS SHALL NOT BE HELD LIABLE FOR ANY DIRECT,
 * INDIRECT OR CONSEQUENTIAL DAMAGES WITH RESPECT TO ANY CLAIMS ARISING FROM THE
 * CONTENT OF SUCH SOFTWARE AND/OR THE USE MADE BY CUSTOMERS OF THE CODING
 * INFORMATION CONTAINED HEREIN IN CONNECTION WITH THEIR PRODUCTS.
 *
 * THIS SOFTWARE IS SPECIFICALLY DESIGNED FOR EXCLUSIVE USE WITH ST PARTS.
 *******************************************************************************/

#include "stm32_pogo_keyboard_v3.h"

#if IS_ENABLED(CONFIG_OF)
static int stm32_parse_dt(struct device *dev, struct stm32_keypad_dev *device_data)
{
	struct device_node *np = dev->of_node;
	struct matrix_keymap_data *keymap_data1;
	struct matrix_keymap_data *keymap_data2;
	int ret, keymap_len1, keymap_len2, i;
	u32 *keymap1, *keymap2, temp;
	const __be32 *map1;
	const __be32 *map2;
	int count;

	count = of_property_count_strings(np, "keypad,input_name");
	if (count < 0)
		count = 1;

	ret = of_property_read_string_array(np, "keypad,input_name", device_data->dtdata->input_name, count);
	if (ret < 0)
		input_err(true, dev, "unable to get model_name\n");

	count = of_property_count_strings(np, "keypad,input_name_row");
	if (count < 0)
		count = 1;

	ret = of_property_read_string_array(np, "keypad,input_name_row", device_data->dtdata_row->input_name, count);
	if (ret < 0)
		input_err(true, dev, "unable to get model_name\n");

	count = of_property_count_u32_elems(np, "keypad,support_keyboard_model");
	if (count < 0)
		count = 1;

	ret = of_property_read_u32_array(np, "keypad,support_keyboard_model", device_data->support_keyboard_model,
						count);
	if (ret < 0)
		input_err(true, dev, "unable to get model_name\n");

	ret = of_property_read_u32(np, "keypad,num-rows", &temp);
	if (ret)
		input_err(true, &device_data->pdev->dev, "%s unable to get num-rows\n", __func__);

	device_data->dtdata_row->num_row = temp;

	ret = of_property_read_u32(np, "keypad,num-columns", &temp);
	if (ret)
		input_err(true, &device_data->pdev->dev, "%s unable to get num-columns\n", __func__);

	device_data->dtdata_row->num_column = temp;

	map1 = of_get_property(np, "linux,keymap1", &keymap_len1);

	if (!map1)
		input_err(true, &device_data->pdev->dev, "%s Keymap not specified\n", __func__);

	map2 = of_get_property(np, "linux,keymap2", &keymap_len2);

	if (!map2)
		input_err(true, &device_data->pdev->dev, "%s Keymap not specified\n", __func__);

	keymap_data1 = devm_kzalloc(dev, sizeof(*keymap_data1), GFP_KERNEL);
	if (!keymap_data1) {
		input_err(true, &device_data->pdev->dev, "%s Unable to allocate memory\n", __func__);
		return -ENOMEM;
	}

	keymap_data2 = devm_kzalloc(dev, sizeof(*keymap_data2), GFP_KERNEL);
	if (!keymap_data2) {
		input_err(true, &device_data->pdev->dev, "%s Unable to allocate memory\n", __func__);
		return -ENOMEM;
	}

	keymap_data1->keymap_size = (unsigned int)(keymap_len1 / sizeof(u32));
	keymap_data2->keymap_size = (unsigned int)(keymap_len2 / sizeof(u32));

	keymap1 = devm_kzalloc(dev, sizeof(uint32_t) * keymap_data1->keymap_size, GFP_KERNEL);
	if (!keymap1) {
		input_err(true, &device_data->pdev->dev, "%s could not allocate memory for keymap\n", __func__);
		return -ENOMEM;
	}

	keymap2 = devm_kzalloc(dev, sizeof(uint32_t) * keymap_data2->keymap_size, GFP_KERNEL);
	if (!keymap2) {
		input_err(true, &device_data->pdev->dev, "%s could not allocate memory for keymap\n", __func__);
		return -ENOMEM;
	}

	for (i = 0; i < keymap_data1->keymap_size; i++) {
		unsigned int key = be32_to_cpup(map1 + i);
		int keycode, row, col;

		row = (key >> 24) & 0xff;
		col = (key >> 16) & 0xff;
		keycode = key & 0xffff;
		keymap1[i] = KEY(row, col, keycode);
	}

	for (i = 0; i < keymap_data2->keymap_size; i++) {
		unsigned int key2 = be32_to_cpup(map2 + i);
		int keycode2, row2, col2;

		row2 = (key2 >> 24) & 0xff;
		col2 = (key2 >> 16) & 0xff;
		keycode2 = key2 & 0xffff;
		keymap2[i] = KEY(row2, col2, keycode2);
	}

	/* short keymap for easy finding key */
	snprintf(device_data->key_name[KEY_1], 10, "1");
	snprintf(device_data->key_name[KEY_2], 10, "2");
	snprintf(device_data->key_name[KEY_3], 10, "3");
	snprintf(device_data->key_name[KEY_4], 10, "4");
	snprintf(device_data->key_name[KEY_5], 10, "5");
	snprintf(device_data->key_name[KEY_6], 10, "6");
	snprintf(device_data->key_name[KEY_7], 10, "7");
	snprintf(device_data->key_name[KEY_8], 10, "8");
	snprintf(device_data->key_name[KEY_9], 10, "9");
	snprintf(device_data->key_name[KEY_0], 10, "0");
	snprintf(device_data->key_name[KEY_MINUS], 10, "-");
	snprintf(device_data->key_name[KEY_EQUAL], 10, "=");
	snprintf(device_data->key_name[KEY_BACKSPACE], 10, "Backspc");
	snprintf(device_data->key_name[KEY_TAB], 10, "Tab");
	snprintf(device_data->key_name[KEY_Q], 10, "q");
	snprintf(device_data->key_name[KEY_W], 10, "w");
	snprintf(device_data->key_name[KEY_E], 10, "e");
	snprintf(device_data->key_name[KEY_R], 10, "r");
	snprintf(device_data->key_name[KEY_T], 10, "t");
	snprintf(device_data->key_name[KEY_Y], 10, "y");
	snprintf(device_data->key_name[KEY_U], 10, "u");
	snprintf(device_data->key_name[KEY_I], 10, "i");
	snprintf(device_data->key_name[KEY_O], 10, "o");
	snprintf(device_data->key_name[KEY_P], 10, "p");
	snprintf(device_data->key_name[KEY_LEFTBRACE], 10, "[");
	snprintf(device_data->key_name[KEY_RIGHTBRACE], 10, "]");
	snprintf(device_data->key_name[KEY_ENTER], 10, "Enter");
	snprintf(device_data->key_name[KEY_LEFTCTRL], 10, "L CTRL");
	snprintf(device_data->key_name[KEY_A], 10, "a");
	snprintf(device_data->key_name[KEY_S], 10, "s");
	snprintf(device_data->key_name[KEY_D], 10, "d");
	snprintf(device_data->key_name[KEY_F], 10, "f");
	snprintf(device_data->key_name[KEY_G], 10, "g");
	snprintf(device_data->key_name[KEY_H], 10, "h");
	snprintf(device_data->key_name[KEY_J], 10, "j");
	snprintf(device_data->key_name[KEY_K], 10, "k");
	snprintf(device_data->key_name[KEY_L], 10, "l");
	snprintf(device_data->key_name[KEY_SEMICOLON], 10, ";");
	snprintf(device_data->key_name[KEY_APOSTROPHE], 10, "\'");
	snprintf(device_data->key_name[KEY_GRAVE], 10, "`");
	snprintf(device_data->key_name[KEY_LEFTSHIFT], 10, "L Shift");
	snprintf(device_data->key_name[KEY_BACKSLASH], 10, "\\"); /* US : backslash , UK : pound*/
	snprintf(device_data->key_name[KEY_Z], 10, "z");
	snprintf(device_data->key_name[KEY_X], 10, "x");
	snprintf(device_data->key_name[KEY_C], 10, "c");
	snprintf(device_data->key_name[KEY_V], 10, "v");
	snprintf(device_data->key_name[KEY_B], 10, "b");
	snprintf(device_data->key_name[KEY_N], 10, "n");
	snprintf(device_data->key_name[KEY_M], 10, "m");
	snprintf(device_data->key_name[KEY_COMMA], 10, ",");
	snprintf(device_data->key_name[KEY_DOT], 10, ".");
	snprintf(device_data->key_name[KEY_SLASH], 10, "/");
	snprintf(device_data->key_name[KEY_RIGHTSHIFT], 10, "R Shift");
	snprintf(device_data->key_name[KEY_LEFTALT], 10, "L ALT");
	snprintf(device_data->key_name[KEY_SPACE], 10, " ");
	snprintf(device_data->key_name[KEY_CAPSLOCK], 10, "CAPSLOCK");
	snprintf(device_data->key_name[KEY_102ND], 10, "\\"); /* only UK : backslash */
	snprintf(device_data->key_name[KEY_RIGHTALT], 10, "R ALT");
	snprintf(device_data->key_name[KEY_UP], 10, "Up");
	snprintf(device_data->key_name[KEY_LEFT], 10, "Left");
	snprintf(device_data->key_name[KEY_RIGHT], 10, "Right");
	snprintf(device_data->key_name[KEY_DOWN], 10, "Down");
	snprintf(device_data->key_name[KEY_HANGEUL], 10, "Lang");
	snprintf(device_data->key_name[KEY_LEFTMETA], 10, "L Meta");
	snprintf(device_data->key_name[KEY_NUMERIC_POUND], 10, "#");
	snprintf(device_data->key_name[706], 10, "SIP"); /* SIP_ON_OFF */
	snprintf(device_data->key_name[710], 10, "Sfinder"); /* SIP_ON_OFF */
	snprintf(device_data->key_name[KEY_ESC], 10, "ESC");
	snprintf(device_data->key_name[KEY_FN], 10, "Fn");
	snprintf(device_data->key_name[KEY_F1], 10, "F1");
	snprintf(device_data->key_name[KEY_F2], 10, "F2");
	snprintf(device_data->key_name[KEY_F3], 10, "F3");
	snprintf(device_data->key_name[KEY_F4], 10, "F4");
	snprintf(device_data->key_name[KEY_F5], 10, "F5");
	snprintf(device_data->key_name[KEY_F6], 10, "F6");
	snprintf(device_data->key_name[KEY_F7], 10, "F7");
	snprintf(device_data->key_name[KEY_F8], 10, "F8");
	snprintf(device_data->key_name[KEY_F9], 10, "F9");
	snprintf(device_data->key_name[KEY_F10], 10, "F10");
	snprintf(device_data->key_name[KEY_F11], 10, "F11");
	snprintf(device_data->key_name[KEY_F12], 10, "F12");
	snprintf(device_data->key_name[KEY_DEX_ON], 10, "DEX");
	snprintf(device_data->key_name[KEY_DELETE], 10, "DEL");
	snprintf(device_data->key_name[KEY_HOMEPAGE], 10, "HOME");
	snprintf(device_data->key_name[KEY_END], 10, "END");
	snprintf(device_data->key_name[KEY_PAGEUP], 10, "PgUp");
	snprintf(device_data->key_name[KEY_PAGEDOWN], 10, "PgDown");
	snprintf(device_data->key_name[KEY_TOUCHPAD_ON], 10, "Tpad ON");
	snprintf(device_data->key_name[KEY_TOUCHPAD_OFF], 10, "Tpad OFF");
	snprintf(device_data->key_name[KEY_VOLUMEDOWN], 10, "VOL DOWN");
	snprintf(device_data->key_name[KEY_VOLUMEUP], 10, "VOL UP");
	snprintf(device_data->key_name[KEY_MUTE], 10, "VOL MUTE");
	snprintf(device_data->key_name[705], 10, "APPS"); //apps
	snprintf(device_data->key_name[KEY_BRIGHTNESSDOWN], 10, "B-DOWN");
	snprintf(device_data->key_name[KEY_BRIGHTNESSUP], 10, "B-UP");
	snprintf(device_data->key_name[KEY_PLAYPAUSE], 10, "PLAYPAUSE");
	snprintf(device_data->key_name[KEY_NEXTSONG], 10, "NEXT");
	snprintf(device_data->key_name[KEY_PREVIOUSSONG], 10, "PREV");
	snprintf(device_data->key_name[KEY_SYSRQ], 10, "SYSRQ");
	snprintf(device_data->key_name[709], 10, "SETTING");
	snprintf(device_data->key_name[713], 10, "KBD SHARE");
	snprintf(device_data->key_name[714], 10, "FN LOCK");
	snprintf(device_data->key_name[715], 10, "FN UNLOCK");

	keymap_data1->keymap = keymap1;
	device_data->dtdata_row->keymap_data1 = keymap_data1;
	keymap_data2->keymap = keymap2;
	device_data->dtdata_row->keymap_data2 = keymap_data2;
	input_info(true, &device_data->pdev->dev,
			"%s %s %s, %s %s %s row:%d, col:%d, keymap1 size:%d keymap2 size:%d count:%d\n",
			device_data->dtdata->input_name[0], device_data->dtdata->input_name[1],
			device_data->dtdata->input_name[2], device_data->dtdata_row->input_name[0],
			device_data->dtdata_row->input_name[1], device_data->dtdata_row->input_name[2],
			device_data->dtdata_row->num_row, device_data->dtdata_row->num_column,
			device_data->dtdata_row->keymap_data1->keymap_size,
			device_data->dtdata_row->keymap_data2->keymap_size, count);
	return 0;
}
#else
static int stm32_parse_dt(struct device *dev, struct stm32_keypad_dev *device_data)
{
	return -ENODEV;
}
#endif
void stm32_toggle_led(struct stm32_keypad_dev *device_data)
{
	bool led_enabled = false;

	STM32_CHECK_LED(device_data, led_enabled, LED_CAPSL);

	if (led_enabled) {
		stm32_caps_led_value = 0x2;

	} else {
		stm32_caps_led_value = 0x1;
	}
	pr_info("%s %s  led_value:%d\n", SECLOG, __func__, stm32_caps_led_value);
}

int stm32_caps_event(struct input_dev *dev, unsigned int type, unsigned int code, int value)
{
	struct stm32_keypad_dev *device_data = input_get_drvdata(dev);

	switch (type) {
	case EV_LED:
		stm32_toggle_led(device_data);
		return 0;
	default:
		pr_err("%s %s(): Got unknown type %d, code %d, value %d\n",
				SECLOG, __func__, type, code, value);
	}

	return -1;
}

static int stm32_kpd_pogo_notifier(struct notifier_block *nb, unsigned long action, void *data)
{
	struct stm32_keypad_dev *stm32 = container_of(nb, struct stm32_keypad_dev, pogo_nb);
	struct pogo_data_struct pogo_data = *(struct pogo_data_struct *)data;
	enum pogo_notifier_id_t notifier_action = (enum pogo_notifier_id_t)action;
	int ret = 0;

	mutex_lock(&stm32->dev_lock);
	ret = stm32_setup_attach_keypad(stm32, pogo_data);
	if (!ret)
		goto out;

	switch (notifier_action) {
	case POGO_NOTIFIER_ID_ATTACHED:
		stm32->keypad_set_input_dev(stm32, pogo_data);
		break;
	case POGO_NOTIFIER_ID_DETACHED:
		stm32->release_all_key(stm32);
		if (stm32->input_dev) {
			input_unregister_device(stm32->input_dev);
			stm32->input_dev = NULL;
			input_info(true, &stm32->pdev->dev, "%s: input dev unregistered\n", __func__);
		}
		break;
	case POGO_NOTIFIER_ID_RESET:
		stm32->release_all_key(stm32);
		break;
	case POGO_NOTIFIER_EVENTID_KEYPAD:
		stm32->pogo_kpd_event(stm32, (u16 *)pogo_data.data, pogo_data.size);
		break;
	case POGO_NOTIFIER_EVENTID_TOUCHPAD:
	case POGO_NOTIFIER_EVENTID_HALL:
		break;
	default:
		input_info(true, &stm32->pdev->dev, "%s: notifier_action type:%d\n", __func__, notifier_action);
	};
out:
	mutex_unlock(&stm32->dev_lock);

	return NOTIFY_DONE;
}

static int stm32_keypad_probe(struct platform_device *pdev)
{
	struct stm32_keypad_dev *stm32;
	int ret = 0;

	input_info(true, &pdev->dev, "%s\n", __func__);

	stm32 = devm_kzalloc(&pdev->dev, sizeof(struct stm32_keypad_dev), GFP_KERNEL);
	if (!stm32) {
		input_err(true, &pdev->dev, "%s: Failed to allocate memory\n", __func__);
		return -ENOMEM;
	}

	stm32->pdev = pdev;

	platform_set_drvdata(pdev, stm32);

	mutex_init(&stm32->dev_lock);

	if (pdev->dev.of_node) {
		stm32->dtdata = devm_kzalloc(&pdev->dev, sizeof(struct stm32_keypad_dtdata), GFP_KERNEL);
		if (!stm32->dtdata) {
			input_err(true, &pdev->dev, "%s: Failed to allocate memory\n", __func__);
			ret = -ENOMEM;
			goto err_config;
		}

		stm32->dtdata_row = devm_kzalloc(&pdev->dev, sizeof(struct stm32_keypad_dtdata_row), GFP_KERNEL);
		if (!stm32->dtdata_row) {
			input_err(true, &pdev->dev, "%s: Failed to allocate memory\n", __func__);
			ret = -ENOMEM;
			goto err_config;
		}
		ret = stm32_parse_dt(&pdev->dev, stm32);
		if (ret) {
			input_err(true, &pdev->dev, "%s: Failed to use device tree\n", __func__);
			ret = -EIO;
			goto err_config;
		}

	} else {
		input_err(true, &stm32->pdev->dev, "Not use device tree\n");
		stm32->dtdata = pdev->dev.platform_data;
		if (!stm32->dtdata) {
			input_err(true, &pdev->dev, "%s: failed to get platform data\n", __func__);
			ret = -ENOENT;
			goto err_config;
		}
	}

	input_info(true, &stm32->pdev->dev, "keymap size1 (%d) keymap size2 (%d)\n",
			stm32->dtdata_row->keymap_data1->keymap_size, stm32->dtdata_row->keymap_data2->keymap_size);

	stm32->keycode = devm_kzalloc(&pdev->dev,
				(stm32->dtdata_row->num_row << STM32_KPC_ROW_SHIFT) * sizeof(unsigned short),
				GFP_KERNEL);
	if (!stm32->keycode) {
		input_err(true, &pdev->dev, "%s: keycode kzalloc memory error\n", __func__);
		ret = -ENOMEM;
		goto err_config;
	}

	stm32_setup_probe_keypad(stm32);

	pogo_notifier_register(&stm32->pogo_nb, stm32_kpd_pogo_notifier, POGO_NOTIFY_DEV_KEYPAD);

	input_info(true, &stm32->pdev->dev, "%s: done\n", __func__);

	return ret;
err_config:
	mutex_destroy(&stm32->dev_lock);
	input_err(true, &pdev->dev, "Error at %s\n", __func__);
	return ret;
}

static int stm32_keypad_remove(struct platform_device *pdev)
{
	struct stm32_keypad_dev *stm32 = platform_get_drvdata(pdev);

	pogo_notifier_unregister(&stm32->pogo_nb);

	input_free_device(stm32->input_dev);

	mutex_destroy(&stm32->dev_lock);

	kfree(stm32);
	return 0;
}

#if IS_ENABLED(CONFIG_OF)
static struct of_device_id stm32_match_table[] = {
	{ .compatible = "stm,keypad",},
	{ },
};
#else
#define stm32_match_table NULL
#endif

static struct platform_driver stm32_pogo_kpd_driver = {
	.driver = {
		.name = STM32KPD_DRV_NAME,
		.owner = THIS_MODULE,
		.of_match_table = stm32_match_table,
	},
	.probe = stm32_keypad_probe,
	.remove = stm32_keypad_remove,
};

int stm32_pogo_kpd_init(void)
{
	pr_info("%s %s\n", SECLOG, __func__);

	return platform_driver_probe(&stm32_pogo_kpd_driver, stm32_keypad_probe);
}
EXPORT_SYMBOL(stm32_pogo_kpd_init);

void stm32_pogo_kpd_exit(void)
{
	pr_info("%s %s\n", SECLOG, __func__);
	platform_driver_unregister(&stm32_pogo_kpd_driver);
}
EXPORT_SYMBOL(stm32_pogo_kpd_exit);

MODULE_DESCRIPTION("STM32 Keypad Driver for POGO Keyboard V2");
MODULE_AUTHOR("Samsung");
