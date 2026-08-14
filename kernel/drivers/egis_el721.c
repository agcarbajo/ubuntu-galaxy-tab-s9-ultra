// SPDX-License-Identifier: GPL-2.0-only
/*
 * Minimal secure-world companion driver for the EgisTec EL721 fingerprint
 * sensor used by the Samsung Galaxy Tab S9 Ultra.
 *
 * On the production device the SPI controller is assigned to Qualcomm's
 * secure world.  Linux must therefore never issue raw SPI transactions or
 * expose frame data.  This driver only owns the sensor's 3.3 V supply and
 * enable/reset line, and implements the non-data portion of Samsung/EgisTec's
 * arm64 ioctl ABI used by the trusted fingerprint service.
 */

#include <linux/capability.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/err.h>
#include <linux/fs.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/machine.h>
#include <linux/ioctl.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm.h>
#include <linux/property.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/uaccess.h>

#define EL721_VENDOR			"EGISTEC"
#define EL721_DEFAULT_NAME		"EL721"
#define EL721_DEFAULT_MODEL		"X916"
#define EL721_DEFAULT_POSITION						\
	"16.70,0.00,9.10,9.10,14.80,14.80,12.00,12.00,5.00"

#define EL721_MODEL_INFO_LEN		10
#define EL721_NAME_LEN			16
#define EL721_POSITION_LEN		96

/* Non-data opcodes from the 64-bit EgisTec userspace ABI. */
#define FP_SENSOR_RESET			0x04
#define FP_POWER_CONTROL		0x05
#define FP_SET_SPI_CLOCK		0x06
#define FP_RESET_CONTROL		0x07
#define FP_DISABLE_SPI_CLOCK		0x10
#define FP_CPU_SPEEDUP			0x11
#define FP_SET_SENSOR_TYPE		0x14
#define FP_IOCTL_RESERVED_06		0x16
#define FP_IOCTL_RESERVED_07		0x17
#define FP_IOCTL_RESERVED_01		0x19
#define FP_SPI_VALUE			0x1a
#define FP_IOCTL_RESERVED_02		0x1c
#define FP_MODEL_INFO			0x1f
#define FP_IOCTL_RESERVED_03		0xa4
#define FP_IOCTL_RESERVED_04		0xa5
#define FP_IOCTL_RESERVED_05		0xa8

/*
 * This is intentionally expressed with fixed-width, 8-byte-aligned user
 * pointers.  Its layout is identical to the vendor struct on arm64 (32 bytes)
 * while avoiding native kernel pointers in a UAPI structure.
 */
struct egis_ioc_transfer {
	__aligned_u64 tx_buf;
	__aligned_u64 rx_buf;
	__u32 len;
	__u32 speed_hz;
	__u16 delay_usecs;
	__u8 bits_per_word;
	__u8 cs_change;
	__u8 opcode;
	__u8 pad[3];
};

#define EGIS_IOC_MAGIC			'k'
#define EGIS_MSGSIZE(n)						\
	((((n) * sizeof(struct egis_ioc_transfer)) < (1U << _IOC_SIZEBITS)) \
	 ? ((n) * sizeof(struct egis_ioc_transfer)) : 0)
#define EGIS_IOC_MESSAGE(n)		_IOW(EGIS_IOC_MAGIC, 0, \
					     char[EGIS_MSGSIZE(n)])

struct el721_data {
	struct device *dev;
	struct gpio_desc *ldo_gpio;
	struct gpio_desc *enable_gpio;
	struct miscdevice miscdev;
	/* Serializes power sequencing, ioctl state and device removal. */
	struct mutex lock;
	struct kref refcount;
	bool powered;
	bool removing;
	unsigned int reset_count;
	int sensor_type;
	u32 spi_value;
	u32 requested_clock_hz;
	char name[EL721_NAME_LEN];
	char model[EL721_MODEL_INFO_LEN];
	char position[EL721_POSITION_LEN];
};

static void el721_free(struct kref *ref)
{
	struct el721_data *el721 = container_of(ref, struct el721_data,
						 refcount);

	kfree(el721);
}

static int el721_prepare_hardware_locked(struct el721_data *el721)
{
	int ret;

	/*
	 * Do not request or drive either resource during probe.  Qualcomm's secure
	 * firmware still owns the EL721 transport while Linux boots, and touching
	 * GPIO155 before an authenticated operation can reset the tablet.  The
	 * metadata and compatibility node remain available while the hardware is
	 * acquired lazily on the first explicit power request.
	 */
	if (!el721->ldo_gpio) {
		el721->ldo_gpio = devm_gpiod_get(el721->dev, "ldo",
						 GPIOD_ASIS);
		if (IS_ERR(el721->ldo_gpio)) {
			ret = PTR_ERR(el721->ldo_gpio);
			el721->ldo_gpio = NULL;
			return dev_err_probe(el721->dev, ret,
					     "failed to get LDO GPIO\n");
		}
	}

	if (!el721->enable_gpio) {
		el721->enable_gpio = devm_gpiod_get(el721->dev, "enable",
						    GPIOD_ASIS);
		if (IS_ERR(el721->enable_gpio)) {
			ret = PTR_ERR(el721->enable_gpio);
			el721->enable_gpio = NULL;
			return dev_err_probe(el721->dev, ret,
					     "failed to get enable GPIO\n");
		}
	}

	return 0;
}

static int el721_power_on_locked(struct el721_data *el721)
{
	int ret;

	if (el721->powered)
		return 0;

	ret = el721_prepare_hardware_locked(el721);
	if (ret)
		return ret;

	/* Exact EL721 GPIO sequence from Samsung's shipping X910 driver. */
	ret = gpiod_direction_output(el721->ldo_gpio, 1);
	if (ret)
		return ret;
	usleep_range(2100, 2150);
	ret = gpiod_direction_output(el721->enable_gpio, 1);
	if (ret) {
		gpiod_set_value_cansleep(el721->ldo_gpio, 0);
		return ret;
	}
	usleep_range(1100, 1150);
	usleep_range(5000, 5050);
	el721->powered = true;

	return 0;
}

static int el721_power_off_locked(struct el721_data *el721)
{
	if (!el721->powered)
		return 0;

	/* Holding enable low keeps the sensor quiescent even if VDD is shared. */
	gpiod_set_value_cansleep(el721->enable_gpio, 0);
	gpiod_set_value_cansleep(el721->ldo_gpio, 0);

	el721->powered = false;
	return 0;
}

static int el721_reset_locked(struct el721_data *el721)
{
	if (!el721->powered)
		return -EHOSTDOWN;

	gpiod_set_value_cansleep(el721->enable_gpio, 0);
	usleep_range(1050, 1100);
	gpiod_set_value_cansleep(el721->enable_gpio, 1);
	el721->reset_count++;

	return 0;
}

static int el721_reset_control_locked(struct el721_data *el721, u32 enabled)
{
	if (enabled > 1)
		return -EINVAL;
	if (!el721->powered)
		return enabled ? -EHOSTDOWN : 0;

	gpiod_set_value_cansleep(el721->enable_gpio, enabled);
	return 0;
}

static int el721_run_transfer_locked(struct el721_data *el721,
				     const struct egis_ioc_transfer *ioc)
{
	char model[EL721_MODEL_INFO_LEN] = { 0 };

	switch (ioc->opcode) {
	case FP_SENSOR_RESET:
		return el721_reset_locked(el721);
	case FP_POWER_CONTROL:
		if (ioc->len > 1)
			return -EINVAL;
		return ioc->len ? el721_power_on_locked(el721) :
				  el721_power_off_locked(el721);
	case FP_RESET_CONTROL:
		return el721_reset_control_locked(el721, ioc->len);
	case FP_SET_SPI_CLOCK:
		/* The SPI clock belongs to secure world on this platform. */
		el721->requested_clock_hz = ioc->speed_hz;
		return 0;
	case FP_DISABLE_SPI_CLOCK:
		el721->requested_clock_hz = 0;
		return 0;
	case FP_CPU_SPEEDUP:
		/* Kept as an ABI-compatible no-op; Linux manages CPU frequency. */
		return 0;
	case FP_SET_SENSOR_TYPE:
		el721->sensor_type = (int)ioc->len;
		return 0;
	case FP_SPI_VALUE:
		el721->spi_value = ioc->len;
		return 0;
	case FP_MODEL_INFO:
		if (!ioc->rx_buf)
			return -EINVAL;
		strscpy(model, el721->model, sizeof(model));
		if (copy_to_user(u64_to_user_ptr(ioc->rx_buf), model,
				 sizeof(model)))
			return -EFAULT;
		return 0;
	case FP_IOCTL_RESERVED_01:
	case FP_IOCTL_RESERVED_02:
	case FP_IOCTL_RESERVED_03:
	case FP_IOCTL_RESERVED_04:
	case FP_IOCTL_RESERVED_05:
	case FP_IOCTL_RESERVED_06:
	case FP_IOCTL_RESERVED_07:
		return 0;
	default:
		/* Raw registers, frames and SPI messages are never exposed here. */
		return -EOPNOTSUPP;
	}
}

static long el721_ioctl(struct file *file, unsigned int cmd,
			unsigned long arg)
{
	struct el721_data *el721 = file->private_data;
	struct egis_ioc_transfer *xfers;
	unsigned int size;
	unsigned int count;
	unsigned int i;
	long ret = 0;

	if (_IOC_TYPE(cmd) != EGIS_IOC_MAGIC ||
	    _IOC_NR(cmd) != _IOC_NR(EGIS_IOC_MESSAGE(0)) ||
	    _IOC_DIR(cmd) != _IOC_WRITE)
		return -ENOTTY;

	size = _IOC_SIZE(cmd);
	if (!size || size % sizeof(*xfers))
		return -EINVAL;

	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;

	xfers = memdup_user((const void __user *)arg, size);
	if (IS_ERR(xfers))
		return PTR_ERR(xfers);

	count = size / sizeof(*xfers);
	mutex_lock(&el721->lock);
	if (el721->removing) {
		ret = -ENODEV;
		goto out_unlock;
	}

	for (i = 0; i < count; i++) {
		ret = el721_run_transfer_locked(el721, &xfers[i]);
		if (ret)
			break;
	}

out_unlock:
	mutex_unlock(&el721->lock);
	kfree(xfers);
	return ret;
}

static int el721_open(struct inode *inode, struct file *file)
{
	struct miscdevice *misc = file->private_data;
	struct el721_data *el721 = container_of(misc, struct el721_data,
						miscdev);
	int ret = 0;

	mutex_lock(&el721->lock);
	if (el721->removing) {
		ret = -ENODEV;
	} else {
		kref_get(&el721->refcount);
		file->private_data = el721;
	}
	mutex_unlock(&el721->lock);

	return ret;
}

static int el721_release(struct inode *inode, struct file *file)
{
	struct el721_data *el721 = file->private_data;

	kref_put(&el721->refcount, el721_free);
	return 0;
}

static const struct file_operations el721_fops = {
	.owner = THIS_MODULE,
	.open = el721_open,
	.release = el721_release,
	.unlocked_ioctl = el721_ioctl,
};

static ssize_t vendor_show(struct device *dev,
			   struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%s\n", EL721_VENDOR);
}
static DEVICE_ATTR_RO(vendor);

static ssize_t name_show(struct device *dev,
			 struct device_attribute *attr, char *buf)
{
	struct el721_data *el721 = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%s\n", el721->name);
}
static DEVICE_ATTR_RO(name);

static ssize_t model_show(struct device *dev,
			  struct device_attribute *attr, char *buf)
{
	struct el721_data *el721 = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%s\n", el721->model);
}
static DEVICE_ATTR_RO(model);

static ssize_t position_show(struct device *dev,
			     struct device_attribute *attr, char *buf)
{
	struct el721_data *el721 = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%s\n", el721->position);
}
static DEVICE_ATTR_RO(position);

static ssize_t power_show(struct device *dev,
			  struct device_attribute *attr, char *buf)
{
	struct el721_data *el721 = dev_get_drvdata(dev);
	bool powered;

	mutex_lock(&el721->lock);
	powered = el721->powered;
	mutex_unlock(&el721->lock);

	return sysfs_emit(buf, "%u\n", powered);
}

static ssize_t power_store(struct device *dev,
			   struct device_attribute *attr, const char *buf,
			   size_t count)
{
	struct el721_data *el721 = dev_get_drvdata(dev);
	bool enabled;
	int ret;

	ret = kstrtobool(buf, &enabled);
	if (ret)
		return ret;

	mutex_lock(&el721->lock);
	if (el721->removing)
		ret = -ENODEV;
	else if (enabled)
		ret = el721_power_on_locked(el721);
	else
		ret = el721_power_off_locked(el721);
	mutex_unlock(&el721->lock);

	return ret ? ret : count;
}
static DEVICE_ATTR(sensor_power, 0600, power_show, power_store);

static ssize_t reset_count_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	struct el721_data *el721 = dev_get_drvdata(dev);
	unsigned int reset_count;

	mutex_lock(&el721->lock);
	reset_count = el721->reset_count;
	mutex_unlock(&el721->lock);

	return sysfs_emit(buf, "%u\n", reset_count);
}
static DEVICE_ATTR_RO(reset_count);

static ssize_t reset_store(struct device *dev,
			   struct device_attribute *attr, const char *buf,
			   size_t count)
{
	struct el721_data *el721 = dev_get_drvdata(dev);
	bool reset;
	int ret;

	ret = kstrtobool(buf, &reset);
	if (ret)
		return ret;
	if (!reset)
		return -EINVAL;

	mutex_lock(&el721->lock);
	ret = el721->removing ? -ENODEV : el721_reset_locked(el721);
	mutex_unlock(&el721->lock);

	return ret ? ret : count;
}
static DEVICE_ATTR_WO(reset);

static struct attribute *el721_attrs[] = {
	&dev_attr_vendor.attr,
	&dev_attr_name.attr,
	&dev_attr_model.attr,
	&dev_attr_position.attr,
	&dev_attr_sensor_power.attr,
	&dev_attr_reset_count.attr,
	&dev_attr_reset.attr,
	NULL,
};

static const struct attribute_group el721_attr_group = {
	.attrs = el721_attrs,
};

static void el721_read_string(struct device *dev, const char *property,
			      const char *legacy_property,
			      const char *fallback, char *dest,
			      size_t dest_size)
{
	const char *value;

	if (device_property_read_string(dev, property, &value) &&
	    device_property_read_string(dev, legacy_property, &value))
		value = fallback;

	strscpy(dest, value, dest_size);
}

static int el721_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct el721_data *el721;
	int ret;

	el721 = kzalloc_obj(*el721);
	if (!el721)
		return -ENOMEM;

	el721->dev = dev;
	mutex_init(&el721->lock);
	kref_init(&el721->refcount);
	platform_set_drvdata(pdev, el721);

	el721_read_string(dev, "egistec,name", "etspi-chipid",
			  EL721_DEFAULT_NAME, el721->name,
			  sizeof(el721->name));
	el721_read_string(dev, "egistec,model", "etspi-modelinfo",
			  EL721_DEFAULT_MODEL, el721->model,
			  sizeof(el721->model));
	el721_read_string(dev, "egistec,position", "etspi-position",
			  EL721_DEFAULT_POSITION, el721->position,
			  sizeof(el721->position));

	el721->miscdev.minor = MISC_DYNAMIC_MINOR;
	el721->miscdev.name = "esfp0";
	el721->miscdev.fops = &el721_fops;
	el721->miscdev.parent = dev;
	el721->miscdev.mode = 0600;

	ret = misc_register(&el721->miscdev);
	if (ret) {
		dev_err(dev, "failed to register /dev/esfp0: %d\n", ret);
		goto err_load;
	}

	ret = device_add_group(dev, &el721_attr_group);
	if (ret) {
		dev_err(dev, "failed to create sysfs attributes: %d\n", ret);
		goto err_misc;
	}

	dev_info(dev, "%s %s secure companion ready (sensor powered off)\n",
		 EL721_VENDOR, el721->name);
	return 0;

err_misc:
	mutex_lock(&el721->lock);
	el721->removing = true;
	el721_power_off_locked(el721);
	mutex_unlock(&el721->lock);
	misc_deregister(&el721->miscdev);
err_load:
	platform_set_drvdata(pdev, NULL);
	kref_put(&el721->refcount, el721_free);
	return ret;
}

static void el721_remove(struct platform_device *pdev)
{
	struct el721_data *el721 = platform_get_drvdata(pdev);
	int ret;

	mutex_lock(&el721->lock);
	el721->removing = true;
	ret = el721_power_off_locked(el721);
	mutex_unlock(&el721->lock);
	if (ret)
		dev_err(&pdev->dev, "failed to disable sensor supply: %d\n", ret);

	device_remove_group(&pdev->dev, &el721_attr_group);
	misc_deregister(&el721->miscdev);
	platform_set_drvdata(pdev, NULL);
	kref_put(&el721->refcount, el721_free);
}

static void el721_shutdown(struct platform_device *pdev)
{
	struct el721_data *el721 = platform_get_drvdata(pdev);
	int ret;

	if (!el721)
		return;

	mutex_lock(&el721->lock);
	el721->removing = true;
	ret = el721_power_off_locked(el721);
	mutex_unlock(&el721->lock);
	if (ret)
		dev_err(&pdev->dev,
			"failed to disable sensor supply at shutdown: %d\n", ret);
}

static int el721_suspend(struct device *dev)
{
	struct el721_data *el721 = dev_get_drvdata(dev);
	int ret;

	mutex_lock(&el721->lock);
	ret = el721_power_off_locked(el721);
	mutex_unlock(&el721->lock);
	if (ret)
		dev_err(dev, "failed to disable sensor supply at suspend: %d\n",
			ret);

	return ret;
}

static DEFINE_SIMPLE_DEV_PM_OPS(el721_pm_ops, el721_suspend, NULL);

static const struct of_device_id el721_of_match[] = {
	{ .compatible = "egistec,el721" },
	{ .compatible = "etspi,el7xx" },
	{ }
};
MODULE_DEVICE_TABLE(of, el721_of_match);

static struct platform_driver el721_driver = {
	.probe = el721_probe,
	.remove = el721_remove,
	.shutdown = el721_shutdown,
	.driver = {
		.name = "egis-el721",
		.of_match_table = el721_of_match,
		.pm = pm_sleep_ptr(&el721_pm_ops),
	},
};

static struct platform_device *el721_fallback_device;

static struct gpiod_lookup_table el721_fallback_gpios = {
	.dev_id = "egis-el721",
	.table = {
		GPIO_LOOKUP("f100000.pinctrl", 91, "ldo", GPIO_ACTIVE_HIGH),
		GPIO_LOOKUP("f100000.pinctrl", 155, "enable", GPIO_ACTIVE_HIGH),
		{ }
	},
};

static int __init el721_init(void)
{
	struct device_node *node;
	int ret;

	ret = platform_driver_register(&el721_driver);
	if (ret)
		return ret;

	/*
	 * Samsung ABL resets before Linux when the EL721 GPIO description is
	 * added to vendor_boot.  Publish the restricted userspace ABI from a
	 * software platform device when firmware supplied no safe DT node.  A
	 * lookup table maps the two stock TLMM lines, but they are not requested or
	 * driven until userspace starts an authenticated operation after boot.
	 */
	node = of_find_compatible_node(NULL, NULL, "egistec,el721");
	if (!node)
		node = of_find_compatible_node(NULL, NULL, "etspi,el7xx");
	if (node) {
		of_node_put(node);
		return 0;
	}

	gpiod_add_lookup_table(&el721_fallback_gpios);
	el721_fallback_device =
		platform_device_register_simple("egis-el721",
						PLATFORM_DEVID_NONE, NULL, 0);
	if (IS_ERR(el721_fallback_device)) {
		ret = PTR_ERR(el721_fallback_device);
		el721_fallback_device = NULL;
		gpiod_remove_lookup_table(&el721_fallback_gpios);
		platform_driver_unregister(&el721_driver);
		return ret;
	}

	return 0;
}

static void __exit el721_exit(void)
{
	if (el721_fallback_device) {
		platform_device_unregister(el721_fallback_device);
		gpiod_remove_lookup_table(&el721_fallback_gpios);
	}
	platform_driver_unregister(&el721_driver);
}

module_init(el721_init);
module_exit(el721_exit);

MODULE_DESCRIPTION("Secure-world companion driver for EgisTec EL721");
MODULE_AUTHOR("Ubuntu Galaxy Tab S9 Ultra port contributors");
MODULE_LICENSE("GPL");
