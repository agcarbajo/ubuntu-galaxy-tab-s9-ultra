/* SPDX-License-Identifier: BSD-3-Clause */
#pragma once

#include <glib.h>
#include <stdint.h>

typedef struct _El721Qtee El721Qtee;

#define EL721_HARDWARE_AUTH_TOKEN_SIZE 69U
#define EL721_CHALLENGE_INFO_SIZE 60U

typedef struct
{
  guint8 bytes[EL721_CHALLENGE_INFO_SIZE];
} El721Challenge;

typedef struct
{
  guint32 sensor;
  guint32 result;
  guint32 status;
  guint32 opcode;
  guint32 quality;
  guint32 progress;
  guint32 template_id;
  guint32 remaining;
  GBytes *data;
} El721Reply;

El721Qtee *el721_qtee_open          (const gchar  *firmware_directory,
                                    GError      **error);
void        el721_qtee_close         (El721Qtee   *session);
gboolean    el721_qtee_prepare       (El721Qtee   *session,
                                     GError      **error);
gboolean    el721_qtee_raw_command   (El721Qtee   *session,
                                     guint32       command,
                                     gsize         input_size,
                                     gsize         output_size,
                                     guint32      *result,
                                     GError      **error);
gboolean    el721_qtee_generate_challenge (El721Qtee      *session,
                                           guint32          user_id,
                                           guint32          authenticator_id,
                                           El721Challenge  *challenge,
                                           guint32         *result,
                                           GError         **error);
gboolean    el721_qtee_hat_op        (El721Qtee           *session,
                                     const guint8         *hat,
                                     gsize                 hat_size,
                                     guint32               selector,
                                     const guint8         *payload,
                                     gsize                 payload_size,
                                     const El721Challenge *challenge,
                                     guint32              *result,
                                     GError              **error);
gboolean    el721_qtee_authorize_enrollment (El721Qtee   *session,
                                             guint32       user_id,
                                             guint32       authenticator_id,
                                             GError      **error);
gboolean    el721_qtee_control_user  (El721Qtee   *session,
                                     guint32       operation,
                                     const guint8 *user,
                                     gsize         user_size,
                                     gboolean      repeat_as_payload,
                                     guint32       scalar,
                                     gsize         response_capacity,
                                     GError      **error);
gboolean    el721_qtee_control_scalar (El721Qtee  *session,
                                     guint32       operation,
                                     guint32       scalar,
                                     gsize         response_capacity,
                                     GError      **error);
gboolean    el721_qtee_control_bytes (El721Qtee   *session,
                                     guint32       operation,
                                     const guint8 *data,
                                     gsize         data_size,
                                     GError      **error);
gboolean    el721_qtee_control_op    (El721Qtee   *session,
                                     guint32       operation,
                                     const guint8 *data,
                                     gsize         data_size,
                                     gsize         response_capacity,
                                     GError      **error);
gboolean    el721_qtee_set_active_group (El721Qtee   *session,
                                         const guint8 *user,
                                         gsize         user_size,
                                         GBytes       *wrapped_key,
                                         GBytes      **generated_key,
                                         GError      **error);
gboolean    el721_qtee_enroll_init   (El721Qtee   *session,
                                     const guint8 *user,
                                     gsize         user_size,
                                     guint32       template_id,
                                     El721Reply   *reply,
                                     GError      **error);
gboolean    el721_qtee_enroll_do     (El721Qtee   *session,
                                     El721Reply   *reply,
                                     GError      **error);
gboolean    el721_qtee_enroll_final  (El721Qtee   *session,
                                     El721Reply   *reply,
                                     GError      **error);
gboolean    el721_qtee_identify_init (El721Qtee   *session,
                                     const guint8 *user,
                                     gsize         user_size,
                                     const guint8 *templates,
                                     gsize         templates_size,
                                     const guint8 *metadata,
                                     gsize         metadata_size,
                                     El721Reply   *reply,
                                     GError      **error);
gboolean    el721_qtee_identify_do   (El721Qtee   *session,
                                     guint32       opcode,
                                     El721Reply   *reply,
                                     GError      **error);
gboolean    el721_qtee_identify_final (El721Qtee  *session,
                                      El721Reply  *reply,
                                      GError     **error);
gboolean    el721_qtee_cancel        (El721Qtee   *session,
                                     El721Reply   *reply,
                                     GError      **error);
void        el721_reply_clear        (El721Reply  *reply);
