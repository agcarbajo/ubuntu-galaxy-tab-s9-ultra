#include "stm32_pogo_v3.h"

static void stm32_get_tc_fw_info_of_bin(struct stm32_dev *stm32)
{
	if (!stm32->tc_fw)
		return;

	stm32->tc_fw_ver_of_bin.data_ver = (u16)(stm32->tc_fw->data[52] | (stm32->tc_fw->data[53] << 8));
	stm32->tc_fw_ver_of_bin.major_ver = (u16)(stm32->tc_fw->data[56] | (stm32->tc_fw->data[57] << 8));
	stm32->tc_fw_ver_of_bin.minor_ver = (u16)(stm32->tc_fw->data[60] | (stm32->tc_fw->data[61] << 8));

	input_info(true, &stm32->client->dev, "%s: [TC BIN] version:0x%02X%02X, data_ver:0x%X\n",
			__func__, stm32->tc_fw_ver_of_bin.major_ver, stm32->tc_fw_ver_of_bin.minor_ver,
			stm32->tc_fw_ver_of_bin.data_ver);
}

static void stm32_get_fw_info_of_bin(struct stm32_dev *stm32)
{
	int magic_offset = (stm32->keyboard_model < STM32_FW_OFFSET_MODEL_DEFINE_VALUE) ?
		STM32_FW_APP_CFG_OFFSET_L0 : STM32_FW_APP_CFG_OFFSET_G0;

	if (!stm32->fw)
		return;

	memcpy(stm32->fw_header, &stm32->fw->data[magic_offset], sizeof(struct stm32_fw_header));
	stm32->crc_of_bin = stm32_crc32((u8 *)stm32->fw->data, stm32->fw->size);

	input_info(true, &stm32->client->dev, "%s: [BIN] %s, version:%d.%d, model_id:%d, hw_rev:%d, CRC:0x%X magic_offset:0x%x\n",
			__func__, stm32->fw_header->magic_word, stm32->fw_header->boot_app_ver.fw_major_ver,
			stm32->fw_header->boot_app_ver.fw_minor_ver, stm32->fw_header->boot_app_ver.model_id,
			stm32->fw_header->boot_app_ver.hw_rev, stm32->crc_of_bin, magic_offset);
}

static int stm32_load_fw_from_fota(struct stm32_dev *stm32, enum stm32_ed_id ed_id)
{
	struct firmware *fw;

	if (ed_id == ID_MCU) {
		fw = stm32->fw;
	} else if (ed_id == ID_TOUCHPAD) {
		fw = stm32->tc_fw;
	} else {
		input_err(true, &stm32->client->dev, "%s: wrong ed_id %d\n", __func__, ed_id);
		return -EINVAL;
	}

	if (stm32->sec_pogo_keyboard_size > STM32_FW_SIZE) {
		input_err(true, &stm32->client->dev, "%s overflow error totalsize:%ld\n",
				__func__, stm32->sec_pogo_keyboard_size);
		stm32->sec_pogo_keyboard_size = 0;
		return -EINVAL;
	}

	memcpy((void *)fw->data, (void *)stm32->sec_pogo_keyboard_fw, stm32->sec_pogo_keyboard_size);
	fw->size = stm32->sec_pogo_keyboard_size;

	if (ed_id == ID_MCU)
		stm32_get_fw_info_of_bin(stm32);
	else if (ed_id == ID_TOUCHPAD)
		stm32_get_tc_fw_info_of_bin(stm32);

	return 0;
}

static bool stm32_check_fw_update(struct stm32_dev *stm32)
{
	u16 fw_ver_bin, fw_ver_ic;

	if (stm32_read_version(stm32) < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to read version\n", __func__);
		return false;
	}

	if (stm32_read_crc(stm32) < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to read crc\n", __func__);
		return false;
	}

	if (stm32_load_fw_from_fota(stm32, ID_MCU) < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to read bin data\n", __func__);
		return false;
	}

	fw_ver_bin = stm32->fw_header->boot_app_ver.fw_major_ver << 8 | stm32->fw_header->boot_app_ver.fw_minor_ver;
	fw_ver_ic = stm32->ic_fw_ver.fw_major_ver << 8 | stm32->ic_fw_ver.fw_minor_ver;

	input_info(true, &stm32->client->dev, "%s: [BIN] V:%d.%d CRC:0x%X / [IC] V:%d.%d CRC:0x%X\n",
			__func__, stm32->fw_header->boot_app_ver.fw_major_ver,
			stm32->fw_header->boot_app_ver.fw_minor_ver,
			stm32->crc_of_bin, stm32->ic_fw_ver.fw_major_ver,
			stm32->ic_fw_ver.fw_minor_ver, stm32->crc_of_ic);

	if (strncmp(STM32_MAGIC_WORD, stm32->fw_header->magic_word, 5) != 0) {
		input_info(true, &stm32->client->dev, "%s: binary file is wrong : %s\n",
				__func__, stm32->fw_header->magic_word);
		return false;
	}

	if (0) { //stm32->fw_header->boot_app_ver.model_id != stm32->ic_fw_ver.model_id) {
		input_info(true, &stm32->client->dev, "%s: [BIN] %d / [IC] %d : different model id. do not update\n",
				__func__, stm32->fw_header->boot_app_ver.model_id, stm32->ic_fw_ver.model_id);
		return false;
	}

	if (fw_ver_bin > fw_ver_ic) {
		input_info(true, &stm32->client->dev, "%s: need to update fw\n", __func__);
		return true;
	} else if (fw_ver_bin == fw_ver_ic && stm32->crc_of_bin != stm32->crc_of_ic) {
		input_err(true, &stm32->client->dev, "%s: CRC mismatch! need to update fw\n", __func__);
		return true;
	}

	input_info(true, &stm32->client->dev, "%s: skip fw update\n", __func__);
	return false;
}

static ssize_t keyboard_connected_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t size)
{
	struct stm32_dev *data = dev_get_drvdata(dev);
	int onoff, err;

	if (strlen(buf) > 2) {
		input_err(true, &data->client->dev, "%s: cmd length is over %d\n", __func__, (int)strlen(buf));
		return -EINVAL;
	}

	err = kstrtoint(buf, 10, &onoff);
	if (err)
		return err;

	if (data->connect_state == !!onoff)
		return size;

	data->connect_state = !!onoff;
	input_info(true, &data->client->dev, "%s: current %d\n", __func__, data->connect_state);
	stm32_keyboard_connect(data);

	return size;
}

static ssize_t keyboard_connected_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *data = dev_get_drvdata(dev);

	input_info(true, dev, "%s: %d\n", __func__, data->connect_state);

	return snprintf(buf, 5, "%d\n", data->connect_state);
}

static ssize_t hw_reset_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *data = dev_get_drvdata(dev);

	input_info(true, dev, "%s\n", __func__);
	gpio_direction_output(data->dtdata->mcu_nrst, 0);
	stm32_delay(3);
	gpio_direction_output(data->dtdata->mcu_nrst, 1);

	return snprintf(buf, 5, "%d\n", data->dtdata->mcu_nrst);
}

static ssize_t get_fw_ver_ic_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	char buff[256] = { 0 };

	if (stm32->hall_closed || !stm32->connect_state)
		return snprintf(buf, 3, "NG");

	snprintf(buff, sizeof(buff), "%s_v%d.%d.%d.%d",
			(stm32->keyboard_model == STM32_KEYBOARD_ROW_DATA_MODEL) ?
			stm32->dtdata->model_name_row[stm32->ic_fw_ver.model_id] :
			stm32->dtdata->model_name[stm32->model_name_id],
			stm32->ic_fw_ver.fw_major_ver,
			stm32->ic_fw_ver.fw_minor_ver,
			stm32->ic_fw_ver.model_id,
			stm32->ic_fw_ver.hw_rev);

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, buff);
	return snprintf(buf, sizeof(buff), "%s", buff);
}

static ssize_t get_fw_ver_bin_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	char buff[256] = { 0 };

	if (stm32_load_fw_from_fota(stm32, ID_MCU) < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to read bin data\n", __func__);
		return snprintf(buf, sizeof(buff), "NG");
	}

	snprintf(buff, sizeof(buff), "%s_v%d.%d.%d.%d",
			(stm32->keyboard_model == STM32_KEYBOARD_ROW_DATA_MODEL) ?
			stm32->dtdata->model_name_row[stm32->ic_fw_ver.model_id] :
			stm32->dtdata->model_name[stm32->model_name_id],
			stm32->fw_header->boot_app_ver.fw_major_ver,
			stm32->fw_header->boot_app_ver.fw_minor_ver,
			stm32->fw_header->boot_app_ver.model_id,
			stm32->fw_header->boot_app_ver.hw_rev);

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, buff);
	return snprintf(buf, sizeof(buff), "%s", buff);
}

static ssize_t get_crc_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	char buff[256] = { 0 };

	if (stm32->hall_closed || !stm32->connect_state)
		return snprintf(buf, 3, "NG");

	snprintf(buff, sizeof(buff), "%08X", stm32->crc_of_ic);

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, buff);
	return snprintf(buf, sizeof(buff), "%s", buff);
}

static ssize_t check_fw_update_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);

	if (stm32_check_fw_update(stm32))
		return snprintf(buf, 3, "OK");
	else
		return snprintf(buf, 3, "NG");
}

static int stm32_write_fw(struct stm32_dev *stm32, enum stm32_ed_id ed_id, u16 page_size)
{
	const struct firmware *fw;
	int page_num, page_index = 0, ret, retry = 3, last_page_size;
	u8 buff[3] = { 0 };

	if (ed_id == ID_MCU) {
		fw = stm32->fw;
	} else if (ed_id == ID_TOUCHPAD) {
		fw = stm32->tc_fw;
	} else {
		input_err(true, &stm32->client->dev, "%s: wrong ed_id %d\n", __func__, ed_id);
		return -EINVAL;
	}

	if (!fw) {
		input_err(true, &stm32->client->dev, "%s: fw is null\n", __func__);
		return -ENOENT;
	}

	page_num = fw->size / page_size;
	last_page_size = fw->size % page_size;

	if (last_page_size == 0) {
		page_num--;
		last_page_size = page_size;
	}

	input_info(true, &stm32->client->dev,
			"%s: fw size: %ld, page size: %d, page num: %d, last page size: %d, packet size: %d\n",
			__func__, fw->size, page_size, page_num, last_page_size, STM32_CFG_PACKET_SIZE);

	while (page_index <= page_num) {
		u8 *pn_data = (u8 *)&fw->data[page_index * page_size];
		u8 send_data[STM32_CFG_PACKET_SIZE + 5] = { 0 };
		u32 page_crc;
		u16 page_index_cmp;
		int delayms = 20; /* test */

		if (ed_id == ID_TOUCHPAD && page_index == page_num) {
			send_data[0] = STM32_CMD_WRITE_LAST_PAGE;
			page_size = last_page_size;
			delayms = 500;
		} else {
			send_data[0] = STM32_CMD_WRITE_PAGE;
		}

		memcpy(&send_data[1], pn_data, page_size);
		page_crc = stm32_crc32(pn_data, page_size);
		memcpy(&send_data[page_size + 1], &page_crc, 4);

		input_dbg(false, &stm32->client->dev, "%s: write page %d, size %d, CRC 0x%08X\n",
				__func__, page_index, page_size, page_crc);

		ret = stm32_i2c_header_write(stm32->client, ed_id, page_size + 5);
		if (ret < 0)
			return ret;

		ret = stm32_i2c_write_burst(stm32->client, send_data, page_size + 5);
		if (ret < 0)
			return ret;

		stm32_delay(delayms);

		/* read page index */
		ret = stm32_i2c_read_bulk(stm32->client, buff, 3);
		if (ret < 0)
			return ret;
		ret = stm32_i2c_read_bulk(stm32->client, buff, 2);
		if (ret < 0)
			return ret;
		memcpy(&page_index_cmp, buff, 2);
		page_index++;

		if (page_index == page_index_cmp) {
			retry = 3;
		} else {
			page_index--;
			input_err(true, &stm32->client->dev, "%s: page %d(%d) is not programmed, retry %d\n",
					__func__, page_index, page_index_cmp, 3 - retry);
			retry--;
		}

		if (retry < 0) {
			input_err(true, &stm32->client->dev, "%s: failed\n", __func__);
			return -EIO;
		}
	}

	input_info(true, &stm32->client->dev, "%s: done\n", __func__);
	return 0;
}

static int stm32_fw_update(struct stm32_dev *stm32)
{
	int ret;
	u8 buff[4] = { 0 };
	u16 page_size;
	struct stm32_fw_version target_fw;
	u32 target_crc;

	if (!stm32->fw)
		return -ENOENT;

	if (strncmp(STM32_MAGIC_WORD, stm32->fw_header->magic_word, 5) != 0) {
		input_info(true, &stm32->client->dev, "%s: firmware file is wrong : %s\n",
				__func__, stm32->fw_header->magic_word);
		memset(stm32->sec_pogo_keyboard_fw, 0x0, stm32->sec_pogo_keyboard_size);
		stm32->sec_pogo_keyboard_size = 0;
		return -ENOENT;
	}

	ret = stm32_set_mode(stm32, MODE_DFU);
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to set DFU mode\n", __func__);
		memset(stm32->sec_pogo_keyboard_fw, 0x0, stm32->sec_pogo_keyboard_size);
		stm32->sec_pogo_keyboard_size = 0;
		return ret;
	}

	stm32_enable_irq(stm32, INT_DISABLE_SYNC);

	stm32_delay(1000);

	ret = stm32_read_version(stm32);
	if (ret < 0)
		goto out;

	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_GET_PROTOCOL_VERSION, 2, buff);
	if (ret < 0)
		goto out;
	input_info(true, &stm32->client->dev, "%s: protocol ver: 0x%02X%02X\n", __func__, buff[1], buff[0]);

	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_GET_PAGE_SIZE, 2, buff);
	if (ret < 0)
		goto out;

	memcpy(&page_size, &buff[0], 2);

	/* disable write protection of target bank & erase the target bank */
	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_START_FW_UPGRADE, 1, buff);
	if (ret < 0 || buff[0] == 0xFF)
		goto out;
	input_info(true, &stm32->client->dev, "%s: bank %02X is erased\n", __func__, buff[0]);

	mutex_lock(&stm32->i2c_lock);
	ret = stm32_write_fw(stm32, ID_MCU, page_size);
	mutex_unlock(&stm32->i2c_lock);
	if (ret < 0)
		goto out;

	/* check fw version & crc of target bank */
	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_GET_TARGET_FW_VERSION, 4, buff);
	if (ret < 0)
		goto out;

	target_fw.hw_rev = buff[0];
	target_fw.model_id = buff[1];
	target_fw.fw_minor_ver = buff[2];
	target_fw.fw_major_ver = buff[3];

	input_info(true, &stm32->client->dev, "%s: [TARGET] version:%d.%d, model_id:%d\n",
			__func__, target_fw.fw_major_ver, target_fw.fw_minor_ver, target_fw.model_id);

	if (target_fw.fw_major_ver != stm32->fw_header->boot_app_ver.fw_major_ver ||
		target_fw.fw_minor_ver != stm32->fw_header->boot_app_ver.fw_minor_ver) {
		input_err(true, &stm32->client->dev, "%s: version mismatch!\n", __func__);
		goto out;
	}

	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, STM32_CMD_GET_TARGET_FW_CRC32, 4, buff);
	if (ret < 0)
		goto out;

	target_crc = buff[3] << 24 | buff[2] << 16 | buff[1] << 8 | buff[0];

	input_info(true, &stm32->client->dev, "%s: [TARGET] CRC:0x%08X\n", __func__, target_crc);
	if (target_crc != stm32->crc_of_bin) {
		input_err(true, &stm32->client->dev, "%s: CRC mismatch!\n", __func__);
		goto out;
	}

	/* leave the DFU mode with switching to target bank */
	ret = stm32_i2c_reg_write(stm32->client, ID_MCU, STM32_CMD_GO);
	if (ret < 0)
		goto out;

	input_info(true, &stm32->client->dev, "%s: [APP MODE] Start with target bank\n", __func__);

	if (stm32->connect_state)
		stm32_enable_irq(stm32, INT_ENABLE);

	memset(stm32->sec_pogo_keyboard_fw, 0x0, stm32->sec_pogo_keyboard_size);
	stm32->sec_pogo_keyboard_size = 0;

	return 0;

out:
	memset(stm32->sec_pogo_keyboard_fw, 0x0, stm32->sec_pogo_keyboard_size);
	stm32->sec_pogo_keyboard_size = 0;

	stm32_delay(1000);

	/* leave the DFU mode without switching to target bank */
	ret = stm32_i2c_reg_write(stm32->client, ID_MCU, STM32_CMD_ABORT);
	if (ret < 0)
		return ret;

	input_info(true, &stm32->client->dev, "%s: [APP MODE] Start with boot bank\n", __func__);

	if (stm32->connect_state)
		stm32_enable_irq(stm32, INT_ENABLE);

	return -EIO;
}

static ssize_t debug_level_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t size)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret, level;

	ret = kstrtoint(buf, 10, &level);
	if (ret)
		return ret;

	stm32->debug_level = level;

	input_info(true, &stm32->client->dev, "%s: %d\n", __func__, stm32->debug_level);
	return size;
}

static ssize_t debug_level_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);

	input_info(true, &stm32->client->dev, "%s: %d\n", __func__, stm32->debug_level);

	return snprintf(buf, 5, "%d\n", stm32->debug_level);
}

#if !IS_ENABLED(CONFIG_SAMSUNG_PRODUCT_SHIP)
static ssize_t write_cmd_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t size)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret, reg;

	ret = kstrtoint(buf, 0, &reg);
	if (ret)
		return ret;

	if (reg > 0xFF)
		return -EIO;

	ret = stm32_i2c_reg_write(stm32->client, ID_MCU, reg);

	input_info(true, &stm32->client->dev, "%s: write 0x%02X, ret: %d\n", __func__, reg, ret);
	return size;
}

static ssize_t read_cmd_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t size)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret, reg;
	u8 buff[256] = { 0 };

	ret = kstrtoint(buf, 0, &reg);
	if (ret)
		return ret;

	if (reg > 0xFF)
		return -EIO;

	ret = stm32_i2c_reg_read(stm32->client, ID_MCU, reg, 255, buff);

	input_info(true, &stm32->client->dev, "%s: read 0x%02X, ret: %d\n", __func__, reg, ret);
	return size;
}

static ssize_t set_booster_voltage_store(struct device *dev, struct device_attribute *attr,
		const char *buf, size_t size)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret, voltage;

	ret = kstrtoint(buf, 0, &voltage);
	if (ret) {
		input_err(true, &stm32->client->dev, "%s: error parm(%s)\n", __func__, buf);
		return size;
	}

	if (voltage == 0 || voltage == 1) {
		ret = stm32_dev_regulator(stm32, voltage);
		if (ret < 0) {
			input_err(true, &stm32->client->dev, "%s: regulator %s error\n",
				__func__, voltage ? "ON" : "OFF");
		}
		stm32_delay(100);

	} else if (voltage >= 260000 && voltage <= 514000) {
		/* for test */
		if (!regulator_is_enabled(stm32->dtdata->vdd_vreg)) {
			input_err(true, &stm32->client->dev, "%s: not enable en pin\n", __func__);
			return size;
		}

		ret = kbd_max77816_control(stm32, voltage);
		if (ret < 0)
			input_err(true, &stm32->client->dev, "%s: control fail(%d)\n", __func__, voltage);
	} else {
		input_err(true, &stm32->client->dev, "%s: out of range voltage:%d\n", __func__, voltage);
		return size;
	}

	input_info(true, &stm32->client->dev, "%s: voltage:%d, ret: %d\n", __func__, voltage, ret);
	return size;
}
#endif

static ssize_t get_tc_fw_ver_bin_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	char buff[256] = { 0 };

	if (stm32_load_fw_from_fota(stm32, ID_TOUCHPAD) < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to read bin data\n", __func__);
		return snprintf(buf, sizeof(buff), "NG");
	}

	snprintf(buff, sizeof(buff), "%s-TC_v%02X%02X",
			(stm32->keyboard_model == STM32_KEYBOARD_ROW_DATA_MODEL) ?
			stm32->dtdata->model_name_row[stm32->ic_fw_ver.model_id] :
			stm32->dtdata->model_name[stm32->model_name_id],
			stm32->tc_fw_ver_of_bin.major_ver & 0xFF, stm32->tc_fw_ver_of_bin.minor_ver & 0xFF);

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, buff);
	return snprintf(buf, sizeof(buff), "%s", buff);
}

static ssize_t get_tc_fw_ver_ic_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	char buff[256] = { 0 };

	mutex_lock(&stm32->dev_lock);

	if (stm32->hall_closed || !stm32->connect_state)
		goto NG;

	if (stm32->tc_crc == STM32_TC_CRC_OK)
		snprintf(buff, sizeof(buff), "%s-TC_v%02X%02X",
				(stm32->keyboard_model == STM32_KEYBOARD_ROW_DATA_MODEL) ?
				stm32->dtdata->model_name_row[stm32->ic_fw_ver.model_id] :
				stm32->dtdata->model_name[stm32->model_name_id],
				stm32->tc_fw_ver_of_ic.major_ver & 0xFF, stm32->tc_fw_ver_of_ic.minor_ver & 0xFF);
	else
		snprintf(buff, sizeof(buff), "%s-TC_v0000",
				(stm32->keyboard_model == STM32_KEYBOARD_ROW_DATA_MODEL) ?
				stm32->dtdata->model_name_row[stm32->ic_fw_ver.model_id] :
				stm32->dtdata->model_name[stm32->model_name_id]);

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, buff);
	mutex_unlock(&stm32->dev_lock);

	return snprintf(buf, sizeof(buff), "%s", buff);

NG:
	snprintf(buff, sizeof(buff), "NG");

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, buff);
	mutex_unlock(&stm32->dev_lock);

	return snprintf(buf, sizeof(buff), "%s", buff);
}

static ssize_t get_tc_crc_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	char buff[256] = { 0 };

	if (stm32->hall_closed || !stm32->connect_state)
		return snprintf(buf, 3, "NG");

	snprintf(buff, sizeof(buff), "%04X", stm32->tc_crc);

	input_info(true, &stm32->client->dev, "%s: %s\n", __func__, buff);
	return snprintf(buf, sizeof(buff), "%s", buff);
}

static ssize_t block_pogo_keyboard_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);

	input_info(true, dev, "%s: %d\n", __func__, stm32->pogo_enable);

	return snprintf(buf, 5, "%d\n", stm32->pogo_enable);
}

static ssize_t block_pogo_keyboard_store(struct device *dev, struct device_attribute *attr,
		const char *buf, size_t size)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret, param;

	ret = kstrtoint(buf, 10, &param);
	if (ret)
		return ret;

	stm32->pogo_enable = !!param;

	gpio_direction_output(stm32->dtdata->mcu_nrst, stm32->pogo_enable);
	stm32_delay(3);

	return size;
}

static int stm32_tc_fw_update(struct stm32_dev *stm32)
{
	int ret = 0;
	u8 buff[3] = { 0 };
	u16 page_size = 0;
	enum stm32_tc_fw_update_result result = TC_FW_RES_FAIL;

	ret = stm32_set_mode(stm32, MODE_DFU);
	if (ret < 0) {
		input_err(true, &stm32->client->dev, "%s: failed to set DFU mode\n", __func__);
		memset(stm32->sec_pogo_keyboard_fw, 0x0, stm32->sec_pogo_keyboard_size);
		stm32->sec_pogo_keyboard_size = 0;
		return ret;
	}

	stm32_enable_irq(stm32, INT_DISABLE_SYNC);

	stm32_delay(1000);

	ret = stm32_read_version(stm32);
	if (ret < 0)
		goto out;

	ret = stm32_read_tc_version(stm32);
	if (ret < 0)
		goto out;

	ret = stm32_read_tc_crc(stm32);
	if (ret < 0)
		goto out;

	ret = stm32_i2c_reg_read(stm32->client, ID_TOUCHPAD, STM32_CMD_GET_PAGE_SIZE, 2, buff);
	if (ret < 0)
		goto out;

	memcpy(&page_size, &buff[0], 2);

	ret = stm32_i2c_reg_write(stm32->client, ID_TOUCHPAD, STM32_CMD_START_FW_UPGRADE);
	if (ret < 0)
		goto out;

	stm32_delay(800);

	ret = stm32_i2c_read_bulk(stm32->client, buff, 3);
	if (ret < 0)
		goto out;

	ret = stm32_i2c_read_bulk(stm32->client, buff, 1);
	if (ret < 0) {
		ret = -EIO;
		input_err(true, &stm32->client->dev, "%s: tc fw update cmd is failed\n", __func__);
		goto out;
	} else {
		result = (enum stm32_tc_fw_update_result)buff[0];
		if (result != TC_FW_RES_OK) {
			ret = -EIO;
			input_err(true, &stm32->client->dev, "%s: tc fw update cmd is failed, 0x%02X\n",
					__func__, buff[0]);
			goto out;
		}
	}

	input_info(true, &stm32->client->dev, "%s: start to update\n", __func__);

	mutex_lock(&stm32->i2c_lock);
	ret = stm32_write_fw(stm32, ID_TOUCHPAD, page_size);
	mutex_unlock(&stm32->i2c_lock);
	if (ret < 0)
		goto out;

	/* check fw version & crc of touch controller */
	ret = stm32_read_tc_version(stm32);
	if (ret < 0)
		goto out;

	ret = stm32_read_tc_crc(stm32);
	if (ret < 0)
		goto out;

	if (stm32->tc_crc != STM32_TC_CRC_OK) {
		ret = -EIO;
		input_err(true, &stm32->client->dev, "%s: CRC mismatch!\n", __func__);
		goto out;
	}

out:
	memset(stm32->sec_pogo_keyboard_fw, 0x0, stm32->sec_pogo_keyboard_size);
	stm32->sec_pogo_keyboard_size = 0;

	if (stm32_i2c_reg_write(stm32->client, ID_MCU, STM32_CMD_ABORT) < 0)
		return -EIO;

	input_info(true, &stm32->client->dev, "%s: [APP MODE] Start with boot bank\n", __func__);

	if (stm32->connect_state)
		stm32_enable_irq(stm32, INT_ENABLE);

	return ret;
}

static ssize_t fw_update_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t size)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret = 0;
	enum stm32_fw_param param = FW_UPDATA_EXCEPTION;

	if (stm32->hall_closed || !stm32->connect_state)
		return -ENODEV;

	ret = kstrtoint(buf, 10, (int *)&param);
	if (ret)
		return ret;

	input_info(true, &stm32->client->dev, "%s\n", __func__);

	switch (param) {
	case FW_UPDATE_MCU:
		ret = stm32_load_fw_from_fota(stm32, ID_MCU);
		if (ret < 0)
			return ret;

		ret = stm32_fw_update(stm32);
		if (ret < 0)
			return ret;
		else
			return size;
	case FW_UPDATE_TC:
		ret = stm32_load_fw_from_fota(stm32, ID_TOUCHPAD);
		if (ret < 0)
			return ret;

		ret = stm32_tc_fw_update(stm32);
		if (ret < 0)
			return ret;
		else
			return size;
	default:
		return -EINVAL;
	}
}

static ssize_t fw_mcu_update_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret;

	ret = stm32_dev_firmware_update_menu(stm32, 1);

	if (!ret)
		return snprintf(buf, 3, "OK");
	else
		return snprintf(buf, 3, "NG");
}

static ssize_t get_mcu_fw_ver_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int ret = 0;

	if (stm32->connect_state)
		return snprintf(buf, 3, "NG");

	ret = stm32_dev_get_ic_ver(stm32);
	if (ret < 0)
		return snprintf(buf, 3, "NG");

	if (stm32->mdata.phone_ver[3] == stm32->mdata.ic_ver[3])
		return snprintf(buf, 3, "%2x", stm32->mdata.ic_ver[3]);
	else
		return snprintf(buf, 3, "NG");
}

#if IS_ENABLED(CONFIG_INPUT_SEC_NOTIFIER)
static ssize_t enabled_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);

	input_info(true, &stm32->client->dev, "%s: %d\n", __func__, atomic_read(&stm32->enabled));

	return snprintf(buf, 2, "%d", atomic_read(&stm32->enabled));
}

static ssize_t enabled_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t count)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	int buff[2];
	int ret;

	ret = sscanf(buf, "%d,%d", &buff[0], &buff[1]);
	if (ret != 2) {
		input_err(true, &stm32->client->dev, "%s: failed read params [%d]\n", __func__, ret);
		return -EINVAL;
	}

	input_info(true, &stm32->client->dev, "%s: %d %d\n", __func__, buff[0], buff[1]);

	if ((buff[0] == DISPLAY_STATE_ON || buff[0] == DISPLAY_STATE_DOZE || buff[0] == DISPLAY_STATE_DOZE_SUSPEND)
		&& stm32->connect_state) {
		stm32_enable_irq(stm32, INT_ENABLE);
		stm32_enable_conn_irq(stm32, INT_ENABLE);
		stm32_enable_conn_wake_irq(stm32, true);
	}

	return count;
}
#endif

static ssize_t sec_pogo_keyboard_fw_store(struct device *dev, struct device_attribute *attr, const char *buf,
						size_t count)
{
	struct stm32_dev *stm32 = dev_get_drvdata(dev);
	ssize_t ret;

	if (!stm32->sec_pogo_keyboard_fw)
		return 0;

	ret = -EINVAL;
	if (count > PAGE_SIZE) {
		input_err(true, &stm32->client->dev, "%s error count %ld %ld\n", __func__, count, PAGE_SIZE);
		return ret;
	}

	if (stm32->sec_pogo_keyboard_size + count > STM32_FW_SIZE) {
		input_err(true, &stm32->client->dev, "%s overflow error totalsize:%ld\n",
				__func__, stm32->sec_pogo_keyboard_size + count);
		return ret;
	}
	
	memcpy(stm32->sec_pogo_keyboard_fw + stm32->sec_pogo_keyboard_size, buf, count);

	stm32->sec_pogo_keyboard_size += count;

	return count;
}

static DEVICE_ATTR_RW(keyboard_connected);
static DEVICE_ATTR_RO(hw_reset);
static DEVICE_ATTR_RO(get_fw_ver_bin);
static DEVICE_ATTR_RO(get_fw_ver_ic);
static DEVICE_ATTR_RO(get_crc);
static DEVICE_ATTR_RO(check_fw_update);
static DEVICE_ATTR_WO(fw_update);
static DEVICE_ATTR_RO(fw_mcu_update);
static DEVICE_ATTR_RW(debug_level);
#if !IS_ENABLED(CONFIG_SAMSUNG_PRODUCT_SHIP)
static DEVICE_ATTR_WO(write_cmd);
static DEVICE_ATTR_WO(read_cmd);
static DEVICE_ATTR_WO(set_booster_voltage);
#endif
static DEVICE_ATTR_RO(get_tc_fw_ver_bin);
static DEVICE_ATTR_RO(get_tc_fw_ver_ic);
static DEVICE_ATTR_RO(get_tc_crc);
static DEVICE_ATTR_RW(block_pogo_keyboard);
static DEVICE_ATTR_RO(get_mcu_fw_ver);
#if IS_ENABLED(CONFIG_INPUT_SEC_NOTIFIER)
static DEVICE_ATTR_RW(enabled);
#endif
static DEVICE_ATTR_WO(sec_pogo_keyboard_fw);

static struct attribute *key_attributes[] = {
	&dev_attr_keyboard_connected.attr,
	&dev_attr_hw_reset.attr,
	&dev_attr_get_fw_ver_bin.attr,
	&dev_attr_get_fw_ver_ic.attr,
	&dev_attr_get_crc.attr,
	&dev_attr_check_fw_update.attr,
	&dev_attr_fw_update.attr,
	&dev_attr_fw_mcu_update.attr,
	&dev_attr_debug_level.attr,
#if !IS_ENABLED(CONFIG_SAMSUNG_PRODUCT_SHIP)
	&dev_attr_write_cmd.attr,
	&dev_attr_read_cmd.attr,
	&dev_attr_set_booster_voltage.attr,
#endif
	&dev_attr_get_tc_fw_ver_bin.attr,
	&dev_attr_get_tc_fw_ver_ic.attr,
	&dev_attr_get_tc_crc.attr,
	&dev_attr_block_pogo_keyboard.attr,
	&dev_attr_get_mcu_fw_ver.attr,
#if IS_ENABLED(CONFIG_INPUT_SEC_NOTIFIER)
	&dev_attr_enabled.attr,
#endif
	&dev_attr_sec_pogo_keyboard_fw.attr,
	NULL,
};

static struct attribute_group key_attr_group = {
	.attrs = key_attributes,
};

int stm32_init_cmd(struct stm32_dev *stm32)
{
	int ret = 0;

	stm32->sec_pogo = sec_device_create(stm32, "sec_keypad");
	if (IS_ERR(stm32->sec_pogo)) {
		input_err(true, &stm32->client->dev, "Failed to create sec_keypad device\n");
		return SEC_ERROR;
	}

	ret = sysfs_create_group(&stm32->sec_pogo->kobj, &key_attr_group);
	if (ret) {
		input_err(true, &stm32->client->dev, "Failed to create sysfs: %d\n", ret);
		stm32_destroy_fn(stm32);
		return SEC_ERROR;
	}

	return SEC_SUCCESS;
}

void stm32_destroy_fn(struct stm32_dev *stm32)
{
	sec_device_destroy(stm32->sec_pogo->devt);
}

MODULE_LICENSE("GPL");
