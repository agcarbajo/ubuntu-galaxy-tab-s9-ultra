// SPDX-License-Identifier: GPL-2.0-only
/*
 * Read-only reader for the Qualcomm TrustZone diagnostic log on the SM-X910.
 *
 * The secure world keeps a ring buffer of its own log; downstream ships this
 * driver as "tzdbg" and mainline has no equivalent, which left the fingerprint
 * work blind.  The EL721 TA records the exact reason its SPI setup fails
 * ("qsee_tlmm_get_gpio_id: BLSP_CLK Failed", "sec_tzspi_open failed : %d",
 * "gpio control tz_open error : %d") and nothing on this system could read it.
 *
 * Two routes exist, and which one applies was settled on the device:
 *
 *   - The stock device tree describes tz-log@146AA720, reg <0x146aa720 0x3000>.
 *     That window is readable, but it is an IMEM pointer area, not the table:
 *     its first quadword is 0x14696000, and mapping *that* resets the tablet
 *     because it is secure memory.
 *   - So the log has to be requested: SIP service 6, command 2 asks TZ to copy
 *     its diagnostic table into a non-secure buffer we supply.  That is the
 *     default here; base=/size= plus scm=0 still allow inspecting the window.
 *
 * The module never writes to secure memory and never asks TZ to do anything
 * but copy out its own log.
 */

#include <linux/arm-smccc.h>
#include <linux/debugfs.h>
#include <linux/fs.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/seq_file.h>
#include <linux/slab.h>
#include <linux/types.h>

#define TZLOG_IMEM_BASE 0x146aa720UL
#define TZLOG_DEFAULT_SIZE 0x3000U
#define TZLOG_DIAG_MAGIC 0x747a6461U /* "tzda" */

/* SIP owner, "misc information" service, get-diagnostics command. */
#define TZLOG_SMC_OWNER_SIP 2
#define TZLOG_SMC_SVC_INFO 6
#define TZLOG_SMC_CMD_DIAG 2
/* Two arguments: a read/write buffer (type 2) then a plain value (type 0). */
#define TZLOG_SMC_ARGINFO 0x22

static bool scm = true;
module_param(scm, bool, 0444);
MODULE_PARM_DESC(scm, "ask TrustZone to copy its log out (default) instead of mapping a window");

/*
 * The diagnostic call is not described in any header shipped with this device,
 * so its command number and argument shape have to be established against the
 * firmware itself.  Keeping them as parameters makes that an insmod away
 * instead of a rebuild.  Everything stays inside the SIP information service.
 */
static unsigned int smc_cmd = TZLOG_SMC_CMD_DIAG;
module_param(smc_cmd, uint, 0444);
MODULE_PARM_DESC(smc_cmd, "command number within the SIP information service");

static unsigned int smc_arginfo = TZLOG_SMC_ARGINFO;
module_param(smc_arginfo, uint, 0444);
MODULE_PARM_DESC(smc_arginfo, "Qualcomm argument descriptor for the call");

static unsigned long smc_arg0 = ~0UL;
module_param(smc_arg0, ulong, 0444);
MODULE_PARM_DESC(smc_arg0, "first argument; the buffer's physical address when left unset");

static unsigned long smc_arg1 = ~0UL;
module_param(smc_arg1, ulong, 0444);
MODULE_PARM_DESC(smc_arg1, "second argument; the buffer size when left unset");

static unsigned long base = TZLOG_IMEM_BASE;
module_param(base, ulong, 0444);
MODULE_PARM_DESC(base, "physical address to map when scm=0");

static unsigned int size = TZLOG_DEFAULT_SIZE;
module_param(size, uint, 0444);
MODULE_PARM_DESC(size, "size of the diagnostic buffer");

/*
 * Only the leading fields are needed to find the ring; the tail of the
 * structure differs between diag versions and is deliberately not decoded.
 */
struct tzdbg_header {
	u32 magic_num;
	u32 version;
	u32 cpu_count;
	u32 vmid_info_off;
	u32 boot_info_off;
	u32 reset_info_off;
	u32 int_info_off;
	u32 ring_off;
	u32 ring_len;
	u32 wakeup_info_off;
};

struct tzdbg_log_pos {
	u32 wrap;
	u32 offset;
};

static void __iomem *tzlog_map;
static char *tzlog_buf;
static struct dentry *tzlog_dir;
static long tzlog_last_result;

/* Refresh the copy TZ gives us; a snapshot is all a ring read can ever be. */
static int tzlog_fetch(void)
{
	struct arm_smccc_res res;
	u32 fn;

	if (!scm)
		return 0;

	fn = ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, ARM_SMCCC_SMC_64,
				TZLOG_SMC_OWNER_SIP,
				(TZLOG_SMC_SVC_INFO << 8) | smc_cmd);
	arm_smccc_smc(fn, smc_arginfo,
		      smc_arg0 == ~0UL ? virt_to_phys(tzlog_buf) : smc_arg0,
		      smc_arg1 == ~0UL ? size : smc_arg1,
		      0, 0, 0, 0, &res);
	tzlog_last_result = (long)res.a0;
	if (res.a0) {
		pr_warn_once("gts9u-tzlog: cmd %u arginfo %#x returned %ld (a1=%#lx a2=%#lx)\n",
			     smc_cmd, smc_arginfo, tzlog_last_result,
			     res.a1, res.a2);
		return -EIO;
	}
	pr_info("gts9u-tzlog: cmd %u arginfo %#x succeeded (a1=%#lx a2=%#lx)\n",
		smc_cmd, smc_arginfo, res.a1, res.a2);
	return 0;
}

static void tzlog_snapshot(void *dst)
{
	if (scm)
		memcpy(dst, tzlog_buf, size);
	else
		memcpy_fromio(dst, tzlog_map, size);
}

static int tzlog_read_header(struct tzdbg_header *header)
{
	if (scm) {
		int ret = tzlog_fetch();

		if (ret)
			return ret;
		memcpy(header, tzlog_buf, sizeof(*header));
	} else {
		memcpy_fromio(header, tzlog_map, sizeof(*header));
	}

	if (header->magic_num != TZLOG_DIAG_MAGIC)
		pr_warn_once("gts9u-tzlog: unexpected magic %08x\n",
			     header->magic_num);
	if (!header->ring_len || header->ring_off < sizeof(struct tzdbg_log_pos) ||
	    header->ring_off > size || header->ring_len > size - header->ring_off)
		return -EINVAL;
	return 0;
}

static int tzlog_log_open(struct inode *inode, struct file *file)
{
	struct tzdbg_header header;
	struct tzdbg_log_pos pos;
	size_t produced;
	char *snapshot;
	char *text;
	int ret;

	ret = tzlog_read_header(&header);
	if (ret)
		return ret;

	snapshot = kmalloc(size, GFP_KERNEL);
	if (!snapshot)
		return -ENOMEM;
	tzlog_snapshot(snapshot);

	memcpy(&pos, snapshot + header.ring_off - sizeof(pos), sizeof(pos));
	if (pos.offset > header.ring_len) {
		kfree(snapshot);
		return -EINVAL;
	}

	text = kmalloc(header.ring_len + 1, GFP_KERNEL);
	if (!text) {
		kfree(snapshot);
		return -ENOMEM;
	}
	if (pos.wrap) {
		size_t tail = header.ring_len - pos.offset;

		memcpy(text, snapshot + header.ring_off + pos.offset, tail);
		memcpy(text + tail, snapshot + header.ring_off, pos.offset);
		produced = header.ring_len;
	} else {
		memcpy(text, snapshot + header.ring_off, pos.offset);
		produced = pos.offset;
	}
	text[produced] = '\0';
	kfree(snapshot);

	file->private_data = text;
	return 0;
}

static ssize_t tzlog_log_read(struct file *file, char __user *buf, size_t count,
			      loff_t *ppos)
{
	const char *text = file->private_data;

	return simple_read_from_buffer(buf, count, ppos, text, strlen(text));
}

static int tzlog_log_release(struct inode *inode, struct file *file)
{
	kfree(file->private_data);
	return 0;
}

static const struct file_operations tzlog_log_fops = {
	.owner = THIS_MODULE,
	.open = tzlog_log_open,
	.read = tzlog_log_read,
	.release = tzlog_log_release,
	.llseek = default_llseek,
};

/*
 * Copy only the window actually asked for, in aligned 32-bit reads when this is
 * a mapping.  A blind memcpy_fromio() over the whole IMEM window faulted.
 */
static ssize_t tzlog_raw_read(struct file *file, char __user *buf, size_t count,
			      loff_t *ppos)
{
	size_t offset = (size_t)*ppos & ~3UL;
	u32 *copy;
	size_t words;
	ssize_t ret;
	size_t i;

	if (offset >= size)
		return 0;
	if (scm && tzlog_fetch())
		return -EIO;
	count = min(count, (size_t)(size - offset));
	words = (count + 3) / 4;
	copy = kmalloc_array(words, sizeof(*copy), GFP_KERNEL);
	if (!copy)
		return -ENOMEM;
	if (scm)
		memcpy(copy, tzlog_buf + offset, words * 4);
	else
		for (i = 0; i < words; i++)
			copy[i] = readl(tzlog_map + offset + i * 4);

	if (copy_to_user(buf, copy, count)) {
		ret = -EFAULT;
	} else {
		*ppos = offset + count;
		ret = count;
	}
	kfree(copy);
	return ret;
}

static const struct file_operations tzlog_raw_fops = {
	.owner = THIS_MODULE,
	.read = tzlog_raw_read,
	.llseek = default_llseek,
};

static int tzlog_info_show(struct seq_file *s, void *unused)
{
	struct tzdbg_header header;
	struct tzdbg_log_pos pos;
	char *snapshot;
	int ret;

	seq_printf(s, "mode        %s\n", scm ? "scm" : "map");
	ret = tzlog_read_header(&header);
	seq_printf(s, "diag_call   %ld\n", tzlog_last_result);
	if (ret) {
		seq_printf(s, "header      unusable (%d)\n", ret);
		return 0;
	}

	snapshot = kmalloc(size, GFP_KERNEL);
	if (!snapshot)
		return -ENOMEM;
	tzlog_snapshot(snapshot);
	memcpy(&pos, snapshot + header.ring_off - sizeof(pos), sizeof(pos));
	kfree(snapshot);

	seq_printf(s, "magic       %08x\n", header.magic_num);
	seq_printf(s, "version     %u.%u\n", header.version >> 16,
		   header.version & 0xffff);
	seq_printf(s, "cpu_count   %u\n", header.cpu_count);
	seq_printf(s, "ring_off    %u\n", header.ring_off);
	seq_printf(s, "ring_len    %u\n", header.ring_len);
	seq_printf(s, "ring_wrap   %u\n", pos.wrap);
	seq_printf(s, "ring_offset %u\n", pos.offset);
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(tzlog_info);

static int __init tzlog_init(void)
{
	struct tzdbg_header header;
	int ret;

	if (!size || size > SZ_1M)
		return -EINVAL;

	if (scm) {
		tzlog_buf = kzalloc(size, GFP_KERNEL);
		if (!tzlog_buf)
			return -ENOMEM;
	} else {
		tzlog_map = ioremap(base, size);
		if (!tzlog_map) {
			pr_err("gts9u-tzlog: cannot map %#lx+%#x\n", base, size);
			return -ENOMEM;
		}
	}

	ret = tzlog_read_header(&header);
	if (!ret)
		pr_info("gts9u-tzlog: diag v%u.%u, ring %u bytes at +%u\n",
			header.version >> 16, header.version & 0xffff,
			header.ring_len, header.ring_off);
	else
		pr_info("gts9u-tzlog: header not usable (%d, diag call %ld); raw dump only\n",
			ret, tzlog_last_result);

	tzlog_dir = debugfs_create_dir("gts9u_tzlog", NULL);
	debugfs_create_file("log", 0400, tzlog_dir, NULL, &tzlog_log_fops);
	debugfs_create_file("info", 0400, tzlog_dir, NULL, &tzlog_info_fops);
	debugfs_create_file("raw", 0400, tzlog_dir, NULL, &tzlog_raw_fops);
	return 0;
}

static void __exit tzlog_exit(void)
{
	debugfs_remove_recursive(tzlog_dir);
	if (tzlog_map)
		iounmap(tzlog_map);
	kfree(tzlog_buf);
}

module_init(tzlog_init);
module_exit(tzlog_exit);

MODULE_DESCRIPTION("Read-only Qualcomm TrustZone diagnostic log reader for the SM-X910");
MODULE_AUTHOR("Ubuntu Galaxy Tab S9 Ultra port contributors");
MODULE_LICENSE("GPL");
