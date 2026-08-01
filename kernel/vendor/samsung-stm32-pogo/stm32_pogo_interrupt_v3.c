#include "stm32_pogo_v3.h"

void stm32_enable_irq(struct stm32_dev *stm32, int enable)
{
	struct irq_desc *desc = irq_to_desc(stm32->dev_irq);

	if (enable != INT_ENABLE && enable != INT_DISABLE_NOSYNC && enable != INT_DISABLE_SYNC)
		return;

	mutex_lock(&stm32->irq_lock);
	if (enable == INT_ENABLE) {
		while (desc->depth > 0)
			enable_irq(stm32->dev_irq);
		input_info(true, &stm32->client->dev, "%s: enable dev irq\n", __func__);
	} else if (enable == INT_DISABLE_NOSYNC) {
		disable_irq_nosync(stm32->dev_irq);
		input_info(true, &stm32->client->dev, "%s: disable dev irq nosync\n", __func__);
	} else {
		disable_irq(stm32->dev_irq);
		input_info(true, &stm32->client->dev, "%s: disable dev irq\n", __func__);
	}
	mutex_unlock(&stm32->irq_lock);
}

void stm32_enable_conn_irq(struct stm32_dev *stm32, int enable)
{
	struct irq_desc *desc = irq_to_desc(stm32->conn_irq);
	if (enable != INT_ENABLE && enable != INT_DISABLE_NOSYNC && enable != INT_DISABLE_SYNC)
		return;

	mutex_lock(&stm32->irq_lock);
	if (enable == INT_ENABLE) {
		while (desc->depth > 0)
			enable_irq(stm32->conn_irq);
		input_info(true, &stm32->client->dev, "%s: enable conn irq\n", __func__);
	} else if (enable == INT_DISABLE_NOSYNC) {
		disable_irq_nosync(stm32->conn_irq);
		input_info(true, &stm32->client->dev, "%s: disable coon irq nosync\n", __func__);
	} else {
		disable_irq(stm32->conn_irq);
		input_info(true, &stm32->client->dev, "%s: disable conn irq\n", __func__);
	}
	mutex_unlock(&stm32->irq_lock);
}

void stm32_enable_conn_wake_irq(struct stm32_dev *stm32, bool enable)
{
	struct irq_desc *desc = irq_to_desc(stm32->conn_irq);

	mutex_lock(&stm32->irq_lock);
	if (enable) {
		while (desc->wake_depth < 1)
			enable_irq_wake(stm32->conn_irq);
		input_info(true, &stm32->client->dev, "%s: enable conn wake irq\n", __func__);
	} else {
		while (desc->wake_depth > 0)
			disable_irq_wake(stm32->conn_irq);
		input_info(true, &stm32->client->dev, "%s: disable conn wake irq\n", __func__);
	}
	mutex_unlock(&stm32->irq_lock);
}

static int stm32_keyboard_start(struct stm32_dev *stm32)
{
	int ret = 0;

	ret = stm32_dev_regulator(stm32, 1);
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "%s: regulator on error\n", __func__);
		goto out;
	}

	stm32_delay(50);
	stm32_enable_irq(stm32, INT_ENABLE);

	input_info(true, &stm32->client->dev, "%s done\n", __func__);
	return 0;
out:
	input_err(true, &stm32->client->dev, "%s: failed. int:%d, sda:%d, scl:%d\n",
			__func__, gpio_get_value(stm32->dtdata->gpio_int), gpio_get_value(stm32->dtdata->gpio_sda),
			gpio_get_value(stm32->dtdata->gpio_scl));

	stm32_enable_irq(stm32, INT_DISABLE_NOSYNC);

	if (stm32_dev_regulator(stm32, 0) < 0)
		input_err(true, &stm32->client->dev, "%s: regulator off error\n", __func__);

	return ret;
}

static int stm32_keyboard_stop(struct stm32_dev *stm32)
{
	int ret = 0;

	stm32_enable_irq(stm32, INT_DISABLE_NOSYNC);

	ret = stm32_dev_regulator(stm32, 0);
	if (ret < 0)
		input_err(true, &stm32->client->dev, "%s: regulator off error\n", __func__);

	atomic_set(&stm32->enabled, false);

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, ret < 0 ? "failed" : "done");

	return ret;
}



void stm32_keyboard_connect(struct stm32_dev *stm32)
{
	mutex_lock(&stm32->dev_lock);

	input_info(true, &stm32->client->dev, "%s: %d\n", __func__, stm32->connect_state);
	stm32->hall_closed = false;

#ifndef CONFIG_SEC_FACTORY
	if (!stm32->resume_done.done)
		__pm_wakeup_event(stm32->stm32_ws, 3 * MSEC_PER_SEC);
#endif
	cancel_delayed_work(&stm32->check_ic_work);

	if (stm32->connect_state) {
		stm32_keyboard_start(stm32);
		schedule_delayed_work(&stm32->check_init_work, 500);
	} else {
		stm32_keyboard_stop(stm32);
		atomic_set(&stm32->check_conn_flag, false);
	}

	pogo_set_conn_state(stm32->connect_state);

	if (!stm32->connect_state)
		cancel_delayed_work(&stm32->print_info_work);
	else
		schedule_delayed_work(&stm32->print_info_work, STM32_PRINT_INFO_DELAY);

	mutex_unlock(&stm32->dev_lock);
}

static void stm32_check_conn_work(struct work_struct *work)
{
	struct stm32_dev *stm32 = container_of(work, struct stm32_dev, check_conn_work.work);
	int current_conn_state;

	mutex_lock(&stm32->conn_lock);
	current_conn_state = gpio_get_value(stm32->dtdata->gpio_conn);
	input_info(true, &stm32->client->dev, "%s: con:%d, current:%d\n",
			__func__, stm32->connect_state, current_conn_state);
	if (stm32->connect_state) {
		if (!current_conn_state) {
			stm32->connect_state = current_conn_state;
			stm32_keyboard_connect(stm32);
			stm32_send_conn_noti(stm32);
		} else {
			stm32_dev_regulator(stm32, 1);
		}
	} else {
		if (current_conn_state) {
			stm32->connect_state = current_conn_state;
			stm32_keyboard_connect(stm32);
		}
	}
	mutex_unlock(&stm32->conn_lock);
}

static void stm32_check_init_work(struct work_struct *work)
{
	struct stm32_dev *stm32 = container_of((struct delayed_work *)work, struct stm32_dev, check_init_work);

	if (!atomic_read(&stm32->check_conn_flag)) {
		input_info(true, &stm32->client->dev, "%s: start\n", __func__);
		stm32->connect_state = 0;
		stm32_keyboard_connect(stm32);
	}
}

static void stm32_check_ic_work(struct work_struct *work)
{
	struct stm32_dev *stm32 = container_of((struct delayed_work *)work, struct stm32_dev, check_ic_work);
	int ret;

	if (!atomic_read(&stm32->check_ic_flag)) {
		if (stm32->hall_closed) {
			input_info(true, &stm32->client->dev, "%s: cover closed or fold backward\n", __func__);
			return;
		}

		ret = stm32_read_version(stm32);
		if (ret < 0) {
			input_err(true, &stm32->client->dev, "%s: failed to read version, %d\n", __func__, ret);
			return;
		}
	}

	ret = stm32_set_mode(stm32, MODE_APP);
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to set APP mode\n", __func__);
		return;
	}

	if (!stm32->hall_flag) {
		ret = stm32_read_crc(stm32);
		if (ret < 0) {
			input_err(true, &stm32->client->dev, "%s: failed to get CRC\n", __func__);
			return;
		}

		ret = stm32_read_tc_version(stm32);
		if (ret < 0) {
			input_err(true, &stm32->client->dev, "%s: failed to read TC version\n", __func__);
			return;
		}

		if ((stm32->tc_fw_ver_of_ic.major_ver != 0xff) || (stm32->tc_fw_ver_of_ic.minor_ver != 0)) {
			ret = stm32_read_tc_crc(stm32);
			if (ret < 0) {
				input_err(true, &stm32->client->dev, "%s: failed to read TC CRC\n", __func__);
				return;
			}

			ret = stm32_read_tc_resolution(stm32);
			if (ret < 0) {
				input_err(true, &stm32->client->dev, "%s: failed to read TC resolution\n", __func__);
				return;
			}
		} else {
			stm32->tc_crc = STM32_TC_CRC_OK;
		}
	}

	atomic_set(&stm32->check_ic_flag, false);
	atomic_set(&stm32->enabled, true);
}

static void stm32_dev_int_proc(struct stm32_dev *stm32)
{
	int ret = 0;
	u8 event_data[STM32_MAX_EVENT_SIZE] = { 0 };
	u16 payload_size;
	u8 buff[3] = { 0 };
	enum pogo_notifier_id_t notifier_id = POGO_NOTIFIER_EVENTID_NONE;

#if IS_ENABLED(CONFIG_PM)
	if (!stm32->resume_done.done) {
		if (!IS_ERR_OR_NULL(stm32->irq_workqueue)) {
			__pm_wakeup_event(stm32->stm32_ws, SEC_TS_WAKE_LOCK_TIME);
			/* waiting for blsp block resuming, if not occurs i2c error */
			input_err(true, &stm32->client->dev, "%s: disable irq and queue waiting work\n", __func__);
			stm32_enable_irq(stm32, INT_DISABLE_NOSYNC);
			queue_work(stm32->irq_workqueue, &stm32->irq_work);
			return;
		}
		input_err(true, &stm32->client->dev, "%s: irq_workqueue not exist\n", __func__);
	}
#endif
	mutex_lock(&stm32->i2c_lock);

	ret = stm32_i2c_header_write(stm32->client, stm32_caps_led_value, 0);
	if (ret < 0)
		goto out_i2c_lock;

	ret = stm32_i2c_read_bulk(stm32->client, buff, 3);
	if (ret < 0)
		goto out_i2c_lock;

	memcpy(&payload_size, buff, 2);
	payload_size -= 3;

	if (!payload_size || payload_size > STM32_MAX_EVENT_SIZE) {
		mutex_unlock(&stm32->i2c_lock);
		stm32->keyboard_model = buff[2];
		input_err(true, &stm32->client->dev, "%s: support_keyboard_model 0x%x\n", __func__, buff[2]);
		ret = stm32_read_version(stm32);
		if (ret < 0)
			input_err(true, &stm32->client->dev, "%s: failed to read version\n", __func__);
		atomic_set(&stm32->check_ic_flag, true);
		schedule_delayed_work(&stm32->check_ic_work, msecs_to_jiffies(10));
		atomic_set(&stm32->check_conn_flag, true);
		stm32_send_conn_noti(stm32);

		ret = kbd_max77816_control(stm32, stm32->dtdata->booster_power_voltage);
		if (ret < 0) {
			input_err(true, &stm32->client->dev, "%s: failed kbd_max77816_control %d V\n",
					__func__, stm32->dtdata->booster_power_voltage);
		}

		input_info(true, &stm32->client->dev, "%s: sendconn\n", __func__);
		return;
	}

	ret = stm32_i2c_read_bulk(stm32->client, event_data, payload_size);
	if (ret < 0)
		goto out_i2c_lock;

	/* burst noise & impulse noise */
	if (event_data[0] == 0x03 && event_data[1] == 0x00 && event_data[2] == 0x05)
		goto out_i2c_lock;

	mutex_unlock(&stm32->i2c_lock);

	notifier_id = (enum pogo_notifier_id_t)buff[2];

	if (notifier_id > POGO_NOTIFIER_EVENTID_MCU && notifier_id < POGO_NOTIFIER_EVENTID_MAX)
		pogo_notifier_notify(stm32, notifier_id, event_data, payload_size);
	else
		input_err(true, &stm32->client->dev, "%s: wrong id %d, size %d\n", __func__, notifier_id, payload_size);

	if (notifier_id == POGO_NOTIFIER_EVENTID_ACESSORY) {
		input_info(true, &stm32->client->dev, "%s: evendata[0] %d, event_data[1] %d\n",
					__func__, event_data[0], event_data[1]);

		if (event_data[1] == 0x01) {
			atomic_set(&stm32->check_conn_flag, true);
			stm32_dev_regulator(stm32, 0);

			stm32->ic_fw_ver.fw_major_ver = 0;
			stm32->ic_fw_ver.fw_minor_ver = 0;
			stm32->ic_fw_ver.model_id = 0;
			stm32->ic_fw_ver.hw_rev = 0;
			stm32->tc_fw_ver_of_ic.major_ver = 0;
			stm32->tc_fw_ver_of_ic.minor_ver = 0;
			stm32->tc_fw_ver_of_ic.data_ver = 0;
			stm32->keyboard_model = 0;
		}
		return;
	}

	/* release all event if hall ic event occurred */
	if (notifier_id == POGO_NOTIFIER_EVENTID_HALL) {
		pogo_notifier_notify(stm32, POGO_NOTIFIER_ID_RESET, 0, 0);
		stm32->hall_closed = (event_data[0] != 2);
		if (stm32->hall_flag && !stm32->hall_closed) {
			input_info(true, &stm32->client->dev, "%s: hall_flag %d, hall_closed:%d\n",
					__func__, stm32->hall_flag, stm32->hall_closed);
			schedule_work(&stm32->check_ic_work.work);
			stm32->hall_flag = false;
		}
	}

	return;

out_i2c_lock:
	mutex_unlock(&stm32->i2c_lock);
}

static irqreturn_t stm32_dev_isr(int irq, void *dev_id)
{
	struct stm32_dev *stm32 = (struct stm32_dev *)dev_id;
#if IS_ENABLED(CONFIG_QCOM_BUS_SCALING) || IS_ENABLED(CONFIG_INTERCONNECT)
	int ret = 0;
#endif
	if (gpio_get_value(stm32->dtdata->gpio_int))
		return IRQ_HANDLED;
#if IS_ENABLED(CONFIG_QCOM_BUS_SCALING)
	if (stm32->stm32_bus_perf_client) {
		cancel_delayed_work(&stm32->bus_voting_work);
		if (stm32->voting_flag == STM32_BUS_VOTING_NONE) {
			ret = msm_bus_scale_client_update_request(stm32->stm32_bus_perf_client, STM32_BUS_VOTING_UP);
			if (ret) {
				input_info(true, &stm32->client->dev, "%s: voting failed ret:%d\n", __func__, ret);
			} else {
				input_info(true, &stm32->client->dev, "%s: voting success ret:%d\n", __func__, ret);
				stm32->voting_flag = STM32_BUS_VOTING_UP;
			}
		}
	}

	if (stm32->stm32_bus_perf_client)
		schedule_delayed_work(&stm32->bus_voting_work, msecs_to_jiffies(15000));

#elif IS_ENABLED(CONFIG_INTERCONNECT)
	if (stm32->stm32_register_ddr) {
		cancel_delayed_work(&stm32->bus_voting_work);
		if (stm32->voting_flag == STM32_BUS_VOTING_NONE) {
			ret = icc_set_bw(stm32->stm32_icc_data, STM32_AB_DATA, STM32_IB_MAX);
			if (ret) {
				input_info(true, &stm32->client->dev, "%s: voting failed ret:%d\n", __func__, ret);
			} else {
				input_info(true, &stm32->client->dev, "%s: voting success ret:%d\n", __func__, ret);
				stm32->voting_flag = STM32_BUS_VOTING_UP;
			}
		}
	}

	if (stm32->stm32_register_ddr)
		schedule_delayed_work(&stm32->bus_voting_work, msecs_to_jiffies(15000));
#endif

	mutex_lock(&stm32->dev_lock);
	stm32_dev_int_proc(stm32);
	mutex_unlock(&stm32->dev_lock);

	return IRQ_HANDLED;
}


#if IS_ENABLED(CONFIG_PM)
static void stm32_handler_wait_resume_work(struct work_struct *work)
{
	struct stm32_dev *stm32 = container_of(work, struct stm32_dev, irq_work);
	int ret;
	struct irq_desc *desc;

	desc = irq_to_desc(stm32->dev_irq);

	ret = wait_for_completion_interruptible_timeout(&stm32->resume_done, msecs_to_jiffies(SEC_TS_WAKE_LOCK_TIME));
	if (ret == 0) {
		input_err(true, &stm32->client->dev, "%s: LPM: pm resume is not handled\n", __func__);
		goto out;
	}
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "%s: LPM: -ERESTARTSYS if interrupted, %d\n", __func__, ret);
		goto out;
	}

	if (desc && desc->action && desc->action->thread_fn) {
		input_info(true, &stm32->client->dev, "%s: run irq thread\n", __func__);
		desc->action->thread_fn(stm32->dev_irq, desc->action->dev_id);
	}
out:
	stm32_enable_irq(stm32, INT_ENABLE);
}

static void stm32_handler_wait_resume_conn_work(struct work_struct *work)
{
	struct stm32_dev *stm32 = container_of(work, struct stm32_dev, conn_irq_work);
	int ret;
	struct irq_desc *desc;

	desc = irq_to_desc(stm32->conn_irq);

	ret = wait_for_completion_interruptible_timeout(&stm32->resume_done, msecs_to_jiffies(SEC_TS_WAKE_LOCK_TIME));
	if (ret == 0) {
		input_err(true, &stm32->client->dev, "%s: LPM: pm resume is not handled\n", __func__);
		goto out;
	}
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "%s: LPM: -ERESTARTSYS if interrupted, %d\n", __func__, ret);
		goto out;
	}

	if (desc && desc->action && desc->action->thread_fn) {
		input_info(true, &stm32->client->dev, "%s: run irq thread\n", __func__);
		desc->action->thread_fn(stm32->conn_irq, desc->action->dev_id);
	}
out:
	stm32_enable_conn_irq(stm32, INT_ENABLE);
}
#endif

static irqreturn_t stm32_conn_isr(int irq, void *dev_id)
{
	struct stm32_dev *stm32 = (struct stm32_dev *)dev_id;

#if IS_ENABLED(CONFIG_PM)
	if (!stm32->resume_done.done) {
		if (!IS_ERR_OR_NULL(stm32->irq_workqueue)) {
			__pm_wakeup_event(stm32->stm32_ws, SEC_TS_WAKE_LOCK_TIME);
			/* waiting for blsp block resuming, if not occurs i2c error */
			input_err(true, &stm32->client->dev, "%s: disable irq and queue waiting work\n", __func__);
			stm32_enable_conn_irq(stm32, INT_DISABLE_NOSYNC);
			queue_work(stm32->conn_irq_workqueue, &stm32->conn_irq_work);
			return IRQ_HANDLED;
		}
		input_err(true, &stm32->client->dev, "%s: irq_workqueue not exist\n", __func__);
	}
#endif
	cancel_delayed_work_sync(&stm32->check_conn_work);
	input_info(true, &stm32->client->dev, "%s (%d)\n", __func__, gpio_get_value(stm32->dtdata->gpio_conn));
	if (!gpio_get_value(stm32->dtdata->gpio_conn)) {
		stm32_dev_regulator(stm32, 0);
		if (!stm32->flip_working)
			schedule_delayed_work(&stm32->check_conn_work, msecs_to_jiffies(250));
	} else {
		schedule_work(&stm32->check_conn_work.work);
	}

	return IRQ_HANDLED;
}

int stm32_interrupt_init(struct stm32_dev *stm32)
{
	int ret = 0;

	if (unlikely(stm32 == NULL)) {
		pr_err("%s %s stm32 is NULL or Error\n", SECLOG, __func__);
		return SEC_ERROR;
	}

#if IS_ENABLED(CONFIG_PM)
	stm32->irq_workqueue = create_singlethread_workqueue("stm32_delayed_irq");
	INIT_WORK(&stm32->irq_work, stm32_handler_wait_resume_work);
	stm32->conn_irq_workqueue = create_singlethread_workqueue("stm32_delayed_conn_irq");
	INIT_WORK(&stm32->conn_irq_work, stm32_handler_wait_resume_conn_work);
#endif
	INIT_DELAYED_WORK(&stm32->check_ic_work, stm32_check_ic_work);
	INIT_DELAYED_WORK(&stm32->check_conn_work, stm32_check_conn_work);
	INIT_DELAYED_WORK(&stm32->check_init_work, stm32_check_init_work);

	stm32->dev_irq = gpio_to_irq(stm32->dtdata->gpio_int);
	if (stm32->dev_irq < 0) {
		input_info(true, &stm32->client->dev, "%s failed to load INT PIN (%d)\n", __func__, stm32->dev_irq);
		return SEC_ERROR;
	}

	input_info(true, &stm32->client->dev, "%s INT mode (%d)\n", __func__, stm32->dev_irq);

	stm32->conn_irq = gpio_to_irq(stm32->dtdata->gpio_conn);
	if (stm32->conn_irq < 0) {
		input_info(true, &stm32->client->dev, "%s failed to load CONN INT PIN (%d)\n",
				__func__, stm32->conn_irq);
		return SEC_ERROR;
	}

	input_info(true, &stm32->client->dev, "%s CONN INT PIN (%d)\n", __func__, stm32->conn_irq);

	ret = request_threaded_irq(stm32->dev_irq, NULL, stm32_dev_isr, stm32->dtdata->irq_type, STM32_DRV_NAME, stm32);
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "stm32_dev_irq request error %d\n", ret);
		return SEC_ERROR;
	}

	ret = request_threaded_irq(stm32->conn_irq, NULL, stm32_conn_isr, stm32->dtdata->irq_conn_type,
					STM32_DRV_CONN_NAME, stm32);
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "stm32_dev_conn_isr request error %d\n", ret);
		return SEC_ERROR;
	}

	stm32_enable_conn_wake_irq(stm32, true);
	stm32_enable_irq(stm32, INT_DISABLE_NOSYNC);

	return SEC_SUCCESS;
}

MODULE_LICENSE("GPL");
