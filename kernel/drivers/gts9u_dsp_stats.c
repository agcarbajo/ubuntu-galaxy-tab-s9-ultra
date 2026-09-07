// SPDX-License-Identifier: GPL-2.0-only
/* Read-only SMEM counters, using the ABI from drivers/soc/qcom/qcom_stats.c. */
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/soc/qcom/smem.h>

struct gts9u_sleep_stats {
	__le32 type;
	__le32 count;
	__le64 entered;
	__le64 exited;
	__le64 accumulated;
};

static int snapshot_get(char *buffer, const struct kernel_param *parameter)
{
	static const unsigned int hosts[] = { 2, 5 };
	static const unsigned int items[] = { 606, 607 };
	static const char * const names[] = { "adsp", "cdsp" };
	struct gts9u_sleep_stats stats;
	size_t size;
	void *memory;
	int i, length = 0;

	if (!of_machine_is_compatible("samsung,gts9uwifi"))
		return -ENODEV;
	for (i = 0; i < ARRAY_SIZE(hosts); ++i) {
		memory = qcom_smem_get(hosts[i], items[i], &size);
		if (IS_ERR(memory)) {
			length += scnprintf(buffer + length, PAGE_SIZE - length,
					    "%s unavailable=%ld\n", names[i],
					    PTR_ERR(memory));
			continue;
		}
		if (size < sizeof(stats))
			return -EINVAL;
		/* Firmware can update these counters while a snapshot is read. */
		memcpy_fromio(&stats, memory, sizeof(stats));
		length += scnprintf(buffer + length, PAGE_SIZE - length,
			"%s count=%u entered=%llu exited=%llu accumulated=%llu\n",
			names[i], le32_to_cpu(stats.count),
			le64_to_cpu(stats.entered), le64_to_cpu(stats.exited),
			le64_to_cpu(stats.accumulated));
	}
	return length;
}

static const struct kernel_param_ops snapshot_ops = { .get = snapshot_get };
module_param_cb(snapshot, &snapshot_ops, NULL, 0444);
MODULE_PARM_DESC(snapshot, "Read-only ADSP/CDSP sleep counters (timer ticks)");
MODULE_DESCRIPTION("Samsung SM-X910 read-only DSP sleep diagnostics");
MODULE_LICENSE("GPL");
