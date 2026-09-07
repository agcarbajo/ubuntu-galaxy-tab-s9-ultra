// SPDX-License-Identifier: GPL-2.0-only
/* Experimental CDSP enablement without changing the Samsung ABL input DTB. */
#include <linux/firmware.h>
#include <linux/module.h>
#include <linux/of_address.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>

static struct of_changeset cdsp_changes;

static int check_memory(struct device_node *np, int index,
			phys_addr_t start, resource_size_t size)
{
	struct device_node *mem = of_parse_phandle(np, "memory-region", index);
	struct resource res;
	int ret = -EINVAL;

	if (mem && of_property_read_bool(mem, "no-map") &&
	    !of_address_to_resource(mem, 0, &res) &&
	    res.start == start && resource_size(&res) == size)
		ret = 0;
	of_node_put(mem);
	return ret;
}

static int __init gts9u_cdsp_init(void)
{
	static const char * const firmware[] = {
		"qcom/sm8550/cdsp.mdt", "qcom/sm8550/cdsp_dtb.mdt",
	};
	struct device_node *np, *parent_np, *glink_np, *fastrpc_np;
	struct platform_device *parent, *pdev;
	const struct firmware *fw;
	int ret, i;

	if (!of_machine_is_compatible("samsung,gts9uwifi"))
		return -ENODEV;
	np = of_find_node_by_path("/soc@0/remoteproc@32300000");
	if (!np)
		return -ENODEV;
	ret = -EINVAL;
	if (!of_device_is_compatible(np, "qcom,sm8550-cdsp-pas") ||
	    check_memory(np, 0, 0x9c900000, 0x2000000) ||
	    check_memory(np, 1, 0x9e900000, 0x80000))
		goto put_node;
	ret = -EBUSY;
	if (of_device_is_available(np))
		goto put_node;
	pdev = of_find_device_by_node(np);
	if (pdev) {
		put_device(&pdev->dev);
		goto put_node;
	}
	parent_np = of_get_parent(np);
	parent = of_find_device_by_node(parent_np);
	of_node_put(parent_np);
	ret = -ENODEV;
	if (!parent)
		goto put_node;
	/* Fail before activating the PAS driver when either image is missing. */
	for (i = 0; i < ARRAY_SIZE(firmware); i++) {
		ret = request_firmware(&fw, firmware[i], &parent->dev);
		if (ret)
			goto put_parent;
		release_firmware(fw);
	}
	of_changeset_init(&cdsp_changes);
	glink_np = of_get_child_by_name(np, "glink-edge");
	fastrpc_np = glink_np ? of_get_child_by_name(glink_np, "fastrpc") : NULL;
	of_node_put(glink_np);
	if (!fastrpc_np) {
		ret = -ENODEV;
		goto destroy;
	}
	ret = of_changeset_add_prop_string_array(&cdsp_changes, np,
			"firmware-name", firmware, ARRAY_SIZE(firmware));
	if (!ret)
		ret = of_changeset_add_prop_bool(&cdsp_changes, np,
						 "qcom,early-glink");
	if (!ret)
		ret = of_changeset_add_prop_bool(&cdsp_changes, np,
						 "qcom,no-auto-boot");
	if (!ret)
		ret = of_changeset_add_prop_u32(&cdsp_changes, np,
					       "qcom,handover-delay-ms", 1000);
	if (!ret)
		ret = of_changeset_add_prop_u32(&cdsp_changes, fastrpc_np,
					       "qcom,early-tx-intent", 40);
	of_node_put(fastrpc_np);
	if (!ret)
		ret = of_changeset_update_prop_string(&cdsp_changes, np,
						     "status", "okay");
	if (ret)
		goto destroy;
	ret = of_changeset_apply(&cdsp_changes);
	if (ret)
		goto destroy;
	/* OF's platform notifier may already have instantiated the device. */
	pdev = of_find_device_by_node(np);
	if (pdev)
		put_device(&pdev->dev);
	else
		pdev = of_platform_device_create(np, NULL, &parent->dev);
	if (!pdev) {
		ret = of_changeset_revert(&cdsp_changes);
		if (ret) {
			/* Retain the module and changeset if rollback is impossible. */
			pr_err("gts9u-cdsp: rollback failed (%d); reboot required\n", ret);
			ret = 0;
			goto put_parent;
		}
		ret = -ENODEV;
		goto destroy;
	}
	pr_info("gts9u-cdsp: enabled CDSP; verify remoteproc and HTP separately\n");
	ret = 0;
	goto put_parent;
destroy:
	of_changeset_destroy(&cdsp_changes);
put_parent:
	put_device(&parent->dev);
put_node:
	of_node_put(np);
	return ret;
}

module_init(gts9u_cdsp_init);
/* Deliberately no module_exit: live DSP clients may hold DMA mappings.
 * Reboot restores the original disabled DT and is the supported rollback.
 * Never autoload this experimental module before physical validation.
 */
MODULE_DESCRIPTION("Samsung SM-X910 experimental runtime CDSP enablement");
MODULE_AUTHOR("Ubuntu gts9u contributors");
MODULE_LICENSE("GPL");
