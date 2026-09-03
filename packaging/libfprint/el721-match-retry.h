/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
/* Include after drivers_api.h. Hardware cleanup must precede notification. */
static inline void
el721_complete_match_retry (FpDevice *device, FpiDeviceAction action, GError *retry)
{
  if (action == FPI_DEVICE_ACTION_VERIFY)
    {
      fpi_device_verify_report (device, FPI_MATCH_ERROR, NULL, retry);
      fpi_device_verify_complete (device, NULL);
    }
  else if (action == FPI_DEVICE_ACTION_IDENTIFY)
    {
      fpi_device_identify_report (device, NULL, NULL, retry);
      fpi_device_identify_complete (device, NULL);
    }
  else
    g_assert_not_reached ();
}
