#include "stm32_pogo_keyboard_v3.h"

struct stm32_keypad_dev_common {
	struct stm32_keypad_dev_function *row;
	struct stm32_keypad_dev_function *bypass;
};

static struct stm32_keypad_dev_common common;

void stm32_setup_probe_keypad(struct stm32_keypad_dev *stm32)
{
	common.row = setup_stm32_keypad_dev_row();
	common.bypass = setup_stm32_keypad_dev_bypass();
}

static enum stm32_model keypad_check_input_dev(struct stm32_keypad_dev *stm32, struct pogo_data_struct pogo_data)
{
	int i = 0;

	if (pogo_data.keyboard_model == STM32_KEYBOARD_ROW_DATA_MODEL)
		return STM32_ROW_MODEL;

	for (i = 0; i < KDB_SUPPORT_MODEL_CNT; i++)
		if (pogo_data.keyboard_model == stm32->support_keyboard_model[i])
			return STM32_BYPASS_MODEL;

	return STM32_NOT_SUPPORT_MODEL;
}

int stm32_setup_attach_keypad(struct stm32_keypad_dev *stm32, struct pogo_data_struct pogo_data)
{
	enum stm32_model model = STM32_NOT_SUPPORT_MODEL;

	model = keypad_check_input_dev(stm32, pogo_data);
	if (model == STM32_ROW_MODEL) {
		stm32->release_all_key = common.row->release_all_key_func;
		stm32->keypad_set_input_dev = common.row->keypad_set_input_dev_func;
		stm32->pogo_kpd_event = common.row->pogo_kpd_event_func;
		return true;
	} else if (model == STM32_BYPASS_MODEL) {
		stm32->release_all_key = common.bypass->release_all_key_func;
		stm32->keypad_set_input_dev = common.bypass->keypad_set_input_dev_func;
		stm32->pogo_kpd_event = common.bypass->pogo_kpd_event_func;
		return true;
	}

	input_err(true, &stm32->pdev->dev, "%s not support this model:%d\n", __func__, model);
	stm32->release_all_key = NULL;
	stm32->keypad_set_input_dev = NULL;
	stm32->pogo_kpd_event = NULL;
	return false;
}
