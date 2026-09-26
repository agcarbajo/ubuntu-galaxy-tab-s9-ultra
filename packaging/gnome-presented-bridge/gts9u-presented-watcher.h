// SPDX-License-Identifier: MIT
#pragma once

#include <clutter/clutter.h>

G_BEGIN_DECLS

#define GTS9U_TYPE_PRESENTED_WATCHER (gts9u_presented_watcher_get_type ())
G_DECLARE_FINAL_TYPE (Gts9uPresentedWatcher, gts9u_presented_watcher,
                      GTS9U, PRESENTED_WATCHER, GObject)

/**
 * gts9u_presented_watcher_new:
 * @stage: the GNOME Shell stage
 *
 * Watches the stage's native presentation signal. The frame-info pointer is
 * intentionally kept in C because GJS cannot marshal its non-null value.
 *
 * Returns: (transfer full): a watcher for @stage
 */
Gts9uPresentedWatcher *gts9u_presented_watcher_new (ClutterStage *stage);

void gts9u_presented_watcher_stop (Gts9uPresentedWatcher *self);

G_END_DECLS
