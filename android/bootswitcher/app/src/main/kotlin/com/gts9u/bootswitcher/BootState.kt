package com.gts9u.bootswitcher

import android.content.Context

/**
 * Which system you are in, and which one the tablet will boot next.
 *
 * These stopped being the same question the moment writing the partitions was
 * split from restarting.  Once a set has been written the four partitions hold
 * the *other* system while this app keeps running on the old one, and that
 * gap can outlive the app: it is closed by a restart, not by a process.
 *
 * So the state is not kept in memory.  It is read back from the tablet every
 * time, from two sources that survive anything:
 *
 *  - the partitions themselves, hashed, say what will boot;
 *  - a note in preferences says what was running when the switch was staged.
 *
 * The note is only ever trusted when the partitions agree with it, so a
 * restart, a switch made from the Linux side, or a stale note all resolve the
 * same way: back to plain reality.
 */
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

    fun read(context: Context): Snapshot {
        val sets = BootSets.discover()
        val nextBoot = BootSets.identify(BootSets.liveHashes(), sets)
        return Snapshot(sets, resolveRunning(context, sets, nextBoot), nextBoot)
    }

    /**
     * Records that [target] has been written while [from] is still running.
     *
     * Passing the same set for both is how a staged switch is undone.
     */
    fun stage(context: Context, from: BootSets.BootSet?, target: BootSets.BootSet) {
        val prefs = Prefs(context)
        if (from == null || from.id == target.id) {
            prefs.clearStaged()
        } else {
            prefs.stagedFrom = from.id
            prefs.stagedTarget = target.id
        }
    }

    private fun resolveRunning(
        context: Context,
        sets: List<BootSets.BootSet>,
        nextBoot: BootSets.BootSet?,
    ): BootSets.BootSet? {
        val prefs = Prefs(context)
        val from = prefs.stagedFrom
        val target = prefs.stagedTarget

        // The note only counts if the partitions still hold what it claims.
        if (from != null && target != null && nextBoot?.id == target && from != target) {
            val running = sets.firstOrNull { it.id == from }
            if (running != null) return running
        }
        if (from != null || target != null) prefs.clearStaged()

        // Without a usable note the partitions are the only evidence — unless
        // the running system says its own name and some *other* set answers to
        // it, which can only mean a switch was staged and the note was lost.
        // That is what keeps the app honest after its data is cleared, instead
        // of quietly claiming to be a system it is not.
        //
        // Deliberately not written back. This is a read, and a read that
        // leaves a "switch staged" note behind makes the app's own state hard
        // to account for later — the answer is recomputed from the same two
        // facts every time anyway, so storing it buys nothing.
        val name = BootSets.runningSystemName()
        val byName = sets.firstOrNull { it.label == name && it.id != nextBoot?.id }
        if (byName != null && nextBoot != null) return byName
        return nextBoot
    }
}
