// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) 2016-2021, The Linux Foundation. All rights reserved.
 * Copyright (c) 2022 Qualcomm Innovation Center, Inc. All rights reserved.
 *
 * Mainline adaptation for the Galaxy Tab S9 Ultra.  Samsung's libspcom uses
 * this device for cross-process SPSS boot events.  The downstream IAR/CMAC
 * memory interface is deliberately not emulated: it needs hypervisor memory
 * assignment which mainline does not expose on this platform.
 */

#include <linux/build_bug.h>
#include <linux/completion.h>
#include <linux/fs.h>
#include <linux/jiffies.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/remoteproc.h>
#include <linux/uaccess.h>

#include <uapi/linux/spss_utils.h>

#define SPSS_FIRMWARE_NAME "spss1p.mdt"

static_assert(SPSS_IOC_WAIT_FOR_EVENT == 0xc00c5302);
static_assert(SPSS_IOC_SIGNAL_EVENT == 0xc0085303);
static_assert(SPSS_IOC_IS_EVENT_SIGNALED == 0xc0085304);

struct spss_utils {
	struct device *dev;
	struct miscdevice miscdev;
	struct rproc *rproc;
	struct rproc_subdev subdev;
	struct completion events[SPSS_NUM_EVENTS];
	bool signaled[SPSS_NUM_EVENTS];
	struct mutex event_lock;
	bool ssr_disabled;
};

static struct spss_utils *file_to_spss(struct file *file)
{
	struct miscdevice *miscdev = file->private_data;

	return container_of(miscdev, struct spss_utils, miscdev);
}

static void spss_utils_reset_event(struct spss_utils *spss, unsigned int id)
{
	reinit_completion(&spss->events[id]);
	spss->signaled[id] = false;
}

static void spss_utils_signal_kernel_event(struct spss_utils *spss,
					   unsigned int id)
{
	complete_all(&spss->events[id]);
	spss->signaled[id] = true;
}

static int spss_utils_subdev_prepare(struct rproc_subdev *subdev)
{
	return 0;
}

static int spss_utils_subdev_start(struct rproc_subdev *subdev)
{
	struct spss_utils *spss = container_of(subdev, struct spss_utils,
						  subdev);

	mutex_lock(&spss->event_lock);
	spss_utils_signal_kernel_event(spss, SPSS_EVENT_ID_SPU_POWER_UP);
	spss_utils_reset_event(spss, SPSS_EVENT_ID_SPU_POWER_DOWN);
	mutex_unlock(&spss->event_lock);

	return 0;
}

static void spss_utils_subdev_stop(struct rproc_subdev *subdev, bool crashed)
{
	struct spss_utils *spss = container_of(subdev, struct spss_utils,
						  subdev);
	unsigned int i;

	mutex_lock(&spss->event_lock);
	for (i = 0; i < SPSS_NUM_EVENTS; i++)
		spss_utils_reset_event(spss, i);
	mutex_unlock(&spss->event_lock);
}

static void spss_utils_subdev_unprepare(struct rproc_subdev *subdev)
{
	struct spss_utils *spss = container_of(subdev, struct spss_utils,
						  subdev);

	mutex_lock(&spss->event_lock);
	spss_utils_signal_kernel_event(spss, SPSS_EVENT_ID_SPU_POWER_DOWN);
	spss_utils_reset_event(spss, SPSS_EVENT_ID_SPU_POWER_UP);
	mutex_unlock(&spss->event_lock);
}

static int spss_utils_wait_for_event(struct spss_utils *spss,
				     struct spss_ioc_wait_for_event *req)
{
	long ret;

	if (req->event_id >= SPSS_NUM_EVENTS)
		return -EINVAL;

	if (req->timeout_sec) {
		ret = wait_for_completion_interruptible_timeout(
			&spss->events[req->event_id],
			secs_to_jiffies(req->timeout_sec));
		if (!ret) {
			req->status = EVENT_STATUS_TIMEOUT;
			return 0;
		}
	} else {
		ret = wait_for_completion_interruptible(
			&spss->events[req->event_id]);
	}

	if (ret < 0) {
		req->status = EVENT_STATUS_ABORTED;
		return ret;
	}

	req->status = EVENT_STATUS_SIGNALED;
	return 0;
}

static int spss_utils_signal_event(struct spss_utils *spss,
				   struct spss_ioc_signal_event *req)
{
	int ret = 0;

	if (req->event_id >= SPSS_NUM_EVENTS)
		return -EINVAL;

	mutex_lock(&spss->event_lock);
	if (spss->signaled[req->event_id]) {
		ret = -EINVAL;
	} else {
		spss_utils_signal_kernel_event(spss, req->event_id);
		req->status = EVENT_STATUS_SIGNALED;
	}
	mutex_unlock(&spss->event_lock);

	return ret;
}

static int spss_utils_is_event_signaled(struct spss_utils *spss,
					struct spss_ioc_is_signaled *req)
{
	if (req->event_id >= SPSS_NUM_EVENTS)
		return -EINVAL;

	mutex_lock(&spss->event_lock);
	req->status = spss->signaled[req->event_id] ?
		EVENT_STATUS_SIGNALED : EVENT_STATUS_NOT_SIGNALED;
	mutex_unlock(&spss->event_lock);

	return 0;
}

static long spss_utils_ioctl(struct file *file, unsigned int cmd,
			     unsigned long arg)
{
	struct spss_utils *spss = file_to_spss(file);
	void __user *user_arg = (void __user *)arg;
	int ret;

	switch (cmd) {
	case SPSS_IOC_WAIT_FOR_EVENT: {
		struct spss_ioc_wait_for_event req;

		if (copy_from_user(&req, user_arg, sizeof(req)))
			return -EFAULT;
		ret = spss_utils_wait_for_event(spss, &req);
		if (copy_to_user(user_arg, &req, sizeof(req)))
			return -EFAULT;
		return ret;
	}
	case SPSS_IOC_SIGNAL_EVENT: {
		struct spss_ioc_signal_event req;

		if (copy_from_user(&req, user_arg, sizeof(req)))
			return -EFAULT;
		ret = spss_utils_signal_event(spss, &req);
		if (!ret && copy_to_user(user_arg, &req, sizeof(req)))
			return -EFAULT;
		return ret;
	}
	case SPSS_IOC_IS_EVENT_SIGNALED: {
		struct spss_ioc_is_signaled req;

		if (copy_from_user(&req, user_arg, sizeof(req)))
			return -EFAULT;
		ret = spss_utils_is_event_signaled(spss, &req);
		if (!ret && copy_to_user(user_arg, &req, sizeof(req)))
			return -EFAULT;
		return ret;
	}
	case SPSS_IOC_SET_SSR_STATE: {
		__u32 disabled;

		if (copy_from_user(&disabled, user_arg, sizeof(disabled)))
			return -EFAULT;
		spss->ssr_disabled = !!disabled;
		return 0;
	}
	case SPSS_IOC_SET_FW_CMAC:
	case SPSS_IOC_SET_FW_AND_APPS_CMAC:
		dev_warn_once(spss->dev,
			      "IAR CMAC memory handoff is not available\n");
		return -EOPNOTSUPP;
	default:
		return -ENOIOCTLCMD;
	}
}

static const struct file_operations spss_utils_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = spss_utils_ioctl,
	.compat_ioctl = spss_utils_ioctl,
	.llseek = noop_llseek,
};

static ssize_t firmware_name_show(struct device *dev,
				  struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%s\n", SPSS_FIRMWARE_NAME);
}
static DEVICE_ATTR_RO(firmware_name);

static ssize_t test_fuse_state_show(struct device *dev,
				    struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "prod\n");
}
static DEVICE_ATTR_RO(test_fuse_state);

static struct attribute *spss_utils_attrs[] = {
	&dev_attr_firmware_name.attr,
	&dev_attr_test_fuse_state.attr,
	NULL,
};
ATTRIBUTE_GROUPS(spss_utils);

static int spss_utils_probe(struct platform_device *pdev)
{
	struct spss_utils *spss;
	unsigned int i;
	int ret;

	spss = devm_kzalloc(&pdev->dev, sizeof(*spss), GFP_KERNEL);
	if (!spss)
		return -ENOMEM;

	spss->dev = &pdev->dev;
	mutex_init(&spss->event_lock);
	for (i = 0; i < SPSS_NUM_EVENTS; i++)
		init_completion(&spss->events[i]);

	spss->rproc = rproc_get_by_child(&pdev->dev);
	if (!spss->rproc)
		return dev_err_probe(&pdev->dev, -EPROBE_DEFER,
				     "SPSS remoteproc is not ready\n");
	/* rproc_get_by_child() returns a borrowed parent-owned reference. */

	spss->subdev.prepare = spss_utils_subdev_prepare;
	spss->subdev.start = spss_utils_subdev_start;
	spss->subdev.stop = spss_utils_subdev_stop;
	spss->subdev.unprepare = spss_utils_subdev_unprepare;
	rproc_add_subdev(spss->rproc, &spss->subdev);

	spss->miscdev.minor = MISC_DYNAMIC_MINOR;
	spss->miscdev.name = "spss_utils";
	spss->miscdev.fops = &spss_utils_fops;
	spss->miscdev.parent = &pdev->dev;
	ret = misc_register(&spss->miscdev);
	if (ret) {
		rproc_remove_subdev(spss->rproc, &spss->subdev);
		return ret;
	}

	platform_set_drvdata(pdev, spss);
	dev_info(&pdev->dev, "SPSS userspace events ready for %s\n",
		 SPSS_FIRMWARE_NAME);
	return 0;
}

static void spss_utils_remove(struct platform_device *pdev)
{
	struct spss_utils *spss = platform_get_drvdata(pdev);

	misc_deregister(&spss->miscdev);
	rproc_remove_subdev(spss->rproc, &spss->subdev);
}

static struct platform_driver spss_utils_driver = {
	.probe = spss_utils_probe,
	.remove = spss_utils_remove,
	.driver = {
		.name = "spss_utils",
		.dev_groups = spss_utils_groups,
	},
};
module_platform_driver(spss_utils_driver);

MODULE_SOFTDEP("pre: qcom_spss");
MODULE_ALIAS("platform:spss_utils");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Qualcomm Secure Processor userspace utilities");
