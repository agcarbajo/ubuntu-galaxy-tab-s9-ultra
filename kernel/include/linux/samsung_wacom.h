/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _LINUX_SAMSUNG_WACOM_H
#define _LINUX_SAMSUNG_WACOM_H

#include <linux/kconfig.h>
#include <linux/types.h>

#if IS_REACHABLE(CONFIG_TOUCHSCREEN_SAMSUNG_WACOM_W90XX)
bool samsung_wacom_should_suppress_touch(void);
#else
static inline bool samsung_wacom_should_suppress_touch(void)
{
	return false;
}
#endif

#endif /* _LINUX_SAMSUNG_WACOM_H */
