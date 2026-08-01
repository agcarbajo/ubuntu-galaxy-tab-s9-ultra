#include "stm32_pogo_v3.h"
struct stm32_tc_resolution g_tc_resolution;

void pogo_get_tc_resolution(int *x, int *y)
{
	*x = g_tc_resolution.x;
	*y = g_tc_resolution.y;
}
EXPORT_SYMBOL(pogo_get_tc_resolution);

void stm32_delay(int ms)
{
	if (ms > 20)
		msleep(ms);
	else
		usleep_range(ms * 1000, ms * 1000);
}

void stm32_print_info(struct stm32_dev *stm32)
{
	struct irq_desc *desc = irq_to_desc(stm32->dev_irq);

	input_info(true, &stm32->client->dev, "mcu_fw(bin):%x, mcu_fw(ic):%x, %s_v%d.%d.%d.%d\n",
			stm32->mdata.phone_ver[3], stm32->mdata.ic_ver[3],
			(stm32->keyboard_model == STM32_KEYBOARD_ROW_DATA_MODEL) ?
			stm32->dtdata->model_name_row[stm32->ic_fw_ver.model_id] :
			stm32->dtdata->model_name[stm32->model_name_id],
			stm32->ic_fw_ver.fw_major_ver, stm32->ic_fw_ver.fw_minor_ver, stm32->ic_fw_ver.model_id,
			stm32->ic_fw_ver.hw_rev);
	input_info(true, &stm32->client->dev, "TC_v%02X%02X.%X, con:%d/%d, int:%d, depth:%d, rst:%d, hall:%d model_id:0x%x\n",
			stm32->tc_fw_ver_of_ic.major_ver, stm32->tc_fw_ver_of_ic.minor_ver,
			stm32->tc_fw_ver_of_ic.data_ver, stm32->connect_state, gpio_get_value(stm32->dtdata->gpio_conn),
			gpio_get_value(stm32->dtdata->gpio_int), desc->depth, stm32->reset_count, stm32->hall_closed,
			stm32->keyboard_model);
}

void stm32_print_info_work(struct work_struct *work)
{
	struct stm32_dev *stm32 = container_of(work, struct stm32_dev, print_info_work.work);

	stm32_print_info(stm32);
	schedule_delayed_work(&stm32->print_info_work, STM32_PRINT_INFO_DELAY);
}

void stm32_power_reset(struct stm32_dev *stm32)
{
	if (stm32->reset_count < 100000)
		stm32->reset_count++;
	input_err(true, &stm32->client->dev, "%s, %d\n", __func__, stm32->reset_count);

	gpio_direction_output(stm32->dtdata->mcu_nrst, 0);
	stm32_delay(3);
	gpio_direction_output(stm32->dtdata->mcu_nrst, 1);
	stm32_delay(10);
}

int stm32_dev_regulator(struct stm32_dev *stm32, int onoff)
{
	struct device *dev = &stm32->client->dev;
	int ret = 0;

	if (IS_ERR_OR_NULL(stm32->dtdata->vdd_vreg))
		return ret;

	if (onoff) {
		if (!regulator_is_enabled(stm32->dtdata->vdd_vreg)) {
			ret = regulator_enable(stm32->dtdata->vdd_vreg);
			if (ret) {
				input_err(true, dev, "%s: Failed to enable vddo: %d\n", __func__, ret);
				return ret;
			}
			kbd_max77816_control_init(stm32);
		} else {
			input_err(true, dev, "%s: vdd is already enabled\n", __func__);
		}
	} else {
		if (regulator_is_enabled(stm32->dtdata->vdd_vreg)) {
			ret = regulator_disable(stm32->dtdata->vdd_vreg);
			if (ret) {
				input_err(true, dev, "%s: Failed to disable vddo: %d\n", __func__, ret);
				return ret;
			}
		} else {
			input_err(true, dev, "%s: vdd is already disabled\n", __func__);
		}
	}

	input_err(true, dev, "%s %s: vdd:%s\n", __func__, onoff ? "on" : "off",
			regulator_is_enabled(stm32->dtdata->vdd_vreg) ? "on" : "off");

	return ret;
}

int stm32_read_crc(struct stm32_dev *stm32)
{
	int ret;
	u8 rbuf[4] = { 0 };

	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_CHECK_CRC, 4, rbuf);
	if (ret < 0)
		return ret;

	stm32->crc_of_ic = rbuf[3] << 24 | rbuf[2] << 16 | rbuf[1] << 8 | rbuf[0];

	input_info(true, &stm32->client->dev, "%s: [IC] BOOT CRC32 = 0x%08X\n", __func__, stm32->crc_of_ic);
	return 0;
}

int stm32_read_version(struct stm32_dev *stm32)
{
	int ret;
	u8 rbuf[4] = { 0 };

	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_CHECK_VERSION, 4, rbuf);
	if (ret < 0)
		return ret;

	stm32->ic_fw_ver.hw_rev = rbuf[0];

	if (rbuf[1] == 0 || rbuf[1] == 1 || rbuf[1] == 2) {
		if (stm32->keyboard_model == 0xd1 || stm32->keyboard_model == 0xd2)
			stm32->model_name_id = 2;
		else if (stm32->keyboard_model == 0x03 || stm32->keyboard_model == 0xd3 || stm32->keyboard_model == 0xd5)
			stm32->model_name_id = 3;
		else if (stm32->keyboard_model == 0xd6)
			stm32->model_name_id = 4;
		else
			stm32->model_name_id = rbuf[1];

		stm32->ic_fw_ver.model_id = rbuf[1];
	} else {
		stm32->model_name_id = 0;
		stm32->ic_fw_ver.model_id = 0;
	}

	stm32->ic_fw_ver.fw_minor_ver = rbuf[2];
	stm32->ic_fw_ver.fw_major_ver = rbuf[3];
	boot_module_id = stm32->ic_fw_ver.model_id;

	input_info(true, &stm32->client->dev, "%s: [IC] version:%d.%d, model_id:%02d, hw_rev:%02d\n",
			__func__, stm32->ic_fw_ver.fw_major_ver, stm32->ic_fw_ver.fw_minor_ver,
			stm32->ic_fw_ver.model_id, stm32->ic_fw_ver.hw_rev);
	return 0;
}

int stm32_read_tc_resolution(struct stm32_dev *stm32)
{
	int ret;
	u8 rbuf[4] = { 0 };

	ret = stm32_i2c_reg_read(stm32->client, ID_TOUCHPAD, STM32_CMD_GET_TC_RESOLUTION, 4, rbuf);
	if (ret < 0)
		return ret;

	g_tc_resolution.x = rbuf[3] << 8 | rbuf[2];
	g_tc_resolution.y = rbuf[1] << 8 | rbuf[0];

	input_info(true, &stm32->client->dev, "%s: x:%d, y:%d\n", __func__, g_tc_resolution.x, g_tc_resolution.y);
	return 0;
}

int stm32_read_tc_crc(struct stm32_dev *stm32)
{
	int ret;
	u8 rbuf[2] = { 0 };

	ret = stm32_i2c_reg_read(stm32->client, ID_TOUCHPAD, STM32_CMD_GET_TC_FW_CRC16, 2, rbuf);
	if (ret < 0)
		return ret;

	stm32->tc_crc = rbuf[1] << 8 | rbuf[0];

	input_info(true, &stm32->client->dev, "%s: [TC IC] CRC = 0x%04X\n", __func__, stm32->tc_crc);
	return 0;
}

int stm32_read_tc_version(struct stm32_dev *stm32)
{
	int ret;
	u8 rbuf[6] = { 0 };

	ret = stm32_i2c_reg_read(stm32->client, ID_TOUCHPAD, STM32_CMD_GET_TC_FW_VERSION, 6, rbuf);
	if (ret < 0)
		return ret;

	stm32->tc_fw_ver_of_ic.minor_ver = rbuf[5] << 8 | rbuf[4];
	stm32->tc_fw_ver_of_ic.major_ver = rbuf[3] << 8 | rbuf[2];
	stm32->tc_fw_ver_of_ic.data_ver = rbuf[1] << 8 | rbuf[0];

	input_info(true, &stm32->client->dev, "%s: [TC IC] version:0x%02X%02X, data ver:0x%X\n",
			__func__, stm32->tc_fw_ver_of_ic.major_ver,
			stm32->tc_fw_ver_of_ic.minor_ver, stm32->tc_fw_ver_of_ic.data_ver);
	return 0;
}

u32 stm32_crc32(u8 *src, size_t len)
{
	u8 *bp;
	size_t idx;
	u32 crc = 0xFFFFFFFF;

	for (idx = 0; idx < len; idx++) {
		bp = src + (idx ^ 0x3);
		crc = (crc << 8) ^ crctab[((crc >> 24) ^ *bp) & 0xFF];
	}
	return crc;
}

int stm32_set_mode(struct stm32_dev *stm32, enum stm32_mode mode)
{
	int ret;
	u8 buff;
	u8 cmd;

	if (mode == MODE_APP)
		cmd = STM32_CMD_ABORT;
	else if (mode == MODE_DFU)
		cmd = STM32_CMD_ENTER_DFU_MODE;
	else
		return -EINVAL;

	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_GET_MODE, 1, &buff);
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to read mode, %d\n", __func__, ret);
		return ret;
	}

	input_info(true, &stm32->client->dev, "[MODE] %d\n", buff);

	if ((enum stm32_mode)buff != mode && (enum stm32_mode)buff != MODE_EXCEPTION) {
		stm32->hall_flag = false;
		input_info(true, &stm32->client->dev, "%s: enter %s mode\n",
				__func__, mode == MODE_APP ? "APP" : "DFU");
		ret = stm32_i2c_reg_write(stm32->client, ID_MCU, cmd);
	} else if ((enum stm32_mode)buff == MODE_EXCEPTION) {
		stm32->hall_flag = true;
	} else {
		input_info(true, &stm32->client->dev, "%s: already same mode buff:%d, mode:%d\n",
				__func__, buff, mode);
	}

	stm32_delay(200);

	return ret;
}

MODULE_LICENSE("GPL");
