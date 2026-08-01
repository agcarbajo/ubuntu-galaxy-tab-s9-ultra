/*
 * kbd_max77816_i2c.c - Platform data for max77816 buck booster hw i2c driver
 *
 * Copyright (C) 2021 Samsung Electronics
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation.
 *
 */

#include "stm32_pogo_v3.h"

#define KBD_MAX77816_READ_SIZE	2
#define KBD_MAX77816_WRITE_SIZE	1

struct kbd_max77816_info kbd_boost_pdata;

int kbd_i2c_read_ex(u8 addr, u8 *value)
{
	u8 wr[] = { addr };
	int retry = 3;
	int ret = 0;

	struct i2c_msg msg[] = {
		{
			.addr = kbd_boost_pdata.client->addr,
			.flags = 0,
			.buf = wr,
			.len = 1
		}, {
			.addr = kbd_boost_pdata.client->addr,
			.flags = I2C_M_RD,
			.buf = value,
			.len = 1
		},
	};

	do {
		ret = i2c_transfer(kbd_boost_pdata.client->adapter, msg, KBD_MAX77816_READ_SIZE);
		if (ret != KBD_MAX77816_READ_SIZE)
			input_err(true, &kbd_boost_pdata.stm32->client->dev,
					"%s : client->addr 0x%02x read_addr 0x%02x error (ret == %d)\n",
					__func__, kbd_boost_pdata.client->addr, addr, ret);
		else
			break;
	} while (--retry);

	return (ret == KBD_MAX77816_READ_SIZE ? ret : -EIO);
}

int kbd_i2c_write_ex(u8 addr, u8 value)
{
	int retry = 3;
	u8 wr[] = { addr, value };
	int ret = -1;

	struct i2c_msg msg[] = {
		{
			.addr = kbd_boost_pdata.client->addr,
			.flags = 0,
			.buf = wr,
			.len = 2
		}
	};

	do {
		ret = i2c_transfer(kbd_boost_pdata.client->adapter, msg, KBD_MAX77816_WRITE_SIZE);
		if (ret != 1) {
			input_err(true, &kbd_boost_pdata.stm32->client->dev,
					"%s : addr 0x%02x value 0x%02x error (ret == %d)\n",
					__func__, addr, value, ret);
		} else
			break;
	} while (--retry);

	return (KBD_MAX77816_WRITE_SIZE == 1 ? ret : -EIO);
}

int kbd_max77816_control_init(struct stm32_dev *stm32)
{
	char max77816_data_config1[2] = { 0x02, 0x8E }; /* 0x8E (3.1A) */
	char max77816_data_config2[2] = { 0x03, 0x70 }; /* BB_EN=1(Enable buck-boost output) */
	int ret = 0;

	kbd_boost_pdata.stm32 = stm32;

	if (!stm32->dtdata->booster_power_model_cnt)
		return 0;

	if (!kbd_boost_pdata.client) {
		input_err(true, &stm32->client->dev, "%s : not probed\n", __func__);
		return -1;
	}

	input_info(true, &stm32->client->dev, "%s\n", __func__);

	ret = kbd_i2c_write_ex(max77816_data_config2[0], max77816_data_config2[1]);
	if (ret < 0)
		input_err(true, &stm32->client->dev, "%s : config2 write error(%d)\n", __func__, ret);

	ret = kbd_i2c_write_ex(max77816_data_config1[0], max77816_data_config1[1]);
	if (ret < 0)
		input_err(true, &stm32->client->dev, "%s : config1 write error(%d)\n", __func__, ret);

	return 0;
}

int kbd_max77816_control(struct stm32_dev *stm32, int voltage_val)
{
	char max77816_data_voltage[2] = { 0x04, 0x23 }; /* 0x23:3.30V(default) */
	char read_buf[2] = { 0 };
	int ret = 0;

	kbd_boost_pdata.stm32 = stm32;

	if (!stm32->dtdata->booster_power_model_cnt) {
		input_err(false, &stm32->client->dev, "%s : not support device\n", __func__);
		return 0;
	}

	if (!kbd_boost_pdata.client) {
		input_err(true, &stm32->client->dev, "%s : not probed\n", __func__);
		return -1;
	}

	if (!stm32_chk_booster_models(stm32)) {
		input_err(false, &stm32->client->dev, "%s : not support keyboard\n", __func__);
		return 0;
	}

	input_info(true, &stm32->client->dev, "%s : %d\n", __func__, voltage_val);

	ret = kbd_i2c_read_ex(max77816_data_voltage[0], &read_buf[0]);
	if (ret < 0)
		input_err(true, &stm32->client->dev, "%s : read error(%d)\n", __func__, ret);
	else
		input_info(true, &stm32->client->dev, "%s : Before set voltage(0X%X, %dv)\n",
				__func__, read_buf[0], KBD_MAX77816_REG_TO_VOL(read_buf[0]));

	max77816_data_voltage[1] = KBD_MAX77816_VOL_TO_REG(voltage_val);
	ret = kbd_i2c_write_ex(max77816_data_voltage[0], max77816_data_voltage[1]);
	if (ret < 0)
		input_err(true, &stm32->client->dev, "%s : write error(%d)\n", __func__, ret);
	else
		input_info(true, &stm32->client->dev, "%s : set voltage(0X%X, %dv)\n",
				__func__, max77816_data_voltage[1], voltage_val);

	ret = kbd_i2c_read_ex(max77816_data_voltage[0], &read_buf[0]);
	if (ret < 0)
		input_err(true, &stm32->client->dev, "%s : read error(%d)\n", __func__, ret);
	else
		input_info(true, &stm32->client->dev, "%s : After set voltage(0X%X, %dv)\n",
				__func__, read_buf[0], KBD_MAX77816_REG_TO_VOL(read_buf[0]));

	return 0;
}

static int kbd_max77816_probe(struct i2c_client *client, const struct i2c_device_id *id)
{
	struct i2c_adapter *adapter = to_i2c_adapter(client->dev.parent);

	input_info(true, &client->dev, "%s start\n", __func__);

	if (!i2c_check_functionality(adapter, I2C_FUNC_I2C)) {
		input_err(true, &client->dev, "%s i2c check fail\n", __func__);
		return -EIO;
	}

	kbd_boost_pdata.client = client;

	i2c_set_clientdata(client, &kbd_boost_pdata);

	return 0;
}

static int kbd_max77816_remove(struct i2c_client *client)
{
	return 0;
}

static const struct i2c_device_id kbd_max77816_id[] = {
	{"kbd_max77816", 0},
	{ }
};
MODULE_DEVICE_TABLE(i2c, kbd_max77816_id);

static const struct of_device_id kbd_max77816_match_table[] = {
	{ .compatible = "max77816,kbd_boost",},
	{ }
};

struct i2c_driver kbd_max77816_driver = {
	.probe = kbd_max77816_probe,
	.remove = kbd_max77816_remove,
	.driver = {
		.name = "kbd_max77816",
		.owner = THIS_MODULE,
#if IS_ENABLED(CONFIG_OF)
		.of_match_table = of_match_ptr(kbd_max77816_match_table),
#endif
		},
	.id_table = kbd_max77816_id,
};

int kbd_max77816_init(void)
{
	int ret = 0;

	pr_info("[sec_input] %s called\n", __func__);

	ret = i2c_add_driver(&kbd_max77816_driver);
	if (ret)
		pr_err("[sec_input] %s registration failed. ret= %d\n", __func__, ret);

	return ret;
}
EXPORT_SYMBOL(kbd_max77816_init);

void kbd_max77816_exit(void)
{
	i2c_del_driver(&kbd_max77816_driver);
}

//module_init(kbd_max77816_init);
//module_exit(kbd_max77816_exit);
