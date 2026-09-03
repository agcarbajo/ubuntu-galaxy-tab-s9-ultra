/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "el721-gallery.h"
#include "el721-touch-light.h"

static void
add (El721Gallery *gallery, const gchar *identity, guint32 slot, gsize size)
{
  g_autofree guint8 *payload = g_malloc0 (size);
  g_autoptr(GVariant) data = g_variant_ref_sink (g_variant_new ("(su@ay)", identity, slot,
    g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, payload, size, 1)));
  g_autoptr(GError) error = NULL;
  g_assert_true (el721_gallery_add (gallery, data, &error));
  g_assert_no_error (error);
}

static void
mixed (void)
{
  El721Gallery gallery = {0};
  add (&gallery, "synthetic-old", 3, 848262);
  add (&gallery, "synthetic-native", 2, 844630);
  g_assert_cmpuint (gallery.entries->len, ==, 2);
  const El721GalleryEntry *entry = el721_gallery_current (&gallery);
  g_assert_cmpstr (entry->identity, ==, "synthetic-old");
  g_assert_cmpuint (g_bytes_get_size (entry->opaque), ==, 848262);
  g_assert_true (el721_gallery_matches_current (&gallery, 3));
  g_assert_false (el721_gallery_matches_current (&gallery, 2));
  g_assert_true (el721_gallery_next (&gallery));
  entry = el721_gallery_current (&gallery);
  g_assert_cmpstr (entry->identity, ==, "synthetic-native");
  g_assert_cmpuint (g_bytes_get_size (entry->opaque), ==, 844630);
  g_assert_true (el721_gallery_matches_current (&gallery, 2));
  g_assert_false (el721_gallery_matches_current (&gallery, 3));
  g_assert_false (el721_gallery_matches_current (&gallery, 0));
  el721_gallery_clear (&gallery);
}

static void
slot_collision (void)
{
  El721Gallery gallery = {0};
  add (&gallery, "synthetic-first", 3, 32);
  add (&gallery, "synthetic-second", 3, 32);
  g_assert_true (el721_gallery_matches_current (&gallery, 3));
  g_assert_cmpuint (gallery.current, ==, 0);
  g_assert_true (el721_gallery_next (&gallery));
  g_assert_true (el721_gallery_matches_current (&gallery, 3));
  g_assert_cmpuint (gallery.current, ==, 1);
  g_assert_cmpstr (el721_gallery_current (&gallery)->identity, ==, "synthetic-second");
  el721_gallery_clear (&gallery);
}

static void
ten_prints (void)
{
  El721Gallery gallery = {0};
  for (guint i = 0; i < 10; i++)
    {
      g_autofree gchar *identity = g_strdup_printf ("synthetic-%u", i);
      add (&gallery, identity, i % 4 + 1, 850000);
    }
  /* Aggregate size exceeds the TA packet limit, but each import stays below
   * it. No identity or ciphertext is combined, even when slots collide. */
  for (guint i = 0; i < 10; i++)
    {
      g_assert_cmpuint (gallery.current, ==, i);
      g_assert_cmpuint (g_bytes_get_size (el721_gallery_current (&gallery)->opaque), ==, 850000);
      g_assert_cmpint (el721_gallery_next (&gallery), ==, i < 9);
    }
  for (guint i = 0; i < 10; i++)
    g_assert_false (el721_gallery_next (&gallery));
  g_assert_false (el721_gallery_matches_current (&gallery, 1));
  el721_gallery_clear (&gallery);
}

static void
single (void)
{
  El721Gallery gallery = {0};
  add (&gallery, "synthetic-single", 1, 1);
  g_assert_true (el721_gallery_matches_current (&gallery, 1));
  g_assert_false (el721_gallery_next (&gallery));
  g_assert_null (el721_gallery_current (&gallery));
  el721_gallery_clear (&gallery);
}

static void
invalid (void)
{
  El721Gallery gallery = {0};
  g_autoptr(GError) error = NULL;
  add (&gallery, "synthetic-valid", 1, 1);
  g_assert_false (el721_gallery_add (&gallery, NULL, &error));
  g_assert_nonnull (error);
  g_assert_cmpuint (gallery.entries->len, ==, 1);
  el721_gallery_clear (&gallery);
}

static void
reset (void)
{
  El721Gallery gallery = {0};
  g_assert_null (el721_gallery_current (&gallery));
  g_assert_false (el721_gallery_next (&gallery));
  add (&gallery, "synthetic-first", 1, 32);
  add (&gallery, "synthetic-second", 2, 32);
  g_assert_true (el721_gallery_next (&gallery));
  el721_gallery_clear (&gallery);
  el721_gallery_clear (&gallery);
  g_assert_cmpuint (gallery.current, ==, 0);
  g_assert_null (gallery.entries);
  add (&gallery, "synthetic-new-action", 4, 32);
  g_assert_cmpuint (gallery.current, ==, 0);
  g_assert_true (el721_gallery_matches_current (&gallery, 4));
  el721_gallery_clear (&gallery);
}

static void
continued_contact (void)
{
  /* Production keeps the settled light and schedules the next candidate's
   * capture after yielding. It must not capture without a held finger. */
  gint64 deadline = 1045000;
  g_assert_cmpint (el721_touch_light_step (&deadline, 1040000, TRUE, FALSE), ==, EL721_LIGHT_WAIT);
  g_assert_cmpint (el721_touch_light_step (&deadline, 1045000, TRUE, FALSE), ==, EL721_LIGHT_CAPTURE);
  g_assert_cmpint (deadline, ==, 0);
  g_assert_cmpint (el721_touch_light_step (&deadline, 1090000, TRUE, FALSE), ==, EL721_LIGHT_WAIT);
}

static void
released_contact (void)
{
  gint64 deadline = 1045000;
  g_assert_cmpint (el721_touch_light_step (&deadline, 1045000, FALSE, FALSE), ==, EL721_LIGHT_OFF);
  g_assert_cmpint (deadline, ==, 0);
  g_assert_cmpint (el721_touch_light_step (&deadline, 1090000, FALSE, FALSE), ==, EL721_LIGHT_WAIT);
  g_assert_cmpint (el721_touch_light_step (&deadline, 1200000, TRUE, TRUE), ==, EL721_LIGHT_ON);
  g_assert_cmpint (el721_touch_light_step (&deadline, 1380000, TRUE, FALSE), ==, EL721_LIGHT_CAPTURE);
}

static void
ui_inhibited (void)
{
  gint64 deadline = 1045000;
  /* The normal UI-inhibition/cancel path clears the pending deadline. */
  deadline = 0;
  g_assert_cmpint (el721_touch_light_step (&deadline, 1045000, TRUE, FALSE), ==, EL721_LIGHT_WAIT);
}

int main (int argc, char **argv)
{
  g_test_init (&argc, &argv, NULL);
  g_test_add_func ("/gallery/mixed-identities-original-and-native", mixed);
  g_test_add_func ("/gallery/slot-collision-selects-current-only", slot_collision);
  g_test_add_func ("/gallery/ten-independent-prints-and-exhaustion", ten_prints);
  g_test_add_func ("/gallery/single-verify", single);
  g_test_add_func ("/gallery/invalid-entry-fails-closed", invalid);
  g_test_add_func ("/gallery/cleanup-and-new-action", reset);
  g_test_add_func ("/gallery/held-contact-yields-before-next-capture", continued_contact);
  g_test_add_func ("/gallery/release-waits-for-new-contact", released_contact);
  g_test_add_func ("/gallery/ui-inhibition-cancels-continuation", ui_inhibited);
  return g_test_run ();
}
