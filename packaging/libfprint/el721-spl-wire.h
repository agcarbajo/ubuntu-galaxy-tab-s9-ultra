/* SPDX-License-Identifier: BSD-3-Clause */
#pragma once

#include <glib.h>
#include <string.h>
#include "qcomtee_object.h"

/* Stock libspl's listener 0xb000 is a raw 12-byte request / 8-byte reply,
 * not the separate libqisl TLV protocol. No credential bytes are involved. */
typedef enum
{
  EL721_SPL_IRQ = 0xaa,
  EL721_SPL_TIMEOUT = 0xbb,
  EL721_SPL_RESET = 0xcc,
  EL721_SPL_CANCEL = 0xdd,
  EL721_SPL_IO_ERROR = 0xee,
  EL721_SPL_UNKNOWN = 0xff,
} El721SplResult;

typedef El721SplResult (*El721SplWait) (guint32 timeout_ms, gpointer data);

typedef struct
{
  guint8 *shared;
  gsize shared_size;
  /* Output pointers must survive dispatch: quic-teec marshals them later. */
  guint32 offsets[4];
  guint32 is_64_bit;
} El721SplWire;

static inline qcomtee_result_t
el721_spl_dispatch (El721SplWire *wire, qcomtee_op_t op,
                    struct qcomtee_param *params, int count,
                    El721SplWait wait, gpointer data)
{
  guint32 command, timeout, reply;
  El721SplResult status = EL721_SPL_UNKNOWN;

  if (!wire || !wire->shared || wire->shared_size < 12 || op || !params ||
      count != 6 || params[0].attr != QCOMTEE_UBUF_OUTPUT ||
      params[0].ubuf.size != 16 || params[1].attr != QCOMTEE_UBUF_OUTPUT ||
      params[1].ubuf.size != 4)
    return QCOMTEE_ERROR_UNAVAIL;
  for (int i = 2; i < 6; i++)
    if (params[i].attr != QCOMTEE_OBJREF_OUTPUT)
      return QCOMTEE_ERROR_UNAVAIL;

  memcpy (&command, wire->shared, 4);
  command = GUINT32_FROM_LE (command);
  if (command == 0x777)
    {
      memcpy (&timeout, wire->shared + 8, 4);
      timeout = GUINT32_FROM_LE (timeout);
      status = wait ? wait (timeout, data) : EL721_SPL_IO_ERROR;
      switch (status)
        {
        case EL721_SPL_IRQ:
        case EL721_SPL_TIMEOUT:
        case EL721_SPL_RESET:
        case EL721_SPL_CANCEL:
        case EL721_SPL_IO_ERROR:
          break;
        case EL721_SPL_UNKNOWN:
        default:
          status = EL721_SPL_IO_ERROR;
        }
    }
  /* The initial 0xdead handshake is unknown in stock libspl too. Only a real
   * IRQ may produce 0xaa; neither registration nor a timeout implies success. */
  reply = GUINT32_TO_LE ((guint32) status);
  memcpy (wire->shared + 4, &reply, 4);
  memset (wire->offsets, 0, sizeof wire->offsets);
  wire->is_64_bit = 0;
  /* Callback output buffers have capacities but NULL addresses on entry. */
  params[0].ubuf.addr = wire->offsets;
  params[1].ubuf.addr = &wire->is_64_bit;
  for (int i = 2; i < 6; i++)
    params[i].object = QCOMTEE_OBJECT_NULL;
  return 0;
}
