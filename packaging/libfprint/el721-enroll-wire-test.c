/* SPDX-License-Identifier: BSD-3-Clause */
/* Synthetic protocol tests: no device, firmware or biometric data required. */
#include "el721-enroll-wire.h"

static void
put_word (guint8 *output, gsize offset, guint32 value)
{
  value = GUINT32_TO_LE (value);
  memcpy (output + offset, &value, sizeof (value));
}

static void
test_response (gconstpointer test_case)
{
  guint mode = GPOINTER_TO_UINT (test_case);
  g_autofree guint8 *output = g_malloc0 (EL721_ENROLL_OUTPUT_SIZE);
  g_autoptr(GError) error = NULL;
  El721Reply reply = { 0 };
  gsize wire_size = EL721_ENROLL_OUTPUT_SIZE;
  guint32 payload_size = 4;
  gboolean valid;

  put_word (output, 16, 100);
  put_word (output, 20, 17);
  put_word (output, 24, 2);
  memcpy (output + EL721_ENROLL_TEMPLATE_OFFSET, "test", 4);
  switch (mode)
    {
    case 1: payload_size = 0; break;
    case 2: payload_size = EL721_ENROLL_TEMPLATE_MAX; break;
    case 3: payload_size = EL721_ENROLL_TEMPLATE_MAX + 1; break;
    case 4: payload_size = G_MAXUINT32; break;
    case 5: wire_size--; break;
    case 6: put_word (output, 4, 71); break;
    case 7: put_word (output, 0, 6); break;
    case 8: put_word (output, 16, 99); break;
    case 9: wire_size++; break;
    case 10: g_clear_pointer (&output, g_free); break;
    default: break;
    }
  if (output)
    put_word (output, EL721_ENROLL_TEMPLATE_LENGTH_OFFSET, payload_size);
  /* A reused reply must not retain a template from an earlier transaction. */
  reply.data = g_bytes_new_static ("old", 3);
  valid = el721_decode_enroll_output (output, wire_size, &reply, &error);
  if (mode == 3 || mode == 4 || mode == 5 || mode == 9 || mode == 10)
    {
      g_assert_false (valid);
      g_assert_nonnull (error);
      g_assert_null (reply.data);
      return;
    }
  g_assert_true (valid);
  g_assert_no_error (error);
  g_assert_cmpuint (reply.remaining, ==, 17);
  g_assert_cmpuint (reply.progress, ==, 2);
  if (mode == 0 || mode == 2)
    {
      gsize size;
      const guint8 *bytes = g_bytes_get_data (reply.data, &size);
      g_assert_cmpuint (size, ==, payload_size);
      g_assert_cmpmem (bytes, 4, "test", 4);
      /* The next QTEE transaction overwrites its shared output buffer. */
      memset (output, 0, EL721_ENROLL_OUTPUT_SIZE);
      g_assert_cmpmem (bytes, 4, "test", 4);
    }
  else
    g_assert_null (reply.data);
  g_clear_pointer (&reply.data, g_bytes_unref);
}

int
main (int argc, char **argv)
{
  static const gchar *names[] = {
    "complete", "empty", "maximum", "oversize", "overflow", "truncated",
    "key-failure", "intermediate-opcode", "partial-coverage", "long", "null"
  };
  g_test_init (&argc, &argv, NULL);
  for (guint i = 0; i < G_N_ELEMENTS (names); i++)
    {
      g_autofree gchar *path = g_strdup_printf ("/el721/enroll/%s", names[i]);
      g_test_add_data_func (path, GUINT_TO_POINTER (i), test_response);
    }
  return g_test_run ();
}
