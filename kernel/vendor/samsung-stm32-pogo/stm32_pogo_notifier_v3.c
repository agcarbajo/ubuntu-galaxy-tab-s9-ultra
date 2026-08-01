#include "stm32_pogo_v3.h"

int boot_module_id;
EXPORT_SYMBOL(boot_module_id);
enum pogo_notifier_id_t pogo_notifier_id;
EXPORT_SYMBOL(pogo_notifier_id);
static DEFINE_MUTEX(stm32_notifier_lock);
static BLOCKING_NOTIFIER_HEAD(pogo_notifier_call_chain);

void stm32_send_conn_noti(struct stm32_dev *stm32)
{
	char str_conn[16] = { 0 };
	char *event[2] = { str_conn, NULL };

	if (stm32->connect_state)
		pogo_notifier_notify(stm32, POGO_NOTIFIER_ID_ATTACHED, 0, 0);
	else
		pogo_notifier_notify(stm32, POGO_NOTIFIER_ID_DETACHED, 0, 0);
	snprintf(str_conn, 16, "CONNECT=%d", stm32->connect_state);
	kobject_uevent_env(&stm32->sec_pogo->kobj, KOBJ_CHANGE, event);
	input_info(true, &stm32->client->dev, "%s: send uevent : %s\n", __func__, event[0]);
}

void pogo_set_conn_state(int state)
{
	if (state)
		pogo_notifier_id = POGO_NOTIFIER_ID_ATTACHED;
	else
		pogo_notifier_id = POGO_NOTIFIER_ID_DETACHED;
	pr_info("%s %s %s: conn:0x%02X\n", __func__, SECLOG, STM32_DRV_NAME, pogo_notifier_id);
}

int pogo_notifier_notify(struct stm32_dev *stm32, enum pogo_notifier_id_t notify_id, char *data, int len)
{
	int ret = 0;
	struct pogo_data_struct send_data;

	if (stm32->debug_level & STM32_DEBUG_LEVEL_IRQ_DATA_LOG)
		input_info(true, &stm32->client->dev, "%s: ID=%d, len=%d\n", __func__, notify_id, len);

	if (len > STM32_MAX_EVENT_SIZE) {
		input_err(true, &stm32->client->dev, "%s: length is too long %d\n", __func__, len);
		return -EINVAL;
	}

	if (len > 0 && data && (stm32->debug_level & STM32_DEBUG_LEVEL_IRQ_DATA_LOG)) {
		int i;

		pr_info("%s %s %s: size:%d, ", SECLOG, STM32_DRV_NAME, __func__, len);
		for (i = 0; i < len; i++)
			pr_cont("%02X ", data[i]);
		pr_cont("\n");
	}

	send_data.size = len;
	send_data.data = data;
	send_data.module_id = stm32->ic_fw_ver.model_id;
	send_data.keyboard_model = stm32->keyboard_model;

	ret = blocking_notifier_call_chain(&pogo_notifier_call_chain, notify_id, &send_data);

	switch (ret) {
	case NOTIFY_STOP_MASK:
	case NOTIFY_BAD:
		input_err(true, &stm32->client->dev, "%s: notify error occur(0x%x)\n", __func__, ret);
		break;
	case NOTIFY_DONE:
	case NOTIFY_OK:
		input_dbg(false, &stm32->client->dev, "%s: notify done(0x%x)\n", __func__, ret);
		break;
	default:
		input_err(true, &stm32->client->dev, "%s: notify status unknown(0x%x)\n", __func__, ret);
		break;
	}

	return ret;
}

int pogo_notifier_register(struct notifier_block *nb, notifier_fn_t notifier, enum pogo_notifier_device_t listener)
{
	struct pogo_data_struct send_data;
	int ret = 0;

	pr_info("%s %s %s: listener=%d register\n", SECLOG, STM32_DRV_NAME, __func__, listener);
	mutex_lock(&stm32_notifier_lock);
	SET_POGO_NOTIFIER_BLOCK(nb, notifier, listener);
	ret = blocking_notifier_chain_register(&pogo_notifier_call_chain, nb);
	if (ret < 0)
		pr_err("%s %s %s: blocking_notifier_chain_register error(%d)\n", SECLOG, STM32_DRV_NAME, __func__, ret);

	send_data.size = 0;
	send_data.data = 0;
	send_data.module_id = boot_module_id;
	nb->notifier_call(nb, pogo_notifier_id, &send_data);
	mutex_unlock(&stm32_notifier_lock);

	return ret;
}
EXPORT_SYMBOL(pogo_notifier_register);

int pogo_notifier_unregister(struct notifier_block *nb)
{
	int ret = 0;

	pr_info("%s %s %s: listener=%d unregister\n", SECLOG, STM32_DRV_NAME, __func__, nb->priority);
	mutex_lock(&stm32_notifier_lock);
	ret = blocking_notifier_chain_unregister(&pogo_notifier_call_chain, nb);
	if (ret < 0)
		pr_err("%s %s %s: blocking_notifier_chain_unregister error(%d)\n",
			SECLOG, STM32_DRV_NAME, __func__, ret);
	DESTROY_POGO_NOTIFIER_BLOCK(nb);
	mutex_unlock(&stm32_notifier_lock);
	return ret;
}
EXPORT_SYMBOL(pogo_notifier_unregister);

#if IS_ENABLED(CONFIG_INPUT_SEC_NOTIFIER)
static void stm32_reset_control(struct stm32_dev *stm32, bool enable)
{
	input_info(true, &stm32->client->dev, "%s: nrst-enabled:%d\n", __func__, enable);
	mutex_lock(&stm32->dev_lock);
	gpio_direction_output(stm32->dtdata->mcu_nrst, enable);
	mutex_unlock(&stm32->dev_lock);
}

static void stm32_keyboard_notify_flip_work(struct work_struct *work)
{
	struct stm32_dev *stm32 = container_of(work, struct stm32_dev, notify_flip_work);
	char hall_data;
	int retry = 80;

	stm32->flip_working = true;
	if (atomic_read(&stm32->flip_state)) {
		hall_data = POGO_HALL_E_LID_NORMAL;
		cancel_delayed_work_sync(&stm32->check_conn_work);
		cancel_delayed_work_sync(&stm32->check_init_work);
		cancel_delayed_work_sync(&stm32->check_ic_work);
		stm32_enable_irq(stm32, INT_DISABLE_SYNC);
		stm32_enable_conn_irq(stm32, INT_DISABLE_NOSYNC);
		stm32_enable_conn_wake_irq(stm32, false);
		pogo_notifier_notify(stm32, POGO_NOTIFIER_ID_RESET, 0, 0);
		pogo_notifier_notify(stm32, POGO_NOTIFIER_EVENTID_HALL, &hall_data, 1);
		stm32_reset_control(stm32, 0);
		stm32_dev_regulator(stm32, 0);
		atomic_set(&stm32->enabled, false);
	} else {
		stm32_enable_irq(stm32, INT_ENABLE);
		stm32_enable_conn_irq(stm32, INT_ENABLE);
		stm32_enable_conn_wake_irq(stm32, true);
		stm32_reset_control(stm32, 1);

		do {
			if (atomic_read(&stm32->flip_state)) {
				input_info(true, &stm32->client->dev, "%s: flip close, return\n", __func__);
				stm32->flip_working = false;
				return;
			} else if (atomic_read(&stm32->enabled)) {
				input_info(true, &stm32->client->dev, "%s: enabled, return (retry %d)\n", __func__, retry);
				stm32->flip_working = false;
				return;
			}
			stm32_delay(20);
		} while (--retry > 0);

		stm32->connect_state = gpio_get_value(stm32->dtdata->gpio_conn);
		input_info(true, &stm32->client->dev, "%s: connect_state %d\n", __func__, stm32->connect_state);

		if (!stm32->connect_state) {
			stm32_send_conn_noti(stm32);
			stm32_dev_regulator(stm32, 0);
		}
	}
	stm32->flip_working = false;
}

static int stm32_keyboard_notify_call(struct notifier_block *n, unsigned long data, void *v)
{
	struct stm32_dev *stm32 = container_of(n, struct stm32_dev, keyboard_input_nb);

	if (!stm32->dtdata->support_open_close)
		return NOTIFY_DONE;

	switch (data) {
	case NOTIFIER_WACOM_KEYBOARDCOVER_FLIP_OPEN:
		atomic_set(&stm32->flip_state, false);
		schedule_work(&stm32->notify_flip_work);
		break;
	case NOTIFIER_WACOM_KEYBOARDCOVER_FLIP_CLOSE:
		atomic_set(&stm32->flip_state, true);
		schedule_work(&stm32->notify_flip_work);
		break;
	default:
		break;
	}

	return NOTIFY_DONE;
}
#endif

void stm32_register_notify(struct stm32_dev *stm32)
{
#if IS_ENABLED(CONFIG_INPUT_SEC_NOTIFIER)
	sec_input_register_notify(&stm32->keyboard_input_nb, stm32_keyboard_notify_call, 1);
	INIT_WORK(&stm32->notify_flip_work, stm32_keyboard_notify_flip_work);
#endif
}

void stm32_unregister_notify(struct stm32_dev *stm32)
{
#if IS_ENABLED(CONFIG_INPUT_SEC_NOTIFIER)
	cancel_work_sync(&stm32->notify_flip_work);
	sec_input_unregister_notify(&stm32->keyboard_input_nb);
#endif
}

MODULE_LICENSE("GPL");
