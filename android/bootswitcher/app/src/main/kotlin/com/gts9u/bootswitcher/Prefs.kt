package com.gts9u.bootswitcher

import android.content.Context

/**
 * The handful of choices worth remembering.
 *
 * Deliberately tiny: the app's real state lives in the partitions, and
 * anything cached here would only be a second version of the truth.
 */
class Prefs(context: Context) {

    private val prefs = context.getSharedPreferences("bootswitcher", Context.MODE_PRIVATE)

    /**
     * Whether to skip the "are you sure" step before rebooting.
     *
     * Off by default: writing the boot partitions and restarting is not
     * something to do by brushing a tile in a pull-down menu.
     */
    var skipConfirmation: Boolean
        get() = prefs.getBoolean(KEY_SKIP_CONFIRMATION, false)
        set(value) = prefs.edit().putBoolean(KEY_SKIP_CONFIRMATION, value).apply()

    private companion object {
        const val KEY_SKIP_CONFIRMATION = "skip_confirmation"
    }
}
