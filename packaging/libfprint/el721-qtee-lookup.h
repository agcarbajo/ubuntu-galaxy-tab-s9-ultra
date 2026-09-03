/* SPDX-License-Identifier: BSD-3-Clause */
#pragma once

#include <stdint.h>
#include <string.h>
#include <glib.h>
#include "qcomtee_object.h"

static inline gboolean
el721_qtee_lookup_controller (struct qcomtee_object *loader, const char *name,
                             struct qcomtee_object **controller,
                             qcomtee_result_t *result)
{
  guint32 architecture = 0;
  struct qcomtee_param params[3] = {
    { .attr = QCOMTEE_UBUF_INPUT,
      .ubuf = { (void *) name, strlen (name) } },
    { .attr = QCOMTEE_UBUF_OUTPUT,
      .ubuf = { &architecture, sizeof (architecture) } },
    { .attr = QCOMTEE_OBJREF_OUTPUT }
  };

  /* QSEECom lookupTA (op 2) returns an architecture and a controller.
   * Omitting the scalar output changes counts 0x1011 to 0x1001, rejected
   * with INVALID before lookup even runs. The TA is not necessarily absent. */
  *controller = QCOMTEE_OBJECT_NULL;
  if (qcomtee_object_invoke (loader, 2, params, G_N_ELEMENTS (params), result))
    return FALSE;
  *controller = params[2].object;
  return TRUE;
}
