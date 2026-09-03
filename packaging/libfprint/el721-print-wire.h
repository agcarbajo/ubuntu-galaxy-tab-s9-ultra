/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include <glib.h>
#include <string.h>

/* The TA authenticates a 256-byte identity alongside each encrypted print.
 * fpi_print_generate_user_id() is random on EVERY call: it is not a lookup. */
static inline gboolean
el721_print_unpack (GVariant *data, gchar **user, guint32 *slot,
                    GBytes **opaque, GError **error)
{
  g_autoptr(GVariant) array = NULL;
  const gchar *identity;
  const guint8 *bytes;
  gsize size;
  *user = NULL;
  *opaque = NULL;
  *slot = 0;
  if (data && g_variant_is_of_type (data, G_VARIANT_TYPE ("(uay)")))
    {
      g_set_error_literal (error, g_quark_from_static_string ("el721-print-error"),
                           1, "EL721 legacy print has no saved identity; enroll again");
      return FALSE;
    }
  if (!data || !g_variant_is_of_type (data, G_VARIANT_TYPE ("(suay)")))
    goto invalid;
  g_variant_get (data, "(&su@ay)", &identity, slot, &array);
  bytes = g_variant_get_fixed_array (array, &size, 1);
  if (!identity[0] || strlen (identity) >= 256 || *slot < 1 || *slot > 4 ||
      !bytes || !size || size >= 0x226000)
    goto invalid;
  *user = g_strdup (identity);
  *opaque = g_variant_get_data_as_bytes (array);
  return TRUE;
invalid:
  *slot = 0;
  g_set_error_literal (error, g_quark_from_static_string ("el721-print-error"),
                       1, "invalid EL721 print identity or opaque payload");
  return FALSE;
}
