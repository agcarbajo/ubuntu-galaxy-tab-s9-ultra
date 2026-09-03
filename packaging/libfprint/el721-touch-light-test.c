/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "el721-touch-light.h"

static void waiting (void)
{
  gint64 deadline = 0;
  for (gint64 now = 1; now <= 90000001; now += 45000)
    g_assert_cmpint (el721_touch_light_step (&deadline, now, FALSE, FALSE), ==,
                     EL721_LIGHT_WAIT);
  g_assert_cmpint (deadline, ==, 0);
}

static void settle (void)
{
  gint64 deadline = 0;
  g_assert_cmpint (el721_touch_light_step (&deadline, 1000, TRUE, TRUE), ==, EL721_LIGHT_ON);
  g_assert_cmpint (deadline, ==, 1000 + EL721_LIGHT_SETTLE_US);
  g_assert_cmpint (el721_touch_light_step (&deadline, 180999, TRUE, FALSE), ==, EL721_LIGHT_WAIT);
  g_assert_cmpint (el721_touch_light_step (&deadline, 181000, TRUE, FALSE), ==, EL721_LIGHT_CAPTURE);
  g_assert_cmpint (deadline, ==, 0);
}

static void held (void)
{
  gint64 deadline = 0;
  el721_touch_light_step (&deadline, 1000, TRUE, TRUE);
  el721_touch_light_step (&deadline, 181000, TRUE, FALSE);
  for (gint64 now = 200000; now < 90000000; now += 45000)
    g_assert_cmpint (el721_touch_light_step (&deadline, now, TRUE, FALSE), ==, EL721_LIGHT_WAIT);
}

static void early_release (void)
{
  gint64 deadline = 0;
  el721_touch_light_step (&deadline, 1000, TRUE, TRUE);
  g_assert_cmpint (el721_touch_light_step (&deadline, 91000, FALSE, FALSE), ==, EL721_LIGHT_OFF);
  g_assert_cmpint (deadline, ==, 0);
  g_assert_cmpint (el721_touch_light_step (&deadline, 181000, FALSE, FALSE), ==, EL721_LIGHT_WAIT);
  g_assert_cmpint (el721_touch_light_step (&deadline, 200000, TRUE, TRUE), ==, EL721_LIGHT_ON);
}

static void release_at_deadline (void)
{
  gint64 deadline = 0;
  el721_touch_light_step (&deadline, 1000, TRUE, TRUE);
  g_assert_cmpint (el721_touch_light_step (&deadline, 181000, FALSE, FALSE), ==, EL721_LIGHT_OFF);
}

static void duplicate_edge (void)
{
  gint64 deadline = 0;
  el721_touch_light_step (&deadline, 1000, TRUE, TRUE);
  g_assert_cmpint (el721_touch_light_step (&deadline, 91000, TRUE, TRUE), ==, EL721_LIGHT_WAIT);
  g_assert_cmpint (deadline, ==, 181000);
}

static void new_action (void)
{
  gint64 deadline = 0;
  el721_touch_light_step (&deadline, 1000, TRUE, TRUE);
  /* Cleanup clears a pending capture for cancel, timeout and completion. */
  deadline = 0;
  g_assert_cmpint (el721_touch_light_step (&deadline, 181000, TRUE, FALSE), ==, EL721_LIGHT_WAIT);
}

int main (int argc, char **argv)
{
  g_test_init (&argc, &argv, NULL);
  g_test_add_func ("/el721/light/wait-no-contact", waiting);
  g_test_add_func ("/el721/light/settle-before-capture", settle);
  g_test_add_func ("/el721/light/held-one-capture", held);
  g_test_add_func ("/el721/light/early-release-repress", early_release);
  g_test_add_func ("/el721/light/release-at-deadline", release_at_deadline);
  g_test_add_func ("/el721/light/duplicate-edge", duplicate_edge);
  g_test_add_func ("/el721/light/new-action", new_action);
  return g_test_run ();
}
