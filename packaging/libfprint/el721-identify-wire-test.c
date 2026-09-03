/* SPDX-License-Identifier: BSD-3-Clause */
/* Synthetic buffers only; no reader, firmware or biometric data. */
#include "el721-identify-wire.h"

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
  g_autofree guint8 *output = g_malloc0 (EL721_IDENTIFY_OUTPUT_SIZE);
  g_autoptr(GError) error = NULL;
  El721Reply reply = { 0 };
  gsize size = EL721_IDENTIFY_OUTPUT_SIZE;
  guint32 payload = 4;
  gboolean valid;
  put_word (output, 16, 91);
  put_word (output, 20, 3);
  memcpy (output + 0x38, "test", 4);
  switch (mode)
    {
    case 1: /* Exact pre-contact response: byte 12 is zero, not completion. */
      put_word (output, 0, 4);
      put_word (output, 8, G_MAXUINT32);
      put_word (output, 16, 0);
      put_word (output, 20, 0);
      payload = G_MAXUINT32;
      break;
    case 2: put_word (output, 20, 0); payload = G_MAXUINT32; break;
    case 3: put_word (output, 4, 39); payload = G_MAXUINT32; break;
    case 4: put_word (output, 4, 41); payload = G_MAXUINT32; break;
    case 5: put_word (output, 0, 87); payload = G_MAXUINT32; break;
    case 6: payload = 0; break;
    case 7: payload = 0x226000; break;
    case 8: payload = 0x226001; break;
    case 9: payload = G_MAXUINT32; break;
    case 10: size--; break;
    case 11: size++; break;
    case 12: g_clear_pointer (&output, g_free); break;
    case 13: put_word (output, 12, 4); break;
    default: break;
    }
  if (output)
    put_word (output, 0x226038, payload);
  reply.data = g_bytes_new_static ("old", 3);
  valid = el721_decode_identify_output (output, size, &reply, &error);
  if (mode >= 8 && mode <= 12)
    {
      g_assert_false (valid);
      g_assert_nonnull (error);
      g_assert_null (reply.data);
      return;
    }
  g_assert_true (valid);
  g_assert_no_error (error);
  g_assert_cmpuint (reply.opcode, ==, mode == 1 ? 4 : mode == 5 ? 87 : 0);
  g_assert_cmpuint (reply.result, ==, mode == 3 ? 39 : mode == 4 ? 41 : 0);
  g_assert_cmpuint (reply.template_id, ==, mode == 1 || mode == 2 ? 0 : 3);
  g_assert_cmpuint (reply.quality, ==, mode == 1 ? 0 : 91);
  if (mode == 1)
    g_assert_cmpuint (reply.status, ==, G_MAXUINT32);
  if (mode == 0 || mode == 7 || mode == 13)
    {
      gsize data_size;
      const guint8 *data = g_bytes_get_data (reply.data, &data_size);
      g_assert_cmpuint (data_size, ==, payload);
      memset (output, 0, EL721_IDENTIFY_OUTPUT_SIZE);
      g_assert_cmpmem (data, 4, "test", 4);
    }
  else
    g_assert_null (reply.data);
  g_clear_pointer (&reply.data, g_bytes_unref);
}

static void
test_contact (gconstpointer test_case)
{
  guint bits = GPOINTER_TO_UINT (test_case);
  gboolean armed = !!(bits & 1), edge = !!(bits & 2);
  gboolean pressed = !!(bits & 4), was_pressed = !!(bits & 8);
  g_assert_cmpint (el721_identify_contact_ready (armed ? 4 : 0, edge,
                                               pressed, was_pressed),
                   ==, bits == 7);
}

static void
test_rejection (gconstpointer test_case)
{
  guint mode = GPOINTER_TO_UINT (test_case);
  El721Reply reply = { .result = 32 };
  switch (mode)
    {
    case 1: reply.result = 0; break;
    case 2: reply.result = 31; break;
    case 3: reply.result = 39; break;
    case 4: reply.result = 41; break;
    case 5: reply.opcode = 4; break;
    case 6: reply.template_id = 3; break;
    case 7: reply.result = G_MAXUINT32; break;
    default: break;
    }
  g_assert_cmpint (el721_identify_is_no_match (&reply), ==, mode == 0);
}

int
main (int argc, char **argv)
{
  static const gchar *names[] = {
    "match-slot-not-score", "wait-regression", "no-match", "quality-retry",
    "movement-retry", "capture-step", "no-update", "maximum-update",
    "oversize", "overflow", "truncated", "long", "null", "aux-not-opcode"
  };
  g_test_init (&argc, &argv, NULL);
  for (guint i = 0; i < G_N_ELEMENTS (names); i++)
    {
      g_autofree gchar *path = g_strdup_printf ("/el721/identify/%s", names[i]);
      g_test_add_data_func (path, GUINT_TO_POINTER (i), test_response);
    }
  for (guint i = 0; i < 16; i++)
    {
      g_autofree gchar *path = g_strdup_printf ("/el721/contact/combination-%u", i);
      g_test_add_data_func (path, GUINT_TO_POINTER (i), test_contact);
    }
  for (guint i = 0; i < 8; i++)
    {
      g_autofree gchar *path = g_strdup_printf ("/el721/rejection/case-%u", i);
      g_test_add_data_func (path, GUINT_TO_POINTER (i), test_rejection);
    }
  return g_test_run ();
}
