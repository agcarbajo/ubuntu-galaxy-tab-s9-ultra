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

#include "stm32_pogo_v3.h"

int stm32_caps_led_value = 0x1;
EXPORT_SYMBOL(stm32_caps_led_value);

int stm32_i2c_read_bulk(struct i2c_client *client, u8 *data, u8 length)
{
	struct stm32_dev *stm32 = i2c_get_clientdata(client);
	int ret;
	int retry = 3;
	struct i2c_msg msgs;

	reinit_completion(&stm32->i2c_done);

	if ((!stm32->connect_state) && (client->addr != 0x51) && mutex_is_locked(&stm32->conn_lock)) {
		input_err(true, &client->dev, "%s: not connected\n", __func__);
		complete_all(&stm32->i2c_done);
		return -ENODEV;
	}

	msgs.addr = client->addr;
	msgs.flags = client->flags | I2C_M_RD | I2C_M_DMA_SAFE;
	msgs.len = length;
	msgs.buf = stm32->read_write_buf;

	while (retry--) {
		ret = i2c_transfer(client->adapter, &msgs, 1);
		if (ret != 1) {
			pogo_notifier_notify(stm32, POGO_NOTIFIER_ID_RESET, 0, 0);
			input_err(true, &client->dev, "scl:%d, sda:%d, int:%d\n",
					gpio_get_value(stm32->dtdata->gpio_scl),
					gpio_get_value(stm32->dtdata->gpio_sda),
					gpio_get_value(stm32->dtdata->gpio_int));
			ret = -EIO;
			stm32_delay(10);
			if ((!stm32->connect_state) && (client->addr != 0x51) && mutex_is_locked(&stm32->conn_lock)) {
				input_err(true, &client->dev, "%s: connect_state=%d\n", __func__, stm32->connect_state);
				complete_all(&stm32->i2c_done);
				return ret;
			}
			continue;
		}
		break;
	}

	if (stm32->debug_level & STM32_DEBUG_LEVEL_I2C_LOG) {
		int i;

		pr_info("%s %s: ", SECLOG, __func__);
		for (i = 0; i < length; i++)
			pr_cont("%02X ", stm32->read_write_buf[i]);
		pr_cont("\n");
	}

	memcpy(data, stm32->read_write_buf, length);
	memset(stm32->read_write_buf, 0x0, length);
	if ((ret < 0) && (client->addr != 0x51))
		stm32_power_reset(stm32);

	complete_all(&stm32->i2c_done);
	return ret;
}

int stm32_i2c_write_burst(struct i2c_client *client, u8 *data, int length)
{
	struct stm32_dev *stm32 = i2c_get_clientdata(client);
	int ret;
	int retry = 3;

	reinit_completion(&stm32->i2c_done);

	if ((!stm32->connect_state) && (client->addr != 0x51) && mutex_is_locked(&stm32->conn_lock)) {
		input_err(true, &client->dev, "%s: not connected\n", __func__);
		complete_all(&stm32->i2c_done);
		return -ENODEV;
	}

	if (length > STM32_DEV_FW_UPDATE_PACKET_SIZE) {
		input_err(true, &client->dev, "%s: The i2c buffer size is exceeded.\n", __func__);
		complete_all(&stm32->i2c_done);
		return -ENOMEM;
	}

	memcpy(stm32->read_write_buf, data, length);

	for (retry = 0; retry < STM32_DEV_I2C_RETRY_CNT; retry++) {
		ret = i2c_master_send_dmasafe(client, stm32->read_write_buf, length);
		if (ret == length)
			break;

		usleep_range(1 * 1000, 1 * 1000);

		if ((!stm32->connect_state) && (client->addr != 0x51) && mutex_is_locked(&stm32->conn_lock)) {
			input_err(true, &client->dev, "%s: connect_state=%d\n", __func__, stm32->connect_state);
			complete_all(&stm32->i2c_done);
			return ret;
		}

		if (retry > 1)
			input_err(true, &client->dev, "%s: I2C retry %d, ret:%d\n", __func__, retry + 1, ret);
	}

	if (retry == STM32_DEV_I2C_RETRY_CNT) {
		input_err(true, &client->dev, "%s: I2C write over retry limit\n", __func__);
		ret = -EIO;
	}

	if (stm32->debug_level & STM32_DEBUG_LEVEL_I2C_LOG) {
		int i;

		pr_info("%s %s: ", SECLOG, __func__);
		for (i = 0; i < length; i++)
			pr_cont("%02X ", stm32->read_write_buf[i]);
		pr_cont("\n");
	}

	memset(stm32->read_write_buf, 0x0, length);

	if ((ret < 0) && (client->addr != 0x51))
		stm32_power_reset(stm32);

	complete_all(&stm32->i2c_done);

	return ret;
}

int stm32_i2c_header_write(struct i2c_client *client, enum stm32_ed_id ed_id, u16 payload_size)
{
	u8 buff[3] = { 0 };

	payload_size += 3;

	buff[0] = payload_size & 0xFF;
	buff[1] = (payload_size >> 8) & 0xFF;
	buff[2] = (u8)ed_id;

	return stm32_i2c_write_burst(client, buff, 3);
}

int stm32_i2c_reg_write(struct i2c_client *client, enum stm32_ed_id ed_id, u8 regaddr)
{
	struct stm32_dev *stm32 = i2c_get_clientdata(client);
	int ret;

	mutex_lock(&stm32->i2c_lock);
	ret = stm32_i2c_header_write(client, ed_id, 1);
	if (ret < 0)
		goto out;

	ret = stm32_i2c_write_burst(client, &regaddr, 1);

out:
	mutex_unlock(&stm32->i2c_lock);
	return ret;
}

int stm32_i2c_reg_read(struct i2c_client *client, enum stm32_ed_id ed_id, u8 regaddr, u16 length, u8 *values)
{
	struct stm32_dev *stm32 = i2c_get_clientdata(client);
	int ret;
	u16 payload_size = 0;
	u8 buff[3] = { 0 };

	mutex_lock(&stm32->i2c_lock);
	ret = stm32_i2c_header_write(client, ed_id, 1);
	if (ret < 0)
		goto out;

	ret = stm32_i2c_write_burst(client, &regaddr, 1);
	if (ret < 0)
		goto out;

	ret = stm32_i2c_read_bulk(client, buff, 3);
	if (ret < 0)
		goto out;

	memcpy(&payload_size, buff, 2);
	payload_size -= 3;
	if (payload_size == 0 || payload_size > 0xFF) {
		input_err(true, &client->dev, "wrong value of payload size %d\n", payload_size);
		ret = -EIO;
		goto out;
	}

	if (payload_size > length) {
		input_err(true, &client->dev, "payload size %d is over buff length %d\n", payload_size, length);
		ret = -EIO;
		goto out;
	}

	ret = stm32_i2c_read_bulk(client, values, payload_size);
out:
	mutex_unlock(&stm32->i2c_lock);
	return ret;
}

static int stm32_dev_allocate(struct i2c_client *client)
{
	struct stm32_dev *stm32;

	if (IS_ERR_OR_NULL(client))
		return SEC_ERROR;

	stm32 = devm_kzalloc(&client->dev, sizeof(struct stm32_dev), GFP_KERNEL);
	if (unlikely(stm32 == NULL)) {
		input_err(true, &client->dev, "Failed to allocate memory\n");
		return SEC_ERROR;
	}

	stm32->dtdata = devm_kzalloc(&client->dev, sizeof(struct stm32_devicetree_data), GFP_KERNEL);
	if (unlikely(stm32->dtdata == NULL)) {
		input_err(true, &client->dev, "Failed to allocate memory dtdata.\n");
		return SEC_ERROR;
	}

	stm32->fw_header = devm_kzalloc(&client->dev, sizeof(struct stm32_fw_header), GFP_KERNEL);
	if (unlikely(stm32->fw_header == NULL)) {
		input_err(true, &client->dev, "fw header kzalloc memory error\n");
		return SEC_ERROR;
	}

	stm32->fw = devm_kzalloc(&client->dev, sizeof(struct firmware), GFP_KERNEL);
	if (unlikely(stm32->fw == NULL)) {
		input_err(true, &client->dev, "fw kzalloc memory error\n");
		return SEC_ERROR;
	}

	stm32->fw->data = devm_kzalloc(&client->dev, STM32_FW_SIZE, GFP_KERNEL);
	if (unlikely(stm32->fw->data == NULL)) {
		input_err(true, &client->dev, "fw data kzalloc memory error\n");
		return SEC_ERROR;
	}

	stm32->tc_fw = devm_kzalloc(&client->dev, sizeof(struct firmware), GFP_KERNEL);
	if (unlikely(stm32->tc_fw == NULL)) {
		input_err(true, &client->dev, "tc fw data kzalloc memory error\n");
		return SEC_ERROR;
	}

	stm32->tc_fw->data = devm_kzalloc(&client->dev, STM32_FW_SIZE, GFP_KERNEL);
	if (unlikely(stm32->tc_fw->data == NULL)) {
		input_err(true, &client->dev, "tc fw data kzalloc memory error\n");
		return SEC_ERROR;
	}

	stm32->sec_pogo_keyboard_fw = devm_kmalloc(&client->dev, STM32_KEYBOARD_FW_SIZE, GFP_KERNEL | __GFP_COMP);
	if (unlikely(stm32->sec_pogo_keyboard_fw == NULL)) {
		input_err(true, &client->dev, "sec_pogo_keyboard_fw kzalloc memory error\n");
		return SEC_ERROR;
	}

	stm32->client = client;

	i2c_set_clientdata(client, stm32);

	return SEC_SUCCESS;
}

static int stm32_dev_probe(struct i2c_client *client, const struct i2c_device_id *id)
{
	struct stm32_dev *stm32;
	int ret = 0;

#if !IS_ENABLED(CONFIG_SEC_FACTORY)
	static int deferred_flag;

	if (!deferred_flag) {
		deferred_flag = 1;
		input_info(true, &client->dev, "deferred_flag boot %s\n", __func__);
		return -EPROBE_DEFER;
	}
#endif

	input_info(true, &client->dev, "%s++\n", __func__);

	if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C)) {
		input_err(true, &client->dev, "i2c_check_functionality fail\n");
		return -EIO;
	}

	ret = stm32_dev_allocate(client);
	if (IS_SEC_ERROR(ret)) {
		input_err(true, &client->dev, "Failed to allocate memory\n");
		return -ENOMEM;
	}

	stm32 = i2c_get_clientdata(client);
	if (unlikely(stm32 == NULL)) {
		input_err(true, &client->dev, "failed i2c_get_clientdata\n");
		return -ENOMEM;
	}

	ret = stm32_pogo_v3_start(stm32);

	return ret;
}

static int stm32_dev_remove(struct i2c_client *client)
{
	struct stm32_dev *stm32 = i2c_get_clientdata(client);

	input_info(true, &client->dev, "%s\n", __func__);

	cancel_delayed_work_sync(&stm32->print_info_work);
	cancel_delayed_work_sync(&stm32->check_ic_work);
	cancel_delayed_work_sync(&stm32->check_conn_work);
	cancel_delayed_work_sync(&stm32->check_init_work);

	stm32_unregister_notify(stm32);
	stm32_voting_remove(stm32);
	device_init_wakeup(&client->dev, false);
	wakeup_source_unregister(stm32->stm32_ws);

	stm32_dev_regulator(stm32, 0);

	i2c_unregister_device(stm32->client_boot);

	free_irq(stm32->dev_irq, stm32);
	free_irq(stm32->conn_irq, stm32);
	sec_device_destroy(stm32->sec_pogo->devt);

	return 0;
}

#if IS_ENABLED(CONFIG_PM)
static int stm32_dev_suspend(struct device *dev)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret = 0;

	ret = wait_for_completion_interruptible_timeout(&stm32->i2c_done, msecs_to_jiffies(3 * MSEC_PER_SEC));
	if (ret <= 0)
		pr_err("%s %s: i2c is not handled, error %d\n", SECLOG, __func__, ret);

	stm32_voting_suspend(stm32);
	cancel_delayed_work(&stm32->print_info_work);

	reinit_completion(&stm32->resume_done);

	if (stm32->connect_state) {
		enable_irq_wake(stm32->dev_irq);
		stm32->irq_wake = true;
		pr_info("%s %s enable irq wake\n", SECLOG, __func__);
	}

	return 0;
}

static int stm32_dev_resume(struct device *dev)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);

	complete_all(&stm32->resume_done);

	if (stm32->irq_wake && device_may_wakeup(dev)) {
		disable_irq_wake(stm32->dev_irq);
		stm32->irq_wake = false;
		pr_info("%s %s disable irq wake\n", SECLOG, __func__);
	}
	if (stm32->connect_state)
		schedule_delayed_work(&stm32->print_info_work, STM32_PRINT_INFO_DELAY);

	return 0;
}

static SIMPLE_DEV_PM_OPS(stm32_dev_pm_ops, stm32_dev_suspend, stm32_dev_resume);
#endif

static const struct i2c_device_id stm32_dev_id[] = {
	{ STM32_DRV_NAME, 0 },
	{ }
};

static struct of_device_id stm32_match_table[] = {
	{ .compatible = "stm,stm32_pogo",},
	{ },
};

static struct i2c_driver stm32_dev_driver = {
	.driver = {
		.name = STM32_DRV_NAME,
		.owner = THIS_MODULE,
		.of_match_table = stm32_match_table,
#if IS_ENABLED(CONFIG_PM)
		.pm = &stm32_dev_pm_ops,
#endif
	},
	.probe = stm32_dev_probe,
	.remove = stm32_dev_remove,
	.id_table = stm32_dev_id,
};

static int __init stm32_dev_init(void)
{
	pr_err("%s++\n", __func__);

	return i2c_add_driver(&stm32_dev_driver);
}
static void __exit stm32_dev_exit(void)
{
	i2c_del_driver(&stm32_dev_driver);
	stm32_pogo_kpd_exit();
	stm32_pogo_touchpad_exit();
#if IS_ENABLED(CONFIG_HALL_LOGICAL)
	hall_logical_exit();
#endif
}
module_init(stm32_dev_init);
module_exit(stm32_dev_exit);

MODULE_DEVICE_TABLE(i2c, stm32_dev_id);

MODULE_DESCRIPTION("STM32 POGO I2C Driver");
MODULE_AUTHOR("Samsung");
MODULE_LICENSE("GPL");
