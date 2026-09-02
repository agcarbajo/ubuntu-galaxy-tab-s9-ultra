/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include <glib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

static inline gboolean
el721_ui_lease_ready (const gchar *contents, gint64 now)
{
  gchar *end = NULL;
  gint64 expires;
  if (!contents || now < 0 || !g_str_has_prefix (contents, "ready ") ||
      !g_ascii_isdigit (contents[6]))
    return FALSE;
  errno = 0;
  expires = g_ascii_strtoll (contents + 6, &end, 10);
  return !errno && (*end == '\0' || (*end == '\n' && end[1] == '\0')) && expires > now &&
         expires - now <= 2 * G_USEC_PER_SEC;
}
