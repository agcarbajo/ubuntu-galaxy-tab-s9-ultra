/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "el721-print-wire.h"

static GVariant *record (const gchar *user, guint slot, gsize size) {
  g_autofree guint8 *bytes = g_malloc0 (size);
  return g_variant_ref_sink (g_variant_new ("(su@ay)", user, slot,
    g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, bytes, size, 1)));
}
static void valid (void) {
  GVariant *value = record ("FP1-synthetic-stable-identity", 3, 32);
  g_autofree gchar *user = NULL;
  g_autoptr(GBytes) opaque = NULL;
  g_autoptr(GError) error = NULL;
  guint32 slot;
  g_assert_true (el721_print_unpack (value, &user, &slot, &opaque, &error));
  g_variant_unref (value);
  g_assert_no_error (error);
  g_assert_cmpstr (user, ==, "FP1-synthetic-stable-identity");
  g_assert_cmpuint (slot, ==, 3);
  g_assert_cmpuint (g_bytes_get_size (opaque), ==, 32);
}
static void invalid (gconstpointer value) {
  g_autofree gchar *user = NULL;
  g_autoptr(GBytes) opaque = NULL;
  g_autoptr(GError) error = NULL;
  guint32 slot;
  g_assert_false (el721_print_unpack ((GVariant *)value, &user, &slot, &opaque, &error));
  g_assert_nonnull (error);
  g_assert_null (user);
  g_assert_null (opaque);
  g_assert_cmpuint (slot, ==, 0);
}
static void legacy (void) {
  g_autoptr(GVariant) value = g_variant_ref_sink (g_variant_new ("(u@ay)", 3,
    g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, "x", 1, 1)));
  g_autofree gchar *user = NULL;
  g_autoptr(GBytes) opaque = NULL;
  g_autoptr(GError) error = NULL;
  guint32 slot;
  g_assert_false (el721_print_unpack (value, &user, &slot, &opaque, &error));
  g_assert_nonnull (strstr (error->message, "enroll again"));
}
static void roundtrip (void) {
  g_autoptr(GVariant) value = record ("synthetic-identity", 1, 64);
  g_autoptr(GBytes) serialized = g_variant_get_data_as_bytes (value);
  g_autoptr(GVariant) restored = g_variant_ref_sink (
    g_variant_new_from_bytes (G_VARIANT_TYPE ("(suay)"), serialized, FALSE));
  g_autofree gchar *user = NULL;
  g_autoptr(GBytes) opaque = NULL;
  g_autoptr(GError) error = NULL;
  guint32 slot;
  g_assert_true (el721_print_unpack (restored, &user, &slot, &opaque, &error));
  g_assert_cmpstr (user, ==, "synthetic-identity");
}
int main (int argc, char **argv) {
  g_test_init (&argc, &argv, NULL);
  g_test_add_func ("/print/valid-lifetime", valid);
  g_test_add_func ("/print/roundtrip", roundtrip);
  g_test_add_func ("/print/legacy-explicit", legacy);
  g_test_add_data_func ("/print/null", NULL, invalid);
  g_autofree gchar *long_user = g_strnfill (256, 'x');
  const gchar *names[] = {"empty-user", "long-user", "slot-zero", "slot-high", "empty", "oversize"};
  GVariant *cases[] = {record ("", 1, 1), record (long_user, 1, 1), record ("u", 0, 1),
    record ("u", 5, 1), record ("u", 1, 0), record ("u", 1, 0x226000)};
  for (guint i = 0; i < G_N_ELEMENTS(cases); i++) {
    g_autofree gchar *path = g_strconcat ("/print/", names[i], NULL);
    g_test_add_data_func_full (path, cases[i], invalid, (GDestroyNotify)g_variant_unref);
  }
  return g_test_run ();
}
