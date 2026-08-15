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

    override fun onStartListening() {
        super.onStartListening()
        refresh()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun refresh() = scope.launch {
        val found = withContext(Dispatchers.IO) {
            if (!Root.available()) return@withContext null
            val sets = BootSets.discover()
            val current = BootSets.identify(BootSets.liveHashes(), sets)
            sets.firstOrNull { it.id != current?.id && it.complete }
        }

        target = found
        qsTile?.apply {
            if (found == null) {
                state = Tile.STATE_UNAVAILABLE
                label = getString(R.string.tile_label)
                subtitle = getString(R.string.tile_unavailable)
            } else {
                state = Tile.STATE_INACTIVE
                label = getString(R.string.tile_label)
                subtitle = found.label
            }
            icon = Icon.createWithResource(this@BootSwitchTile, R.drawable.ic_tile_dualboot)
            updateTile()
        }
    }

    override fun onClick() {
        super.onClick()
        val set = target ?: return
        // The tile can be tapped over a lock screen, and neither the dialog nor
        // the reboot should happen behind one.
        unlockAndRun {
            if (Prefs(this).skipConfirmation) switch(set) else confirm(set)
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
        Toast.makeText(this@BootSwitchTile, R.string.tile_writing, Toast.LENGTH_SHORT).show()

        val ok = withContext(Dispatchers.IO) {
            // The partition-by-partition log belongs in the app; from a tile
            // only the verdict matters, and a failure must not reboot.
            BootSets.write(set) { }
        }

        if (ok) {
            withContext(Dispatchers.IO) { BootSets.reboot() }
        } else {
            Toast.makeText(this@BootSwitchTile, R.string.tile_failed, Toast.LENGTH_LONG).show()
            refresh()
        }
    }
}
