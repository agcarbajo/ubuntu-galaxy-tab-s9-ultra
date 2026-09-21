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

static inline gboolean
el721_ui_light_ready (const gchar *contents, gint64 token, gint64 now)
{
  g_autofree gchar *expected = NULL;
  if (token <= 0 || token > G_MAXINT64 - G_USEC_PER_SEC ||
      token > now || now - token >= G_USEC_PER_SEC)
    return FALSE;
  expected = g_strdup_printf ("ready %" G_GINT64_FORMAT "\n", token + G_USEC_PER_SEC);
  return g_strcmp0 (contents, expected) == 0 && el721_ui_lease_ready (contents, now);
}
