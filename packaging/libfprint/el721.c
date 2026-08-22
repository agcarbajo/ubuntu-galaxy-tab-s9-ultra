/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* EgisTec EL721 secure UDFPS driver for the Galaxy Tab S9 Ultra. */

#define FP_COMPONENT "el721"

#include "drivers_api.h"
#include "el721.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include <glib/gstdio.h>

#define EL721_FIRMWARE "/usr/lib/firmware/gts9u/fingerprint"
#define EL721_TOUCH "/sys/bus/i2c/devices/13-005d"
#define EL721_PANEL "/sys/class/backlight/ae94000.dsi.0"
#define EL721_POLL_MS 45
#define EL721_ACTION_TIMEOUT_US (90 * G_USEC_PER_SEC)
#define EL721_ENROLL_STAGES 10

G_DEFINE_TYPE (FpiDeviceEl721, fpi_device_el721, FP_TYPE_DEVICE)

static const FpIdEntry id_table[] = {
  {
    .udev_types = FPI_DEVICE_UDEV_SUBTYPE_PLATFORM,
    .spi_acpi_id = "egis-el721",
  },
  { .udev_types = 0 },
};

static gboolean
write_sysfs (const gchar *path, const gchar *value, GError **error)
{
  FILE *stream = g_fopen (path, "w");
  if (!stream)
    {
      g_set_error (error, G_FILE_ERROR, g_file_error_from_errno (errno),
                   "cannot open %s: %s", path, g_strerror (errno));
      return FALSE;
    }
  if (fputs (value, stream) == EOF || fclose (stream))
    {
      g_set_error (error, G_FILE_ERROR, g_file_error_from_errno (errno),
                   "cannot write %s: %s", path, g_strerror (errno));
      return FALSE;
    }
  return TRUE;
}

static gboolean
write_child (const gchar *directory, const gchar *name, const gchar *value,
             GError **error)
{
  g_autofree gchar *path = g_build_filename (directory, name, NULL);
  return write_sysfs (path, value, error);
}

static void
call_overlay (const gchar *method)
{
  g_autoptr(GDir) run_user = g_dir_open ("/run/user", 0, NULL);
  const gchar *entry;

  if (!run_user)
    return;
  while ((entry = g_dir_read_name (run_user)))
    {
      g_autofree gchar *bus_path = g_build_filename ("/run/user", entry, "bus", NULL);
      g_autofree gchar *address = NULL;
      g_autoptr(GDBusConnection) connection = NULL;
      g_autoptr(GVariant) response = NULL;
      g_autoptr(GError) error = NULL;

      if (!g_file_test (bus_path, G_FILE_TEST_EXISTS))
        continue;
      address = g_strdup_printf ("unix:path=%s", bus_path);
      connection = g_dbus_connection_new_for_address_sync (
        address,
        G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT |
        G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION,
        NULL, NULL, &error);
      if (!connection)
        continue;
      response = g_dbus_connection_call_sync (
        connection,
        "io.github.agcarbajo.Gts9uFingerprintOverlay",
        "/io/github/agcarbajo/Gts9uFingerprintOverlay",
        "io.github.agcarbajo.Gts9uFingerprintOverlay",
        method, NULL, NULL, G_DBUS_CALL_FLAGS_NONE, 500, NULL, &error);
      if (response)
        return;
    }
}

static gboolean
set_sensor_power (FpiDeviceEl721 *self, gboolean enabled, GError **error)
{
  return write_child (self->sysfs_path, "sensor_power", enabled ? "1\n" : "0\n",
                      error);
}

static gboolean
udfps_begin (FpiDeviceEl721 *self, GError **error)
{
  if (self->udfps_active)
    return TRUE;

  if (!write_child (EL721_TOUCH, "fod_rect", "854 2732 994 2872\n", error) ||
      !write_child (EL721_TOUCH, "fod_enable", "1\n", error))
    return FALSE;
  call_overlay ("Show");
  if (!write_child (EL721_PANEL, "fod_mode", "1\n", error))
    {
      write_child (EL721_TOUCH, "fod_enable", "0\n", NULL);
      call_overlay ("Hide");
      return FALSE;
    }
  self->udfps_active = TRUE;
  return TRUE;
}

static void
udfps_end (FpiDeviceEl721 *self)
{
  if (!self->udfps_active)
    return;
  write_child (EL721_PANEL, "fod_mode", "0\n", NULL);
  write_child (EL721_TOUCH, "fod_enable", "0\n", NULL);
  call_overlay ("Hide");
  self->udfps_active = FALSE;
}

static void
stop_poll (FpiDeviceEl721 *self)
{
  if (!self->poll_source)
    return;
  g_source_destroy (self->poll_source);
  g_clear_pointer (&self->poll_source, g_source_unref);
}

static void
action_cleanup (FpiDeviceEl721 *self)
{
  stop_poll (self);
  udfps_end (self);
  set_sensor_power (self, FALSE, NULL);
  self->action = EL721_ACTION_NONE;
  self->finger_present = FALSE;
  self->opcode = 0;
  fpi_device_report_finger_status (FP_DEVICE (self), FP_FINGER_STATUS_NONE);
}

static void
action_fail (FpiDeviceEl721 *self, GError *error)
{
  FpDevice *device = FP_DEVICE (self);
  El721Action action = self->action;
  action_cleanup (self);
  switch (action)
    {
    case EL721_ACTION_NONE:
      g_clear_error (&error);
      break;
    case EL721_ACTION_ENROLL:
      fpi_device_enroll_complete (device, NULL, error);
      break;
    case EL721_ACTION_VERIFY:
      fpi_device_verify_complete (device, error);
      break;
    case EL721_ACTION_IDENTIFY:
      fpi_device_identify_complete (device, error);
      break;
    }
}

static gboolean
read_fod_pressed (gboolean *pressed, GError **error)
{
  g_autofree gchar *path = g_build_filename (EL721_TOUCH, "fod_state", NULL);
  g_autofree gchar *state = NULL;
  if (!g_file_get_contents (path, &state, NULL, error))
    return FALSE;
  *pressed = g_str_has_prefix (state, "pressed") ||
             g_str_has_prefix (state, "vi ");
  return TRUE;
}

static gboolean
print_data (FpPrint *print, guint32 *template_id, const guint8 **bytes,
            gsize *size)
{
  g_autoptr(GVariant) data = NULL;
  g_autoptr(GVariant) array = NULL;
  if (!print)
    return FALSE;
  g_object_get (print, "fpi-data", &data, NULL);
  if (!data || !g_variant_is_of_type (data, G_VARIANT_TYPE ("(uay)")))
    return FALSE;
  g_variant_get (data, "(u@ay)", template_id, &array);
  *bytes = g_variant_get_fixed_array (array, size, sizeof (guint8));
  return *bytes != NULL && *size > 0;
}

static GByteArray *
build_gallery (FpiDeviceEl721 *self, GPtrArray **prints_out,
               gchar **user_out, GError **error)
{
  FpDevice *device = FP_DEVICE (self);
  FpiDeviceAction current = fpi_device_get_current_action (device);
  GPtrArray *prints = NULL;
  FpPrint *single = NULL;
  GByteArray *gallery = g_byte_array_new ();
  guint i;

  if (current == FPI_DEVICE_ACTION_VERIFY)
    {
      prints = g_ptr_array_new ();
      fpi_device_get_verify_data (device, &single);
      g_ptr_array_add (prints, single);
    }
  else
    {
      fpi_device_get_identify_data (device, &prints);
      g_ptr_array_ref (prints);
    }
  for (i = 0; i < prints->len; i++)
    {
      const guint8 *bytes;
      gsize size;
      guint32 template_id;
      FpPrint *print = g_ptr_array_index (prints, i);
      if (!print_data (print, &template_id, &bytes, &size))
        {
          g_set_error_literal (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_INVALID,
                               "invalid EL721 template");
          g_ptr_array_unref (prints);
          g_byte_array_unref (gallery);
          return NULL;
        }
      g_byte_array_append (gallery, bytes, size);
    }
  if (!prints->len)
    {
      g_set_error_literal (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_NOT_FOUND,
                           "no EL721 templates supplied");
      g_ptr_array_unref (prints);
      g_byte_array_unref (gallery);
      return NULL;
    }
  *user_out = fpi_print_generate_user_id (g_ptr_array_index (prints, 0));
  *prints_out = prints;
  return gallery;
}

static void poll_action (FpDevice *device, gpointer user_data);

static void
schedule_poll (FpiDeviceEl721 *self)
{
  self->poll_source = fpi_device_add_timeout (FP_DEVICE (self), EL721_POLL_MS,
                                               poll_action, NULL, NULL);
  g_source_ref (self->poll_source);
}

static FpPrint *
find_print (GPtrArray *prints, guint32 template_id)
{
  guint i;
  for (i = 0; i < prints->len; i++)
    {
      const guint8 *bytes;
      gsize size;
      guint32 candidate;
      if (print_data (g_ptr_array_index (prints, i), &candidate, &bytes, &size) &&
          candidate == template_id)
        return g_ptr_array_index (prints, i);
    }
  return NULL;
}

static void
finish_identify (FpiDeviceEl721 *self, guint32 template_id)
{
  FpDevice *device = FP_DEVICE (self);
  FpiDeviceAction current = fpi_device_get_current_action (device);
  GPtrArray *prints = NULL;
  FpPrint *verify_print = NULL;
  FpPrint *match = NULL;
  El721Reply final = { 0 };

  if (current == FPI_DEVICE_ACTION_VERIFY)
    {
      prints = g_ptr_array_new ();
      fpi_device_get_verify_data (device, &verify_print);
      g_ptr_array_add (prints, verify_print);
    }
  else
    {
      fpi_device_get_identify_data (device, &prints);
      g_ptr_array_ref (prints);
    }
  match = find_print (prints, template_id);
  el721_qtee_identify_final (self->qtee, &final, NULL);
  el721_reply_clear (&final);
  action_cleanup (self);
  if (current == FPI_DEVICE_ACTION_VERIFY)
    {
      fpi_device_verify_report (device, match ? FPI_MATCH_SUCCESS : FPI_MATCH_FAIL,
                                match, NULL);
      fpi_device_verify_complete (device, NULL);
    }
  else
    {
      fpi_device_identify_report (device, match, match, NULL);
      fpi_device_identify_complete (device, NULL);
    }
  g_ptr_array_unref (prints);
}

static gboolean
handle_enroll_do (FpiDeviceEl721 *self, GError **error)
{
  El721Reply reply = { 0 };
  guint progress = 0;

  if (!el721_qtee_enroll_do (self->qtee, &reply, error))
    return FALSE;
  fp_dbg ("EnrollDo result=%u status=%u opcode=%u fields=%u/%u/%u data=%zu",
          reply.result, reply.status, reply.opcode, reply.quality, reply.progress,
          reply.remaining, reply.data ? g_bytes_get_size (reply.data) : 0);
  if (reply.result)
    {
      GError *retry = fpi_device_retry_new (FP_DEVICE_RETRY_GENERAL);
      fpi_device_enroll_progress (FP_DEVICE (self), self->enroll_stage, NULL, retry);
      el721_reply_clear (&reply);
      return TRUE;
    }

  if (reply.progress <= 100)
    progress = reply.progress;
  if (reply.remaining <= EL721_ENROLL_STAGES && reply.remaining > 0)
    progress = MAX (progress, (EL721_ENROLL_STAGES - reply.remaining) * 100 /
                              EL721_ENROLL_STAGES);
  progress = MIN (progress, 100);
  if (progress)
    {
      guint stage = MIN (EL721_ENROLL_STAGES - 1,
                         (progress * EL721_ENROLL_STAGES + 99) / 100);
      while (self->enroll_stage < stage)
        {
          self->enroll_stage++;
          fpi_device_enroll_progress (FP_DEVICE (self), self->enroll_stage,
                                      NULL, NULL);
        }
    }
  if (progress >= 100 || (reply.progress > 0 && reply.remaining == 0))
    {
      FpPrint *print = NULL;
      El721Reply final = { 0 };
      gsize size;
      const guint8 *bytes;
      GVariant *array;
      GVariant *data;

      el721_reply_clear (&reply);
      if (!el721_qtee_enroll_final (self->qtee, &final, error))
        {
          el721_reply_clear (&final);
          return FALSE;
        }
      if (final.result || !final.data)
        {
          g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                       "EL721 EnrollFinal returned %u without a template",
                       final.result);
          el721_reply_clear (&final);
          return FALSE;
        }
      bytes = g_bytes_get_data (final.data, &size);
      fpi_device_get_enroll_data (FP_DEVICE (self), &print);
      array = g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, bytes, size, 1);
      data = g_variant_new ("(u@ay)", self->template_id, array);
      fpi_print_set_type (print, FPI_PRINT_RAW);
      fpi_print_set_device_stored (print, FALSE);
      g_object_set (print, "fpi-data", data, NULL);
      action_cleanup (self);
      fpi_device_enroll_progress (FP_DEVICE (self), EL721_ENROLL_STAGES,
                                  print, NULL);
      fpi_device_enroll_complete (FP_DEVICE (self), g_object_ref (print), NULL);
      el721_reply_clear (&final);
      return TRUE;
    }
  el721_reply_clear (&reply);
  return TRUE;
}

static gboolean
handle_identify_do (FpiDeviceEl721 *self, GError **error)
{
  El721Reply reply = { 0 };
  if (!el721_qtee_identify_do (self->qtee, self->opcode, &reply, error))
    return FALSE;
  fp_dbg ("IdentifyDo result=%u status=%u opcode=%u template=%u quality=%u update=%zu",
          reply.result, reply.status, reply.opcode, reply.template_id,
          reply.quality, reply.data ? g_bytes_get_size (reply.data) : 0);
  self->opcode = reply.opcode;
  if (reply.result == 39)
    {
      GError *retry = fpi_device_retry_new (FP_DEVICE_RETRY_GENERAL);
      if (self->action == EL721_ACTION_VERIFY)
        fpi_device_verify_report (FP_DEVICE (self), FPI_MATCH_ERROR, NULL, retry);
      else
        fpi_device_identify_report (FP_DEVICE (self), NULL, NULL, retry);
    }
  else if (reply.result)
    {
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 IdentifyDo returned %u", reply.result);
      el721_reply_clear (&reply);
      return FALSE;
    }
  else if (reply.opcode == 0)
    {
      guint32 template_id = reply.template_id;
      el721_reply_clear (&reply);
      finish_identify (self, template_id);
      return TRUE;
    }
  el721_reply_clear (&reply);
  return TRUE;
}

static void
poll_action (FpDevice *device, gpointer user_data)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  g_autoptr(GError) error = NULL;
  gboolean pressed = FALSE;
  gboolean process;

  g_clear_pointer (&self->poll_source, g_source_unref);
  if (self->action == EL721_ACTION_NONE)
    return;
  if (g_cancellable_is_cancelled (fpi_device_get_cancellable (device)))
    {
      action_fail (self, g_error_new_literal (G_IO_ERROR, G_IO_ERROR_CANCELLED,
                                               "fingerprint operation cancelled"));
      return;
    }
  if (g_get_monotonic_time () - self->action_started > EL721_ACTION_TIMEOUT_US)
    {
      action_fail (self, fpi_device_error_new_msg (FP_DEVICE_ERROR_GENERAL,
                                                   "EL721 operation timed out"));
      return;
    }
  if (!read_fod_pressed (&pressed, &error))
    {
      action_fail (self, g_steal_pointer (&error));
      return;
    }
  if (pressed != self->finger_present)
    {
      self->finger_present = pressed;
      fpi_device_report_finger_status_changes (
        device,
        pressed ? FP_FINGER_STATUS_PRESENT : FP_FINGER_STATUS_NEEDED,
        pressed ? FP_FINGER_STATUS_NEEDED : FP_FINGER_STATUS_PRESENT);
    }
  process = pressed || (self->action != EL721_ACTION_ENROLL && self->opcode != 4);
  if (process)
    {
      gboolean ok = self->action == EL721_ACTION_ENROLL ?
                    handle_enroll_do (self, &error) :
                    handle_identify_do (self, &error);
      if (!ok)
        {
          action_fail (self, g_steal_pointer (&error));
          return;
        }
      if (self->action == EL721_ACTION_NONE)
        return;
    }
  schedule_poll (self);
}

static gboolean
operation_prepare (FpiDeviceEl721 *self, GError **error)
{
  if (!set_sensor_power (self, TRUE, error))
    return FALSE;
  if (!el721_qtee_prepare (self->qtee, error))
    {
      set_sensor_power (self, FALSE, NULL);
      return FALSE;
    }
  return TRUE;
}

static void
el721_enroll (FpDevice *device)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  FpPrint *print = NULL;
  g_autofree gchar *user = NULL;
  g_autoptr(GError) error = NULL;
  El721Reply reply = { 0 };

  fpi_device_get_enroll_data (device, &print);
  user = fpi_print_generate_user_id (print);
  self->template_id = fp_print_get_finger (print);
  if (!self->template_id)
    self->template_id = 1;
  if (!operation_prepare (self, &error) ||
      !el721_qtee_enroll_init (self->qtee, (guint8 *) user, strlen (user),
                               self->template_id, &reply, &error))
    {
      el721_reply_clear (&reply);
      set_sensor_power (self, FALSE, NULL);
      fpi_device_enroll_complete (device, NULL, g_steal_pointer (&error));
      return;
    }
  if (reply.result)
    g_set_error (&error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                 "EL721 EnrollInit returned %u", reply.result);
  if (error || !udfps_begin (self, &error))
    {
      el721_reply_clear (&reply);
      set_sensor_power (self, FALSE, NULL);
      fpi_device_enroll_complete (device, NULL, g_steal_pointer (&error));
      return;
    }
  fp_dbg ("EnrollInit status=%u opcode=%u", reply.status, reply.opcode);
  el721_reply_clear (&reply);
  self->action = EL721_ACTION_ENROLL;
  self->enroll_stage = 0;
  self->action_started = g_get_monotonic_time ();
  fpi_device_report_finger_status (device, FP_FINGER_STATUS_NEEDED);
  schedule_poll (self);
}

static void
start_identify (FpDevice *device)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  g_autoptr(GError) error = NULL;
  g_autoptr(GByteArray) gallery = NULL;
  g_autoptr(GPtrArray) prints = NULL;
  g_autofree gchar *user = NULL;
  El721Reply reply = { 0 };
  FpiDeviceAction current = fpi_device_get_current_action (device);

  gallery = build_gallery (self, &prints, &user, &error);
  if (!gallery || !operation_prepare (self, &error) ||
      !el721_qtee_identify_init (self->qtee, (guint8 *) user, strlen (user),
                                 gallery->data, gallery->len, NULL, 0,
                                 &reply, &error))
    {
      el721_reply_clear (&reply);
      set_sensor_power (self, FALSE, NULL);
      if (current == FPI_DEVICE_ACTION_VERIFY)
        fpi_device_verify_complete (device, g_steal_pointer (&error));
      else
        fpi_device_identify_complete (device, g_steal_pointer (&error));
      return;
    }
  if (reply.result)
    g_set_error (&error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                 "EL721 IdentifyInit returned %u", reply.result);
  if (error || !udfps_begin (self, &error))
    {
      el721_reply_clear (&reply);
      set_sensor_power (self, FALSE, NULL);
      if (current == FPI_DEVICE_ACTION_VERIFY)
        fpi_device_verify_complete (device, g_steal_pointer (&error));
      else
        fpi_device_identify_complete (device, g_steal_pointer (&error));
      return;
    }
  self->opcode = reply.status;
  fp_dbg ("IdentifyInit status/opcode=%u id-bytes=%zu", self->opcode,
          reply.data ? g_bytes_get_size (reply.data) : 0);
  el721_reply_clear (&reply);
  self->action = current == FPI_DEVICE_ACTION_VERIFY ?
                 EL721_ACTION_VERIFY : EL721_ACTION_IDENTIFY;
  self->action_started = g_get_monotonic_time ();
  fpi_device_report_finger_status (device, FP_FINGER_STATUS_NEEDED);
  schedule_poll (self);
}

static void
el721_cancel (FpDevice *device)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  El721Reply reply = { 0 };
  if (self->action == EL721_ACTION_NONE)
    return;
  el721_qtee_cancel (self->qtee, &reply, NULL);
  el721_reply_clear (&reply);
  action_fail (self, g_error_new_literal (G_IO_ERROR, G_IO_ERROR_CANCELLED,
                                           "fingerprint operation cancelled"));
}

static void
el721_probe (FpDevice *device)
{
  const gchar *path = fpi_device_get_udev_data (device, FPI_DEVICE_UDEV_SUBTYPE_PLATFORM);
  g_autofree gchar *vendor_path = NULL;
  g_autofree gchar *name_path = NULL;
  g_autofree gchar *vendor = NULL;
  g_autofree gchar *name = NULL;
  g_autoptr(GError) error = NULL;

  if (!path)
    goto unsupported;
  vendor_path = g_build_filename (path, "vendor", NULL);
  name_path = g_build_filename (path, "name", NULL);
  if (!g_file_get_contents (vendor_path, &vendor, NULL, &error) ||
      !g_file_get_contents (name_path, &name, NULL, &error))
    {
      fpi_device_probe_complete (device, NULL, NULL, g_steal_pointer (&error));
      return;
    }
  g_strchomp (vendor);
  g_strchomp (name);
  if (!g_str_equal (vendor, "EGISTEC") || !g_str_equal (name, "EL721"))
    goto unsupported;
  fpi_device_probe_complete (device, "gts9u-el721", "EgisTec EL721 UDFPS", NULL);
  return;

unsupported:
  fpi_device_probe_complete (device, NULL, NULL,
                             fpi_device_error_new (FP_DEVICE_ERROR_NOT_SUPPORTED));
}

static void
el721_open (FpDevice *device)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  g_autoptr(GError) error = NULL;
  self->sysfs_path = g_strdup (fpi_device_get_udev_data (
    device, FPI_DEVICE_UDEV_SUBTYPE_PLATFORM));
  if (!set_sensor_power (self, TRUE, &error))
    goto fail;
  self->qtee = el721_qtee_open (EL721_FIRMWARE, &error);
  if (!self->qtee || !el721_qtee_prepare (self->qtee, &error))
    goto fail;
  set_sensor_power (self, FALSE, NULL);
  fpi_device_open_complete (device, NULL);
  return;

fail:
  set_sensor_power (self, FALSE, NULL);
  el721_qtee_close (self->qtee);
  self->qtee = NULL;
  fpi_device_open_complete (device, g_steal_pointer (&error));
}

static void
el721_close (FpDevice *device)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  action_cleanup (self);
  el721_qtee_close (self->qtee);
  self->qtee = NULL;
  g_clear_pointer (&self->sysfs_path, g_free);
  fpi_device_close_complete (device, NULL);
}

static void
fpi_device_el721_init (FpiDeviceEl721 *self)
{
}

static void
fpi_device_el721_class_init (FpiDeviceEl721Class *klass)
{
  FpDeviceClass *device_class = FP_DEVICE_CLASS (klass);
  device_class->id = FP_COMPONENT;
  device_class->full_name = "EgisTec EL721 secure UDFPS";
  device_class->type = FP_DEVICE_TYPE_UDEV;
  device_class->scan_type = FP_SCAN_TYPE_PRESS;
  device_class->id_table = id_table;
  device_class->nr_enroll_stages = EL721_ENROLL_STAGES;
  device_class->temp_hot_seconds = -1;
  device_class->probe = el721_probe;
  device_class->open = el721_open;
  device_class->close = el721_close;
  device_class->enroll = el721_enroll;
  device_class->verify = start_identify;
  device_class->identify = start_identify;
  device_class->cancel = el721_cancel;
  fpi_device_class_auto_initialize_features (device_class);
}
