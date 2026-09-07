// SPDX-License-Identifier: GPL-2.0-only
/* Read-only Gunyah identity probe for physical bring-up. */

#include <linux/bitfield.h>
#include <linux/arm-smccc.h>
#include <linux/debugfs.h>
#include <linux/gunyah.h>
#include <linux/io.h>
#include <linux/libfdt.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/uaccess.h>

#define GTS9U_GUNYAH_HYP_IDENTIFY                                      \
	ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, ARM_SMCCC_SMC_64,        \
			   ARM_SMCCC_OWNER_VENDOR_HYP, 0x8000)
#define GTS9U_GUNYAH_ADDRSPACE_FIND_INFO_AREA                         \
	ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, ARM_SMCCC_SMC_64,        \
			   ARM_SMCCC_OWNER_VENDOR_HYP, 0x806a)
#define GTS9U_QCOM_EXT_CALL_UID                                      \
	ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, ARM_SMCCC_SMC_32,        \
			   ARM_SMCCC_OWNER_VENDOR_HYP, 0x3f01)
/* Legacy Qualcomm SIP call used by ABL to locate struct HypBootInfo. */
#define GTS9U_HYP_INFO_GET_DTB_ADDRESS	0x02000609U
#define GTS9U_HYP_BOOTINFO_MAGIC		0xc06b0071U
#define GTS9U_HYP_MAX_DTBOS		4

struct gts9u_hyp_bootinfo {
	u32 magic;
	u32 version;
	u32 size;
	u32 pil_enable;
	u32 vm_type;
	u32 num_dtbos;
	struct {
		u64 base;
		u64 size;
	} dtbo[GTS9U_HYP_MAX_DTBOS];
} __packed;

static struct dentry *probe_debugfs_dir;
static struct debugfs_blob_wrapper dtbo_blobs[GTS9U_HYP_MAX_DTBOS];

static void export_dtbo(unsigned int index, phys_addr_t phys, size_t size)
{
	char name[16];
	void __iomem *mapping;
	void *copy;
	const struct fdt_header *header;
	size_t totalsize;
	int ret;

	if (!size || size > SZ_1M)
		return;
	mapping = ioremap(phys, size);
	if (!mapping)
		return;
	copy = kmalloc(size, GFP_KERNEL);
	if (!copy) {
		iounmap(mapping);
		return;
	}
	ret = copy_from_kernel_nofault(copy, (const void __force *)mapping, size);
	iounmap(mapping);
	header = copy;
	totalsize = be32_to_cpu(header->totalsize);
	if (ret || be32_to_cpu(header->magic) != FDT_MAGIC ||
	    totalsize < sizeof(*header) || totalsize > size) {
		pr_warn("gts9u-gunyah: dtbo%u read/validation failed: %d\n",
			index, ret);
		kfree(copy);
		return;
	}

	dtbo_blobs[index].data = copy;
	dtbo_blobs[index].size = totalsize;
	snprintf(name, sizeof(name), "dtbo%u", index);
	debugfs_create_blob(name, 0400, probe_debugfs_dir, &dtbo_blobs[index]);
	pr_info("gts9u-gunyah: exported %s (%lu bytes) via debugfs\n",
		name, dtbo_blobs[index].size);
}

static void probe_hyp_bootinfo(phys_addr_t phys)
{
	struct gts9u_hyp_bootinfo info = {};
	void __iomem *mapping;
	unsigned int i, count;
	int ret;

	if (!IS_ALIGNED(phys, sizeof(u64))) {
		pr_warn("gts9u-gunyah: unaligned HypBootInfo address %pa\n", &phys);
		return;
	}

	mapping = ioremap(phys, sizeof(info));
	if (!mapping) {
		pr_warn("gts9u-gunyah: cannot map HypBootInfo at %pa\n", &phys);
		return;
	}
	ret = copy_from_kernel_nofault(&info, (const void __force *)mapping,
				       sizeof(info));
	iounmap(mapping);
	if (ret) {
		pr_warn("gts9u-gunyah: HypBootInfo read at %pa failed: %d\n",
			&phys, ret);
		return;
	}

	pr_info("gts9u-gunyah: bootinfo magic=%#x version=%u size=%u pil=%u vm-type=%u dtbos=%u\n",
		info.magic, info.version, info.size, info.pil_enable,
		info.vm_type, info.num_dtbos);
	if (info.magic != GTS9U_HYP_BOOTINFO_MAGIC)
		return;

	count = min_t(unsigned int, info.num_dtbos, GTS9U_HYP_MAX_DTBOS);
	for (i = 0; i < count; i++)
		pr_info("gts9u-gunyah: dtbo%u base=%#llx size=%#llx\n", i,
			info.dtbo[i].base, info.dtbo[i].size);
	for (i = 0; i < count; i++)
		export_dtbo(i, info.dtbo[i].base, info.dtbo[i].size);
}

static void log_result(const char *call, const struct arm_smccc_res *res)
{
	pr_info("gts9u-gunyah: %s=%#lx/%#lx/%#lx/%#lx\n", call,
		res->a0, res->a1, res->a2, res->a3);
}

static int __init gts9u_gunyah_identify_init(void)
{
	struct gh_hypercall_hyp_identify_resp identity = {};
	struct arm_smccc_res res = {};
	bool uuid_matches;

	probe_debugfs_dir = debugfs_create_dir("gts9u_gunyah", NULL);

	pr_info("gts9u-gunyah: smccc-conduit=%d\n",
		arm_smccc_1_1_get_conduit());
	arm_smccc_1_1_smc(ARM_SMCCC_VENDOR_HYP_CALL_UID_FUNC_ID, &res);
	log_result("uid-smc", &res);
	memset(&res, 0, sizeof(res));
	arm_smccc_1_1_hvc(ARM_SMCCC_VENDOR_HYP_CALL_UID_FUNC_ID, &res);
	log_result("uid-hvc", &res);
	memset(&res, 0, sizeof(res));
	arm_smccc_1_1_smc(GTS9U_GUNYAH_HYP_IDENTIFY, &res);
	log_result("identify-smc", &res);
	memset(&res, 0, sizeof(res));
	arm_smccc_1_1_hvc(GTS9U_GUNYAH_HYP_IDENTIFY, &res);
	log_result("identify-hvc", &res);
	memset(&res, 0, sizeof(res));
	arm_smccc_1_1_hvc(GTS9U_GUNYAH_ADDRSPACE_FIND_INFO_AREA, 0, &res);
	log_result("find-info-area-hvc", &res);
	memset(&res, 0, sizeof(res));
	arm_smccc_1_1_smc(GTS9U_QCOM_EXT_CALL_UID, &res);
	log_result("qcom-ext-uid-smc", &res);
	memset(&res, 0, sizeof(res));
	arm_smccc_1_1_smc(GTS9U_HYP_INFO_GET_DTB_ADDRESS, &res);
	log_result("hyp-bootinfo-smc", &res);
	if (!res.a0 && res.a1)
		probe_hyp_bootinfo(res.a1);

	uuid_matches = arch_is_gh_guest();
	gh_hypercall_hyp_identify(&identity);
	pr_info("gts9u-gunyah: uuid-match=%u variant=%#llx api=v%u flags=%#llx/%#llx/%#llx\n",
		uuid_matches, FIELD_GET(GH_API_INFO_VARIANT_MASK, identity.api_info),
		gh_api_version(&identity), identity.flags[0],
		identity.flags[1], identity.flags[2]);

	return 0;
}

static void __exit gts9u_gunyah_identify_exit(void)
{
	unsigned int i;

	debugfs_remove_recursive(probe_debugfs_dir);
	for (i = 0; i < GTS9U_HYP_MAX_DTBOS; i++)
		kfree(dtbo_blobs[i].data);
}

module_init(gts9u_gunyah_identify_init);
module_exit(gts9u_gunyah_identify_exit);

MODULE_DESCRIPTION("Read-only Qualcomm Gunyah identity probe for the SM-X910");
MODULE_LICENSE("GPL");
