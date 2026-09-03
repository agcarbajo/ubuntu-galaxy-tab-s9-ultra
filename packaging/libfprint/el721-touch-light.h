/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include <glib.h>

/* Allow the 50 ms Shell observer and several compositor frames to present
 * the white target before the synchronous secure capture. This is a bounded
 * settling interval, not an acknowledgement from the compositor. */
#define EL721_LIGHT_SETTLE_US (180 * 1000)

typedef enum
{
  EL721_LIGHT_WAIT,
  EL721_LIGHT_ON,
  EL721_LIGHT_OFF,
  EL721_LIGHT_CAPTURE,
} El721LightStep;

static inline El721LightStep
el721_touch_light_step (gint64 *deadline, gint64 now,
                        gboolean pressed, gboolean new_contact)
{
  if (*deadline)
    {
      if (!pressed)
        {
          *deadline = 0;
          return EL721_LIGHT_OFF;
        }
      if (now >= *deadline)
        {
          *deadline = 0;
          return EL721_LIGHT_CAPTURE;
        }
    }
  else if (new_contact && pressed)
    {
      *deadline = now + EL721_LIGHT_SETTLE_US;
      return EL721_LIGHT_ON;
    }
  return EL721_LIGHT_WAIT;
}
