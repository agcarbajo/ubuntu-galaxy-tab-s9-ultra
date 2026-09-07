// SPDX-License-Identifier: GPL-2.0-only
#include <linux/module.h>
#include <linux/of.h>
static struct of_changeset changes;
static struct device_node *node;
static int __init intents_probe_init(void)
{
 const u32 values[] = {100, 64};
 int ret;
 if (!of_machine_is_compatible("samsung,gts9uwifi")) return -ENODEV;
 node = of_find_node_by_path("/soc@0/remoteproc@32300000/glink-edge/fastrpc");
 if (!node) return -ENODEV;
 of_changeset_init(&changes);
 ret = of_changeset_add_prop_u32_array(&changes, node, "qcom,intents", values, 2);
 if (!ret) ret = of_changeset_apply(&changes);
 if (ret) { of_changeset_destroy(&changes); of_node_put(node); }
 return ret;
}
static void __exit intents_probe_exit(void)
{
 of_changeset_revert(&changes); of_changeset_destroy(&changes); of_node_put(node);
}
module_init(intents_probe_init);
module_exit(intents_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("CDSP stock FastRPC intent pool diagnostic");
