package com.gts9u.bootswitcher

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Serialized with discovery/writes; keeps OTA images accessible from Ubuntu. */
object BootMaintenance {
    private var context: Context? = null
    private fun quote(value: String) = "'" + value.replace("'", "'\\''") + "'"

    fun log(context: Context): String = context.getSharedPreferences("maintenance", 0)
        .getString("log", "") ?: ""

    private fun record(context: Context, message: String) {
        val time = SimpleDateFormat("MM-dd HH:mm:ss", Locale.ROOT).format(Date())
        context.getSharedPreferences("maintenance", 0).edit()
            .putString("log", (log(context) + "\n$time $message").takeLast(6000)).commit()
    }

    fun recoverInterrupted() {
        if (!BootSets.mountLinuxRoot()) return
        Root.run("""
            m=${BootSets.LINUX_MOUNT}
            b=${BootSets.LINUX_MOUNT}/var/lib/gts9u-boot-backups
            for previous in "${'$'}b"/*.previous; do
                [ -d "${'$'}previous" ] || continue
                id=${'$'}{previous##*/}; id=${'$'}{id%.previous}
                case "${'$'}id" in ''|*[!a-zA-Z0-9_-]*) continue;; esac
                target=${BootSets.LINUX_SETS}/${'$'}id
                [ ! -e "${'$'}target" ] || continue
                if grep " ${'$'}m " /proc/mounts | grep -q noload; then exit 1; fi
                mount -o remount,rw "${'$'}m"
                trap 'sync; mount -o remount,ro "${'$'}m"' EXIT
                mv "${'$'}previous" "${'$'}target"
                sync
            done
        """.trimIndent())
    }

    fun beforeSwitch(): Boolean {
        val ctx = context ?: return false
        return refresh(ctx, BootSets.discover(), BootSets.liveHashes())
    }

    fun refresh(ctx: Context, sets: List<BootSets.BootSet>, live: Map<String, String>): Boolean {
        context = ctx.applicationContext
        val android = sets.filterNot { BootSets.isLinux(it) }.singleOrNull()
        val decision = BootSets.backupDecision(sets, live)
        if (android == null || decision == BootSets.BackupDecision.AMBIGUOUS) {
            record(ctx, "Android: cannot identify a unique backup or read all partitions.")
            return false
        }
        val next = BootSets.identify(live, sets)
        if (decision == BootSets.BackupDecision.LINUX_STAGED) {
            record(ctx, "Android: Linux is staged; Android backup preserved.")
            return true
        }
        if (decision == BootSets.BackupDecision.MIXED) {
            record(ctx, "Android: mixed boot partitions; backup preserved, switching blocked.")
            return false
        }
        if (android.dir != "${BootSets.LINUX_SETS}/${android.id}" ||
            !android.id.matches(Regex("[a-zA-Z0-9_-]+"))) {
            record(ctx, "Android: manual backup override; automatic replacement refused.")
            return next?.id == android.id
        }
        val name = BootSets.runningSystemName()
        val changed = next?.id != android.id
        if (!changed && android.label == name) {
            record(ctx, "Android: all four backup hashes match; no copy needed.")
            return true
        }
        val expected = BootSets.PARTITIONS.joinToString("\n") {
            "${live.getValue(it.device)}  ${it.name}.img"
        }
        val script = ctx.assets.open("refresh-android.sh").bufferedReader().use { it.readText() }
        val result = Root.run("SET_ID=${quote(android.id)}", "SYSTEM_NAME=${quote(name)}",
            "EXPECTED=${quote(expected)}", "CHANGED=${if (changed) 1 else 0}", script)
        record(ctx, (if (result.ok) "" else "Android: backup refresh failed (${result.code}).\n") +
            result.output.takeLast(2000))
        if (!result.ok) return false
        Prefs(ctx).clearTileCache()
        return true
    }
}
