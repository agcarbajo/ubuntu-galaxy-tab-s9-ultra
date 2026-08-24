/* SPDX-License-Identifier: BSD-3-Clause */
/* Non-biometric open/prepare/close smoke test for the EL721 userspace bridge. */

#include "el721-qtee.h"

#include <glib.h>
#include <glib/gstdio.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#define OP_WAIT_INTERRUPT 4U
#define OP_NOTIFY_DOWN 5U
#define OP_CAPTURE_SUCCESS 6U
#define OP_CAPTURE_STEP 87U
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
  if (!g_getenv ("EL721_SKIP_POWER") &&
      !write_value (EL721_POWER, "1\n", &error))
    goto out;
  session = el721_qtee_open (argv[1], &error);
  if (!session)
    goto out;
  if (g_getenv ("EL721_AUTO_PADDR"))
    {
      g_autofree gchar *output = NULL;
      g_auto(GStrv) lines = NULL;

      if (g_spawn_command_line_sync
            ("sh -c \"dmesg | grep -o 'bridged object: paddr 0x[0-9a-f]*' "
             "| tail -2 | grep -o '0x[0-9a-f]*'\"",
             &output, NULL, NULL, &error))
        {
          lines = g_strsplit (g_strstrip (output), "\n", -1);
          if (lines[0] && lines[1])
            {
              g_setenv ("EL721_INPUT_PADDR", lines[0], TRUE);
              g_setenv ("EL721_OUTPUT_PADDR", lines[1], TRUE);
              g_print ("using raw buffers %s and %s\n", lines[0], lines[1]);
            }
        }
      g_clear_error (&error);
    }
  g_usleep (1000000);
  if (!g_getenv ("EL721_SKIP_PREPARE") && !el721_qtee_prepare (session, &error))
    goto out;
  g_print ("EL721 userspace transport: signed TA loaded and Prepare succeeded.\n");
  /* One ordered probe list, so a stock sequence can be replayed exactly:
   * "c84" a bare control, "c22=1" a control with one byte, "u49" a control
   * carrying the user identifier, "r2:376:12" a raw command. */
  if (g_getenv ("EL721_SEQ"))
    {
      g_auto(GStrv) steps = g_strsplit (g_getenv ("EL721_SEQ"), ",", -1);
      guint step;

      for (step = 0; steps[step]; step++)
        {
          const gchar *item = steps[step];

          if (item[0] == 'P')
            {
              g_print ("seq prepare\n");
              if (!el721_qtee_prepare (session, &error))
                goto out;
            }
          else if (item[0] == 'r')
            {
              g_auto(GStrv) parts = g_strsplit (item + 1, ":", 3);
              guint32 command = (guint32) g_ascii_strtoull (parts[0], NULL, 0);
              gsize in_size = (gsize) g_ascii_strtoull (parts[1], NULL, 0);
              gsize out_size = (gsize) g_ascii_strtoull (parts[2], NULL, 0);
              guint32 raw = 0;

              if (el721_qtee_raw_command (session, command, in_size, out_size,
                                          &raw, &error))
                g_print ("seq raw %u -> result=%u\n", command, raw);
              else
                {
                  g_print ("seq raw %u -> %s\n", command, error->message);
                  g_clear_error (&error);
                }
            }
          else if ((item[0] == 'u' || item[0] == 'b') && argc == 3)
            {
              g_auto(GStrv) fields = g_strsplit (item + 1, "=", 2);
              g_auto(GStrv) parts = g_strsplit (fields[0], "/", 2);
              guint32 operation = (guint32) g_ascii_strtoull (parts[0], NULL, 10);
              gsize capacity = parts[1] ?
                (gsize) g_ascii_strtoull (parts[1], NULL, 0) : 0;
              guint32 scalar = fields[1] ?
                (guint32) g_ascii_strtoull (fields[1], NULL, 0) : 0;

              g_print ("seq control %u with user%s\n", operation,
                       item[0] == 'b' ? " twice" : "");
              if (!el721_qtee_control_user (session, operation,
                                            (const guint8 *) argv[2],
                                            strlen (argv[2]),
                                            item[0] == 'b', scalar, capacity,
                                            &error))
                goto out;
            }
          else if (item[0] == 'k')
            {
              g_auto(GStrv) fields = g_strsplit (item + 1, "=", 2);
              g_auto(GStrv) parts = g_strsplit (fields[0], "/", 2);
              guint32 operation = (guint32) g_ascii_strtoull (parts[0], NULL, 10);
              gsize capacity = parts[1] ?
                (gsize) g_ascii_strtoull (parts[1], NULL, 0) : 0;
              guint32 scalar = fields[1] ?
                (guint32) g_ascii_strtoull (fields[1], NULL, 0) : 0;

              g_print ("seq control %u scalar %u\n", operation, scalar);
              if (!el721_qtee_control_scalar (session, operation, scalar,
                                              capacity, &error))
                goto out;
            }
          else if (item[0] == 'f')
            {
              g_auto(GStrv) fields = g_strsplit (item + 1, "=", 2);
              g_auto(GStrv) parts = g_strsplit (fields[0], "/", 2);
              guint32 operation = (guint32) g_ascii_strtoull (parts[0], NULL, 10);
              gsize capacity = parts[1] ?
                (gsize) g_ascii_strtoull (parts[1], NULL, 0) : 0;
              g_autofree gchar *blob = NULL;
              gsize blob_size = 0;

              if (!g_file_get_contents (fields[1], &blob, &blob_size, &error))
                goto out;
              g_print ("seq control %u with %" G_GSIZE_FORMAT " bytes from %s\n",
                       operation, blob_size, fields[1]);
              if (!el721_qtee_control_op (session, operation,
                                          (const guint8 *) blob, blob_size,
                                          capacity, &error))
                goto out;
            }
          else if (item[0] == 'p')
            {
              g_auto(GStrv) fields = g_strsplit (item + 1, "=", 2);
              guint32 operation = (guint32) g_ascii_strtoull (fields[0], NULL, 10);

              g_print ("seq control %u with payload %s\n", operation,
                       fields[1] ? fields[1] : "");
              if (!el721_qtee_control_bytes (session, operation,
                                             (const guint8 *) fields[1],
                                             fields[1] ? strlen (fields[1]) + 1 : 0,
                                             &error))
                goto out;
            }
          else if (item[0] == 'c')
            {
              g_auto(GStrv) fields = g_strsplit (item + 1, "=", 2);
              g_auto(GStrv) parts = g_strsplit (fields[0], "/", 2);
              guint32 operation = (guint32) g_ascii_strtoull (parts[0], NULL, 10);
              gsize capacity = parts[1] ?
                (gsize) g_ascii_strtoull (parts[1], NULL, 0) : 0;
              guint8 value = 0;
              gsize value_size = 0;

              if (fields[1])
                {
                  value = (guint8) g_ascii_strtoull (fields[1], NULL, 0);
                  value_size = sizeof (value);
                }
              g_print ("seq control %u\n", operation);
              if (!el721_qtee_control_op (session, operation, &value,
                                          value_size, capacity, &error))
                goto out;
            }
        }
    }
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
  if (g_getenv ("EL721_USER_OPS") && argc == 3)
    {
      g_auto(GStrv) ops = g_strsplit (g_getenv ("EL721_USER_OPS"), ",", -1);
      guint index;

      for (index = 0; ops[index]; index++)
        {
          guint32 operation = (guint32) g_ascii_strtoull (ops[index], NULL, 10);

          g_print ("probe control %u with user %s\n", operation, argv[2]);
          if (!el721_qtee_control_user (session, operation,
                                        (const guint8 *) argv[2],
                                        strlen (argv[2]), FALSE, 0, 0, &error))
            goto out;
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
                                      0, &error))
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
      /* EL721_ENROLL_DO=<n> runs the capture loop for at most n passes, which
       * is the only part of enrolment that needs a finger on the reader. */
      if (g_getenv ("EL721_ENROLL_DO"))
        {
          guint passes = (guint) g_ascii_strtoull (g_getenv ("EL721_ENROLL_DO"),
                                                   NULL, 10);
          guint pass;

          for (pass = 0; pass < passes; pass++)
            {
              el721_reply_clear (&reply);
              if (!el721_qtee_enroll_do (session, &reply, &error))
                goto out;
              g_print ("EnrollDo %u: result=%u status=%d opcode=%u "
                       "quality=%u progress=%u remaining=%u\n", pass + 1,
                       reply.result, (gint) reply.status, reply.opcode,
                       reply.quality, reply.progress, reply.remaining);
              /* The TA drives enrolment through the opcode it returns: it asks
               * to be called back once the reader has raised its interrupt, and
               * asks for two control operations around the capture itself. */
              if (reply.opcode == OP_WAIT_INTERRUPT)
                {
                  g_usleep (50 * 1000);
                  continue;
                }
              if (reply.opcode == OP_NOTIFY_DOWN)
                {
                  if (!el721_qtee_control_op (session, 87, NULL, 0, 0, &error) ||
                      !el721_qtee_control_op (session, 80, NULL, 0, 0, &error))
                    goto out;
                  continue;
                }
              if (reply.opcode == OP_CAPTURE_STEP)
                {
                  if (!el721_qtee_control_op (session, 87, NULL, 0, 0, &error))
                    goto out;
                  continue;
                }
              if (reply.opcode == OP_CAPTURE_SUCCESS)
                continue;
              if (reply.opcode == 0)
                break;
            }
          el721_reply_clear (&reply);
          if (!el721_qtee_enroll_final (session, &reply, &error))
            goto out;
          g_print ("EnrollFinal: result=%u status=%u template=%u bytes\n",
                   reply.result, reply.status,
                   reply.data ?
                   (guint) g_bytes_get_size (reply.data) : 0u);
          el721_reply_clear (&reply);
        }
      if (!el721_qtee_cancel (session, &reply, &error))
        goto out;
      g_print ("Cancel: result=%u status=%u opcode=%u\n",
               reply.result, reply.status, reply.opcode);
    }
  result = 0;

out:
  el721_reply_clear (&reply);
  el721_qtee_close (session);
  if (!g_getenv ("EL721_SKIP_POWER") &&
      !write_value (EL721_POWER, "0\n", error ? NULL : &error) && !error)
    g_set_error_literal (&error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
                         "cannot power the EL721 down");
  if (error)
    g_printerr ("EL721 userspace transport failed: %s\n", error->message);
  return error ? 1 : result;
}
