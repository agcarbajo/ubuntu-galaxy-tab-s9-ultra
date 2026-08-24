/* SPDX-License-Identifier: BSD-3-Clause */
/* Minimal Samsung BAUTH transport over Qualcomm's upstream QTEE object API. */

#include "el721-qtee.h"

#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <glib/gstdio.h>
#include "qcomtee_object.h"
#include "qcomtee_object_types.h"

#define QSEECOM_APP_LOADER_UID 122U
#define QSEE_INTERRUPT_SERVICE_UID 87U
#define QSEE_INTERRUPT_LISTENER_ID 0xb000U
#define QSEE_INTERRUPT_BUFFER_SIZE 1024U
#define QSEE_REGISTER_LISTENER_OP 0U
#define QSEECOM_LOOKUP_TA_OP 2U
#define QSEECOM_LOAD_REGION_OP 0U
#define QSEECOM_SEND_REQUEST_OP 0U
#define QSEECOM_UNLOAD_OP 2U
#define EL721_TA_SEGMENTS 9U
#define EL721_SHARED_ALLOC 0x2a4000U
#define EL721_INPUT_SHARED_SIZE 0x2a3110U
#define EL721_OUTPUT_SHARED_SIZE 0x2a3010U
#define EL721_MESSAGE_SIZE 64U
#define EL721_SENSOR_TYPE 8U
#define EL721_MAX_TA_SIZE (32U * 1024U * 1024U)
#define EL721_CELL_ID_SYSFS "/sys/class/backlight/ae94000.dsi.0/cell_id"
#define EL721_DEVICE "/dev/esfp0"
#define EGIS_IOC_MAGIC 'k'
#define EGIS_SENSOR_RESET 0x04U

#define CMD_PREPARE 1U
#define CMD_ENROLL_INIT 2U
#define CMD_ENROLL_DO 3U
#define CMD_ENROLL_FINAL 4U
#define CMD_IDENTIFY_INIT 5U
#define CMD_IDENTIFY_DO 6U
#define CMD_IDENTIFY_FINAL 7U
#define CMD_CANCEL 10U
#define CANCEL_WIRE_SIZE 8U
#define CMD_CONTROL 12U

#define PREPARE_SIZE 0x80010U
#define PREPARE_MODE_CALIBRATED 36U
#define PREPARE_DATA_OFFSET 0xcU
#define PREPARE_DATA_MAX 0x80000U
#define PREPARE_LENGTH_OFFSET 0x8000cU
#define CONTROL_INPUT_SIZE 0x2a3110U
#define CONTROL_OUTPUT_SIZE 0x2a3010U
#define CONTROL_STRING_OFFSET 0xcU
#define CONTROL_STRING_MAX 0x100U
#define CONTROL_DATA_OFFSET 0x10cU
#define CONTROL_DATA_MAX 0x2a3000U
#define CONTROL_LENGTH_OFFSET 0x2a310cU
#define CONTROL_OUTPUT_DATA_OFFSET 0xcU
#define CONTROL_OUTPUT_LENGTH_OFFSET 0x2a300cU
#define CONTROL_GENERATE_GROUP_KEY 45U
#define CONTROL_SET_ACTIVE_GROUP 46U
#define CONTROL_LCD_PANEL_TYPE 401U
#define CONTROL_LCD_WINDOW_TYPE 402U
#define CONTROL_GDXOPT_CALIB 94U
#define EL721_WINDOW_TYPE_SYSFS "/sys/class/lcd/panel/window_type"
#define CONTROL_BOOTSTRAP 76U
#define CONTROL_BOOTSTRAP_RESPONSE 1024U
#define CONTROL_RESET_BDS 81U
#define CONTROL_LOAD_BDS 82U
#define EL721_BDS_MAX_CHUNK 3U
#define CONTROL_CPU_IDLE 83U
/* Two control operations look the running board up in the TA's table of
 * Samsung model codes, and only this one goes on to build the matcher's
 * configuration from the entry it found.  Operation 90 sets the index and
 * stops there, which leaves the matcher unbuilt and every biometric command
 * answering 29. */
#define CONTROL_SELECT_MODEL 88U
#define EL721_MODEL "X916"
#define EL721_MODEL_FIELD 10U
#define EL721_BDS_MAX (4U * 1024U * 1024U)
#define EL721_BDS_CHUNK 0x3000U
#define ENROLL_INIT_SIZE 0x178U
#define ENROLL_INIT_OUT_SIZE 0xcU
#define ENROLL_DO_OUT_SIZE 0x230024U
#define FINAL_OUT_SIZE 0xa018U
#define IDENTIFY_INIT_SIZE 0x2265bdU
#define IDENTIFY_INIT_OUT_SIZE 0x1a0U
#define IDENTIFY_DO_OUT_SIZE 0x230089U

#define EL721_ERROR el721_qtee_error_quark ()

struct _El721Qtee
{
  struct qcomtee_object *root;
  struct qcomtee_object *client_env;
  struct qcomtee_object *qis_service;
  struct qcomtee_object *qis_memory;
  struct qcomtee_object *app_loader;
  struct qcomtee_object *controller;
  struct qcomtee_object *input;
  struct qcomtee_object *output;
  gchar *firmware_directory;
  gboolean loaded_here;
};

typedef struct
{
  pthread_t thread;
  struct qcomtee_object *root;
} El721Supplicant;

typedef struct
{
  struct qcomtee_object object;
} El721QisCallback;

typedef struct
{
  guint64 tx_buf;
  guint64 rx_buf;
  guint32 len;
  guint32 speed_hz;
  guint16 delay_usecs;
  guint8 bits_per_word;
  guint8 cs_change;
  guint8 opcode;
  guint8 pad[3];
} El721IocTransfer;

#define EGIS_IOC_MESSAGE _IOW (EGIS_IOC_MAGIC, 0, El721IocTransfer)

static GQuark
el721_qtee_error_quark (void)
{
  return g_quark_from_static_string ("el721-qtee-error");
}

static guint32 el721_probe_u32 (const gchar *name, guint32 fallback);
static gboolean el721_qtee_load_bds (El721Qtee *session, GError **error);

static void
put_u64 (guint8 *buffer, gsize offset, guint64 value)
{
  guint i;

  for (i = 0; i < 8; i++)
    buffer[offset + i] = (guint8) (value >> (8 * i));
}

static guint64
el721_probe_u64 (const gchar *name)
{
  const gchar *value = g_getenv (name);

  return value ? g_ascii_strtoull (value, NULL, 0) : 0;
}

static void
put_u32 (guint8 *buffer, gsize offset, guint32 value)
{
  memcpy (buffer + offset, &value, sizeof (value));
}

static guint32
get_u32 (const guint8 *buffer, gsize offset)
{
  guint32 value;
  memcpy (&value, buffer + offset, sizeof (value));
  return value;
}

#ifdef __GLIBC__
static int
tee_call (int fd, unsigned long op, ...)
#else
static int
tee_call (int fd, int op, ...)
#endif
{
  va_list ap;
  void *arg;
  int result;

  va_start (ap, op);
  arg = va_arg (ap, void *);
  va_end (ap);
  pthread_setcanceltype (PTHREAD_CANCEL_ASYNCHRONOUS, NULL);
  result = ioctl (fd, op, arg);
  pthread_setcanceltype (PTHREAD_CANCEL_DEFERRED, NULL);
  return result;
}

static void *
supplicant_worker (void *data)
{
  El721Supplicant *supplicant = data;
  while (TRUE)
    {
      int result;

      pthread_testcancel ();
      result = qcomtee_object_process_one (supplicant->root);
      if (result)
        {
          g_debug ("QTEE supplicant stopped with result %d", result);
          break;
        }
      g_debug ("QTEE supplicant handled a secure-world callback");
    }
  return NULL;
}

static void
supplicant_release (void *data)
{
  El721Supplicant *supplicant = data;
  if (supplicant->thread)
    {
      pthread_cancel (supplicant->thread);
      pthread_join (supplicant->thread, NULL);
    }
  g_free (supplicant);
}

static struct qcomtee_object *
open_root (GError **error)
{
  El721Supplicant *supplicant = g_new0 (El721Supplicant, 1);
  struct qcomtee_object *root;

  root = qcomtee_object_root_init ("/dev/tee0", tee_call,
                                  supplicant_release, supplicant);
  if (root == QCOMTEE_OBJECT_NULL)
    {
      g_set_error (error, EL721_ERROR, errno,
                   "cannot open the QTEE object namespace: %s", g_strerror (errno));
      g_free (supplicant);
      return QCOMTEE_OBJECT_NULL;
    }
  supplicant->root = root;
  if (pthread_create (&supplicant->thread, NULL, supplicant_worker, supplicant))
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "cannot start the QTEE supplicant thread");
      qcomtee_object_refs_dec (root);
      return QCOMTEE_OBJECT_NULL;
    }
  return root;
}

static struct qcomtee_object *
open_client_env (struct qcomtee_object *root, GError **error)
{
  struct qcomtee_object *credentials = QCOMTEE_OBJECT_NULL;
  struct qcomtee_param params[2] = { 0 };
  qcomtee_result_t result = QCOMTEE_ERROR;

  if (qcomtee_object_credentials_init (root, &credentials))
    goto fail;
  params[0].attr = QCOMTEE_OBJREF_INPUT;
  params[0].object = credentials;
  params[1].attr = QCOMTEE_OBJREF_OUTPUT;
  if (qcomtee_object_invoke (root, 2, params, 2, &result) || result)
    goto fail;
  return params[1].object;

fail:
  qcomtee_object_refs_dec (credentials);
  g_set_error (error, EL721_ERROR, result,
               "cannot register the QTEE client (result %u)", result);
  return QCOMTEE_OBJECT_NULL;
}

static struct qcomtee_object *
open_service (struct qcomtee_object *client_env, guint32 uid, GError **error)
{
  struct qcomtee_param params[2] = { 0 };
  qcomtee_result_t result = QCOMTEE_ERROR;

  params[0].attr = QCOMTEE_UBUF_INPUT;
  params[0].ubuf.addr = &uid;
  params[0].ubuf.size = sizeof (uid);
  params[1].attr = QCOMTEE_OBJREF_OUTPUT;
  if (qcomtee_object_invoke (client_env, 0, params, 2, &result) || result)
    {
      g_set_error (error, EL721_ERROR, result,
                   "cannot open QTEE service %u (result %u)", uid, result);
      return QCOMTEE_OBJECT_NULL;
    }
  return params[1].object;
}

static void
qis_callback_release (struct qcomtee_object *object)
{
  g_free (container_of (object, El721QisCallback, object));
}

static qcomtee_result_t
qis_callback_dispatch (struct qcomtee_object *object,
                       qcomtee_op_t op,
                       struct qcomtee_param *params,
                       int num)
{
  (void) object;

  g_debug ("SPL listener callback op=%u params=%d", op, num);
  for (int i = 0; i < num; i++)
    {
      if (params[i].attr == QCOMTEE_UBUF_INPUT ||
          params[i].attr == QCOMTEE_UBUF_OUTPUT)
        g_debug ("SPL listener callback param[%d] attr=%" G_GUINT64_FORMAT
                 " size=%zu", i, params[i].attr, params[i].ubuf.size);
      else
        g_debug ("SPL listener callback param[%d] attr=%" G_GUINT64_FORMAT,
                 i, params[i].attr);
    }

  /* Registration is useful before the first request arrives.  A complete
   * QIS request dispatcher is deliberately not guessed from the proprietary
   * protocol: report it explicitly if secure world needs one during Prepare. */
  return QCOMTEE_ERROR_UNAVAIL;
}

static gboolean
register_qis_listener (El721Qtee *session, GError **error)
{
  static struct qcomtee_object_ops callback_ops = {
    .release = qis_callback_release,
    .dispatch = qis_callback_dispatch,
  };
  El721QisCallback *callback = g_new0 (El721QisCallback, 1);
  struct qcomtee_param params[3] = { 0 };
  qcomtee_result_t result = QCOMTEE_ERROR;
  guint32 listener_id = QSEE_INTERRUPT_LISTENER_ID;
  gboolean callback_initialized = FALSE;

  session->qis_service = open_service (session->client_env,
                                       QSEE_INTERRUPT_SERVICE_UID, error);
  if (session->qis_service == QCOMTEE_OBJECT_NULL)
    goto fail;
  if (qcomtee_memory_object_alloc (QSEE_INTERRUPT_BUFFER_SIZE, session->root,
                                   &session->qis_memory))
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "cannot allocate the QIS listener buffer");
      goto fail;
    }
  if (qcomtee_object_cb_init (&callback->object, &callback_ops, session->root))
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "cannot initialize the QIS listener callback");
      goto fail;
    }
  callback_initialized = TRUE;

  params[0].attr = QCOMTEE_UBUF_INPUT;
  params[0].ubuf.addr = &listener_id;
  params[0].ubuf.size = sizeof (listener_id);
  params[1].attr = QCOMTEE_OBJREF_INPUT;
  params[1].object = &callback->object;
  params[2].attr = QCOMTEE_OBJREF_INPUT;
  params[2].object = session->qis_memory;
  if (qcomtee_object_invoke (session->qis_service, QSEE_REGISTER_LISTENER_OP,
                             params, G_N_ELEMENTS (params), &result) || result)
    {
      g_set_error (error, EL721_ERROR, result,
                   "cannot register QIS listener 0x%x (result %u)",
                   listener_id, result);
      goto fail;
    }

  g_debug ("registered SPL listener 0x%x", listener_id);
  return TRUE;

fail:
  /* On a successful invocation ownership of the callback reference is passed
   * to QTEE.  Every failure above happens before that transfer. */
  if (callback_initialized)
    qcomtee_object_refs_dec (&callback->object);
  else
    g_free (callback);
  return FALSE;
}

static gboolean
read_file (const gchar *path, guint8 *buffer, gsize size, GError **error)
{
  gsize actual = 0;
  g_autofree gchar *contents = NULL;
  if (!g_file_get_contents (path, &contents, &actual, error))
    return FALSE;
  if (actual != size)
    {
      g_set_error (error, EL721_ERROR, 1, "%s changed while it was read", path);
      return FALSE;
    }
  memcpy (buffer, contents, size);
  return TRUE;
}

static gboolean
assemble_ta (const gchar *directory, guint8 **image_out, gsize *size_out,
             GError **error)
{
  Elf64_Ehdr header;
  Elf64_Phdr phdr[EL721_TA_SEGMENTS];
  gsize segment_sizes[EL721_TA_SEGMENTS] = { 0 };
  g_autofree gchar *first = g_build_filename (directory, "dualfp.b00", NULL);
  g_autofree gchar *header_data = NULL;
  gsize header_size = 0;
  guint8 *image;
  gsize image_size;
  guint i;

  if (!g_file_get_contents (first, &header_data, &header_size, error))
    return FALSE;
  if (header_size < sizeof (header) + sizeof (phdr))
    goto invalid;
  memcpy (&header, header_data, sizeof (header));
  if (memcmp (header.e_ident, ELFMAG, SELFMAG) ||
      header.e_ident[EI_CLASS] != ELFCLASS64 || header.e_machine != EM_AARCH64 ||
      header.e_phnum != EL721_TA_SEGMENTS ||
      header.e_phentsize != sizeof (Elf64_Phdr) ||
      header.e_phoff + sizeof (phdr) > header_size)
    goto invalid;
  memcpy (phdr, header_data + header.e_phoff, sizeof (phdr));
  segment_sizes[0] = header_size;
  for (i = 1; i < EL721_TA_SEGMENTS; i++)
    {
      g_autofree gchar *name = g_strdup_printf ("dualfp.b%02u", i);
      g_autofree gchar *path = g_build_filename (directory, name, NULL);
      GStatBuf stat_buffer;
      if (g_stat (path, &stat_buffer) || stat_buffer.st_size < 0)
        {
          g_set_error (error, EL721_ERROR, errno,
                       "cannot stat %s: %s", path, g_strerror (errno));
          return FALSE;
        }
      segment_sizes[i] = stat_buffer.st_size;
    }
  image_size = phdr[EL721_TA_SEGMENTS - 1].p_offset +
               segment_sizes[EL721_TA_SEGMENTS - 1];
  if (image_size < header_size || image_size > EL721_MAX_TA_SIZE)
    goto invalid;
  image = g_malloc0 (image_size);
  for (i = 0; i < EL721_TA_SEGMENTS; i++)
    {
      g_autofree gchar *name = g_strdup_printf ("dualfp.b%02u", i);
      g_autofree gchar *path = g_build_filename (directory, name, NULL);
      gsize offset = i ? phdr[i].p_offset : 0;
      if (offset > image_size || segment_sizes[i] > image_size - offset ||
          !read_file (path, image + offset, segment_sizes[i], error))
        {
          g_free (image);
          return FALSE;
        }
    }
  *image_out = image;
  *size_out = image_size;
  return TRUE;

invalid:
  g_set_error_literal (error, EL721_ERROR, 1,
                       "dualfp.b00 has an unsupported signed ELF layout");
  return FALSE;
}

static gboolean
lookup_ta (El721Qtee *session, struct qcomtee_object **controller,
           qcomtee_result_t *result)
{
  /* EL721 is an optical in-display sensor.  Samsung's gateway selects the
   * dualfp trustlet for this path; securefp is a different, concurrently
   * available TA and can therefore be looked up successfully by mistake. */
  static const gchar name[] = "dualfp";
  struct qcomtee_param params[2] = { 0 };
  params[0].attr = QCOMTEE_UBUF_INPUT;
  params[0].ubuf.addr = (void *) name;
  params[0].ubuf.size = strlen (name);
  params[1].attr = QCOMTEE_OBJREF_OUTPUT;
  if (qcomtee_object_invoke (session->app_loader, QSEECOM_LOOKUP_TA_OP,
                             params, 2, result))
    return FALSE;
  *controller = params[1].object;
  return TRUE;
}

static gboolean
load_ta (El721Qtee *session, const gchar *directory, GError **error)
{
  static const gchar load_name[] = "dualfp";
  g_autofree guint8 *image = NULL;
  gsize image_size = 0;
  struct qcomtee_object *memory = QCOMTEE_OBJECT_NULL;
  struct qcomtee_param params[3] = { 0 };
  qcomtee_result_t result = QCOMTEE_ERROR;

  if (!assemble_ta (directory, &image, &image_size, error))
    return FALSE;
  if (qcomtee_memory_object_alloc (image_size, session->root, &memory))
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "cannot allocate the signed TA memory object");
      return FALSE;
    }
  memcpy (qcomtee_memory_object_addr (memory), image, image_size);
  params[0].attr = QCOMTEE_UBUF_INPUT;
  params[0].ubuf.addr = (void *) load_name;
  params[0].ubuf.size = strlen (load_name);
  params[1].attr = QCOMTEE_OBJREF_INPUT;
  params[1].object = memory;
  params[2].attr = QCOMTEE_OBJREF_OUTPUT;
  if (qcomtee_object_invoke (session->app_loader, QSEECOM_LOAD_REGION_OP,
                             params, 3, &result) || result ||
      params[2].object == QCOMTEE_OBJECT_NULL)
    {
      g_set_error (error, EL721_ERROR, result,
                   "TrustZone rejected the signed dualfp image (result %u)", result);
      qcomtee_memory_object_release (memory);
      return FALSE;
    }
  session->controller = params[2].object;
  session->loaded_here = TRUE;
  qcomtee_memory_object_release (memory);
  return TRUE;
}

El721Qtee *
el721_qtee_open (const gchar *firmware_directory, GError **error)
{
  El721Qtee *session = g_new0 (El721Qtee, 1);
  qcomtee_result_t lookup_result = QCOMTEE_ERROR;

  session->firmware_directory = g_strdup (firmware_directory);

  session->root = open_root (error);
  if (session->root == QCOMTEE_OBJECT_NULL)
    goto fail;
  session->client_env = open_client_env (session->root, error);
  if (session->client_env == QCOMTEE_OBJECT_NULL)
    goto fail;
  if (g_strcmp0 (g_getenv ("EL721_QIS_DIAGNOSTIC"), "1") == 0 &&
      !register_qis_listener (session, error))
    goto fail;
  if (g_getenv ("EL721_SCAN_SERVICES"))
    {
      guint uid;

      for (uid = 1; uid < 512; uid++)
        {
          struct qcomtee_object *service = QCOMTEE_OBJECT_NULL;
          struct qcomtee_param params[2] = { 0 };
          qcomtee_result_t result = QCOMTEE_ERROR;

          params[0] = (struct qcomtee_param) {
            .attr = QCOMTEE_UBUF_INPUT, .ubuf = { &uid, sizeof (uid) } };
          params[1] = (struct qcomtee_param) { .attr = QCOMTEE_OBJREF_OUTPUT };
          if (!qcomtee_object_invoke (session->client_env, 0, params, 2,
                                      &result) && !result)
            {
              service = params[1].object;
              g_print ("service UID %u is available\n", uid);
              qcomtee_object_refs_dec (service);
            }
        }
    }

  if (g_getenv ("EL721_SERVICE_PROBE"))
    {
      g_auto(GStrv) parts = g_strsplit (g_getenv ("EL721_SERVICE_PROBE"), ":", 2);
      guint32 uid = (guint32) g_ascii_strtoull (parts[0], NULL, 0);
      guint32 last_op = parts[1] ?
        (guint32) g_ascii_strtoull (parts[1], NULL, 0) : 8;
      struct qcomtee_object *service = open_service (session->client_env, uid,
                                                     NULL);
      guint32 op;

      if (service == QCOMTEE_OBJECT_NULL)
        g_print ("service %u did not open\n", uid);
      for (op = 0; service != QCOMTEE_OBJECT_NULL && op <= last_op; op++)
        {
          g_autofree guint8 *sink = g_malloc0 (4096);
          struct qcomtee_param params[1] = { 0 };
          qcomtee_result_t result = QCOMTEE_ERROR;
          gsize seen;

          params[0] = (struct qcomtee_param) {
            .attr = QCOMTEE_UBUF_OUTPUT, .ubuf = { sink, 4096 } };
          if (qcomtee_object_invoke (service, op, params, 1, &result))
            continue;
          if (result)
            continue;
          for (seen = 0; seen < 64 && sink[seen]; seen++)
            ;
          g_print ("service %u op %u returned %" G_GSIZE_FORMAT
                   " printable bytes: %.48s\n", uid, op, seen,
                   seen ? (const gchar *) sink : "");
        }
      if (service != QCOMTEE_OBJECT_NULL)
        qcomtee_object_refs_dec (service);
    }

  session->app_loader = open_service (session->client_env,
                                      QSEECOM_APP_LOADER_UID, error);
  if (session->app_loader == QCOMTEE_OBJECT_NULL)
    goto fail;
  if (!lookup_ta (session, &session->controller, &lookup_result))
    {
      g_set_error_literal (error, EL721_ERROR, 1, "lookupTA transport failed");
      goto fail;
    }
  g_debug ("lookupTA(dualfp) returned %u; the TA was %s", lookup_result,
           lookup_result || session->controller == QCOMTEE_OBJECT_NULL ?
           "not resident and is being loaded" : "already resident");
  if (lookup_result || session->controller == QCOMTEE_OBJECT_NULL)
    {
      qcomtee_object_refs_dec (session->controller);
      session->controller = QCOMTEE_OBJECT_NULL;
      if (!load_ta (session, firmware_directory, error))
        goto fail;
    }
  /* The wire views are smaller, but every command handler in the TA validates
   * the two non-secure pointers as ranges of exactly EL721_SHARED_ALLOC bytes
   * before it reads them, and answers 29 when that validation fails. */
  gsize shared_alloc = el721_probe_u32 ("EL721_SHARED_ALLOC", EL721_SHARED_ALLOC);

  /* A traced One UI cold start invokes operation 16 on the freshly loaded
   * controller before any BAUTH command ("QSApp SB Size is 128", "opta").
   * Reproduce it on request while its shape is still being matched. */
  if (g_getenv ("EL721_OPTA"))
    {
      guint32 op = (guint32) g_ascii_strtoull (g_getenv ("EL721_OPTA"), NULL, 0);
      guint32 size = 128;
      struct qcomtee_param probe[1] = { 0 };
      qcomtee_result_t probe_result = QCOMTEE_ERROR;
      int failed;

      probe[0].attr = QCOMTEE_UBUF_INPUT;
      probe[0].ubuf.addr = &size;
      probe[0].ubuf.size = sizeof (size);
      failed = qcomtee_object_invoke (session->controller, op, probe, 1,
                                      &probe_result);
      g_debug ("controller operation %u: transport %d, result %u", op, failed,
               probe_result);
    }

  g_debug ("allocating two BAUTH shared buffers of %zu bytes", shared_alloc);
  if (qcomtee_memory_object_alloc (shared_alloc, session->root,
                                   &session->input) ||
      qcomtee_memory_object_alloc (shared_alloc, session->root,
                                   &session->output))
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "cannot allocate the BAUTH shared buffers");
      goto fail;
    }
  return session;

fail:
  el721_qtee_close (session);
  return NULL;
}

void
el721_qtee_close (El721Qtee *session)
{
  if (!session)
    return;
  qcomtee_memory_object_release (session->output);
  qcomtee_memory_object_release (session->input);
  if (session->loaded_here && session->controller != QCOMTEE_OBJECT_NULL)
    {
      qcomtee_result_t result = QCOMTEE_ERROR;
      qcomtee_object_invoke (session->controller, QSEECOM_UNLOAD_OP,
                             NULL, 0, &result);
    }
  qcomtee_object_refs_dec (session->controller);
  qcomtee_object_refs_dec (session->app_loader);
  qcomtee_object_refs_dec (session->qis_service);
  qcomtee_memory_object_release (session->qis_memory);
  qcomtee_object_refs_dec (session->client_env);
  qcomtee_object_refs_dec (session->root);
  g_free (session->firmware_directory);
  g_free (session);
}

void
el721_reply_clear (El721Reply *reply)
{
  if (!reply)
    return;
  g_clear_pointer (&reply->data, g_bytes_unref);
  memset (reply, 0, sizeof (*reply));
}

static gboolean invoke_body (El721Qtee *session, guint32 command,
                             gsize input_size, gsize output_size,
                             const guint8 *body, gsize body_size,
                             guint8 **output, GError **error);
static gboolean invoke_body_full (El721Qtee *session, guint32 command,
                                  gsize input_size, gsize output_size,
                                  const guint8 *body, gsize body_size,
                                  gsize out_capacity_offset,
                                  guint32 out_capacity,
                                  guint8 **output, GError **error);

static gboolean
load_runtime_file (El721Qtee *session, const gchar *name, gsize maximum,
                   gchar **contents, gsize *size, GError **error)
{
  g_autofree gchar *path = g_build_filename (session->firmware_directory,
                                             name, NULL);

  if (!g_file_get_contents (path, contents, size, error))
    return FALSE;
  if (*size == 0 || *size > maximum)
    {
      g_set_error (error, EL721_ERROR, 1,
                   "%s has invalid size %" G_GSIZE_FORMAT " (maximum %" G_GSIZE_FORMAT ")",
                   path, *size, maximum);
      g_clear_pointer (contents, g_free);
      return FALSE;
    }
  return TRUE;
}

static gboolean
reset_sensor (GError **error)
{
  El721IocTransfer transfer = { .opcode = EGIS_SENSOR_RESET };
  int fd = open (EL721_DEVICE, O_RDWR | O_CLOEXEC);
  int saved_errno;

  if (fd < 0)
    goto fail;
  if (ioctl (fd, EGIS_IOC_MESSAGE, &transfer) < 0)
    {
      saved_errno = errno;
      close (fd);
      errno = saved_errno;
      goto fail;
    }
  close (fd);
  return TRUE;

fail:
  saved_errno = errno;
  g_set_error (error, G_FILE_ERROR, g_file_error_from_errno (saved_errno),
               "cannot reset EL721: %s", g_strerror (saved_errno));
  return FALSE;
}

static gboolean
el721_qtee_control_full (El721Qtee *session, guint32 operation, guint32 scalar,
                         const guint8 *user, gsize user_size,
                         const guint8 *data, gsize data_size,
                         guint8 *response_data, gsize response_capacity,
                         gsize *response_size, gboolean require_zero_result,
                         GError **error)
{
  g_autofree guint8 *body = g_malloc0 (CONTROL_INPUT_SIZE);
  guint8 *output;
  guint32 result;
  guint32 returned_size;

  if (user_size > CONTROL_STRING_MAX || (user_size && !user) ||
      data_size > CONTROL_DATA_MAX || (data_size && !data) ||
      (response_capacity && !response_data))
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "invalid BAUTH control payload");
      return FALSE;
    }
  put_u32 (body, 0, CMD_CONTROL);
  put_u32 (body, 4, scalar);
  put_u32 (body, 8, operation);
  if (user_size)
    memcpy (body + CONTROL_STRING_OFFSET, user, user_size);
  if (data_size)
    memcpy (body + CONTROL_DATA_OFFSET, data, data_size);
  put_u32 (body, CONTROL_LENGTH_OFFSET,
           el721_probe_u32 ("EL721_FORCE_DATA_LEN", (guint32) data_size));
  /* One UI states the room it has for a response in the output buffer, and
   * zero for the operations that return nothing.  Operations that do return
   * data answer 51 when that field is smaller than they need. */
  if (!invoke_body_full (session, CMD_CONTROL, CONTROL_INPUT_SIZE,
                         CONTROL_OUTPUT_SIZE, body, CONTROL_INPUT_SIZE,
                         CONTROL_OUTPUT_LENGTH_OFFSET,
                         (guint32) response_capacity,
                         &output, error))
    return FALSE;
  result = get_u32 (output, 4);
  if (result != 0 && require_zero_result)
    {
      g_set_error (error, EL721_ERROR, result,
                   "BAUTH control %u scalar %u returned result=%u "
                   "(word0=%u, word2=%u)",
                   operation, scalar, result,
                   get_u32 (output, 0), get_u32 (output, 8));
      return FALSE;
    }
  if (result != 0)
    g_debug ("BAUTH control %u returned the non-fatal stock status %u",
             operation, result);
  if (response_size)
    {
      returned_size = get_u32 (output, CONTROL_OUTPUT_LENGTH_OFFSET);
      if (returned_size > CONTROL_DATA_MAX || returned_size > response_capacity)
        {
          g_set_error (error, EL721_ERROR, 1,
                       "BAUTH control %u returned invalid payload size %u",
                       operation, returned_size);
          return FALSE;
        }
      if (returned_size)
        memcpy (response_data, output + CONTROL_OUTPUT_DATA_OFFSET,
                returned_size);
      *response_size = returned_size;
    }
  return TRUE;
}

static gboolean
el721_qtee_control (El721Qtee *session, guint32 operation, guint32 scalar,
                    const guint8 *data, gsize data_size,
                    gboolean require_zero_result, GError **error)
{
  return el721_qtee_control_full (session, operation, scalar, NULL, 0,
                                  data, data_size, NULL, 0, NULL,
                                  require_zero_result, error);
}

/* Diagnostic: send one bare BAUTH control operation and let the debug log
 * report the status the TA answers.  Not used by the driver. */
/* Diagnostic: send one bare command with the wire sizes the caller names,
 * so the TA's per-command length and buffer checks can be mapped without
 * building a real request.  Not used by the driver. */
gboolean
el721_qtee_raw_command (El721Qtee *session, guint32 command,
                        gsize input_size, gsize output_size,
                        guint32 *result, GError **error)
{
  g_autofree guint8 *body = g_malloc0 (input_size);
  guint8 *output;

  put_u32 (body, 0, command);
  if (!invoke_body (session, command, input_size, output_size, body,
                    input_size, &output, error))
    return FALSE;
  if (result)
    *result = get_u32 (output, 4);
  if (g_getenv ("EL721_DUMP_RAW"))
    {
      gsize word;

      for (word = 0; word * 4 + 4 <= MIN (output_size, (gsize) 32); word++)
        g_debug ("  command %u output word %" G_GSIZE_FORMAT " = %u", command,
                 word, get_u32 (output, word * 4));
    }
  return TRUE;
}

/* Diagnostic: One UI sends several control operations with the active user
 * identifier and no payload; reproduce exactly that shape. */
gboolean
el721_qtee_control_user (El721Qtee *session, guint32 operation,
                         const guint8 *user, gsize user_size,
                         gboolean repeat_as_payload, guint32 scalar,
                         gsize response_capacity, GError **error)
{
  g_autofree guint8 *response = response_capacity ?
    g_malloc0 (response_capacity) : NULL;
  gsize response_size = 0;

  /* One UI logs "reqUserID = User_0 | User_0" for operation 12, so that
   * request carries the identifier twice: once in the string field and once
   * as the payload. */
  if (!el721_qtee_control_full (session, operation, scalar, user, user_size,
                                repeat_as_payload ? user : NULL,
                                repeat_as_payload ? user_size : 0,
                                response, response_capacity,
                                response_capacity ? &response_size : NULL,
                                FALSE, error))
    return FALSE;
  if (response_size)
    g_debug ("BAUTH control %u returned %" G_GSIZE_FORMAT
             " bytes: %02x %02x %02x %02x", operation, response_size,
             response[0], response_size > 1 ? response[1] : 0,
             response_size > 2 ? response[2] : 0,
             response_size > 3 ? response[3] : 0);
  else
    g_debug ("BAUTH control %u returned no payload", operation);
  return TRUE;
}

/* Diagnostic: BAUTH_OP_CODE_SEND_STOREPATH and friends take their argument
 * in the payload field rather than in the identifier field. */
/* Diagnostic: the TA reads a small selector from the scalar field for
 * several operations; drive it directly. */
gboolean
el721_qtee_control_scalar (El721Qtee *session, guint32 operation,
                           guint32 scalar, gsize response_capacity,
                           GError **error)
{
  g_autofree guint8 *response = response_capacity ?
    g_malloc0 (response_capacity) : NULL;
  gsize response_size = 0;

  return el721_qtee_control_full (session, operation, scalar, NULL, 0,
                                  NULL, 0, response, response_capacity,
                                  response_capacity ? &response_size : NULL,
                                  FALSE, error);
}

gboolean
el721_qtee_control_bytes (El721Qtee *session, guint32 operation,
                          const guint8 *data, gsize data_size,
                          GError **error)
{
  return el721_qtee_control (session, operation, 0, data, data_size,
                             FALSE, error);
}

gboolean
el721_qtee_control_op (El721Qtee *session, guint32 operation,
                       const guint8 *data, gsize data_size,
                       gsize response_capacity, GError **error)
{
  g_autofree guint8 *response = response_capacity ?
    g_malloc0 (response_capacity) : NULL;
  gsize response_size = 0;

  return el721_qtee_control_full (session, operation, 0, NULL, 0, data,
                                  data_size, response, response_capacity,
                                  response_capacity ? &response_size : NULL,
                                  FALSE, error);
}

gboolean
el721_qtee_set_active_group (El721Qtee *session,
                             const guint8 *user, gsize user_size,
                             GBytes *wrapped_key, GBytes **generated_key,
                             GError **error)
{
  g_autofree guint8 *key_buffer = NULL;
  const guint8 *key_data = NULL;
  gsize key_size = 0;
  guint8 create = 1;

  if (!user || user_size == 0 || user_size > CONTROL_STRING_MAX)
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "invalid BAUTH active-group identifier");
      return FALSE;
    }
  if (generated_key)
    *generated_key = NULL;
  if (wrapped_key)
    key_data = g_bytes_get_data (wrapped_key, &key_size);
  else
    {
      key_buffer = g_malloc0 (PREPARE_DATA_MAX);
      if (!el721_qtee_control_full (session, CONTROL_GENERATE_GROUP_KEY, 0,
                                    user, user_size, &create, sizeof (create),
                                    key_buffer, PREPARE_DATA_MAX, &key_size,
                                    TRUE, error))
        return FALSE;
      if (key_size == 0)
        {
          g_set_error_literal (error, EL721_ERROR, 1,
                               "BAUTH generated an empty active-group key");
          return FALSE;
        }
      key_data = key_buffer;
      if (generated_key)
        *generated_key = g_bytes_new (key_data, key_size);
    }
  if (key_size > CONTROL_DATA_MAX)
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "invalid BAUTH wrapped active-group key");
      return FALSE;
    }
  return el721_qtee_control_full (session, CONTROL_SET_ACTIVE_GROUP, 0,
                                  user, user_size, key_data, key_size,
                                  NULL, 0, NULL, TRUE, error);
}

static gboolean
el721_qtee_load_bds (El721Qtee *session, GError **error)
{
  g_autofree gchar *bds = NULL;
  gsize bds_size = 0;
  gsize offset = 0;
  guint32 chunk_index = 0;

  if (!load_runtime_file (session, "egoptbds.dat", EL721_BDS_MAX,
                          &bds, &bds_size, error))
    return FALSE;

  /* The TA keeps one optical blob and splits the upload in two operations:
   * CONTROL_RESET_BDS frees whatever it holds, and CONTROL_LOAD_BDS appends,
   * with the chunk index in the scalar field and CONTROL_DATA_MAX bytes per
   * chunk.  The first chunk also declares the total size, so index and size
   * have to agree; the TA answers 51 to an index above three. */
  if (!el721_qtee_control (session, CONTROL_RESET_BDS, 0, NULL, 0, TRUE,
                           error))
    return FALSE;
  while (offset < bds_size)
    {
      gsize chunk_size = MIN ((gsize) CONTROL_DATA_MAX, bds_size - offset);

      if (chunk_index > EL721_BDS_MAX_CHUNK)
        {
          g_set_error_literal (error, EL721_ERROR, 1,
                               "the optical blob needs more chunks than the "
                               "TA accepts");
          return FALSE;
        }
      if (!el721_qtee_control (session, CONTROL_LOAD_BDS, chunk_index,
                               (const guint8 *) bds + offset, chunk_size,
                               TRUE, error))
        return FALSE;
      offset += chunk_size;
      chunk_index++;
    }

  return TRUE;
}

gboolean
el721_qtee_prepare (El721Qtee *session, GError **error)
{
  g_autofree guint8 *body = g_malloc0 (PREPARE_SIZE);
  g_autofree gchar *calibration = NULL;
  gsize calibration_size = 0;
  guint8 *output;
  guint attempt;
  guint32 sensor_type = 0;
  guint32 result = 0;
  guint32 function_status = 0;
  guint32 opcode = 0;

  if (!load_runtime_file (session, "calib.dat", PREPARE_DATA_MAX,
                          &calibration, &calibration_size, error))
    return FALSE;

  /* Probe: One UI's common_prepare() loads the optical blob around the
   * Prepare command; try the other order too. */
  if (g_getenv ("EL721_BDS_FIRST") && !el721_qtee_load_bds (session, error))
    return FALSE;
  memset (body, 0, PREPARE_SIZE);
  put_u32 (body, 0, CMD_PREPARE);
  put_u32 (body, 8, el721_probe_u32 ("EL721_PREPARE_MODE",
                                    PREPARE_MODE_CALIBRATED));
  memcpy (body + PREPARE_DATA_OFFSET, calibration, calibration_size);
  put_u32 (body, PREPARE_LENGTH_OFFSET,
           el721_probe_u32 ("EL721_CALIB_LEN", (guint32) calibration_size));
  for (attempt = 0; attempt < 6; attempt++)
    {
      if (!invoke_body (session, CMD_PREPARE,
                        el721_probe_u32 ("EL721_PREPARE_IN", PREPARE_SIZE),
                        el721_probe_u32 ("EL721_PREPARE_OUT", PREPARE_SIZE),
                        body, PREPARE_SIZE, &output, error))
        return FALSE;
      /* The Prepare envelope is not the BAUTH reply envelope: word 0 carries
       * the sensor type rather than an opcode, and the opcode - when the TA
       * asks for host work at all - lives in word 3 like everywhere else. */
      sensor_type = get_u32 (output, 0);
      result = get_u32 (output, 4);
      function_status = get_u32 (output, 8);
      opcode = get_u32 (output, 12);
      g_debug ("BAUTH calibrated Prepare attempt %u returned sensor_type=%u "
               "result=%u function_status=%u opcode=%u", attempt + 1,
               sensor_type, result, function_status, opcode);
      if (g_getenv ("EL721_DUMP_PREPARE"))
        {
          guint word;

          for (word = 0; word < 16; word++)
            g_debug ("  Prepare response word %2u = %u", word,
                     get_u32 (output, word * 4));
        }
      if (result || function_status)
        break;
      if (opcode == 0)
        break;
      if (opcode == 8)
        {
          if (!reset_sensor (error))
            return FALSE;
          continue;
        }
      if (opcode == 9)
        {
          /* Samsung's check_opcode() does not power-cycle the reader here.
           * It drops the optional CPU boost (irrelevant under Linux) and
           * acknowledges the idle transition with control opcode 83. */
          if (!el721_qtee_control (session, CONTROL_CPU_IDLE, 0,
                                   NULL, 0, FALSE, error))
            return FALSE;
          continue;
        }
      break;
    }
  if (g_getenv ("EL721_ANY_SENSOR_TYPE") && !result && !function_status &&
      !opcode)
    sensor_type = EL721_SENSOR_TYPE;
  if (result || function_status || opcode || sensor_type != EL721_SENSOR_TYPE)
    {
      g_set_error (error, EL721_ERROR, result,
                   "calibrated Prepare returned sensor_type=%u, result=%u, "
                   "function_status=%u, opcode=%u",
                   sensor_type, result, function_status, opcode);
      return FALSE;
    }
  /* One UI's common_prepare() continues with the optical bring-up before any
   * enrolment is possible: set_lcd_pannel_type (401, one byte), then
   * set_lcd_window_type (402, up to sixteen bytes read verbatim from
   * /sys/class/lcd/panel/window_type), then load_gdxopt_calib (94) and
   * load_bds (81).  Operations 76 and 88 were guesses; this TA answers 51. */
  /* A traced One UI cold start runs exactly this after the Prepare command:
   * control 76, control 88 and then the optical blob.  Operation 76 needs a
   * response capacity or it answers 51; 88 is not implemented in this build
   * and is advisory, as the stock service skips the calibration update for an
   * optical sensor anyway. */
  if (!el721_qtee_control_scalar (session, CONTROL_BOOTSTRAP, 0,
                                  CONTROL_BOOTSTRAP_RESPONSE, error))
    return FALSE;
  /* Operation 88 selects the board from a table of Samsung model codes the TA
   * carries; this one is "X916", the model the kernel driver reports. */
  /* The TA resolves the board against a table of twenty-nine Samsung model
   * codes and keeps the index in the structure the matcher is configured
   * from; "X916" is what this tablet's driver reports.  Two operations reach
   * that setter, 88 and 90, and they differ in one detail: 88 also logs the
   * name, and doing so over the non-secure buffer takes the TA down, so this
   * uses 90. */
  {
    guint8 model[EL721_MODEL_FIELD] = { 0 };

    memcpy (model, EL721_MODEL, strlen (EL721_MODEL));
    if (!el721_qtee_control_bytes (session, CONTROL_SELECT_MODEL, model,
                                   strlen (EL721_MODEL) + 1, error))
      return FALSE;
  }
  return el721_qtee_load_bds (session, error);
}

/* The command-specific calls below use a two-pass body helper. */
static gboolean
invoke_body (El721Qtee *session, guint32 command, gsize input_size,
             gsize output_size, const guint8 *body, gsize body_size,
             guint8 **output, GError **error)
{
  return invoke_body_full (session, command, input_size, output_size, body,
                           body_size, 0, 0, output, error);
}

/* Several control operations refuse to run unless the caller states how much
 * room the response buffer has: the TA reads that capacity from the output
 * buffer itself and answers 51 when it is too small for the operation. */
static gboolean
invoke_body_full (El721Qtee *session, guint32 command, gsize input_size,
                  gsize output_size, const guint8 *body, gsize body_size,
                  gsize out_capacity_offset, guint32 out_capacity,
                  guint8 **output, GError **error)
{
  guint8 request[EL721_MESSAGE_SIZE] = { 0 };
  guint8 response[EL721_MESSAGE_SIZE] = { 0 };
  guint8 request_out[EL721_MESSAGE_SIZE] = { 0 };
  guint8 response_out[EL721_MESSAGE_SIZE] = { 0 };
  guint32 offsets[] = { 4, 16 };
  guint32 is_64_bit = 1;
  struct qcomtee_param params[10] = { 0 };
  qcomtee_result_t result = QCOMTEE_ERROR;
  gboolean share = g_getenv ("EL721_SHARE_OBJECT") != NULL;
  guint64 raw_input_paddr = el721_probe_u64 ("EL721_INPUT_PADDR");
  guint64 raw_output_paddr = el721_probe_u64 ("EL721_OUTPUT_PADDR");
  guint8 *input = qcomtee_memory_object_addr (session->input);
  guint8 *out = qcomtee_memory_object_addr (share ? session->input
                                                  : session->output);
  guint32 trustlet, payload;

  if (input_size > EL721_INPUT_SHARED_SIZE ||
      output_size > EL721_OUTPUT_SHARED_SIZE ||
      body_size > input_size)
    {
      g_set_error_literal (error, EL721_ERROR, 1, "invalid BAUTH body size");
      return FALSE;
    }
  memset (input, 0, EL721_INPUT_SHARED_SIZE);
  if (!share)
    memset (out, 0, EL721_OUTPUT_SHARED_SIZE);
  if (out_capacity)
    put_u32 (out, out_capacity_offset, out_capacity);
  if (body_size)
    memcpy (input, body, body_size);
  put_u32 (input, 0, command);
  put_u32 (request, 0, command);
  put_u32 (request, 12, input_size);
  put_u32 (request, 24, output_size);
  params[0] = (struct qcomtee_param) { .attr = QCOMTEE_UBUF_INPUT,
                                      .ubuf = { request, sizeof (request) } };
  params[1] = (struct qcomtee_param) { .attr = QCOMTEE_UBUF_INPUT,
                                      .ubuf = { response, sizeof (response) } };
  /* Diagnostic: hand the TA the physical addresses directly instead of
   * letting QTEE patch its own mapped memory objects into the request, to
   * see whether qsee_register_shared_buffer() refuses a range QTEE has
   * already mapped for this invocation. */
  if (raw_input_paddr && raw_output_paddr)
    {
      put_u64 (request, 4, raw_input_paddr);
      put_u64 (request, 16, raw_output_paddr);
    }
  params[2] = (struct qcomtee_param) { .attr = QCOMTEE_UBUF_INPUT,
                                      .ubuf = { offsets,
                                                raw_input_paddr ? 0
                                                                : sizeof (offsets) } };
  params[3] = (struct qcomtee_param) { .attr = QCOMTEE_UBUF_INPUT,
                                      .ubuf = { &is_64_bit, sizeof (is_64_bit) } };
  params[4] = (struct qcomtee_param) { .attr = QCOMTEE_UBUF_OUTPUT,
                                      .ubuf = { request_out, sizeof (request_out) } };
  params[5] = (struct qcomtee_param) { .attr = QCOMTEE_UBUF_OUTPUT,
                                      .ubuf = { response_out, sizeof (response_out) } };
  params[6] = (struct qcomtee_param) { .attr = QCOMTEE_OBJREF_INPUT,
                                      .object = raw_input_paddr
                                                ? QCOMTEE_OBJECT_NULL
                                                : session->input };
  params[7] = (struct qcomtee_param) { .attr = QCOMTEE_OBJREF_INPUT,
                                      .object = raw_output_paddr
                                                ? QCOMTEE_OBJECT_NULL
                                                : (share ? session->input
                                                         : session->output) };
  /* Diagnostic: One UI leaves the last two object slots empty, but the
   * enrolment handlers register the buffers themselves; repeat them here to
   * see whether QTEE then hands the TA a mapping it can register. */
  if (g_getenv ("EL721_REPEAT_OBJECTS"))
    {
      params[8] = (struct qcomtee_param) { .attr = QCOMTEE_OBJREF_INPUT,
                                          .object = session->input };
      params[9] = (struct qcomtee_param) { .attr = QCOMTEE_OBJREF_INPUT,
                                          .object = session->output };
    }
  else
    {
      params[8] = (struct qcomtee_param) { .attr = QCOMTEE_OBJREF_INPUT,
                                          .object = QCOMTEE_OBJECT_NULL };
      params[9] = (struct qcomtee_param) { .attr = QCOMTEE_OBJREF_INPUT,
                                          .object = QCOMTEE_OBJECT_NULL };
    }
  if (qcomtee_object_invoke (session->controller, QSEECOM_SEND_REQUEST_OP,
                             params, 10, &result))
    {
      g_set_error_literal (error, EL721_ERROR, 1, "BAUTH transport failed");
      return FALSE;
    }
  trustlet = get_u32 (response_out, 4);
  payload = output_size >= 8 ? get_u32 (out, 4) : 0;
  if (result || trustlet)
    {
      g_set_error (error, EL721_ERROR, trustlet,
                   "BAUTH command %u failed (invoke=%u, trustlet=%u, payload=%u,"
                   " out=%u/%u/%u, response=%u/%u/%u)",
                   command, result, trustlet, payload,
                   output_size >= 4 ? get_u32 (out, 0) : 0,
                   output_size >= 8 ? get_u32 (out, 4) : 0,
                   output_size >= 12 ? get_u32 (out, 8) : 0,
                   get_u32 (response_out, 0), get_u32 (response_out, 8),
                   get_u32 (response_out, 12));
      return FALSE;
    }
  *output = out;
  return TRUE;
}

/* Diagnostic override for a single wire field while the enrolment structure
 * is still being matched against the stock gateway.  Absent in normal use. */
static guint32
el721_probe_u32 (const gchar *name, guint32 fallback)
{
  const gchar *value = g_getenv (name);

  return value ? (guint32) g_ascii_strtoull (value, NULL, 0) : fallback;
}

static void
decode_common (El721Reply *reply, const guint8 *output)
{
  el721_reply_clear (reply);
  reply->sensor = get_u32 (output, 0);
  reply->result = get_u32 (output, 4);
  reply->status = get_u32 (output, 8);
  reply->opcode = get_u32 (output, 12);
}

static gchar *
load_cell_id (El721Qtee *session, GError **error)
{
  g_autofree gchar *fallback = NULL;
  gchar *cell_id = NULL;
  gsize size = 0;
  guint i;

  if (!g_file_get_contents (EL721_CELL_ID_SYSFS, &cell_id, &size, NULL))
    {
      fallback = g_build_filename (session->firmware_directory, "cell_id", NULL);
      if (!g_file_get_contents (fallback, &cell_id, &size, error))
        return NULL;
    }
  g_strchomp (cell_id);
  size = strlen (cell_id);
  if (size != 22)
    goto invalid;
  for (i = 0; i < size; i++)
    if (!g_ascii_isxdigit (cell_id[i]))
      goto invalid;
  return cell_id;

invalid:
  g_set_error (error, EL721_ERROR, 1,
               "invalid ANA38407 cell ID (expected 22 hexadecimal characters)");
  g_free (cell_id);
  return NULL;
}

gboolean
el721_qtee_enroll_init (El721Qtee *session, const guint8 *user, gsize user_size,
                        guint32 template_id,
                        El721Reply *reply, GError **error)
{
  g_autofree guint8 *body = g_malloc0 (ENROLL_INIT_SIZE);
  g_autofree gchar *cell_id = NULL;
  guint8 *output;
  if (!user || user_size > 0x100)
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "invalid enrolment user identifier");
      return FALSE;
    }
  if (template_id < 1 || template_id > 4)
    {
      g_set_error_literal (error, EL721_ERROR, 1,
                           "invalid EL721 template index");
      return FALSE;
    }
  cell_id = load_cell_id (session, error);
  if (!cell_id)
    return FALSE;
  put_u32 (body, 0, CMD_ENROLL_INIT);
  /* Stock EnrollContext starts in opcode/state 1.  These are not the sensor
   * type and an Android group: BAuth_Enroll_Init serialises the available
   * template slot (1..4) and the EL721 capture count (7) at the tail. */
  put_u32 (body, 8, el721_probe_u32 ("EL721_ENROLL_STATE", 1));
  memcpy (body + 0xc, user, user_size);
  put_u32 (body, 0x10c, template_id);
  put_u32 (body, 0x110, 7);
  memcpy (body + 0x114, cell_id, strlen (cell_id));
  if (!invoke_body (session, CMD_ENROLL_INIT, ENROLL_INIT_SIZE,
                    el721_probe_u32 ("EL721_ENROLL_OUT", ENROLL_INIT_OUT_SIZE),
                    body, ENROLL_INIT_SIZE, &output, error))
    return FALSE;
  decode_common (reply, output);
  return TRUE;
}

gboolean
el721_qtee_enroll_do (El721Qtee *session, El721Reply *reply, GError **error)
{
  guint8 body[12] = { 0 };
  guint8 *output;
  put_u32 (body, 0, CMD_ENROLL_DO);
  put_u32 (body, 8, el721_probe_u32 ("EL721_SENSOR_TYPE",
                                     EL721_SENSOR_TYPE));
  if (!invoke_body (session, CMD_ENROLL_DO, sizeof (body), ENROLL_DO_OUT_SIZE,
                    body, sizeof (body), &output, error))
    return FALSE;
  decode_common (reply, output);
  reply->quality = get_u32 (output, 16);
  reply->progress = get_u32 (output, 20);
  reply->remaining = get_u32 (output, 24);
  return TRUE;
}

static gboolean
final_command (El721Qtee *session, guint32 command, El721Reply *reply,
               GError **error)
{
  guint8 body[12] = { 0 };
  guint8 *output;
  guint32 size;
  put_u32 (body, 0, command);
  put_u32 (body, 8, el721_probe_u32 ("EL721_SENSOR_TYPE",
                                     EL721_SENSOR_TYPE));
  if (!invoke_body (session, command, sizeof (body), FINAL_OUT_SIZE,
                    body, sizeof (body), &output, error))
    return FALSE;
  decode_common (reply, output);
  size = get_u32 (output, 0xa014);
  if (size > 0xa000)
    {
      g_set_error (error, EL721_ERROR, 1,
                   "BAUTH returned an invalid template size %u", size);
      return FALSE;
    }
  if (size)
    reply->data = g_bytes_new (output + 0x14, size);
  return TRUE;
}

gboolean
el721_qtee_enroll_final (El721Qtee *session, El721Reply *reply, GError **error)
{
  return final_command (session, CMD_ENROLL_FINAL, reply, error);
}

gboolean
el721_qtee_identify_init (El721Qtee *session, const guint8 *user,
                          gsize user_size, const guint8 *templates,
                          gsize templates_size, const guint8 *metadata,
                          gsize metadata_size, El721Reply *reply, GError **error)
{
  g_autofree guint8 *body = g_malloc0 (IDENTIFY_INIT_SIZE);
  g_autofree gchar *cell_id = NULL;
  guint8 *output;
  guint32 ids_size;
  if (!user || user_size > 0x100 || !templates || !templates_size ||
      templates_size >= 0x226000 || metadata_size > 0x400)
    {
      g_set_error_literal (error, EL721_ERROR, 1, "invalid identify gallery");
      return FALSE;
    }
  cell_id = load_cell_id (session, error);
  if (!cell_id)
    return FALSE;
  put_u32 (body, 0, CMD_IDENTIFY_INIT);
  put_u32 (body, 8, el721_probe_u32 ("EL721_SENSOR_TYPE",
                                     EL721_SENSOR_TYPE));
  memcpy (body + 0xc, user, user_size);
  memcpy (body + 0x10c, templates, templates_size);
  put_u32 (body, 0x22610c, templates_size);
  if (metadata_size)
    memcpy (body + 0x226110, metadata, metadata_size);
  put_u32 (body, 0x226510, metadata_size);
  memcpy (body + 0x226559, cell_id, strlen (cell_id));
  if (!invoke_body (session, CMD_IDENTIFY_INIT, IDENTIFY_INIT_SIZE,
                    IDENTIFY_INIT_OUT_SIZE, body, IDENTIFY_INIT_SIZE,
                    &output, error))
    return FALSE;
  decode_common (reply, output);
  ids_size = get_u32 (output, 0x19c);
  if (ids_size <= 0x190 && ids_size)
    reply->data = g_bytes_new (output + 0xc, ids_size);
  return TRUE;
}

gboolean
el721_qtee_identify_do (El721Qtee *session, guint32 opcode,
                        El721Reply *reply, GError **error)
{
  guint8 body[12] = { 0 };
  guint8 *output;
  guint32 update_size;
  put_u32 (body, 0, CMD_IDENTIFY_DO);
  put_u32 (body, 4, opcode);
  put_u32 (body, 8, el721_probe_u32 ("EL721_SENSOR_TYPE",
                                     EL721_SENSOR_TYPE));
  if (!invoke_body (session, CMD_IDENTIFY_DO, sizeof (body), IDENTIFY_DO_OUT_SIZE,
                    body, sizeof (body), &output, error))
    return FALSE;
  decode_common (reply, output);
  reply->template_id = get_u32 (output, 16);
  reply->quality = get_u32 (output, 20);
  update_size = get_u32 (output, 0x226038);
  if (update_size <= 0x226000 && update_size)
    reply->data = g_bytes_new (output + 0x38, update_size);
  return TRUE;
}

gboolean
el721_qtee_identify_final (El721Qtee *session, El721Reply *reply, GError **error)
{
  return final_command (session, CMD_IDENTIFY_FINAL, reply, error);
}

gboolean
el721_qtee_cancel (El721Qtee *session, El721Reply *reply, GError **error)
{
  guint8 body[CANCEL_WIRE_SIZE] = { 0 };
  guint8 *output;
  put_u32 (body, 0, CMD_CANCEL);
  if (!invoke_body (session, CMD_CANCEL, CANCEL_WIRE_SIZE, CANCEL_WIRE_SIZE,
                    body, sizeof (body), &output, error))
    return FALSE;
  decode_common (reply, output);
  return TRUE;
}
