package com.gts9u.bootswitcher

import android.app.AlertDialog
import android.graphics.drawable.Icon
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.Toast
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * A quick settings tile that restarts the tablet into the other system.
 *
 * It asks first.  On Linux the polkit password is the confirmation; here root
 * is already granted to the app, so a bare tap would reboot the tablet from a
 * pull-down menu with nothing in between — and a tile sits one thumb away from
 * the brightness slider.
 */
class BootSwitchTile : TileService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var target: BootSets.BootSet? = null

    private var running: BootSets.BootSet? = null

    /** True when the images are already on the partitions and only a restart is left. */
    private var staged = false

    override fun onStartListening() {
        super.onStartListening()
        refresh()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    /**
     * Brings the tile up to date, from the cache unless [force].
     *
     * Reading the tablet means about ten root shells and hashing 432 MiB, and
     * this runs every single time the shade comes down.  See [Prefs.tileBoot]
     * for why one read per boot is enough.
     */
    private fun refresh(force: Boolean = false) = scope.launch {
        val prefs = Prefs(this@BootSwitchTile)
        if (!force && Prefs.sameBoot(prefs.tileBoot, Prefs.bootStamp())) {
            draw(prefs.tileLabel)
            return@launch
        }

        val shot = withContext(Dispatchers.IO) {
            if (!Root.available()) return@withContext null
            BootState.read(this@BootSwitchTile)
        }

        // The tile goes to the other system, which is whichever is not running
        // — the same one the app offers, staged or not.
        val found = shot?.sets?.firstOrNull { it.id != shot.running?.id && it.complete }
        target = found
        running = shot?.running
        staged = shot?.staged == true && shot.nextBoot?.id == found?.id

        // Only a real read is worth keeping.  Caching a failed one would leave
        // the tile insisting there is nowhere to go until the next restart.
        if (shot != null) {
            prefs.tileLabel = found?.label
            prefs.tileBoot = Prefs.bootStamp()
        }
        draw(found?.label)
    }

    private fun draw(other: String?) {
        qsTile?.apply {
            if (other == null) {
                state = Tile.STATE_UNAVAILABLE
                subtitle = getString(R.string.tile_unavailable)
            } else {
                state = Tile.STATE_INACTIVE
                subtitle = other
            }
            label = getString(R.string.tile_label)
            icon = Icon.createWithResource(this@BootSwitchTile, R.drawable.ic_tile_dualboot)
            updateTile()
        }
    }

    override fun onClick() {
        super.onClick()
        // The tile can be tapped over a lock screen, and neither the dialog nor
        // the reboot should happen behind one.
        unlockAndRun {
            scope.launch {
                // What is on screen may have been drawn from the cache, and a
                // cached label is not enough to write with: the set carries the
                // files. Nothing is touched until the tablet has been asked.
                refresh(force = true).join()
                val set = target ?: return@launch
                if (Prefs(this@BootSwitchTile).skipConfirmation) switch(set) else confirm(set)
            }
        }
    }

    private fun confirm(set: BootSets.BootSet) {
        val dialog = AlertDialog.Builder(this)
            .setTitle(getString(R.string.tile_confirm_title, set.label))
            .setMessage(R.string.tile_confirm_message)
            .setNegativeButton(android.R.string.cancel) { d, _ -> d.dismiss() }
            .setPositiveButton(R.string.tile_confirm_ok) { d, _ ->
                d.dismiss()
                switch(set)
            }
            .create()
        showDialog(dialog)
    }

    private fun switch(set: BootSets.BootSet) = scope.launch {
        // Already written from the app: rewriting four identical partitions
        // would only delay the restart.
        if (staged) {
            withContext(Dispatchers.IO) { BootSets.reboot() }
            return@launch
        }

        Toast.makeText(this@BootSwitchTile, R.string.tile_writing, Toast.LENGTH_SHORT).show()

        val ok = withContext(Dispatchers.IO) {
            // The partition-by-partition log belongs in the app; from a tile
            // only the verdict matters, and a failure must not reboot.
            BootSets.write(set) { }
        }

        if (ok) {
            // `running` was read before the write: afterwards the partitions
            // report the new system and the old one is unrecoverable.
            BootState.stage(this@BootSwitchTile, running, set)
            withContext(Dispatchers.IO) { BootSets.reboot() }
        } else {
            Toast.makeText(this@BootSwitchTile, R.string.tile_failed, Toast.LENGTH_LONG).show()
            refresh(force = true)
        }
    }
}
