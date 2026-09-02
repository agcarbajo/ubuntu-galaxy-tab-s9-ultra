/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* EgisTec EL721 secure UDFPS driver for the Galaxy Tab S9 Ultra. */

#define FP_COMPONENT "el721"

#include "drivers_api.h"
#include "el721.h"
#include "el721-print-wire.h"
#include "el721-identify-wire.h"
#include "el721-match-retry.h"
#include "el721-touch-light.h"
#include "el721-ui-lease.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include <glib/gstdio.h>

#define EL721_FIRMWARE "/usr/lib/firmware/gts9u/fingerprint"
#define EL721_TOUCH "/sys/bus/i2c/devices/13-005d"
#define EL721_PANEL "/sys/class/backlight/ae94000.dsi.0"
#define EL721_VISUAL_STATE "/run/gts9u-fingerprint/active"
#define EL721_UI_LEASE "/run/gts9u-fingerprint-ui/ready"
#define EL721_BATTERY_TEMP "/sys/class/power_supply/battery/temp"
#define EL721_BATTERY_TEMP_FALLBACK "/sys/class/power_supply/sm5714-battery/temp"
#define EL721_POLL_MS 45
#define EL721_ACTION_TIMEOUT_US (90 * G_USEC_PER_SEC)
#define EL721_UDFPS_REFRESH_US (5 * G_USEC_PER_SEC)
#define EL721_ENROLL_STAGES 17
#define EL721_OP_WAIT_INTERRUPT 4U
#define EL721_OP_NOTIFY_DOWN 5U
#define EL721_OP_CAPTURE_SUCCESS 6U
#define EL721_OP_ACQUIRED_EVENT 63U
#define EL721_OP_CAPTURE_STEP 87U
#define EL721_CAPTURE_STEPS_MAX 16U

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

static gboolean
read_fod_state (gboolean *pressed, gboolean *released, guint *x_out,
                guint *y_out, guint64 *sequence, GError **error)
{
  g_autofree gchar *path = g_build_filename (EL721_TOUCH, "fod_state", NULL);
  g_autofree gchar *state = NULL;
  gchar name[16] = { 0 };
  guint x;
  guint y;

  if (!g_file_get_contents (path, &state, NULL, error))
    return FALSE;
  if (sscanf (state, "%15s %u %u %" G_GUINT64_FORMAT,
              name, &x, &y, sequence) != 4)
    {
      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                   "invalid FOD state: %s", state);
      return FALSE;
    }
  *pressed = g_str_equal (name, "pressed") || g_str_equal (name, "vi");
  *released = g_str_equal (name, "released");
  *x_out = x;
  *y_out = y;
  return TRUE;
}

static gboolean
read_battery_temperature (gint32 *temperature, GError **error)
{
  g_autofree gchar *contents = NULL;
  const gchar *path = EL721_BATTERY_TEMP;
  gchar *end = NULL;
  gint64 value;

  if (!g_file_get_contents (path, &contents, NULL, NULL))
    {
      path = EL721_BATTERY_TEMP_FALLBACK;
      if (!g_file_get_contents (path, &contents, NULL, error))
        return FALSE;
    }
  value = g_ascii_strtoll (contents, &end, 10);
  if (end == contents || value < G_MININT32 || value > G_MAXINT32)
    {
      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                   "invalid battery temperature in %s: %s", path, contents);
      return FALSE;
    }
  *temperature = (gint32) value;
  return TRUE;
}

static gboolean
set_sensor_power (FpiDeviceEl721 *self, gboolean enabled, GError **error)
{
  return write_child (self->sysfs_path, "sensor_power", enabled ? "1\n" : "0\n",
                      error);
}

static gboolean
udfps_publish (FpiDeviceEl721 *self, GError **error)
{
  gint64 now = g_get_monotonic_time ();
  g_autofree gchar *state = NULL;

  if (self->visual_refreshed && now - self->visual_refreshed < G_USEC_PER_SEC)
    return TRUE;
  /* Root-owned RuntimeDirectory; Shell can only read this short lease. No
   * identity, template or authentication result crosses this boundary. */
  state = g_strdup_printf ("active %" G_GINT64_FORMAT "\n",
                           now + 3 * G_USEC_PER_SEC);
  if (!g_file_set_contents_full (EL721_VISUAL_STATE, state, -1,
                                 G_FILE_SET_CONTENTS_CONSISTENT, 0644, error))
    return FALSE;
  self->visual_refreshed = now;
  return TRUE;
}

static gboolean
udfps_light (FpiDeviceEl721 *self, gboolean enabled, GError **error)
{
  if (!write_child (EL721_PANEL, "fod_mode", enabled ? "1\n" : "0\n", error))
    return FALSE;
  self->udfps_lit = enabled;
  self->udfps_refreshed = enabled ? g_get_monotonic_time () : 0;
  return TRUE;
}

static gboolean
udfps_begin (FpiDeviceEl721 *self, GError **error)
{
  gboolean pressed;
  gboolean released;
  guint x;
  guint y;

  if (self->udfps_active)
    return TRUE;

  if (!write_child (EL721_TOUCH, "fod_rect", "854 2732 994 2872\n", error) ||
      !write_child (EL721_TOUCH, "fod_enable", "0\n", error))
    return FALSE;
  if (!read_fod_state (&pressed, &released, &x, &y, &self->fod_sequence,
                       error))
    {
      write_child (EL721_TOUCH, "fod_enable", "0\n", NULL);
      return FALSE;
    }
  self->enroll_armed = FALSE;
  self->enroll_arm_status = 0;
  self->capture_deadline = 0;
  self->visual_refreshed = 0;
  if (!udfps_light (self, FALSE, error) || !udfps_publish (self, error))
    {
      write_child (EL721_TOUCH, "fod_enable", "0\n", NULL);
      g_unlink (EL721_VISUAL_STATE);
      return FALSE;
    }
  self->udfps_active = TRUE;
  self->touch_inhibited = TRUE;
  g_message ("EL721 touch-to-light armed; waiting for visible target without HBM");
  return TRUE;
}

static gboolean
udfps_refresh (FpiDeviceEl721 *self, GError **error)
{
  gint64 now;

  if (!self->udfps_lit)
    return TRUE;
  now = g_get_monotonic_time ();
  if (now - self->udfps_refreshed < EL721_UDFPS_REFRESH_US)
    return TRUE;

  /* Rewriting an already enabled mode rearms the panel's safety watchdog.
   * The unprivileged desktop integration owns its own visual lifetime; a
   * root fprintd process cannot authenticate to the user's session bus. */
  if (!write_child (EL721_PANEL, "fod_mode", "1\n", error))
    return FALSE;
  self->udfps_refreshed = now;
  return TRUE;
}

static void
udfps_end (FpiDeviceEl721 *self)
{
  if (!self->udfps_active)
    return;
  write_child (EL721_PANEL, "fod_mode", "0\n", NULL);
  write_child (EL721_TOUCH, "fod_enable", "0\n", NULL);
  self->udfps_active = FALSE;
  self->udfps_lit = FALSE;
  self->touch_inhibited = TRUE;
  self->capture_deadline = 0;
  self->visual_refreshed = 0;
  g_unlink (EL721_VISUAL_STATE);
  self->udfps_refreshed = 0;
  self->fod_sequence = 0;
  self->enroll_armed = FALSE;
  self->enroll_arm_status = 0;
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
  self->enroll_armed = FALSE;
  self->enroll_arm_status = 0;
  self->opcode = 0;
  g_clear_pointer (&self->enroll_user, g_free);
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
print_data (FpPrint *print, gchar **user, guint32 *template_id,
            GBytes **opaque, GError **error)
{
  g_autoptr(GVariant) data = NULL;
  if (!print)
    return FALSE;
  g_object_get (print, "fpi-data", &data, NULL);
  return el721_print_unpack (data, user, template_id, opaque, error);
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
  g_autofree gchar *gallery_user = NULL;
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
      g_autofree gchar *user = NULL;
      g_autoptr(GBytes) opaque = NULL;
      guint32 template_id;
      FpPrint *print = g_ptr_array_index (prints, i);
      if (!print_data (print, &user, &template_id, &opaque, error))
        {
          g_ptr_array_unref (prints);
          g_byte_array_unref (gallery);
          return NULL;
        }
      bytes = g_bytes_get_data (opaque, &size);
      if ((gallery_user && !g_str_equal (gallery_user, user)) ||
          gallery->len >= 0x226000 || size >= 0x226000 - gallery->len)
        {
          g_set_error_literal (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_INVALID,
                               "EL721 gallery has mixed identities or is too large");
          g_ptr_array_unref (prints);
          g_byte_array_unref (gallery);
          return NULL;
        }
      if (!gallery_user)
        gallery_user = g_strdup (user);
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
  *user_out = g_steal_pointer (&gallery_user);
  *prints_out = prints;
  return gallery;
}

static void poll_action (FpDevice *device, gpointer user_data);
static gboolean initialize_identify (FpiDeviceEl721 *self, GError **error);

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
      g_autofree gchar *user = NULL;
      g_autoptr(GBytes) opaque = NULL;
      guint32 candidate;
      if (print_data (g_ptr_array_index (prints, i), &user, &candidate, &opaque, NULL) &&
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
  /* The capture path already required IdentifyFinal to succeed. */
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
arm_enroll_capture (FpiDeviceEl721 *self, GError **error)
{
  El721Reply reply = { 0 };
  gboolean ok = FALSE;

  /* One UI enters EnrollDo once before the contact.  Opcode 4 makes the
   * sensor service arm its interrupt and wait for the next finger-down edge;
   * it is not an instruction to call EnrollDo again immediately. */
  if (!el721_qtee_enroll_do (self->qtee, &reply, error))
    goto out;
  if (reply.result || reply.opcode != EL721_OP_WAIT_INTERRUPT)
    {
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 arm returned result/opcode %u/%u",
                   reply.result, reply.opcode);
      goto out;
    }
  self->enroll_armed = TRUE;
  self->enroll_arm_status = reply.status;
  fp_dbg ("Enroll armed status=%u", reply.status);
  ok = TRUE;

out:
  el721_reply_clear (&reply);
  return ok;
}

static gboolean
handle_enroll_do (FpiDeviceEl721 *self, GError **error)
{
  El721Reply reply = { 0 };
  El721Reply final = { 0 };
  g_autoptr(GBytes) template = NULL;
  g_autofree gchar *user = NULL;
  guint32 capture_result = 0;
  guint coverage = 0;
  guint accepted = 0;
  guint progress = 0;
  guint step;
  gboolean terminal = FALSE;
  gint64 capture_started = g_get_monotonic_time ();
  g_autoptr(GString) protocol = g_string_new (NULL);
  /* One UI sends 2 for a held contact. The TA's control-87 implementation
   * only acts on value 1 (fp_set_finger_off); both 0 and 2 are no-ops.
   * Do not attribute image-quality changes to a 0-to-2 transition. */
  guint8 touch_flags = 2;
  gint32 battery_temperature;

  if (!self->enroll_armed)
    {
      g_set_error_literal (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                           "EL721 contact arrived before capture was armed");
      return FALSE;
    }
  g_string_append_printf (protocol, "%u:0:%u", EL721_OP_WAIT_INTERRUPT,
                          self->enroll_arm_status);
  self->enroll_armed = FALSE;

  /* The TA calls fpsec_do_get_image_only BEFORE returning opcode 87.
   * Splitting at 87 cannot defer acquisition until RELEASE. Complete the
   * stock synchronous sequence while the finger covers the illuminated area. */
  for (step = 0; step < EL721_CAPTURE_STEPS_MAX; step++)
    {
      if (!el721_qtee_enroll_do (self->qtee, &reply, error))
        goto fail;
      if (protocol->len)
        g_string_append_c (protocol, ',');
      g_string_append_printf (protocol, "%u:%u:%u", reply.opcode,
                              reply.result, reply.status);
      fp_dbg ("EnrollDo result=%u status=%u opcode=%u fields=%u/%u/%u data=%zu",
              reply.result, reply.status, reply.opcode, reply.quality,
              reply.progress, reply.remaining,
              reply.data ? g_bytes_get_size (reply.data) : 0);
      capture_result = reply.result;
      if (capture_result || reply.opcode == 0)
        {
          terminal = TRUE;
          break;
        }
      if (reply.opcode == EL721_OP_CAPTURE_SUCCESS ||
          reply.opcode == EL721_OP_ACQUIRED_EVENT)
        {
          /* Stock handles 63 as a callback and immediately continues. The
           * TA's do_enroll_stub emits it AFTER an internal result 70 and
           * latches that fatal result for the next call, not at a coverage
           * milestone. Preserve the final error instead of retrying it. */
          el721_reply_clear (&reply);
          continue;
        }
      if (reply.opcode == EL721_OP_NOTIFY_DOWN)
        {
          /* Samsung passes both values as input data.  Control 87 receives
           * the first byte of its touch-status triplet (2 while pressed),
           * then control 80 receives the battery temperature in tenths of a
           * degree Celsius.  Treating these as response capacities made 80
           * return 51 and eventually made EnrollDo abort with result 70. */
          if (!read_battery_temperature (&battery_temperature, error))
            goto fail;
          if (!el721_qtee_control_op (self->qtee, EL721_OP_CAPTURE_STEP,
                                      &touch_flags, sizeof (touch_flags), 0,
                                      error) ||
              !el721_qtee_control_op (self->qtee, 80,
                                      (const guint8 *) &battery_temperature,
                                      sizeof (battery_temperature), 0, error))
            goto fail;
          el721_reply_clear (&reply);
          continue;
        }
      if (reply.opcode == EL721_OP_CAPTURE_STEP)
        {
          if (!el721_qtee_control_op (self->qtee, EL721_OP_CAPTURE_STEP,
                                      &touch_flags, sizeof (touch_flags), 0,
                                      error))
            goto fail;
          el721_reply_clear (&reply);
          continue;
        }
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 EnrollDo returned unknown opcode %u", reply.opcode);
      goto fail;
    }
  if (!terminal)
    {
      g_set_error_literal (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                           "EL721 capture protocol did not terminate");
      goto fail;
    }

  /* EnrollFinal closes every capture, including BAD_QUALITY (39).  Omitting
   * it leaves the trustlet in its 0x80000000 sentinel and all later touches
   * become no-ops. */
  /* The first capture metric is coverage and the third is the accepted-sample
   * counter.  Keep fprintd below its terminal stage until EnrollDo returns an
   * encrypted template AND EnrollFinal succeeds. */
  progress = MIN (reply.quality, 99);
  coverage = reply.quality;
  accepted = reply.remaining;
  if (reply.remaining > 0)
    progress = MAX (progress,
                    MIN (reply.remaining, EL721_ENROLL_STAGES - 1) * 100 /
                    EL721_ENROLL_STAGES);
  template = g_steal_pointer (&reply.data);
  el721_reply_clear (&reply);
  if (!el721_qtee_enroll_final (self->qtee, &final, error))
    goto fail;
  if (template && !final.result)
    progress = 100;
  fp_dbg ("EnrollFinal result=%u status=%u opcode=%u template=%zu progress=%u",
          final.result, final.status, final.opcode,
          template ? g_bytes_get_size (template) : 0, progress);
  /* One compact, non-biometric record per physical sample.  Tab Companion's
   * bounded test consumes this without enabling global GLib debug logging. */
  /* MESSAGE is retained by fprintd's default systemd journal policy.  INFO is
   * filtered unless G_MESSAGES_DEBUG is set, which made field diagnostics
   * lose the secure aggregate result while still showing fprintd retries. */
  g_message ("EL721 sample result=%u final=%u coverage=%u accepted=%u template=%zu steps=%s final_status=%u capture_ms=%" G_GINT64_FORMAT,
             capture_result, final.result, coverage, accepted,
             template ? g_bytes_get_size (template) : 0, protocol->str,
             final.status, (g_get_monotonic_time () - capture_started) / 1000);

  if ((!capture_result || capture_result == 39 || capture_result == 41) &&
      (!final.result || final.result == 39 || final.result == 41) &&
      (capture_result || final.result))
    {
      GError *retry = fpi_device_retry_new (FP_DEVICE_RETRY_GENERAL);
      fpi_device_enroll_progress (FP_DEVICE (self), self->enroll_stage,
                                  NULL, retry);
    }
  else if (capture_result || final.result)
    {
      if (capture_result == 71 || capture_result == 72)
        g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                     "EL721 cannot encrypt the template: HwVault key "
                     "derivation failed (secure result %u)", capture_result);
      else
        g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 capture/final returned %u/%u", capture_result,
                   final.result);
      goto fail;
    }

  if (!capture_result && !final.result)
    {
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
      if (progress >= 100 && template)
        {
          FpPrint *print = NULL;
          gsize size;
          const guint8 *bytes;
          GVariant *array;
          GVariant *data;

          bytes = g_bytes_get_data (template, &size);
          fpi_device_get_enroll_data (FP_DEVICE (self), &print);
          array = g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, bytes, size, 1);
          data = g_variant_new ("(su@ay)", self->enroll_user, self->template_id, array);
          fpi_print_set_type (print, FPI_PRINT_RAW);
          fpi_print_set_device_stored (print, FALSE);
          g_object_set (print, "fpi-data", data, NULL);
          action_cleanup (self);
          fpi_device_enroll_progress (FP_DEVICE (self), EL721_ENROLL_STAGES,
                                      print, NULL);
          fpi_device_enroll_complete (FP_DEVICE (self), g_object_ref (print),
                                      NULL);
          el721_reply_clear (&final);
          return TRUE;
        }
    }

  /* A capture is one Init/Do/Final transaction.  The trustlet retains the
   * partial template in this QTEE session; start the next transaction using
   * the same libfprint identity and secure slot. */
  user = g_strdup (self->enroll_user);
  el721_reply_clear (&final);
  if (!el721_qtee_enroll_init (self->qtee, (guint8 *) user, strlen (user),
                               self->template_id, &reply, error))
    goto fail;
  fp_dbg ("EnrollInit(next) result=%u status=%u opcode=%u",
          reply.result, reply.status, reply.opcode);
  if (reply.result)
    {
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 next EnrollInit returned %u", reply.result);
      el721_reply_clear (&reply);
      return FALSE;
    }
  el721_reply_clear (&reply);
  if (!arm_enroll_capture (self, error))
    goto fail;
  /* The timeout protects against an abandoned operation, not the total time
   * needed to collect a variable number of coverage samples. */
  self->action_started = g_get_monotonic_time ();
  return TRUE;

fail:
  el721_reply_clear (&reply);
  el721_reply_clear (&final);
  return FALSE;
}

static gboolean
handle_identify_do (FpiDeviceEl721 *self, GError **error)
{
  El721Reply reply = { 0 };
  El721Reply final = { 0 };
  guint8 touch_flags = 2;
  gint32 temperature;
  gboolean terminal = FALSE;
  g_autoptr(GString) steps = g_string_new ("4");
  for (guint step = 0; step < EL721_CAPTURE_STEPS_MAX; step++)
    {
      if (!el721_qtee_identify_do (self->qtee, self->opcode, &reply, error))
        goto fail;
      self->opcode = reply.opcode;
      g_string_append_printf (steps, ",%u:%u", reply.opcode, reply.result);
      if (reply.result || reply.opcode == 0)
        { terminal = TRUE; break; }
      if (reply.opcode == EL721_OP_NOTIFY_DOWN)
        {
          if (!read_battery_temperature (&temperature, error) ||
              !el721_qtee_control_op (self->qtee, 87, &touch_flags, 1, 0, error) ||
              !el721_qtee_control_op (self->qtee, 80, (guint8 *) &temperature,
                                      sizeof (temperature), 0, error))
            goto fail;
        }
      else if (reply.opcode == EL721_OP_CAPTURE_STEP)
        {
          if (!el721_qtee_control_op (self->qtee, 87, &touch_flags, 1, 0, error))
            goto fail;
        }
      else if (reply.opcode != EL721_OP_CAPTURE_SUCCESS &&
               reply.opcode != EL721_OP_ACQUIRED_EVENT)
        {
          g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                       "EL721 IdentifyDo returned unexpected opcode %u", reply.opcode);
          goto fail;
        }
      el721_reply_clear (&reply);
    }
  if (!terminal)
    {
      g_set_error_literal (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                           "EL721 identify capture did not terminate");
      goto fail;
    }
  if (!el721_qtee_identify_final (self->qtee, &final, error))
    goto fail;
  g_message ("EL721 verify result=%u final=%u matched_slot=%u score=%u steps=%s",
             reply.result, final.result, reply.template_id, reply.quality, steps->str);
  if (final.result)
    {
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 IdentifyFinal returned %u", final.result);
      goto fail;
    }
  el721_reply_clear (&final);
  if (reply.result == 39 || reply.result == 41)
    {
      GError *retry = fpi_device_retry_new (FP_DEVICE_RETRY_GENERAL);
      FpiDeviceAction current = fpi_device_get_current_action (FP_DEVICE (self));
      el721_reply_clear (&reply);
      /* libfprint permits exactly ONE result per action, including retries.
       * fprintd starts the next action. Rearming here left result_reported set
       * and made the next physical contact violate that contract. */
      action_cleanup (self);
      el721_complete_match_retry (FP_DEVICE (self), current, retry);
      return TRUE;
    }
  else if (el721_identify_is_no_match (&reply))
    {
      el721_reply_clear (&reply);
      finish_identify (self, 0);
      return TRUE;
    }
  else if (reply.result)
    {
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 IdentifyDo returned %u", reply.result);
      goto fail;
    }
  else if (reply.opcode == 0)
    {
      guint32 template_id = reply.template_id;
      el721_reply_clear (&reply);
      finish_identify (self, template_id);
      return TRUE;
    }
  el721_reply_clear (&reply);
  self->action_started = g_get_monotonic_time ();
  return TRUE;
fail:
  el721_reply_clear (&reply);
  el721_reply_clear (&final);
  return FALSE;
}

static void
poll_action (FpDevice *device, gpointer user_data)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  g_autoptr(GError) error = NULL;
  gboolean pressed = FALSE;
  gboolean released = FALSE;
  gboolean event;
  gboolean capture;
  El721LightStep light_step;
  g_autofree gchar *touch_enabled = NULL;
  g_autofree gchar *ui_lease = NULL;
  guint x;
  guint y;
  guint64 sequence;
  guint64 sequence_delta;

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
  if (!udfps_publish (self, &error))
    {
      action_fail (self, g_steal_pointer (&error));
      return;
    }
  g_file_get_contents (EL721_UI_LEASE, &ui_lease, NULL, NULL);
  if (!el721_ui_lease_ready (ui_lease, g_get_monotonic_time ()))
    {
      if (!self->touch_inhibited)
        {
          if (!udfps_light (self, FALSE, &error) ||
              !write_child (EL721_TOUCH, "fod_enable", "0\n", &error))
            {
              action_fail (self, g_steal_pointer (&error));
              return;
            }
          self->touch_inhibited = TRUE;
          self->capture_deadline = 0;
          self->finger_present = FALSE;
          fpi_device_report_finger_status (device, FP_FINGER_STATUS_NEEDED);
          g_message ("EL721 target unavailable; touch suppression and HBM disabled");
        }
      schedule_poll (self);
      return;
    }
  if (self->touch_inhibited)
    {
      if (!write_child (EL721_TOUCH, "fod_enable", "1\n", &error) ||
          !read_fod_state (&pressed, &released, &x, &y, &self->fod_sequence, &error))
        {
          action_fail (self, g_steal_pointer (&error));
          return;
        }
      /* Seed both sequence and latch: a keyboard finger already held down
       * must not become a capture when the keyboard is dismissed. */
      self->finger_present = pressed;
      self->touch_inhibited = FALSE;
      g_message ("EL721 target available; waiting for a fresh contact");
    }
  /* Suspend disables the touch controller's FOD mode. Do not leave a stale
   * prompt armed after resume or silently re-enable it behind the lock UI. */
  if (!g_file_get_contents (EL721_TOUCH "/fod_enable", &touch_enabled, NULL, &error) ||
      !g_str_has_prefix (touch_enabled, "1"))
    {
      if (!error)
        error = fpi_device_error_new_msg (FP_DEVICE_ERROR_GENERAL,
                                           "EL721 touch mode ended (display suspended)");
      action_fail (self, g_steal_pointer (&error));
      return;
    }
  if (!udfps_refresh (self, &error))
    {
      action_fail (self, g_steal_pointer (&error));
      return;
    }
  if (!read_fod_state (&pressed, &released, &x, &y, &sequence, &error))
    {
      action_fail (self, g_steal_pointer (&error));
      return;
    }
  sequence_delta = sequence - self->fod_sequence;
  event = sequence_delta != 0;
  self->fod_sequence = sequence;
  /* One capture per observed PRESS edge; RELEASE only clears the latch.
   * Verification must not depend on enrollment-only state (gts9u36 did). */
  capture = self->action == EL721_ACTION_ENROLL ?
            event && !self->finger_present && pressed && self->enroll_armed :
            el721_identify_contact_ready (self->opcode, event, pressed, self->finger_present);
  if (event)
    g_message ("EL721 contact pressed=%u released=%u sequence=%" G_GUINT64_FORMAT
               " delta=%" G_GUINT64_FORMAT " x=%u y=%u capture=%u",
               pressed, released, sequence, sequence_delta, x, y, capture);
  if (pressed != self->finger_present)
    {
      self->finger_present = pressed;
      fpi_device_report_finger_status_changes (
        device,
        pressed ? FP_FINGER_STATUS_PRESENT : FP_FINGER_STATUS_NEEDED,
        pressed ? FP_FINGER_STATUS_NEEDED : FP_FINGER_STATUS_PRESENT);
    }
  light_step = el721_touch_light_step (&self->capture_deadline,
                                       g_get_monotonic_time (), pressed, capture);
  if (light_step == EL721_LIGHT_ON || light_step == EL721_LIGHT_OFF)
    {
      if (!udfps_light (self, light_step == EL721_LIGHT_ON, &error))
        {
          action_fail (self, g_steal_pointer (&error));
          return;
        }
      /* The panel write itself takes time. Settle from completion, not from
       * before the DDIC command, without blocking the cancellation loop. */
      if (light_step == EL721_LIGHT_ON)
        self->capture_deadline = g_get_monotonic_time () + EL721_LIGHT_SETTLE_US;
      g_message ("EL721 touch-to-light %s",
                 light_step == EL721_LIGHT_ON ? "on; settling" : "off; early release");
    }
  if (light_step == EL721_LIGHT_CAPTURE)
    {
      g_message ("EL721 touch-to-light settled; capturing");
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
      /* Enrollment may remain active for the next sample. A held finger
       * must not keep HBM on or trigger another capture without a new edge. */
      if (!udfps_light (self, FALSE, &error))
        {
          action_fail (self, g_steal_pointer (&error));
          return;
        }
    }
  schedule_poll (self);
}

static gboolean
operation_prepare (FpiDeviceEl721 *self, GError **error)
{
  /* The QTEE session is prepared and its matcher is configured by open().
   * A second CMD_PREPARE in the same session is rejected by BAUTH with 29.
   * fprintd opens the device before each claimed operation, so only restore
   * the sensor power that open() deliberately dropped while it was idle. */
  return set_sensor_power (self, TRUE, error);
}

static guint32
template_slot_for_finger (FpFinger finger)
{
  /* BAUTH exposes four template slots, whereas FpFinger numbers the ten
   * anatomical fingers from 1 to 10.  Keep the mapping stable so a template
   * stored by fprintd carries the same secure-world identifier when reloaded.
   * The four-print limit and collision handling remain integration work. */
  if (finger == FP_FINGER_UNKNOWN)
    return 1;
  return ((guint32) finger - 1) % 4 + 1;
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
  g_clear_pointer (&self->enroll_user, g_free);
  self->enroll_user = fpi_print_generate_user_id (print);
  user = g_strdup (self->enroll_user);
  self->template_id = template_slot_for_finger (fp_print_get_finger (print));
  if (!operation_prepare (self, &error) ||
      !el721_qtee_authorize_enrollment (self->qtee, 0, 0, &error) ||
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
  if (!arm_enroll_capture (self, &error))
    {
      udfps_end (self);
      set_sensor_power (self, FALSE, NULL);
      fpi_device_enroll_complete (device, NULL, g_steal_pointer (&error));
      return;
    }
  self->action = EL721_ACTION_ENROLL;
  self->enroll_stage = 0;
  self->action_started = g_get_monotonic_time ();
  fpi_device_report_finger_status (device, FP_FINGER_STATUS_NEEDED);
  schedule_poll (self);
}

static gboolean
initialize_identify (FpiDeviceEl721 *self, GError **error)
{
  g_autoptr(GByteArray) gallery = NULL;
  g_autoptr(GPtrArray) prints = NULL;
  g_autofree gchar *user = NULL;
  El721Reply reply = { 0 };
  gboolean ok = FALSE;
  guint32 initial;
  gallery = build_gallery (self, &prints, &user, error);
  if (!gallery ||
      !el721_qtee_identify_init (self->qtee, (guint8 *) user, strlen (user),
                                 gallery->data, gallery->len, NULL, 0,
                                 &reply, error))
    goto out;
  if (reply.result)
    {
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 IdentifyInit returned %u", reply.result);
      goto out;
    }
  initial = reply.status;
  el721_reply_clear (&reply);
  /* Enter Do once, then WAIT. Never interpret its byte-12 auxiliary zero as
   * a completed no-match: byte 0 contains the actual operation code (4). */
  if (!el721_qtee_identify_do (self->qtee, initial, &reply, error))
    goto out;
  if (reply.result || reply.opcode != EL721_OP_WAIT_INTERRUPT)
    {
      g_set_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_GENERAL,
                   "EL721 identify arm returned result/opcode %u/%u",
                   reply.result, reply.opcode);
      goto out;
    }
  self->opcode = reply.opcode;
  g_message ("EL721 verify armed opcode=%u status=%u; waiting for a new press",
             reply.opcode, reply.status);
  ok = TRUE;
out:
  el721_reply_clear (&reply);
  return ok;
}

static void
start_identify (FpDevice *device)
{
  FpiDeviceEl721 *self = FPI_DEVICE_EL721 (device);
  g_autoptr(GError) error = NULL;
  FpiDeviceAction current = fpi_device_get_current_action (device);
  if (!operation_prepare (self, &error) ||
      !initialize_identify (self, &error) || !udfps_begin (self, &error))
    {
      El721Reply reply = { 0 };
      el721_qtee_identify_final (self->qtee, &reply, NULL);
      el721_reply_clear (&reply);
      action_cleanup (self);
      if (current == FPI_DEVICE_ACTION_VERIFY)
        fpi_device_verify_complete (device, g_steal_pointer (&error));
      else
        fpi_device_identify_complete (device, g_steal_pointer (&error));
      return;
    }
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
