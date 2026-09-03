/* SPDX-License-Identifier: BSD-3-Clause */
/* Boot-only owner of the global SPL listener and Keymaster DMA lease.
 * No enrollment, provisioning, root generation, secure PUT or Android data.
 * Keep transport internals private; this is a separate executable, not a new
 * exported libfprint ABI. Only the measured fresh-start sequence is available.
 */
#define _GNU_SOURCE
#include "el721-qtee.c"
#include <linux/dma-heap.h>
#include <uapi/linux/spcom.h>

static gboolean shared_with_ta;
static int lease_fd = -1;
static int spcom_fd = -1;
static struct qcomtee_object *lease_memory;

static gboolean
qc_command (struct qcomtee_object *controller, const guint8 *request,
            gsize size, gboolean optional_status)
{
  guint8 input[40960] = {0}, output[40960] = {0}, updated[128] = {0};
  guint32 architecture = 1;
  g_assert (size <= sizeof updated);
  /* Preserve the measured stock output capacity of Configure (28-byte
   * framing reservation, although this CBOR body is 25 bytes). */
  gsize capacity = sizeof input - (get_u32 (request, 0) == 0x2116 ? 28 : size);
  struct qcomtee_param params[10] = {
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { (void *) request, size } },
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { input, capacity } },
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { NULL, 0 } },
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { &architecture, sizeof architecture } },
    { .attr = QCOMTEE_UBUF_OUTPUT, .ubuf = { updated, size } },
    { .attr = QCOMTEE_UBUF_OUTPUT, .ubuf = { output, capacity } },
  };
  for (guint i = 6; i < G_N_ELEMENTS (params); i++)
    params[i].attr = QCOMTEE_OBJREF_INPUT;
  qcomtee_result_t result = QCOMTEE_ERROR;
  int transport = qcomtee_object_invoke (controller, 0, params, 10, &result);
  gint32 status = (gint32) get_u32 (output, 0);
  g_print ("SECURE_COMMAND cmd=%#x transport=%d result=%u status=%d\n",
           get_u32 (request, 0), transport, result, status);
  secure_clear (input, sizeof input);
  secure_clear (output, sizeof output);
  secure_clear (updated, sizeof updated);
  return !transport && !result && (optional_status || !status);
}

static gboolean
bind_spu_buffer (El721Qtee *session, struct qcomtee_object *controller)
{
  struct dma_heap_allocation_data allocation = {
    .len = 20480, .fd_flags = O_RDWR | O_CLOEXEC
  };
  struct spcom_ioctl_ch channel = {0};
  struct spcom_ioctl_dmabuf_lock lock = {0};
  int heap = open ("/dev/dma_heap/qcom,secure-sp-tz", O_RDONLY | O_CLOEXEC);
  if (heap < 0) return FALSE;
  int failed = ioctl (heap, DMA_HEAP_IOCTL_ALLOC, &allocation);
  close (heap);
  if (failed) return FALSE;
  lease_fd = allocation.fd;
  if (qcomtee_memory_object_register_fd (lease_fd, session->root, &lease_memory))
    return FALSE;
  spcom_fd = open ("/dev/spcom", O_RDWR | O_CLOEXEC);
  if (spcom_fd < 0) return FALSE;
  g_strlcpy (channel.ch_name, "sp_keymaster", sizeof channel.ch_name);
  if (ioctl (spcom_fd, SPCOM_IOCTL_CH_REGISTER, &channel)) return FALSE;
  for (guint i = 0; ; i++)
    {
      int connected = ioctl (spcom_fd, SPCOM_IOCTL_CH_IS_CONNECTED, &channel);
      if (connected > 0) break;
      if (connected < 0 || i == 49) return FALSE;
      g_usleep (100000);
    }
  lock.fd = lease_fd;
  g_strlcpy (lock.ch_name, "sp_keymaster", sizeof lock.ch_name);
  if (ioctl (spcom_fd, SPCOM_IOCTL_DMABUF_LOCK, &lock)) return FALSE;
  guint8 request[16] = {0}, updated[16] = {0};
  guint8 input[40944] = {0}, output[40944] = {0};
  guint32 offset = 4, architecture = 1;
  put_u32 (request, 0, 0x20d);
  put_u32 (request, 12, 20480);
  struct qcomtee_param params[10] = {
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { request, sizeof request } },
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { input, sizeof input } },
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { &offset, sizeof offset } },
    { .attr = QCOMTEE_UBUF_INPUT, .ubuf = { &architecture, sizeof architecture } },
    { .attr = QCOMTEE_UBUF_OUTPUT, .ubuf = { updated, sizeof updated } },
    { .attr = QCOMTEE_UBUF_OUTPUT, .ubuf = { output, sizeof output } },
    { .attr = QCOMTEE_OBJREF_INPUT, .object = lease_memory },
    { .attr = QCOMTEE_OBJREF_INPUT }, { .attr = QCOMTEE_OBJREF_INPUT },
    { .attr = QCOMTEE_OBJREF_INPUT },
  };
  qcomtee_result_t result = QCOMTEE_ERROR;
  /* A failed/uncertain transport may already have delivered the DMA address.
   * From this point onward, even failure must retain this process and memory. */
  shared_with_ta = TRUE;
  int transport = qcomtee_object_invoke (controller, 0, params, 10, &result);
  gint32 status = (gint32) get_u32 (output, 0);
  g_print ("SECURE_DMA_BIND transport=%d result=%u status=%d\n", transport, result, status);
  secure_clear (output, sizeof output);
  secure_clear (updated, sizeof updated);
  if (transport || result || status) return FALSE;
  if (ioctl (spcom_fd, SPCOM_IOCTL_CH_UNREGISTER, &channel)) return FALSE;
  return TRUE;
}

int main (int argc, char **argv)
{
  if (argc != 2 || strcmp (argv[1], "--boot")) return 64;
  if (geteuid () != 0) return 77;
  setvbuf (stdout, NULL, _IOLBF, 0);
  /* The supervisor creates this exclusive boot marker before launching us. */
  if (access ("/run/gts9u-fingerprint-secure/attempt", F_OK)) return 78;
  g_autoptr(GError) error = NULL;
  El721Qtee *session = g_new0 (El721Qtee, 1);
  struct qcomtee_object *controller = QCOMTEE_OBJECT_NULL;
  qcomtee_result_t result = QCOMTEE_ERROR;
  guint8 request[128] = {0};
  gboolean ready = FALSE;
  session->firmware_directory = g_strdup ("/usr/lib/firmware/gts9u/fingerprint");
  session->root = open_root (&error);
  if (!session->root) goto finished;
  session->client_env = open_client_env (session->root, &error);
  if (!session->client_env) goto finished;
  session->app_loader = open_service (session->client_env, QSEECOM_APP_LOADER_UID, &error);
  if (!session->app_loader || !register_qis_listener (session, &error)) goto finished;
  if (!lookup_ta (session, "keymaster64", &controller, &result) || result || !controller)
    goto finished;
  put_u32 (request, 0, 0x200);
  if (!qc_command (controller, request, 4, FALSE)) goto finished;
  put_u32 (request, 0, 0x207);
  put_u32 (request, 4, 4); put_u32 (request, 8, 5);
  put_u32 (request, 12, 4); put_u32 (request, 16, 5);
  if (!qc_command (controller, request, 24, FALSE) || !bind_spu_buffer (session, controller))
    goto finished;
  memset (request, 0, sizeof request);
  put_u32 (request, 0, 0x215);
  if (!qc_command (controller, request, 12, FALSE)) goto finished;
  put_u32 (request, 0, 0x3121);
  memcpy (request + 4, "\xa1\x0b\x18\xc8", 4);
  /* Stock continues past negative SetVersion status on this API. Configure and
   * authenticated cache restoration below must still actually succeed. */
  if (!qc_command (controller, request, 8, TRUE)) goto finished;
  memset (request, 0, sizeof request);
  put_u32 (request, 0, 0x2116);
  static const guint8 parameters[] = {
    0xa4, 0x16, 0x03,
    0x1a, 0x30, 0x00, 0x02, 0xc1, 0x00,
    0x1a, 0x30, 0x00, 0x02, 0xc2, 0x00,
    0x1a, 0x30, 0x00, 0x02, 0xce, 0x00
  };
  memcpy (request + 4, parameters, sizeof parameters);
  if (!qc_command (controller, request, 4 + sizeof parameters, FALSE)) goto finished;
  ready = el721_qtee_restore_hwvault (session, &error);
finished:
  g_print ("%s\n", ready ? "SECURE_READY" : "SECURE_FAILED");
  if (error) g_printerr ("Secure startup: %s\n", error->message);
  if (!shared_with_ta) return ready ? 0 : 1;
  /* This process is boot-lifetime infrastructure, not a restartable matcher.
   * Readiness failure is reported, but resources remain owned until the full
   * OS reboot. The service forbids manual stop/restart and automatic restart. */
  for (;;) pause ();
}
