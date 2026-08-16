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

    /**
     * The set that was running when a switch was staged, and the one written.
     *
     * This is the one thing the partitions cannot tell us: once written they
     * report the system that *will* boot, and nothing on them remembers the
     * one still running.  Kept only until the two agree again — see
     * [BootState], which never trusts these without checking the hashes.
     */
    var stagedFrom: String?
        get() = prefs.getString(KEY_STAGED_FROM, null)
        set(value) = prefs.edit().putString(KEY_STAGED_FROM, value).apply()

    var stagedTarget: String?
        get() = prefs.getString(KEY_STAGED_TARGET, null)
        set(value) = prefs.edit().putString(KEY_STAGED_TARGET, value).apply()

    fun clearStaged() {
        prefs.edit().remove(KEY_STAGED_FROM).remove(KEY_STAGED_TARGET).apply()
    }

    private companion object {
        const val KEY_SKIP_CONFIRMATION = "skip_confirmation"
        const val KEY_STAGED_FROM = "staged_from"
        const val KEY_STAGED_TARGET = "staged_target"
    }
}
