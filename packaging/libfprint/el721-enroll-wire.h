/* SPDX-License-Identifier: BSD-3-Clause */
#pragma once

#include "el721-qtee.h"
#include <string.h>

#define EL721_ENROLL_OUTPUT_SIZE 0x230024U
#define EL721_ENROLL_TEMPLATE_OFFSET 0x1cU
#define EL721_ENROLL_TEMPLATE_MAX 0x226000U
#define EL721_ENROLL_TEMPLATE_LENGTH_OFFSET 0x22601cU

static inline guint32
el721_wire_u32 (const guint8 *buffer, gsize offset)
{
  guint32 value;
  memcpy (&value, buffer + offset, sizeof (value));
  return GUINT32_FROM_LE (value);
}

/* Only the encrypted EnrollDo payload is a reusable template.  EnrollFinal's
 * much smaller output contains optional bitmap/debug data, not this payload.
 * Keeping the decoder independent of QTEE permits synthetic boundary tests. */
static inline gboolean
el721_decode_enroll_output (const guint8 *output, gsize output_size,
                           El721Reply *reply, GError **error)
{
  guint32 size;

  g_clear_pointer (&reply->data, g_bytes_unref);
  memset (reply, 0, sizeof (*reply));
  if (!output || output_size != EL721_ENROLL_OUTPUT_SIZE)
    {
      g_set_error_literal (error, g_quark_from_static_string ("el721-qtee-error"),
                           1, "invalid BAUTH EnrollDo response size");
      return FALSE;
    }
  reply->opcode = el721_wire_u32 (output, 0);
  reply->result = el721_wire_u32 (output, 4);
  reply->status = el721_wire_u32 (output, 12);
  reply->quality = el721_wire_u32 (output, 16);   /* coverage, 0..100 */
  reply->remaining = el721_wire_u32 (output, 20); /* accepted samples */
  reply->progress = el721_wire_u32 (output, 24);

  /* Failed and intermediate replies must never expose template bytes. */
  if (reply->result || reply->opcode || reply->quality != 100)
    return TRUE;
  size = el721_wire_u32 (output, EL721_ENROLL_TEMPLATE_LENGTH_OFFSET);
  if (size > EL721_ENROLL_TEMPLATE_MAX)
    {
      g_set_error (error, g_quark_from_static_string ("el721-qtee-error"),
                   1, "invalid BAUTH encrypted template size %u", size);
      return FALSE;
    }
  if (size)
    reply->data = g_bytes_new (output + EL721_ENROLL_TEMPLATE_OFFSET, size);
  return TRUE;
}
