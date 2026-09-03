/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once

#include "fpi-device.h"
#include "el721-qtee.h"
#include "el721-gallery.h"

G_DECLARE_FINAL_TYPE (FpiDeviceEl721, fpi_device_el721, FPI, DEVICE_EL721, FpDevice)

typedef enum
{
  EL721_ACTION_NONE,
  EL721_ACTION_ENROLL,
  EL721_ACTION_VERIFY,
  EL721_ACTION_IDENTIFY,
} El721Action;

struct _FpiDeviceEl721
{
  FpDevice parent;
  gchar *sysfs_path;
  El721Qtee *qtee;
  GSource *poll_source;
  El721Action action;
  gboolean finger_present;
  gboolean udfps_active;
  gboolean udfps_lit;
  gboolean touch_inhibited;
  gint64 capture_deadline;
  gint64 visual_refreshed;
  gboolean enroll_armed;
  guint32 enroll_arm_status;
  gint64 udfps_refreshed;
  guint64 fod_sequence;
  guint32 opcode;
  guint32 template_id;
  guint enroll_stage;
  gchar *enroll_user;
  El721Gallery gallery;
  GPtrArray *match_prints;
  gboolean match_continue;
  gint64 action_started;
};
