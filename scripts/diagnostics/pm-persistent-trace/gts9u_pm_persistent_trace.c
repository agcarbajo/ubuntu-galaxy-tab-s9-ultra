// SPDX-License-Identifier: GPL-2.0-only
/* Temporary PM stage trace in the empty last page of sec-debug-pool. */
#include <asm/sysreg.h>
#include <linux/bitops.h>
#include <linux/device.h>
#include <linux/io.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_reserved_mem.h>
#include <linux/sizes.h>
#include <linux/spinlock.h>
#include <linux/string.h>
#include <trace/events/power.h>

#define TRACE_MAGIC 0x4d505447 /* GTPM */
#define TRACE_RECORDS 11
#define TRACE_COPIES 20
#define OLD_COPIES 5
#define OLD_RING_BYTES (16 + 10 * 64)

struct pm_record {
	u32 sequence;
	s32 value;
	u32 action_hash;
	u8 start;
	u8 reserved[3];
};

struct pm_ring {
	u32 magic;
	u32 version;
	u32 last_sequence;
	u32 record_count;
	struct pm_record records[TRACE_RECORDS];
};

static void *pool_mapping;
static void *trace_page;
static struct pm_ring *rings;
static DEFINE_RAW_SPINLOCK(trace_lock);
static struct pm_record trace_state[TRACE_RECORDS];
static u32 sequence;
static bool early_resume;

static u32 hash_action(const char *action)
{
	u32 hash = 2166136261U;

	for (; *action; action++)
		hash = (hash ^ (u8)*action) * 16777619U;
	return hash;
}

static bool previous_trace_page(void)
{
	u8 *page = trace_page;
	int i, matches = 0;

	if (memchr_inv(page + OLD_COPIES * OLD_RING_BYTES, 0,
		       SZ_4K - OLD_COPIES * OLD_RING_BYTES))
		return false;
	for (i = 0; i < OLD_COPIES; i++) {
		struct pm_ring *old =
			(struct pm_ring *)(page + i * OLD_RING_BYTES);

		if (hweight32(READ_ONCE(old->magic) ^ TRACE_MAGIC) <= 8 &&
		    hweight32(READ_ONCE(old->version) ^ 3) <= 2 &&
		    hweight32(READ_ONCE(old->record_count) ^ 10) <= 2)
			matches++;
	}
	return matches >= 3;
}

static bool current_trace_page(void)
{
	u8 *page = trace_page;
	int i, matches = 0;

	if (memchr_inv(page + TRACE_COPIES * sizeof(*rings), 0,
		       SZ_4K - TRACE_COPIES * sizeof(*rings)))
		return false;
	for (i = 0; i < TRACE_COPIES; i++) {
		if (hweight32(READ_ONCE(rings[i].magic) ^ TRACE_MAGIC) <= 8 &&
		    (hweight32(READ_ONCE(rings[i].version) ^ 4) <= 2 ||
		     hweight32(READ_ONCE(rings[i].version) ^ 5) <= 2 ||
		     hweight32(READ_ONCE(rings[i].version) ^ 6) <= 2) &&
		    hweight32(READ_ONCE(rings[i].record_count) ^ TRACE_RECORDS) <= 2)
			matches++;
	}
	return matches >= 11;
}

static void flush_to_ram(const void *address, size_t size)
{
	unsigned long line_size = 4UL << ((read_sysreg(ctr_el0) >> 16) & 15);
	unsigned long cache_line = (unsigned long)address & ~(line_size - 1);
	unsigned long end = (unsigned long)address + size;

	for (; cache_line < end; cache_line += line_size)
		asm volatile("dc cvac, %0" : : "r"(cache_line) : "memory");
	asm volatile("dsb sy" : : : "memory");
}

static void write_state_locked(void)
{
	int i;

	for (i = 0; i < TRACE_COPIES; i++) {
		memcpy(rings[i].records, trace_state, sizeof(trace_state));
		WRITE_ONCE(rings[i].last_sequence, sequence);
	}
	flush_to_ram(trace_page, SZ_4K);
}

static void record_stage(const char *action, int value, bool start)
{
	unsigned long flags;

	raw_spin_lock_irqsave(&trace_lock, flags);
	trace_state[0].sequence = ++sequence;
	trace_state[0].value = value;
	trace_state[0].action_hash = hash_action(action) & 0x7fffffffU;
	trace_state[0].start = start;
	write_state_locked();
	raw_spin_unlock_irqrestore(&trace_lock, flags);
}

static void trace_stage(void *unused, const char *action, int value,
			bool start)
{
	bool is_early = !strcmp(action, "dpm_resume_early");

	if (is_early && start)
		WRITE_ONCE(early_resume, true);
	record_stage(action, value, start);
	if (is_early && !start)
		WRITE_ONCE(early_resume, false);
}

static int callback_entry(struct kretprobe_instance *instance,
			  struct pt_regs *regs)
{
	struct device *dev;
	unsigned long flags;
	u32 *slot_data = (u32 *)instance->data;
	int slot;

	*slot_data = 0;
	if (!READ_ONCE(early_resume) || !regs->regs[0])
		return 0;
	dev = (struct device *)regs->regs[1];
	raw_spin_lock_irqsave(&trace_lock, flags);
	for (slot = 1; slot < TRACE_RECORDS; slot++)
		if (!trace_state[slot].start)
			break;
	if (slot < TRACE_RECORDS) {
		*slot_data = slot;
		trace_state[slot].sequence = ++sequence;
		trace_state[slot].value = 0;
		trace_state[slot].action_hash =
			hash_action(dev_name(dev)) | 0x80000000U;
		trace_state[slot].start = 1;
		write_state_locked();
	}
	raw_spin_unlock_irqrestore(&trace_lock, flags);
	return 0;
}

static int callback_return(struct kretprobe_instance *instance,
			   struct pt_regs *regs)
{
	u32 slot = *(u32 *)instance->data;
	unsigned long flags;

	if (!slot)
		return 0;
	raw_spin_lock_irqsave(&trace_lock, flags);
	trace_state[slot].sequence = ++sequence;
	trace_state[slot].start = 0;
	write_state_locked();
	raw_spin_unlock_irqrestore(&trace_lock, flags);
	return 0;
}

static int nested_entry(struct kretprobe_instance *instance,
			struct pt_regs *regs)
{
	unsigned long flags;
	u32 *slot_data = (u32 *)instance->data;
	const char *name = get_kretprobe(instance)->kp.symbol_name;
	int slot;

	*slot_data = 0;
	if (!READ_ONCE(early_resume))
		return 0;
	raw_spin_lock_irqsave(&trace_lock, flags);
	for (slot = 1; slot < TRACE_RECORDS; slot++)
		if (!trace_state[slot].start)
			break;
	if (slot < TRACE_RECORDS) {
		*slot_data = slot;
		trace_state[slot].sequence = ++sequence;
		trace_state[slot].value = 0;
		trace_state[slot].action_hash = hash_action(name) & 0x7fffffffU;
		trace_state[slot].start = 1;
		write_state_locked();
	}
	raw_spin_unlock_irqrestore(&trace_lock, flags);
	return 0;
}

static struct kretprobe callback_probe = {
	.kp.symbol_name = "dpm_run_callback",
	.entry_handler = callback_entry,
	.handler = callback_return,
	.data_size = sizeof(u32),
	.maxactive = 128,
};

#define NESTED_PROBE(name) { \
	.kp.symbol_name = name, \
	.entry_handler = nested_entry, \
	.handler = callback_return, \
	.data_size = sizeof(u32), \
	.maxactive = 32, \
}

static struct kretprobe nested_probes[] = {
	NESTED_PROBE("ath12k_pci_pm_resume_early"),
	NESTED_PROBE("ath12k_core_resume_early"),
	NESTED_PROBE("ath12k_pci_power_up"),
	NESTED_PROBE("ath12k_pci_sw_reset"),
	NESTED_PROBE("ath12k_mhi_start"),
	NESTED_PROBE("ath12k_mhi_set_state"),
	NESTED_PROBE("mhi_prepare_for_power_up"),
	NESTED_PROBE("mhi_sync_power_up"),
};

static int __init gts9u_pm_trace_init(void)
{
	struct device_node *memory_node;
	struct reserved_mem *reserved;
	int i, ret;

	memory_node = of_find_node_by_path(
		"/reserved-memory/sec-debug-pool@880100000");
	if (!memory_node)
		return -ENODEV;
	reserved = of_reserved_mem_lookup(memory_node);
	of_node_put(memory_node);
	if (!reserved || reserved->size < SZ_4K ||
	    sizeof(*rings) * TRACE_COPIES > SZ_4K)
		return -EINVAL;
	pool_mapping = memremap(reserved->base, reserved->size, MEMREMAP_WB);
	if (!pool_mapping)
		return -ENOMEM;
	trace_page = (u8 *)pool_mapping + reserved->size - SZ_4K;
	rings = trace_page;
	/* Accept only our archived diagnostic marker, not arbitrary pool data. */
	if (memchr_inv(trace_page, 0, SZ_4K) &&
	    !previous_trace_page() && !current_trace_page()) {
		memunmap(pool_mapping);
		return -EBUSY;
	}
	memset(trace_page, 0, SZ_4K);
	for (i = 0; i < TRACE_COPIES; i++) {
		rings[i].magic = TRACE_MAGIC;
		rings[i].version = 6;
		rings[i].record_count = TRACE_RECORDS;
	}
	flush_to_ram(trace_page, SZ_4K);
	record_stage("module_loaded", 0, true);
	ret = register_trace_suspend_resume(trace_stage, NULL);
	if (ret) {
		memunmap(pool_mapping);
		return ret;
	}
	ret = register_kretprobe(&callback_probe);
	if (ret)
		goto unregister_stage;
	for (i = 0; i < ARRAY_SIZE(nested_probes); i++) {
		ret = register_kretprobe(&nested_probes[i]);
		if (ret)
			goto unregister_nested;
	}
	pr_info("gts9u persistent PM trace armed in sec-debug-pool last page\n");
	return 0;

unregister_nested:
	while (i--)
		unregister_kretprobe(&nested_probes[i]);
	unregister_kretprobe(&callback_probe);
unregister_stage:
	unregister_trace_suspend_resume(trace_stage, NULL);
	tracepoint_synchronize_unregister();
	memunmap(pool_mapping);
	return ret;
}

static void __exit gts9u_pm_trace_exit(void)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(nested_probes); i++)
		unregister_kretprobe(&nested_probes[i]);
	unregister_kretprobe(&callback_probe);
	unregister_trace_suspend_resume(trace_stage, NULL);
	tracepoint_synchronize_unregister();
	record_stage("module_unloaded", 0, true);
	memunmap(pool_mapping);
}

module_init(gts9u_pm_trace_init);
module_exit(gts9u_pm_trace_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Temporary persistent gts9uwifi PM stage trace");
