/* SPDX-License-Identifier: BSD-3-Clause */
/* Synthetic only: never opens the sensor or any secure service. */
#include "el721-hwvault-wire.h"

static void
word (guint8 *buffer, gsize offset, guint32 value)
{
  value = GUINT32_TO_LE (value);
  memcpy (buffer + offset, &value, 4);
}

static void
bytes (guint8 *buffer, gsize *offset, guint32 tag,
        const gchar *data, gsize length)
{
  word (buffer, *offset, tag);
  word (buffer, *offset + 4, length);
  memcpy (buffer + *offset + 8, data, length);
  *offset += 8 + length;
}

static void
test_restore (gconstpointer data)
{
  guint mode = GPOINTER_TO_UINT (data);
  g_autofree guint8 *buffer = g_malloc0 (EL721_HWVAULT_WIRE_SIZE);
  g_autoptr(GError) error = NULL;
  const gchar *cache = "hwvault [INF] (set_cached_cred:350) set_cached_cred id=11, persistent=0, ret=0";
  gsize offset = 8, credential_size = 999;
  gsize output_size = EL721_HWVAULT_WIRE_SIZE;
  gboolean success;

  if (mode == 1)
    cache = "hwvault [INF] (set_cached_cred:350) set_cached_cred id=0, persistent=1, ret=0\n";
  else if (mode == 2)
    cache = "hwvault [INF] (set_cached_cred:350) set_cached_cred id=11, persistent=0, ret=9936";
  else if (mode == 5)
    cache = "set_cached_cred id=1, persistent=0, ret=0";
  else if (mode == 6)
    cache = "set_cached_cred id=11, persistent=1, ret=0";
  else if (mode == 11)
    cache = "set_cached_cred id=11, persistent=0, ret=-1";
  else if (mode == 12)
    cache = "set_cached_cred id=11, persistent=0, ret=4294967296";
  else if (mode == 17)
    cache = "set_cached_cred id=11, persistent=0, ret=0oops";

  word (buffer, offset, 0x01000001);
  word (buffer, offset + 4, mode == 3 ? 17 : 0);
  offset += 8;
  if (mode == 7)
    {
      word (buffer, offset, 0x01000001);
      offset += 8;
    }
  if (mode != 14)
    bytes (buffer, &offset, 0x02010006, "synthetic", 9);
  if (mode != 4)
    bytes (buffer, &offset, 0x02002710, cache, strlen (cache) + (mode != 16));
  if (mode == 13)
    bytes (buffer, &offset, 0x02002710, cache, strlen (cache));
  if (mode == 15)
    {
      word (buffer, offset, 0x03000000);
      offset += 8;
    }
  if (mode == 19)
    bytes (buffer, &offset, 0x02002710, "a\0b", 3);
  if (mode == 20)
    bytes (buffer, &offset, 0x02010006, "duplicate", 9);
  word (buffer, 4, offset - 8);
  if (mode == 8)
    word (buffer, 4, offset - 9);
  if (mode == 9)
    word (buffer, 4, G_MAXUINT32);
  if (mode == 10)
    g_clear_pointer (&buffer, g_free);
  if (mode == 18)
    output_size--;

  success = el721_decode_hwvault_restore (buffer, output_size,
                                          mode == 1 ? 0 : 11, mode == 1,
                                          &credential_size, &error);
  if (mode == 0 || mode == 1 || mode == 16)
    {
      g_assert_true (success);
      g_assert_no_error (error);
      g_assert_cmpuint (credential_size, ==, 9);
    }
  else
    {
      g_assert_false (success);
      g_assert_nonnull (error);
      g_assert_cmpuint (credential_size, ==, 0);
      if (mode == 2)
        g_assert_nonnull (strstr (error->message, "9936"));
    }
}

int
main (int argc, char **argv)
{
  static const gchar *names[] = {
    "ordinary", "persistent", "hidden-cache-failure", "outer-failure",
    "missing-cache", "wrong-index", "wrong-namespace", "duplicate-status",
    "truncated-tlv", "oversize", "null", "negative", "integer-overflow",
    "duplicate-cache", "missing-credential", "unknown-type", "no-nul",
    "trailing-garbage", "short-response", "embedded-nul", "duplicate-credential"
  };
  g_test_init (&argc, &argv, NULL);
  for (guint i = 0; i < G_N_ELEMENTS (names); i++)
    {
      g_autofree gchar *path = g_strdup_printf ("/el721/hwvault/%s", names[i]);
      g_test_add_data_func (path, GUINT_TO_POINTER (i), test_restore);
    }
  return g_test_run ();
}
