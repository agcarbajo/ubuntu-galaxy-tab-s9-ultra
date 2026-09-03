/* SPDX-License-Identifier: BSD-3-Clause */
/* Stub the notification API to exercise the production retry dispatcher. */
#include <glib.h>
typedef enum { FPI_DEVICE_ACTION_VERIFY, FPI_DEVICE_ACTION_IDENTIFY } FpiDeviceAction;
typedef enum { FPI_MATCH_ERROR } FpiMatchResult;
typedef struct { guint reports; guint completions; GError *retry; } FpDevice;

static void
fpi_device_verify_report (FpDevice *device, FpiMatchResult result, void *print,
                          GError *retry)
{
  g_assert_cmpint (result, ==, FPI_MATCH_ERROR);
  g_assert_null (print);
  g_assert_nonnull (retry);
  g_assert_cmpuint (device->reports++, ==, 0);
  g_assert_cmpuint (device->completions, ==, 0);
  device->retry = retry;
}
static void
fpi_device_verify_complete (FpDevice *device, GError *error)
{
  g_assert_null (error);
  g_assert_cmpuint (device->reports, ==, 1);
  g_assert_cmpuint (device->completions++, ==, 0);
}
static void
fpi_device_identify_report (FpDevice *device, void *match, void *print, GError *retry)
{
  g_assert_null (match);
  fpi_device_verify_report (device, FPI_MATCH_ERROR, print, retry);
}
static void
fpi_device_identify_complete (FpDevice *device, GError *error)
{
  fpi_device_verify_complete (device, error);
}
#include "el721-match-retry.h"

static void
test_retry (gconstpointer data)
{
  FpiDeviceAction action = GPOINTER_TO_UINT (data);
  for (guint i = 0; i < 5; i++)
    {
      FpDevice device = { 0 };
      GError *retry = g_error_new_literal (g_quark_from_static_string ("retry"),
                                         1, "synthetic quality retry");
      el721_complete_match_retry (&device, action, retry);
      g_assert_true (device.retry == retry);
      g_assert_cmpuint (device.reports, ==, 1);
      g_assert_cmpuint (device.completions, ==, 1);
      g_clear_error (&device.retry);
    }
}
int
main (int argc, char **argv)
{
  g_test_init (&argc, &argv, NULL);
  g_test_add_data_func ("/retry/verify-five-actions", GUINT_TO_POINTER (FPI_DEVICE_ACTION_VERIFY), test_retry);
  g_test_add_data_func ("/retry/identify-five-actions", GUINT_TO_POINTER (FPI_DEVICE_ACTION_IDENTIFY), test_retry);
  return g_test_run ();
}
