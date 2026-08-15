package com.gts9u.bootswitcher

/**
 * Switching between Ubuntu and One UI on this tablet means replacing four
 * partitions and nothing else.
 *
 * `vbmeta` is deliberately absent.  One UI runs fine with the unsigned
 * flags=2 vbmeta that Ubuntu needs, so it never has to change — and it must
 * not, because rewriting it invalidates the key Android derives for its
 * metadata-encrypted /data, which costs a full wipe of Android's user data
 * every single time.
 */
object BootSets {

    /** Sizes are fixed by the partition table; anything else is a wrong file. */
    val PARTITIONS: List<Partition> = listOf(
        Partition("boot", 100_663_296L),
        Partition("init_boot", 8_388_608L),
        Partition("vendor_boot", 100_663_296L),
        Partition("dtbo", 16_777_216L),
    )

    data class Partition(val name: String, val bytes: Long) {
        val device: String get() = "/dev/block/by-name/$name"
    }

    enum class System(val id: String, val label: String) {
        UBUNTU("ubuntu", "Ubuntu 24.04"),
        ONEUI("oneui", "One UI 8"),
    }

    /** Where the two sets of images live on the tablet. */
    const val ROOT_DIR = "/sdcard/BootSets"

    fun dirFor(system: System): String = "$ROOT_DIR/${system.id}"

    fun fileFor(system: System, part: Partition): String = "${dirFor(system)}/${part.name}.img"

    // -- reading -------------------------------------------------------------

    /** sha256 of every boot partition as the tablet holds it right now. */
    fun liveHashes(): Map<String, String> {
        val result = Root.run(*PARTITIONS.map { "sha256sum ${it.device}" }.toTypedArray())
        if (!result.ok) return emptyMap()
        return parseSums(result.output, PARTITIONS.map { it.device })
    }

    /**
     * sha256 of a stored set, or an empty map when the set is incomplete.
     *
     * A missing or short file has to be caught here, before anything is
     * written: half a set on disk would otherwise become half a set on the
     * partitions, and the tablet would boot neither system.
     */
    fun setHashes(system: System): Map<String, String> {
        val files = PARTITIONS.map { fileFor(system, it) }
        val checks = PARTITIONS.map { part ->
            val f = fileFor(system, part)
            "[ -f \"$f\" ] || { echo \"FALTA $f\"; exit 1; }\n" +
                "[ \"\$(stat -c %s \"$f\")\" = \"${part.bytes}\" ] || { echo \"TAMANO $f\"; exit 1; }"
        }
        val result = Root.run(*(checks + files.map { "sha256sum \"$it\"" }).toTypedArray())
        if (!result.ok) return emptyMap()
        return parseSums(result.output, files)
    }

    /** Which system the four live partitions correspond to, if any. */
    fun identify(live: Map<String, String>, sets: Map<System, Map<String, String>>): System? {
        if (live.size != PARTITIONS.size) return null
        return System.entries.firstOrNull { system ->
            val stored = sets[system] ?: return@firstOrNull false
            stored.size == PARTITIONS.size && PARTITIONS.all { part ->
                live[part.device] != null && live[part.device] == stored[fileFor(system, part)]
            }
        }
    }

    // -- writing -------------------------------------------------------------

    sealed interface Progress {
        data class Step(val message: String) : Progress
        data class Failed(val message: String) : Progress
        data object Done : Progress
    }

    /**
     * Writes one system's set, verifying every partition by reading it back.
     *
     * Nothing reboots here.  A caller that has seen [Progress.Failed] must be
     * able to stop, because a tablet with three of four partitions replaced
     * still boots the system it is on — but only until it is restarted.
     */
    fun write(system: System, log: (Progress) -> Unit): Boolean {
        val stored = setHashes(system)
        if (stored.size != PARTITIONS.size) {
            log(Progress.Failed("El juego de ${system.label} está incompleto o tiene tamaños raros."))
            return false
        }

        for (part in PARTITIONS) {
            val file = fileFor(system, part)
            val expected = stored[file]
            log(Progress.Step("Escribiendo ${part.name}…"))

            val write = Root.run(
                "dd if=\"$file\" of=\"${part.device}\" bs=4M",
                "sync",
            )
            if (!write.ok) {
                log(Progress.Failed("No pude escribir ${part.name}: ${write.output.take(200)}"))
                return false
            }

            val reread = Root.run("sha256sum ${part.device}")
            val got = parseSums(reread.output, listOf(part.device))[part.device]
            if (got == null || got != expected) {
                log(Progress.Failed("${part.name} no coincide al releerla. No reinicies: revísalo."))
                return false
            }
            log(Progress.Step("${part.name} verificada."))
        }

        log(Progress.Done)
        return true
    }

    fun reboot() {
        Root.run("sync", "svc power reboot || reboot")
    }

    // -- helpers -------------------------------------------------------------

    /**
     * `sha256sum` prints "<hash>  <path>", and busybox and toybox disagree on
     * the spacing, so the path is matched rather than the column.
     */
    private fun parseSums(output: String, paths: List<String>): Map<String, String> {
        val out = mutableMapOf<String, String>()
        output.lineSequence().forEach { line ->
            val trimmed = line.trim()
            val hash = trimmed.substringBefore(' ').trim()
            if (hash.length != 64) return@forEach
            val path = paths.firstOrNull { trimmed.endsWith(it) }
            if (path != null) out[path] = hash
        }
        return out
    }
}
