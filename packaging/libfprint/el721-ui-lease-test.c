/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "el721-ui-lease.h"

int main (int argc, char **argv)
{
  const struct { const gchar *text; gint64 now; gboolean ready; } cases[] = {
    { NULL, 1000, FALSE }, { "", 1000, FALSE },
    { "ready 2001000\n", 1000, TRUE }, { "ready 2001000", 1000, TRUE },
    { "ready 1000\n", 1000, FALSE }, { "ready 999\n", 1000, FALSE },
    { "ready 2001001\n", 1000, FALSE }, { "blocked 2001000\n", 1000, FALSE },
    { "ready -1\n", 1000, FALSE }, { "ready 10000\nextra", 1000, FALSE },
    { "ready 99999999999999999999999999\n", 1000, FALSE },
    { "ready 9223372036854775807\n", 1000, FALSE },
    { "ready 10000\n", -1, FALSE }, { "ready +10000\n", 1000, FALSE },
    { "ready \n", 1000, FALSE }, { "ready 1001\n", 1000, TRUE },
  };
  g_test_init (&argc, &argv, NULL);
  g_assert_true (el721_ui_light_ready ("ready 1001000\n", 1000, 2000));
  g_assert_false (el721_ui_light_ready ("ready 1001000\n", 1001, 2000));
  g_assert_false (el721_ui_light_ready ("ready 1001000\n", 1000, 1001000));
  g_assert_false (el721_ui_light_ready (NULL, 1000, 2000));
  g_assert_false (el721_ui_light_ready ("ready 1\n", G_MAXINT64, G_MAXINT64));
  g_assert_false (el721_ui_light_ready ("ready 1001000\n", 0, 2000));
  for (guint i = 0; i < G_N_ELEMENTS (cases); i++)
    g_assert_cmpint (el721_ui_lease_ready (cases[i].text, cases[i].now), ==, cases[i].ready);
  g_print ("PASS: %u optical availability lease cases\n", (guint) G_N_ELEMENTS (cases));
  return 0;
}
