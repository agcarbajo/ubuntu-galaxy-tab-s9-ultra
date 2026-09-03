/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include "el721-print-wire.h"

/* IdentifyInit accepts ONE authenticated identity, not an array of identities.
 * Enrollments use independent random identities, so never concatenate their
 * ciphertexts or replace the identity to force them into one TA transaction.
 * Slots are only meaningful within the currently loaded entry. */
typedef struct
{
  gchar *identity;
  guint32 slot;
  GBytes *opaque;
} El721GalleryEntry;

typedef struct
{
  GPtrArray *entries;
  guint current;
} El721Gallery;

static inline void
el721_gallery_entry_free (gpointer data)
{
  El721GalleryEntry *entry = data;
  g_free (entry->identity);
  g_clear_pointer (&entry->opaque, g_bytes_unref);
  g_free (entry);
}

static inline void
el721_gallery_clear (El721Gallery *gallery)
{
  g_clear_pointer (&gallery->entries, g_ptr_array_unref);
  gallery->current = 0;
}

static inline gboolean
el721_gallery_add (El721Gallery *gallery, GVariant *data, GError **error)
{
  El721GalleryEntry *entry = g_new0 (El721GalleryEntry, 1);
  if (!el721_print_unpack (data, &entry->identity, &entry->slot,
                           &entry->opaque, error))
    {
      el721_gallery_entry_free (entry);
      return FALSE;
    }
  if (!gallery->entries)
    gallery->entries = g_ptr_array_new_with_free_func (el721_gallery_entry_free);
  g_ptr_array_add (gallery->entries, entry);
  return TRUE;
}

static inline El721GalleryEntry *
el721_gallery_current (const El721Gallery *gallery)
{
  if (!gallery->entries || gallery->current >= gallery->entries->len)
    return NULL;
  return g_ptr_array_index (gallery->entries, gallery->current);
}

/* Only call after an explicit secure NO_MATCH and successful IdentifyFinal.
 * Exhaustion is sticky, so an unknown finger cannot wrap and scan forever. */
static inline gboolean
el721_gallery_next (El721Gallery *gallery)
{
  if (el721_gallery_current (gallery))
    gallery->current++;
  return el721_gallery_current (gallery) != NULL;
}

static inline gboolean
el721_gallery_matches_current (const El721Gallery *gallery, guint32 slot)
{
  const El721GalleryEntry *entry = el721_gallery_current (gallery);
  return entry && slot && slot == entry->slot;
}
