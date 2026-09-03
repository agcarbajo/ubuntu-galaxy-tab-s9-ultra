// SPDX-License-Identifier: GPL-2.0
/*
 * DMA-BUF heap shared by HLOS and the Qualcomm Secure Processing SubSystem.
 *
 * Samsung's SPCom userspace allocates NVM buffers from qcom,sp-hlos and then
 * uses the downstream mem_buf driver to grant CP_SPSS_HLOS_SHARED access.  The
 * mainline kernel has neither that heap nor mem_buf.  Export the same small,
 * contiguous CMA allocations and perform the SCM ownership transition in the
 * heap, so the transition has exactly the same lifetime as the DMA-BUF.
 */

#define pr_fmt(fmt) "qcom_sp_hlos_heap: " fmt

#include <dt-bindings/firmware/qcom,scm.h>
#include <linux/cma.h>
#include <linux/dma-buf.h>
#include <linux/dma-heap.h>
#include <linux/dma-map-ops.h>
#include <linux/err.h>
#include <linux/firmware/qcom/qcom_scm.h>
#include <linux/highmem.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/scatterlist.h>
#include <linux/slab.h>
#include <linux/sizes.h>
#include <linux/vmalloc.h>

#define SP_HLOS_HEAP_NAME "qcom,sp-hlos"
#define SP_HLOS_HEAP_MAX_SIZE SZ_16M

struct sp_hlos_heap {
	struct dma_heap *heap;
	struct cma *cma;
};

struct sp_hlos_buffer {
	struct sp_hlos_heap *heap;
	struct list_head attachments;
	/* Serializes attachment state and kernel virtual mappings. */
	struct mutex lock;
	unsigned long len;
	struct page *cma_pages;
	struct page **pages;
	pgoff_t pagecount;
	int vmap_count;
	void *vaddr;
};

struct sp_hlos_attachment {
	struct device *dev;
	struct sg_table table;
	struct list_head node;
	bool mapped;
};

static int sp_hlos_attach(struct dma_buf *dmabuf,
			  struct dma_buf_attachment *attachment)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;
	struct sp_hlos_attachment *a;
	int ret;

	a = kzalloc_obj(*a);
	if (!a)
		return -ENOMEM;

	ret = sg_alloc_table_from_pages(&a->table, buffer->pages,
					buffer->pagecount, 0, buffer->len,
					GFP_KERNEL);
	if (ret) {
		kfree(a);
		return ret;
	}

	a->dev = attachment->dev;
	attachment->priv = a;
	mutex_lock(&buffer->lock);
	list_add(&a->node, &buffer->attachments);
	mutex_unlock(&buffer->lock);
	return 0;
}

static void sp_hlos_detach(struct dma_buf *dmabuf,
			   struct dma_buf_attachment *attachment)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;
	struct sp_hlos_attachment *a = attachment->priv;

	mutex_lock(&buffer->lock);
	list_del(&a->node);
	mutex_unlock(&buffer->lock);
	sg_free_table(&a->table);
	kfree(a);
}

static struct sg_table *
sp_hlos_map_dma_buf(struct dma_buf_attachment *attachment,
		    enum dma_data_direction direction)
{
	struct sp_hlos_attachment *a = attachment->priv;
	int ret;

	ret = dma_map_sgtable(attachment->dev, &a->table, direction, 0);
	if (ret)
		return ERR_PTR(ret);
	a->mapped = true;
	return &a->table;
}

static void sp_hlos_unmap_dma_buf(struct dma_buf_attachment *attachment,
				  struct sg_table *table,
				  enum dma_data_direction direction)
{
	struct sp_hlos_attachment *a = attachment->priv;

	a->mapped = false;
	dma_unmap_sgtable(attachment->dev, table, direction, 0);
}

static int sp_hlos_begin_cpu_access(struct dma_buf *dmabuf,
				    enum dma_data_direction direction)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;
	struct sp_hlos_attachment *a;

	mutex_lock(&buffer->lock);
	if (buffer->vmap_count)
		invalidate_kernel_vmap_range(buffer->vaddr, buffer->len);
	list_for_each_entry(a, &buffer->attachments, node) {
		if (a->mapped)
			dma_sync_sgtable_for_cpu(a->dev, &a->table, direction);
	}
	mutex_unlock(&buffer->lock);
	return 0;
}

static int sp_hlos_end_cpu_access(struct dma_buf *dmabuf,
				  enum dma_data_direction direction)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;
	struct sp_hlos_attachment *a;

	mutex_lock(&buffer->lock);
	if (buffer->vmap_count)
		flush_kernel_vmap_range(buffer->vaddr, buffer->len);
	list_for_each_entry(a, &buffer->attachments, node) {
		if (a->mapped)
			dma_sync_sgtable_for_device(a->dev, &a->table, direction);
	}
	mutex_unlock(&buffer->lock);
	return 0;
}

static vm_fault_t sp_hlos_vm_fault(struct vm_fault *vmf)
{
	struct sp_hlos_buffer *buffer = vmf->vma->vm_private_data;

	if (vmf->pgoff >= buffer->pagecount)
		return VM_FAULT_SIGBUS;
	return vmf_insert_pfn(vmf->vma, vmf->address,
			      page_to_pfn(buffer->pages[vmf->pgoff]));
}

static const struct vm_operations_struct sp_hlos_vm_ops = {
	.fault = sp_hlos_vm_fault,
};

static int sp_hlos_mmap(struct dma_buf *dmabuf, struct vm_area_struct *vma)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;

	if (!(vma->vm_flags & (VM_SHARED | VM_MAYSHARE)))
		return -EINVAL;
	vm_flags_set(vma, VM_IO | VM_PFNMAP | VM_DONTEXPAND | VM_DONTDUMP);
	vma->vm_ops = &sp_hlos_vm_ops;
	vma->vm_private_data = buffer;
	return 0;
}

static int sp_hlos_vmap(struct dma_buf *dmabuf, struct iosys_map *map)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;
	void *vaddr;
	int ret = 0;

	mutex_lock(&buffer->lock);
	if (buffer->vmap_count) {
		buffer->vmap_count++;
		iosys_map_set_vaddr(map, buffer->vaddr);
		goto out;
	}
	vaddr = vmap(buffer->pages, buffer->pagecount, VM_MAP, PAGE_KERNEL);
	if (!vaddr) {
		ret = -ENOMEM;
		goto out;
	}
	buffer->vaddr = vaddr;
	buffer->vmap_count = 1;
	iosys_map_set_vaddr(map, vaddr);
out:
	mutex_unlock(&buffer->lock);
	return ret;
}

static void sp_hlos_vunmap(struct dma_buf *dmabuf, struct iosys_map *map)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;

	mutex_lock(&buffer->lock);
	if (!--buffer->vmap_count) {
		vunmap(buffer->vaddr);
		buffer->vaddr = NULL;
	}
	mutex_unlock(&buffer->lock);
	iosys_map_clear(map);
}

static void sp_hlos_release(struct dma_buf *dmabuf)
{
	struct sp_hlos_buffer *buffer = dmabuf->priv;
	struct qcom_scm_vmperm hlos = {
		.vmid = QCOM_SCM_VMID_HLOS,
		.perm = QCOM_SCM_PERM_RW,
	};
	u64 owners = BIT_ULL(QCOM_SCM_VMID_HLOS) |
		     BIT_ULL(QCOM_SCM_VMID_CP_SPSS_HLOS_SHARED);
	int ret;

	if (buffer->vmap_count) {
		WARN(1, "buffer still mapped in the kernel\n");
		vunmap(buffer->vaddr);
	}

	ret = qcom_scm_assign_mem(page_to_phys(buffer->cma_pages), buffer->len,
				  &owners, &hlos, 1);
	if (ret) {
		/* Never return memory still visible to SPSS to the general CMA pool. */
		pr_err("failed to reclaim %lu bytes at %pa: %d; quarantining pages\n",
		       buffer->len, &(phys_addr_t) {
			       page_to_phys(buffer->cma_pages) }, ret);
	} else {
		cma_release(buffer->heap->cma, buffer->cma_pages,
			    buffer->pagecount);
	}
	kfree(buffer->pages);
	kfree(buffer);
}

static const struct dma_buf_ops sp_hlos_buf_ops = {
	.attach = sp_hlos_attach,
	.detach = sp_hlos_detach,
	.map_dma_buf = sp_hlos_map_dma_buf,
	.unmap_dma_buf = sp_hlos_unmap_dma_buf,
	.begin_cpu_access = sp_hlos_begin_cpu_access,
	.end_cpu_access = sp_hlos_end_cpu_access,
	.mmap = sp_hlos_mmap,
	.vmap = sp_hlos_vmap,
	.vunmap = sp_hlos_vunmap,
	.release = sp_hlos_release,
};

static struct dma_buf *sp_hlos_allocate(struct dma_heap *heap,
					unsigned long len, u32 fd_flags,
					u64 heap_flags)
{
	struct sp_hlos_heap *sp_heap = dma_heap_get_drvdata(heap);
	struct qcom_scm_vmperm destinations[] = {
		{
			.vmid = QCOM_SCM_VMID_HLOS,
			.perm = QCOM_SCM_PERM_RW,
		},
		{
			.vmid = QCOM_SCM_VMID_CP_SPSS_HLOS_SHARED,
			.perm = QCOM_SCM_PERM_RW,
		},
	};
	struct sp_hlos_buffer *buffer;
	DEFINE_DMA_BUF_EXPORT_INFO(exp_info);
	unsigned long size = PAGE_ALIGN(len);
	pgoff_t pagecount = size >> PAGE_SHIFT;
	unsigned int align = min_t(unsigned int, get_order(size),
				   CONFIG_CMA_ALIGNMENT);
	struct page *cma_pages;
	struct dma_buf *dmabuf;
	u64 owners = BIT_ULL(QCOM_SCM_VMID_HLOS);
	pgoff_t page;
	int ret;

	if (!len || len > SP_HLOS_HEAP_MAX_SIZE || heap_flags)
		return ERR_PTR(-EINVAL);
	buffer = kzalloc_obj(*buffer);
	if (!buffer)
		return ERR_PTR(-ENOMEM);

	cma_pages = cma_alloc(sp_heap->cma, pagecount, align, false);
	if (!cma_pages) {
		ret = -ENOMEM;
		goto free_buffer;
	}
	if (PageHighMem(cma_pages)) {
		for (page = 0; page < pagecount; page++)
			clear_highpage(cma_pages + page);
	} else {
		clear_pages(page_address(cma_pages), pagecount);
	}

	buffer->pages = kmalloc_objs(*buffer->pages, pagecount);
	if (!buffer->pages) {
		ret = -ENOMEM;
		goto free_cma;
	}
	for (page = 0; page < pagecount; page++)
		buffer->pages[page] = cma_pages + page;

	ret = qcom_scm_assign_mem(page_to_phys(cma_pages), size, &owners,
				  destinations, ARRAY_SIZE(destinations));
	if (ret) {
		pr_err("failed to share %lu-byte allocation with SPSS: %d\n",
		       size, ret);
		goto free_pages;
	}

	buffer->heap = sp_heap;
	buffer->len = size;
	buffer->cma_pages = cma_pages;
	buffer->pagecount = pagecount;
	INIT_LIST_HEAD(&buffer->attachments);
	mutex_init(&buffer->lock);

	exp_info.exp_name = dma_heap_get_name(heap);
	exp_info.ops = &sp_hlos_buf_ops;
	exp_info.size = size;
	exp_info.flags = fd_flags;
	exp_info.priv = buffer;
	dmabuf = dma_buf_export(&exp_info);
	if (IS_ERR(dmabuf)) {
		struct qcom_scm_vmperm hlos = {
			.vmid = QCOM_SCM_VMID_HLOS,
			.perm = QCOM_SCM_PERM_RW,
		};

		ret = PTR_ERR(dmabuf);
		if (qcom_scm_assign_mem(page_to_phys(cma_pages), size, &owners,
					&hlos, 1)) {
			pr_err("export failed and allocation could not be reclaimed; quarantining pages\n");
			goto free_pages_only;
		}
		goto free_pages;
	}
	return dmabuf;

free_pages:
	kfree(buffer->pages);
free_cma:
	cma_release(sp_heap->cma, cma_pages, pagecount);
free_buffer:
	kfree(buffer);
	return ERR_PTR(ret);

free_pages_only:
	kfree(buffer->pages);
	kfree(buffer);
	return ERR_PTR(ret);
}

static const struct dma_heap_ops sp_hlos_heap_ops = {
	.allocate = sp_hlos_allocate,
};

static int __init sp_hlos_heap_init(void)
{
	static struct sp_hlos_heap sp_heap;
	struct dma_heap_export_info info = {
		.name = SP_HLOS_HEAP_NAME,
		.ops = &sp_hlos_heap_ops,
		.priv = &sp_heap,
	};

	if (!qcom_scm_is_available())
		return -EPROBE_DEFER;
	sp_heap.cma = dev_get_cma_area(NULL);
	if (!sp_heap.cma) {
		pr_err("default CMA area is unavailable\n");
		return -ENODEV;
	}
	sp_heap.heap = dma_heap_add(&info);
	if (IS_ERR(sp_heap.heap))
		return PTR_ERR(sp_heap.heap);
	pr_info("registered %s from default CMA\n", SP_HLOS_HEAP_NAME);
	return 0;
}
module_init(sp_hlos_heap_init);

MODULE_DESCRIPTION("Qualcomm HLOS/SPSS shared DMA-BUF heap");
MODULE_LICENSE("GPL");
MODULE_IMPORT_NS("DMA_BUF");
MODULE_IMPORT_NS("DMA_BUF_HEAP");
