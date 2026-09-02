/* SPDX-License-Identifier: BSD-3-Clause */
/* Synthetic frames only: no hardware, secure services, credentials or keys. */
#include "el721-spl-wire.h"

static guint calls;
static guint32 last_timeout;
static El721SplResult next_result;

static El721SplResult
fake_wait (guint32 timeout, gpointer data)
{
  g_assert_true (data == &calls);
  calls++;
  last_timeout = timeout;
  return next_result;
}

static void
put_word (guint8 *bytes, guint32 word)
{
  word = GUINT32_TO_LE (word);
  memcpy (bytes, &word, 4);
}

static guint32
get_word (const guint8 *bytes)
{
  guint32 word;
  memcpy (&word, bytes, 4);
  return GUINT32_FROM_LE (word);
}

static void
init_frame (guint8 *frame, struct qcomtee_param *params)
{
  memset (frame, 0x55, 16);
  put_word (frame, 0x777);
  put_word (frame + 8, 4000);
  memset (params, 0, sizeof (*params) * 6);
  params[0].attr = QCOMTEE_UBUF_OUTPUT;
  params[0].ubuf.size = 16;
  params[1].attr = QCOMTEE_UBUF_OUTPUT;
  params[1].ubuf.size = 4;
  for (int i = 2; i < 6; i++) params[i].attr = QCOMTEE_OBJREF_OUTPUT;
  calls = 0;
  last_timeout = G_MAXUINT32;
}

static void
test_response (gconstpointer data)
{
  guint8 frame[16], saved[16];
  struct qcomtee_param params[6];
  El721SplWire wire = { .shared = frame, .shared_size = sizeof frame };
  guint32 expected = GPOINTER_TO_UINT (data);

  init_frame (frame, params);
  memcpy (saved, frame, sizeof saved);
  next_result = expected;
  memset (wire.offsets, 0xa5, sizeof wire.offsets);
  wire.is_64_bit = 123;
  g_assert_cmpuint (el721_spl_dispatch (&wire, 0, params, 6, fake_wait, &calls), ==, 0);
  g_assert_cmpuint (calls, ==, 1);
  g_assert_cmpuint (last_timeout, ==, 4000);
  if (expected < EL721_SPL_IRQ || expected == EL721_SPL_UNKNOWN)
    expected = EL721_SPL_IO_ERROR;
  g_assert_cmpuint (get_word (frame + 4), ==, expected);
  g_assert_cmpmem (frame, 4, saved, 4);
  g_assert_cmpmem (frame + 8, 8, saved + 8, 8);
  /* NULL callback output addresses were replaced, not dereferenced. The
   * storage still exists after dispatch returns, through SUPPL_SEND. */
  g_assert_true (params[0].ubuf.addr == wire.offsets);
  g_assert_true (params[1].ubuf.addr == &wire.is_64_bit);
  for (int i = 0; i < 4; i++) g_assert_cmpuint (wire.offsets[i], ==, 0);
  g_assert_cmpuint (wire.is_64_bit, ==, 0);
  for (int i = 2; i < 6; i++) g_assert_null (params[i].object);
}

static void
test_unknown (gconstpointer data)
{
  guint8 frame[16];
  struct qcomtee_param params[6];
  El721SplWire wire = { .shared = frame, .shared_size = sizeof frame };
  guint32 command = GPOINTER_TO_UINT (data);

  init_frame (frame, params);
  put_word (frame, command);
  g_assert_cmpuint (el721_spl_dispatch (&wire, 0, params, 6, fake_wait, &calls), ==, 0);
  g_assert_cmpuint (get_word (frame), ==, command);
  g_assert_cmpuint (get_word (frame + 4), ==, EL721_SPL_UNKNOWN);
  g_assert_cmpuint (calls, ==, 0);
}

static void
test_timeout (gconstpointer data)
{
  guint8 frame[16];
  struct qcomtee_param params[6];
  El721SplWire wire = { .shared = frame, .shared_size = sizeof frame };
  guint32 timeout = GPOINTER_TO_UINT (data);

  init_frame (frame, params);
  put_word (frame + 8, timeout);
  next_result = EL721_SPL_TIMEOUT;
  g_assert_cmpuint (el721_spl_dispatch (&wire, 0, params, 6, fake_wait, &calls), ==, 0);
  g_assert_cmpuint (last_timeout, ==, timeout);
  g_assert_cmpuint (get_word (frame + 4), ==, EL721_SPL_TIMEOUT);
}

static void
test_malformed (gconstpointer data)
{
  guint8 frame[16], saved[16];
  struct qcomtee_param params[6];
  El721SplWire wire = { .shared = frame, .shared_size = sizeof frame };
  qcomtee_op_t op = 0;
  int count = 6;
  guint which = GPOINTER_TO_UINT (data);

  init_frame (frame, params);
  memcpy (saved, frame, sizeof saved);
  switch (which)
    {
    case 0: wire.shared = NULL; break;
    case 1: wire.shared_size = 11; break;
    case 2: op = 1; break;
    case 3: count = 5; break;
    case 4: count = 7; break;
    case 5: params[0].attr = QCOMTEE_UBUF_INPUT; break;
    case 6: params[0].ubuf.size = 15; break;
    case 7: params[1].attr = QCOMTEE_UBUF_INPUT; break;
    case 8: params[1].ubuf.size = 3; break;
    default: params[which - 7].attr = QCOMTEE_OBJREF_INPUT; break;
    }
  g_assert_cmpuint (el721_spl_dispatch (&wire, op, params, count, fake_wait, &calls),
                    ==, (qcomtee_result_t) QCOMTEE_ERROR_UNAVAIL);
  g_assert_cmpuint (calls, ==, 0);
  g_assert_cmpmem (frame, sizeof frame, saved, sizeof saved);
  g_assert_null (params[0].ubuf.addr);
  g_assert_null (params[1].ubuf.addr);
}

static void
test_null_arguments (void)
{
  guint8 frame[16];
  struct qcomtee_param params[6];
  El721SplWire wire = { .shared = frame, .shared_size = sizeof frame };

  init_frame (frame, params);
  g_assert_cmpuint (el721_spl_dispatch (NULL, 0, params, 6, fake_wait, &calls),
                    ==, (qcomtee_result_t) QCOMTEE_ERROR_UNAVAIL);
  g_assert_cmpuint (el721_spl_dispatch (&wire, 0, NULL, 6, fake_wait, &calls),
                    ==, (qcomtee_result_t) QCOMTEE_ERROR_UNAVAIL);
  g_assert_cmpuint (el721_spl_dispatch (&wire, 0, params, 6, NULL, NULL), ==, 0);
  g_assert_cmpuint (get_word (frame + 4), ==, EL721_SPL_IO_ERROR);
}

int
main (int argc, char **argv)
{
  static const guint results[] = { 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0 };
  g_test_init (&argc, &argv, NULL);
  for (guint i = 0; i < G_N_ELEMENTS (results); i++)
    {
      g_autofree gchar *name = g_strdup_printf ("/spl/response/%x", results[i]);
      g_test_add_data_func (name, GUINT_TO_POINTER (results[i]), test_response);
    }
  g_test_add_data_func ("/spl/handshake", GUINT_TO_POINTER (0xdead), test_unknown);
  g_test_add_data_func ("/spl/unknown", GUINT_TO_POINTER (0x123), test_unknown);
  g_test_add_data_func ("/spl/timeout/zero", NULL, test_timeout);
  g_test_add_data_func ("/spl/timeout/maximum", GUINT_TO_POINTER (G_MAXUINT32), test_timeout);
  for (guint i = 0; i < 13; i++)
    {
      g_autofree gchar *name = g_strdup_printf ("/spl/malformed/%u", i);
      g_test_add_data_func (name, GUINT_TO_POINTER (i), test_malformed);
    }
  g_test_add_func ("/spl/null-arguments", test_null_arguments);
  return g_test_run ();
}
