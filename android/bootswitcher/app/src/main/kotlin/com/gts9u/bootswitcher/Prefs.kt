package com.gts9u.bootswitcher

import android.content.Context
import android.os.SystemClock

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

    /**
     * What the quick settings tile last drew, and the boot it drew it in.
     *
     * The tile's `onStartListening` runs every time the shade comes down, and
     * answering it honestly costs about ten root shells and 432 MiB of sha256 --
     * which Magisk announces each time, so it reads as the app pestering for root
     * while the tile is on screen.  The four partitions cannot change without
     * either a reboot or this app writing them, so the answer holds for a whole
     * boot: it is kept against [bootStamp] and thrown away by [BootState.stage].
     * A tap still asks the tablet for the truth before anything is written.
     */
    var tileBoot: Long
        get() = prefs.getLong(KEY_TILE_BOOT, 0L)
        set(value) = prefs.edit().putLong(KEY_TILE_BOOT, value).apply()

    /** The other system's name, or null when there is nothing to switch to. */
    var tileLabel: String?
        get() = prefs.getString(KEY_TILE_LABEL, null)
        set(value) = prefs.edit().putString(KEY_TILE_LABEL, value).apply()

    fun clearTileCache() {
        prefs.edit().remove(KEY_TILE_BOOT).remove(KEY_TILE_LABEL).apply()
    }

    companion object {
        /** Identifies this boot, asking root for nothing: when the tablet started. */
        fun bootStamp(): Long = System.currentTimeMillis() - SystemClock.elapsedRealtime()

        /**
         * Whether two stamps are the same boot.
         *
         * Compared loosely because the wall clock is corrected after boot, which
         * moves the computed start by a second or two without the tablet having
         * restarted at all.
         */
        fun sameBoot(a: Long, b: Long): Boolean =
            a != 0L && b != 0L && Math.abs(a - b) < 60_000L

        private const val KEY_SKIP_CONFIRMATION = "skip_confirmation"
        private const val KEY_STAGED_FROM = "staged_from"
        private const val KEY_STAGED_TARGET = "staged_target"
        private const val KEY_TILE_BOOT = "tile_boot"
        private const val KEY_TILE_LABEL = "tile_label"
    }
}
