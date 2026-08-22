/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Enumerate and open/close the EL721 through libfprint, without a capture. */

#include <libfprint/fprint.h>

int
main (void)
{
  g_autoptr(FpContext) context = fp_context_new ();
  GPtrArray *devices = fp_context_get_devices (context);
  FpDevice *el721 = NULL;
  g_autoptr(GError) error = NULL;
  guint i;

  for (i = 0; i < devices->len; i++)
    {
      FpDevice *device = g_ptr_array_index (devices, i);
      g_print ("device[%u]: driver=%s name=%s id=%s\n", i,
               fp_device_get_driver (device), fp_device_get_device_id (device),
               fp_device_get_name (device));
      if (g_strcmp0 (fp_device_get_driver (device), "el721") == 0)
        el721 = device;
    }
  if (!el721)
    {
      g_printerr ("EL721 was not enumerated by libfprint\n");
      return 2;
    }
  if (!fp_device_open_sync (el721, NULL, &error))
    {
      g_printerr ("EL721 open failed: %s\n", error->message);
      return 3;
    }
  g_print ("EL721 opened through libfprint; features=0x%x\n",
           fp_device_get_features (el721));
  if (!fp_device_close_sync (el721, NULL, &error))
    {
      g_printerr ("EL721 close failed: %s\n", error->message);
      return 4;
    }
  g_print ("PASS: EL721 enumerated, prepared and closed through libfprint.\n");
  return 0;
}
