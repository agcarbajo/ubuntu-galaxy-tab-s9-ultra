// SPDX-License-Identifier: GPL-2.0-only
/* Read-only, one-shot snapshot of the board's existing Samsung LOGM ring. */
#include <linux/debugfs.h>
#include <linux/err.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_reserved_mem.h>
#include <linux/sizes.h>
#include <linux/string.h>
#include <linux/vmalloc.h>

static struct debugfs_blob_wrapper snapshot_blob;
static struct dentry *snapshot_file;
static struct debugfs_blob_wrapper reset_blob;
static struct dentry *reset_file;
static struct debugfs_blob_wrapper debug_pool_blob;
static struct dentry *debug_pool_file;

static int snapshot_region(struct device_node *node,
			   struct debugfs_blob_wrapper *blob,
			   struct dentry **file, const char *name)
{
	struct reserved_mem *reserved;
	void *mapping;

	reserved = of_reserved_mem_lookup(node);
	if (!reserved || reserved->size < 16 || reserved->size > SZ_4M)
		return -EINVAL;
	blob->data = vmalloc(reserved->size);
	if (!blob->data)
		return -ENOMEM;
	mapping = memremap(reserved->base, reserved->size, MEMREMAP_WB);
	if (!mapping) {
		vfree(blob->data);
		return -ENOMEM;
	}
	memcpy(blob->data, mapping, reserved->size);
	memunmap(mapping);
	blob->size = reserved->size;
	*file = debugfs_create_blob(name, 0400, NULL, blob);
	if (IS_ERR_OR_NULL(*file)) {
		vfree(blob->data);
		return *file ? PTR_ERR(*file) : -ENOMEM;
	}
	return 0;
}

static int __init gts9u_sec_log_snapshot_init(void)
{
	struct device_node *device_node, *memory_node, *reset_node;
	struct device_node *debug_pool_node;
	int ret;

	device_node = of_find_compatible_node(NULL, NULL,
				"samsung,gts9uwifi-sec-kernel-log");
	if (!device_node)
		return -ENODEV;
	memory_node = of_parse_phandle(device_node, "memory-region", 0);
	of_node_put(device_node);
	if (!memory_node)
		return -ENODEV;
	ret = snapshot_region(memory_node, &snapshot_blob, &snapshot_file,
			      "gts9u_sec_log_snapshot");
	of_node_put(memory_node);
	if (ret)
		return ret;
	reset_node = of_find_node_by_path(
		"/reserved-memory/sec-reset-info@8801ff000");
	if (!reset_node) {
		ret = -ENODEV;
		goto remove_log;
	}
	ret = snapshot_region(reset_node, &reset_blob, &reset_file,
			      "gts9u_reset_info_snapshot");
	of_node_put(reset_node);
	if (ret)
		goto remove_log;
	debug_pool_node = of_find_node_by_path(
		"/reserved-memory/sec-debug-pool@880100000");
	if (!debug_pool_node) {
		ret = -ENODEV;
		goto remove_reset;
	}
	ret = snapshot_region(debug_pool_node, &debug_pool_blob,
			      &debug_pool_file, "gts9u_debug_pool_snapshot");
	of_node_put(debug_pool_node);
	if (ret)
		goto remove_reset;
	pr_info("gts9u LOGM/reset/debug-pool snapshots: %zu/%zu/%zu bytes captured\n",
		(size_t)snapshot_blob.size, (size_t)reset_blob.size,
		(size_t)debug_pool_blob.size);
	return 0;

remove_reset:
	debugfs_remove(reset_file);
	vfree(reset_blob.data);
remove_log:
	debugfs_remove(snapshot_file);
	vfree(snapshot_blob.data);
	return ret;
}

static void __exit gts9u_sec_log_snapshot_exit(void)
{
	debugfs_remove(debug_pool_file);
	vfree(debug_pool_blob.data);
	debugfs_remove(snapshot_file);
	vfree(snapshot_blob.data);
	debugfs_remove(reset_file);
	vfree(reset_blob.data);
}

module_init(gts9u_sec_log_snapshot_init);
module_exit(gts9u_sec_log_snapshot_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only snapshot of gts9uwifi Samsung LOGM console");
