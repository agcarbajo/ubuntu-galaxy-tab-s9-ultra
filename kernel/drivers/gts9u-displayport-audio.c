// SPDX-License-Identifier: GPL-2.0-only
/* Supply the missing sound-card backend before OF platform population,
 * keeping the bootloader-facing DTB byte-identical to the accepted image. */
#include <linux/init.h>
#include <linux/of.h>
#include <linux/printk.h>
#include "gts9u-displayport-audio-overlay.h"

static int __init gts9u_displayport_audio_init(void)
{
	int id, ret;

	if (!of_machine_is_compatible("samsung,gts9uwifi"))
		return 0;
	ret = of_overlay_fdt_apply(gts9u_displayport_audio_overlay,
				  sizeof(gts9u_displayport_audio_overlay), &id, NULL);
	if (ret)
		pr_err("gts9u: DisplayPort audio overlay failed: %d\n", ret);
	return ret;
}
core_initcall(gts9u_displayport_audio_init);
