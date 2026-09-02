// SPDX-License-Identifier: GPL-2.0-only
/*
 * SM-X910 secure-processor interrupt notification for the SPL listener.
 * The stock device tree routes qsee_ipc_irq_spss to IPCC client 16, signal 1,
 * rising edge. This is separate from SPSS GLINK's signal 0.
 * No secure memory or key material is exposed through this device.
 */
#include <linux/atomic.h>
#include <linux/fs.h>
#include <linux/interrupt.h>
#include <linux/irqdomain.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/poll.h>

static DECLARE_WAIT_QUEUE_HEAD(spss_irq_wait);
static atomic_t spss_irq_pending = ATOMIC_INIT(0);
static atomic_t spss_irq_opened = ATOMIC_INIT(0);
static unsigned int spss_irq;

static irqreturn_t spss_irq_handler(int irq, void *data)
{
	atomic_set(&spss_irq_pending, 1);
	wake_up_interruptible(&spss_irq_wait);
	return IRQ_HANDLED;
}

static int spss_irq_open(struct inode *inode, struct file *file)
{
	/* The shared SPL listener is the sole consumer of each notification. */
	if (atomic_cmpxchg(&spss_irq_opened, 0, 1))
		return -EBUSY;
	return 0;
}

static int spss_irq_release(struct inode *inode, struct file *file)
{
	atomic_set(&spss_irq_opened, 0);
	return 0;
}

static __poll_t spss_irq_poll(struct file *file, poll_table *wait)
{
	poll_wait(file, &spss_irq_wait, wait);
	/*
	 * Register the waiter before consuming pending state to avoid lost IRQs.
	 * Like the stock bridge, a successful poll acknowledges the event.
	 */
	return atomic_xchg(&spss_irq_pending, 0) ? EPOLLIN : 0;
}

static const struct file_operations spss_irq_fops = {
	.owner = THIS_MODULE,
	.open = spss_irq_open,
	.release = spss_irq_release,
	.poll = spss_irq_poll,
	.llseek = noop_llseek,
};

static struct miscdevice spss_irq_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "qsee_ipc_irq_spss",
	.fops = &spss_irq_fops,
	.mode = 0600,
};

static int __init spss_irq_init(void)
{
	struct device_node *ipcc;
	struct irq_fwspec spec = { .param_count = 3 };
	int ret;

	if (!of_machine_is_compatible("samsung,gts9uwifi"))
		return -ENODEV;
	ipcc = of_find_compatible_node(NULL, NULL, "qcom,sm8550-ipcc");
	if (!ipcc)
		ipcc = of_find_compatible_node(NULL, NULL, "qcom,ipcc");
	if (!ipcc)
		return -ENODEV;
	spec.fwnode = of_fwnode_handle(ipcc);
	spec.param[0] = 16;
	spec.param[1] = 1;
	spec.param[2] = IRQ_TYPE_EDGE_RISING;
	spss_irq = irq_create_fwspec_mapping(&spec);
	of_node_put(ipcc);
	if (!spss_irq)
		return -EPROBE_DEFER;
	ret = request_irq(spss_irq, spss_irq_handler, IRQF_TRIGGER_RISING,
			  "qsee_ipc_irq_spss", &spss_irq_device);
	if (ret)
		return ret;
	ret = misc_register(&spss_irq_device);
	if (ret) {
		free_irq(spss_irq, &spss_irq_device);
		return ret;
	}
	pr_info("qcom_spss_irq: IPCC 16:1 on IRQ %u\n", spss_irq);
	return 0;
}

static void __exit spss_irq_exit(void)
{
	misc_deregister(&spss_irq_device);
	free_irq(spss_irq, &spss_irq_device);
	/* IPCC owns the mapping; never dispose a possibly pre-existing mapping. */
}

module_init(spss_irq_init);
module_exit(spss_irq_exit);
MODULE_DESCRIPTION("Galaxy Tab S9 Ultra secure-processor IRQ notification");
MODULE_LICENSE("GPL");
MODULE_SOFTDEP("pre: qcom_ipcc");
