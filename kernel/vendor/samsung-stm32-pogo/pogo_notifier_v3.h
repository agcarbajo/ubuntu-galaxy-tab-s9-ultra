
#ifndef __POGO_NOTIFIER_V3_H__
#define __POGO_NOTIFIER_V3_H__

#include <linux/notifier.h>

#define POGO_HALL_E_LID_NORMAL		2

enum pogo_notifier_device_t {
	POGO_NOTIFY_DEV_TOUCHPAD = 0,
	POGO_NOTIFY_DEV_KEYPAD,
	POGO_NOTIFY_DEV_HALLIC,
	POGO_NOTIFY_DEV_SENSOR,
	POGO_NOTIFY_DEV_WACOM,
};

enum stm32_ed_id {
	ID_MCU = 1,
	ID_TOUCHPAD = 2,
	ID_KEYPAD = 3,
	ID_HALL = 4,
	ID_ACESSORY = 5,
};

enum pogo_notifier_id_t {
	POGO_NOTIFIER_EVENTID_NONE	= 0,
	POGO_NOTIFIER_EVENTID_MCU	= ID_MCU,
	POGO_NOTIFIER_EVENTID_TOUCHPAD	= ID_TOUCHPAD,
	POGO_NOTIFIER_EVENTID_KEYPAD	= ID_KEYPAD,
	POGO_NOTIFIER_EVENTID_HALL	= ID_HALL,
	POGO_NOTIFIER_EVENTID_ACESSORY	= ID_ACESSORY,
  /* add new device upper here */
	POGO_NOTIFIER_EVENTID_MAX,

	POGO_NOTIFIER_ID_ATTACHED	= 0xE0,
	POGO_NOTIFIER_ID_DETACHED,
	POGO_NOTIFIER_ID_RESET,
};

enum stm32_model {
	STM32_ROW_MODEL = 1,
	STM32_BYPASS_MODEL,
	STM32_NOT_SUPPORT_MODEL,
};

#define SET_POGO_NOTIFIER_BLOCK(nb, fn, dev)		\
		do {					\
			(nb)->notifier_call = (fn);	\
			(nb)->priority = (dev);		\
		} while (0)

#define DESTROY_POGO_NOTIFIER_BLOCK(nb) SET_POGO_NOTIFIER_BLOCK(nb, NULL, -1)

struct pogo_data_struct {
	u8 size;
	char *data;
	int module_id;
	enum stm32_model keyboard_model;
};

int pogo_notifier_register(struct notifier_block *nb, notifier_fn_t notifier,
				enum pogo_notifier_device_t listener);
int pogo_notifier_unregister(struct notifier_block *nb);

#endif /* __POGO_I2C_NOTIFIER_H__*/
