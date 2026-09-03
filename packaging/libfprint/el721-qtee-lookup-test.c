/* SPDX-License-Identifier: BSD-3-Clause */
/* No TEE library is linked: this stub verifies the actual lookup call shape. */
#include "el721-qtee-lookup.h"

static struct qcomtee_object loader, returned;
static qcomtee_result_t secure_result;
static int transport_result;
static const char *expected_name;

int
qcomtee_object_invoke (struct qcomtee_object *object, qcomtee_op_t operation,
                      struct qcomtee_param *params, int count,
                      qcomtee_result_t *result)
{
  g_assert_true (object == &loader);
  g_assert_cmpuint (operation, ==, 2);
  g_assert_cmpint (count, ==, 3);
  g_assert_cmpuint (params[0].attr, ==, QCOMTEE_UBUF_INPUT);
  g_assert_cmpuint (params[0].ubuf.size, ==, strlen (expected_name));
  g_assert_cmpmem (params[0].ubuf.addr, params[0].ubuf.size,
                   expected_name, strlen (expected_name));
  g_assert_cmpuint (params[1].attr, ==, QCOMTEE_UBUF_OUTPUT);
  g_assert_cmpuint (params[1].ubuf.size, ==, sizeof (guint32));
  g_assert_cmpuint (*(guint32 *) params[1].ubuf.addr, ==, 0);
  g_assert_cmpuint (params[2].attr, ==, QCOMTEE_OBJREF_OUTPUT);
  g_assert_null (params[2].object);
  *(guint32 *) params[1].ubuf.addr = 2;
  *result = secure_result;
  params[2].object = secure_result ? QCOMTEE_OBJECT_NULL : &returned;
  return transport_result;
}

static void
test_resident (gconstpointer data)
{
  struct qcomtee_object *controller = QCOMTEE_OBJECT_NULL;
  qcomtee_result_t result = QCOMTEE_ERROR;
  expected_name = data;
  secure_result = 0;
  transport_result = 0;
  g_assert_true (el721_qtee_lookup_controller (&loader, expected_name, &controller, &result));
  g_assert_cmpuint (result, ==, 0);
  g_assert_true (controller == &returned);
}

static void
test_missing (void)
{
  struct qcomtee_object *controller = &returned;
  qcomtee_result_t result = QCOMTEE_ERROR;
  expected_name = "dualfp";
  secure_result = 23;
  transport_result = 0;
  g_assert_true (el721_qtee_lookup_controller (&loader, expected_name, &controller, &result));
  g_assert_cmpuint (result, ==, 23);
  g_assert_null (controller);
}

static void
test_transport_failure (void)
{
  struct qcomtee_object *controller = &returned;
  qcomtee_result_t result = QCOMTEE_ERROR;
  expected_name = "hwvault";
  secure_result = 0;
  transport_result = -1;
  g_assert_false (el721_qtee_lookup_controller (&loader, expected_name, &controller, &result));
  g_assert_null (controller);
}

int
main (int argc, char **argv)
{
  g_test_init (&argc, &argv, NULL);
  g_test_add_data_func ("/qtee/lookup/dualfp", "dualfp", test_resident);
  g_test_add_data_func ("/qtee/lookup/hwvault", "hwvault", test_resident);
  g_test_add_data_func ("/qtee/lookup/skeymast", "skeymast", test_resident);
  g_test_add_data_func ("/qtee/lookup/keymaster64", "keymaster64", test_resident);
  g_test_add_func ("/qtee/lookup/missing", test_missing);
  g_test_add_func ("/qtee/lookup/transport-failure", test_transport_failure);
  return g_test_run ();
}
