/* SPDX-License-Identifier: MIT
 *
 * libhardware_legacy.so replacement for the SPU daemons running under Ubuntu.
 *
 * spdaemon links libhardware_legacy only for the Android wake-lock API.  The
 * real library (even the VNDK 33 build) pulls in libbinder, libhidlbase and
 * the suspend HAL, none of which exist in this runtime, so the daemon cannot
 * even start with it.  The hand-built stub validated on 2026-09-01 exported
 * exactly acquire_wake_lock and release_wake_lock, both returning 0 and
 * importing nothing; this file reproduces it.  Ubuntu's own power management
 * decides when the tablet sleeps.
 */

int acquire_wake_lock(int lock, const char *id)
{
	(void)lock;
	(void)id;
	return 0;
}

int release_wake_lock(const char *id)
{
	(void)id;
	return 0;
}
