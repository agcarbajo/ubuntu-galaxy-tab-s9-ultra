/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include "el721-enroll-wire.h"

#define EL721_IDENTIFY_OUTPUT_SIZE 0x230089U
#define EL721_IDENTIFY_NO_MATCH 32U

/* A normal rejection is terminal, has no matched slot and is distinct from
 * malformed data, transport errors and quality retries. Fail closed on a
 * contradictory slot/result pair instead of reporting authentication. */
static inline gboolean
el721_identify_is_no_match (const El721Reply *reply)
{
  return reply->result == EL721_IDENTIFY_NO_MATCH &&
         reply->opcode == 0 && reply->template_id == 0;
}

/* IdentifyDo is not decode_common's layout. The next operation is at byte 0,
 * not byte 12; the matched secure slot is at byte 20, not the score at 16.
 * In particular {4, 0, 0xffffffff, 0, 0, 0} means WAIT, never NO_MATCH. */
static inline gboolean
el721_decode_identify_output (const guint8 *output, gsize size,
                             El721Reply *reply, GError **error)
{
  guint32 update_size;
  g_clear_pointer (&reply->data, g_bytes_unref);
  memset (reply, 0, sizeof (*reply));
  if (!output || size != EL721_IDENTIFY_OUTPUT_SIZE)
    goto invalid;
  reply->opcode = el721_wire_u32 (output, 0);
  reply->result = el721_wire_u32 (output, 4);
  reply->status = el721_wire_u32 (output, 8);
  reply->quality = el721_wire_u32 (output, 16);
  reply->template_id = el721_wire_u32 (output, 20);
  /* Only a completed successful match may expose an opaque update. */
  if (reply->result || reply->opcode || !reply->template_id)
    return TRUE;
  update_size = el721_wire_u32 (output, 0x226038);
  if (update_size > 0x226000)
    goto invalid;
  if (update_size)
    reply->data = g_bytes_new (output + 0x38, update_size);
  return TRUE;
invalid:
  g_set_error_literal (error, g_quark_from_static_string ("el721-qtee-error"),
                       1, "invalid BAUTH IdentifyDo response size");
  return FALSE;
}

static inline gboolean
el721_identify_contact_ready (guint32 opcode, gboolean edge,
                             gboolean pressed, gboolean was_pressed)
{
  return opcode == 4 && edge && pressed && !was_pressed;
}
