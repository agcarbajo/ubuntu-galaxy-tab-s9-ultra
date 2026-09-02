/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once

#include "fpi-device.h"
#include "el721-qtee.h"

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
  gboolean capture_pending;
  gint64 finger_pressed_at;
  gint64 udfps_refreshed;
  guint64 fod_sequence;
  guint32 opcode;
  guint32 template_id;
  guint enroll_stage;
  gint64 action_started;
};
