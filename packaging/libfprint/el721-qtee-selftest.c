/* SPDX-License-Identifier: BSD-3-Clause */
/* Non-biometric open/prepare/close smoke test for the EL721 userspace bridge. */

#include "el721-qtee.h"

#include <glib.h>
#include <glib/gstdio.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#define EL721_POWER "/sys/bus/platform/devices/egis-el721/sensor_power"

static gboolean
write_value (const gchar *path, const gchar *value, GError **error)
{
  FILE *stream = g_fopen (path, "w");
  if (!stream)
    {
      g_set_error (error, G_FILE_ERROR, g_file_error_from_errno (errno),
                   "cannot open %s: %s", path, g_strerror (errno));
      return FALSE;
    }
  if (fputs (value, stream) == EOF || fclose (stream))
    {
      g_set_error (error, G_FILE_ERROR, g_file_error_from_errno (errno),
                   "cannot write %s: %s", path, g_strerror (errno));
      return FALSE;
    }
  return TRUE;
}

int
main (int argc, char **argv)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(GBytes) group_key = NULL;
  El721Qtee *session = NULL;
  El721Reply reply = { 0 };
  int result = 1;

  if (argc < 2 || argc > 3)
    {
      g_printerr ("usage: %s FIRMWARE_DIRECTORY [ENROLL_USER]\n", argv[0]);
      return 64;
    }
  if (!write_value (EL721_POWER, "1\n", &error))
    goto out;
  session = el721_qtee_open (argv[1], &error);
  if (!session)
    goto out;
  g_usleep (1000000);
  if (!g_getenv ("EL721_SKIP_PREPARE") && !el721_qtee_prepare (session, &error))
    goto out;
  g_print ("EL721 userspace transport: signed TA loaded and Prepare succeeded.\n");
  if (g_getenv ("EL721_RAW"))
    {
      g_auto(GStrv) items = g_strsplit (g_getenv ("EL721_RAW"), ",", -1);
      guint item;

      for (item = 0; items[item]; item++)
        {
          g_auto(GStrv) parts = g_strsplit (items[item], ":", 3);
          guint32 command = (guint32) g_ascii_strtoull (parts[0], NULL, 0);
          gsize in_size = (gsize) g_ascii_strtoull (parts[1], NULL, 0);
          gsize out_size = (gsize) g_ascii_strtoull (parts[2], NULL, 0);
          guint32 raw = 0;

          if (el721_qtee_raw_command (session, command, in_size, out_size,
                                      &raw, &error))
            g_print ("raw %u in=%zu out=%zu -> result=%u\n", command,
                     in_size, out_size, raw);
          else
            {
              g_print ("raw %u in=%zu out=%zu -> %s\n", command, in_size,
                       out_size, error->message);
              g_clear_error (&error);
            }
        }
    }
  if (g_getenv ("EL721_EXTRA_OPS"))
    {
      g_auto(GStrv) ops = g_strsplit (g_getenv ("EL721_EXTRA_OPS"), ",", -1);
      guint index;

      for (index = 0; ops[index]; index++)
        {
          g_auto(GStrv) fields = g_strsplit (ops[index], "=", 2);
          guint32 operation = (guint32) g_ascii_strtoull (fields[0], NULL, 10);
          guint8 value = 0;
          gsize value_size = 0;

          if (fields[1])
            {
              value = (guint8) g_ascii_strtoull (fields[1], NULL, 0);
              value_size = sizeof (value);
            }

          g_print ("probe control %u\n", operation);
          if (!el721_qtee_control_op (session, operation, &value, value_size,
                                      &error))
            goto out;
        }
    }
  if (argc == 3)
    {
      if (g_getenv ("EL721_SKIP_GROUP"))
        {
          g_print ("Active group skipped by request\n");
        }
      else if (!el721_qtee_set_active_group (session,
                                             (const guint8 *) argv[2],
                                             strlen (argv[2]), NULL,
                                             &group_key, &error))
        {
          goto out;
        }
      else
        {
          g_print ("Active group user=%s: generated %zu wrapped bytes\n",
                   argv[2], g_bytes_get_size (group_key));
        }
      if (!el721_qtee_enroll_init (session, (const guint8 *) argv[2],
                                   strlen (argv[2]), 1, &reply, &error))
        goto out;
      g_print ("EnrollInit user=%s: result=%u status=%u opcode=%u\n",
               argv[2], reply.result, reply.status, reply.opcode);
      el721_reply_clear (&reply);
      if (!el721_qtee_cancel (session, &reply, &error))
        goto out;
      g_print ("Cancel: result=%u status=%u opcode=%u\n",
               reply.result, reply.status, reply.opcode);
    }
  result = 0;

out:
  el721_reply_clear (&reply);
  el721_qtee_close (session);
  if (!write_value (EL721_POWER, "0\n", error ? NULL : &error) && !error)
    g_set_error_literal (&error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
                         "cannot power the EL721 down");
  if (error)
    g_printerr ("EL721 userspace transport failed: %s\n", error->message);
  return error ? 1 : result;
}
