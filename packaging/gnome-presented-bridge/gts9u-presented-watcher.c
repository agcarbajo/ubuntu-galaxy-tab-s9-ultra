// SPDX-License-Identifier: MIT
#include "gts9u-presented-watcher.h"

struct _Gts9uPresentedWatcher {
  GObject parent_instance;
  ClutterStage *stage;
  gulong handler;
};

G_DEFINE_TYPE (Gts9uPresentedWatcher, gts9u_presented_watcher, G_TYPE_OBJECT)

enum {
  PRESENTED,
  N_SIGNALS,
};

static guint signals[N_SIGNALS];

typedef struct {
  Gts9uPresentedWatcher *watcher;
  ClutterStageView *view;
} PendingPresentation;

static gboolean
emit_presented (gpointer data)
{
  PendingPresentation *pending = data;

  if (pending->watcher->stage)
    g_signal_emit (pending->watcher, signals[PRESENTED], 0, pending->view);

  return G_SOURCE_REMOVE;
}

static void
free_presentation (gpointer data)
{
  PendingPresentation *pending = data;

  g_object_unref (pending->view);
  g_object_unref (pending->watcher);
  g_free (pending);
}

static void
stage_presented (ClutterStage     *stage,
                 ClutterStageView *view,
                 gpointer          frame_info,
                 gpointer          user_data)
{
  Gts9uPresentedWatcher *self = user_data;
  PendingPresentation *pending;

  (void) stage;
  (void) frame_info;
  pending = g_new0 (PendingPresentation, 1);
  pending->watcher = g_object_ref (self);
  pending->view = g_object_ref (view);
  g_idle_add_full (G_PRIORITY_HIGH, emit_presented, pending,
                   free_presentation);
}

static void
gts9u_presented_watcher_dispose (GObject *object)
{
  Gts9uPresentedWatcher *self = GTS9U_PRESENTED_WATCHER (object);

  gts9u_presented_watcher_stop (self);
  G_OBJECT_CLASS (gts9u_presented_watcher_parent_class)->dispose (object);
}

void
gts9u_presented_watcher_stop (Gts9uPresentedWatcher *self)
{
  g_return_if_fail (GTS9U_IS_PRESENTED_WATCHER (self));
  if (self->handler) {
    g_signal_handler_disconnect (self->stage, self->handler);
    self->handler = 0;
  }
  g_clear_object (&self->stage);
}

static void
gts9u_presented_watcher_class_init (Gts9uPresentedWatcherClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);

  object_class->dispose = gts9u_presented_watcher_dispose;
  signals[PRESENTED] = g_signal_new ("presented", G_TYPE_FROM_CLASS (klass),
                                    G_SIGNAL_RUN_LAST, 0, NULL, NULL, NULL,
                                    G_TYPE_NONE, 1, CLUTTER_TYPE_STAGE_VIEW);
}

static void
gts9u_presented_watcher_init (Gts9uPresentedWatcher *self)
{
  (void) self;
}

Gts9uPresentedWatcher *
gts9u_presented_watcher_new (ClutterStage *stage)
{
  Gts9uPresentedWatcher *self;

  g_return_val_if_fail (CLUTTER_IS_STAGE (stage), NULL);
  self = g_object_new (GTS9U_TYPE_PRESENTED_WATCHER, NULL);
  self->stage = g_object_ref (stage);
  self->handler = g_signal_connect (stage, "presented",
                                    G_CALLBACK (stage_presented), self);
  return self;
}
