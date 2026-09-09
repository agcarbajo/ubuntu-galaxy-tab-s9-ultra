package com.gts9u.bootswitcher

import android.content.Context

/** Running Android is distinct from the system staged on the boot partitions. */
object BootState {

    data class Snapshot(
        val sets: List<BootSets.BootSet>,
        /** The system this app is running on. */
        val running: BootSets.BootSet?,
        /** The system the four partitions will boot. */
        val nextBoot: BootSets.BootSet?,
    ) {
        /** Written but not yet booted: the restart is still pending. */
        val staged: Boolean
            get() = running != null && nextBoot != null && running.id != nextBoot.id
    }

    @Synchronized
    fun read(context: Context): Snapshot = synchronized(BootSets) {
        BootMaintenance.recoverInterrupted()
        var sets = BootSets.discover()
        val live = BootSets.liveHashes()
        BootMaintenance.refresh(context, sets, live)
        sets = BootSets.discover()
        val name = BootSets.runningSystemName()
        val running = BootSets.runningAndroid(sets, name)
        val shown = sets.map { if (it.id == running?.id) running else it }
        // This Android application cannot be running Ubuntu. Image hashes only
        // describe the next boot, and name.txt may have been stamped by Linux.
        Prefs(context).clearStaged()
        return@synchronized Snapshot(shown, running, BootSets.identify(live, shown))
    }

    /**
     * Records that [target] has been written while [from] is still running.
     *
     * Passing the same set for both is how a staged switch is undone.
     */
    fun stage(context: Context, from: BootSets.BootSet?, target: BootSets.BootSet) {
        val prefs = Prefs(context)
        // The partitions are about to say something else, so whatever the tile
        // drew for this boot is now a lie.
        prefs.clearTileCache()
        if (from == null || from.id == target.id) {
            prefs.clearStaged()
        } else {
            prefs.stagedFrom = from.id
            prefs.stagedTarget = target.id
        }
    }

}
