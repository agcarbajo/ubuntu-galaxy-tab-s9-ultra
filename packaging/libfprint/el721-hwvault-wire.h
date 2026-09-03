/* SPDX-License-Identifier: BSD-3-Clause */
#pragma once

#include <glib.h>
#include <string.h>

#define EL721_HWVAULT_WIRE_SIZE 41088U

static inline guint32
el721_hv_word (const guint8 *data, gsize offset)
{
  guint32 value;
  memcpy (&value, data + offset, sizeof (value));
  return GUINT32_FROM_LE (value);
}

static inline gboolean
el721_hv_number (const gchar **cursor, guint32 *value)
{
  gchar *end;
  guint64 number;

  if (!g_ascii_isdigit (**cursor))
    return FALSE;
  number = g_ascii_strtoull (*cursor, &end, 10);
  if (number > G_MAXUINT32)
    return FALSE;
  *value = (guint32) number;
  *cursor = end;
  return TRUE;
}

static inline gboolean
el721_hv_literal (const gchar **cursor, const gchar *literal)
{
  if (!g_str_has_prefix (*cursor, literal))
    return FALSE;
  *cursor += strlen (literal);
  return TRUE;
}

/* This signed firmware reports VERIFY_GET success even when its subsequent
 * set_cached_cred fails.  The diagnostic TLV is the only returned cache result.
 * Require a matching positive cache acknowledgement before claiming restore.
 * This is an early error check, not a substitute for secure EnrollDo success.
 * Never log, return or persist credential bytes from this decoder. */
static inline gboolean
el721_decode_hwvault_restore (const guint8 *output, gsize output_size,
                              guint32 expected_index, gboolean persistent,
                              gsize *credential_size, GError **error)
{
  const GQuark domain = g_quark_from_static_string ("el721-qtee-error");
  guint32 status = G_MAXUINT32;
  guint32 cache_status = G_MAXUINT32;
  gboolean cache_seen = FALSE;
  gboolean status_seen = FALSE;
  gboolean credential_seen = FALSE;
  gsize offset = 8, end;

  *credential_size = 0;
  if (!output || output_size != EL721_HWVAULT_WIRE_SIZE ||
      el721_hv_word (output, 4) > output_size - 8)
    goto malformed;
  end = 8 + el721_hv_word (output, 4);
  while (offset + 8 <= end)
    {
      guint32 tag = el721_hv_word (output, offset);
      guint32 value = el721_hv_word (output, offset + 4);
      offset += 8;
      if ((tag >> 24) == 1)
        {
          if (tag == 0x01000001)
            {
              if (status_seen)
                goto malformed;
              status_seen = TRUE;
              status = value;
            }
        }
      else if ((tag >> 24) == 2)
        {
          if (value > end - offset)
            goto malformed;
          if (tag == 0x02010006)
            {
              if (credential_seen || !value)
                goto malformed;
              credential_seen = TRUE;
              *credential_size = value;
            }
          else if (tag == 0x02002710)
            {
              g_autofree gchar *line = g_strndup ((const gchar *) output + offset,
                                                 value);
              const gchar *cursor = strstr (line, "set_cached_cred id=");
              for (gsize i = strlen (line); i < value; i++)
                if (output[offset + i])
                  goto malformed;
              if (cursor)
                {
                  guint32 index, namespace_flag;
                  if (cache_seen ||
                      !el721_hv_literal (&cursor, "set_cached_cred id=") ||
                      !el721_hv_number (&cursor, &index) ||
                      !el721_hv_literal (&cursor, ", persistent=") ||
                      !el721_hv_number (&cursor, &namespace_flag) ||
                      !el721_hv_literal (&cursor, ", ret=") ||
                      !el721_hv_number (&cursor, &cache_status) ||
                      index != expected_index || namespace_flag != !!persistent)
                    goto malformed;
                  while (g_ascii_isspace (*cursor))
                    cursor++;
                  if (*cursor)
                    goto malformed;
                  cache_seen = TRUE;
                }
            }
          offset += value;
        }
      else
        goto malformed;
    }
  if (offset != end || !status_seen)
    goto malformed;
  if (status)
    {
      g_set_error (error, domain, 1,
                   "HwVault credential verification failed (status=%u)", status);
      goto fail;
    }
  if (!credential_seen || !cache_seen)
    {
      g_set_error (error, domain, 1,
                   "HwVault credential %u has no confirmed cache restore",
                   expected_index);
      goto fail;
    }
  if (cache_status)
    {
      g_set_error (error, domain, 1,
                   "HwVault credential %u could not be prepared for fingerprint "
                   "encryption (cache status=%u%s)", expected_index, cache_status,
                   cache_status == 9936 ? "; StrongBox Keymaster not configured" : "");
      goto fail;
    }
  return TRUE;

malformed:
  g_set_error_literal (error, domain, 1, "invalid HwVault restore response");
fail:
  *credential_size = 0;
  return FALSE;
}
