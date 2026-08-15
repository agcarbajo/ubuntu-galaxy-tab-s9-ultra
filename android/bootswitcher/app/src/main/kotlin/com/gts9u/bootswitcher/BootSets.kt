package com.gts9u.bootswitcher

/**
 * Switching systems on this tablet means replacing four partitions.
 *
 * The sets are discovered rather than hardcoded: every directory under
 * [ROOT_DIR] that holds the four images is a system the tablet can boot, so
 * adding LineageOS is dropping a folder in, not editing this file.
 *
 * `vbmeta` is deliberately not in the list.  One UI runs fine with the
 * unsigned flags=2 vbmeta that Ubuntu needs, so it never has to change — and
 * it must not, because rewriting it invalidates the key Android derives for
 * its metadata-encrypted /data, which costs a full wipe of Android's user data
 * every single time.
 *
 * What this app does NOT do is move `super`.  Two Android ROMs — One UI and
 * LineageOS — share that partition, so they cannot both be installed at once;
 * swapping their boot sets alone would boot a kernel against the other ROM's
 * system.  The pairing that works is Ubuntu against whichever Android is
 * installed.
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

    /** One bootable system: a directory of images plus a name to show. */
    data class BootSet(
        val id: String,
        val label: String,
        val complete: Boolean,
        val hashes: Map<String, String>,
    ) {
        val dir: String get() = "$ROOT_DIR/$id"
        fun file(part: Partition): String = "$dir/${part.name}.img"
    }

    const val ROOT_DIR = "/sdcard/BootSets"

    /**
     * Last-resort names, deliberately without version numbers.
     *
     * A real name comes from `name.txt`, stamped by whichever system is
     * running — see [runningSystemName].  Guessing a version here is how a
     * tablet on One UI 7 ends up being told it runs One UI 8.
     */
    private val KNOWN_LABELS = mapOf(
        "ubuntu" to "Ubuntu",
        "oneui" to "Android",
        "lineage" to "LineageOS",
        "lineageos" to "LineageOS",
    )

    /**
     * What the system running right now calls itself.
     *
     * One UI encodes its version as major*10000 + minor*100 + patch, so 80000
     * is 8.0.  LineageOS publishes its own property.  Anything else falls back
     * to the Android release number, which is always there.
     */
    fun runningSystemName(): String {
        fun prop(name: String): String =
            Root.run("getprop $name").output.trim().takeIf { it.isNotEmpty() } ?: ""

        prop("ro.lineage.display.version").takeIf { it.isNotEmpty() }?.let {
            return "LineageOS $it"
        }
        prop("ro.lineage.version").takeIf { it.isNotEmpty() }?.let {
            return "LineageOS $it"
        }

        val release = prop("ro.build.version.release").ifEmpty { "?" }
        val oneui = prop("ro.build.version.oneui").toIntOrNull()
        if (oneui != null && oneui > 0) {
            val major = oneui / 10000
            val minor = (oneui % 10000) / 100
            return if (minor == 0) "One UI $major" else "One UI $major.$minor"
        }
        return "Android $release"
    }

    /**
     * The Linux side's real name, read out of its own root filesystem.
     *
     * Each system keeps its own copy of the sets, and neither can write into
     * the other's: Android's /sdcard is encrypted and Ubuntu never sees it.
     * But root here can mount linuxroot read-only and simply ask, which beats
     * showing a name nobody chose.
     */
    fun linuxSystemName(): String {
        val mount = "/mnt/gts9u-linuxroot"
        val result = Root.run(
            "mkdir -p $mount",
            "mount -o ro -t ext4 /dev/block/by-name/linuxroot $mount 2>/dev/null || true",
            "grep -m1 '^PRETTY_NAME=' $mount/etc/os-release 2>/dev/null || true",
            "umount $mount 2>/dev/null || true",
            "rmdir $mount 2>/dev/null || true",
        )
        val line = result.output.lineSequence()
            .firstOrNull { it.startsWith("PRETTY_NAME=") } ?: return ""
        return line.removePrefix("PRETTY_NAME=").trim().trim('"')
    }

    /**
     * Writes the running system's real name into its own set.
     *
     * Each system can only name itself, so both labels become true once each
     * has booted at least once.  Until then the generic fallback is used, which
     * is vague but never wrong.
     */
    fun stampRunningName(set: BootSet) = writeName(set, runningSystemName())

    /** Records a set's name, leaving it alone when nothing has changed. */
    fun writeName(set: BootSet, name: String) {
        if (name.isBlank()) return
        val file = "${set.dir}/name.txt"
        val existing = Root.run("cat \"$file\" 2>/dev/null || true").output.trim()
        if (existing == name) return
        Root.run("printf '%s\\n' \"$name\" > \"$file\"")
    }

    // -- reading -------------------------------------------------------------

    /** sha256 of every boot partition as the tablet holds it right now. */
    fun liveHashes(): Map<String, String> {
        val result = Root.run(*PARTITIONS.map { "sha256sum ${it.device}" }.toTypedArray())
        if (!result.ok) return emptyMap()
        return parseSums(result.output, PARTITIONS.map { it.device })
    }

    /** Every directory under [ROOT_DIR], whether or not its images are usable. */
    fun discover(): List<BootSet> {
        val listing = Root.run("ls -1 $ROOT_DIR 2>/dev/null || true")
        val ids = listing.output.lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.contains('/') }
            .toList()

        return ids.sorted().map { id ->
            val label = KNOWN_LABELS[id.lowercase()] ?: id.replaceFirstChar { it.uppercase() }
            val hashes = hashesOf(id)
            BootSet(
                id = id,
                label = readLabel(id) ?: label,
                complete = hashes.size == PARTITIONS.size,
                hashes = hashes,
            )
        }
    }

    /** An optional `name.txt` lets a set say what it wants to be called. */
    private fun readLabel(id: String): String? {
        val r = Root.run("cat \"$ROOT_DIR/$id/name.txt\" 2>/dev/null || true")
        val line = r.output.lineSequence().firstOrNull()?.trim()
        return line?.takeIf { it.isNotEmpty() && it.length <= 40 }
    }

    /**
     * sha256 of a stored set, or an empty map when the set is incomplete.
     *
     * A missing or short file has to be caught here, before anything is
     * written: half a set on disk would otherwise become half a set on the
     * partitions, and the tablet would boot no system at all.
     */
    private fun hashesOf(id: String): Map<String, String> {
        val files = PARTITIONS.map { "$ROOT_DIR/$id/${it.name}.img" }
        val checks = PARTITIONS.map { part ->
            val f = "$ROOT_DIR/$id/${part.name}.img"
            "[ -f \"$f\" ] || exit 1\n" +
                "[ \"\$(stat -c %s \"$f\")\" = \"${part.bytes}\" ] || exit 1"
        }
        val result = Root.run(*(checks + files.map { "sha256sum \"$it\"" }).toTypedArray())
        if (!result.ok) return emptyMap()
        return parseSums(result.output, files)
    }

    /** Which stored set the four live partitions correspond to, if any. */
    fun identify(live: Map<String, String>, sets: List<BootSet>): BootSet? {
        if (live.size != PARTITIONS.size) return null
        return sets.firstOrNull { set ->
            set.complete && PARTITIONS.all { part ->
                val here = live[part.device]
                here != null && here == set.hashes[set.file(part)]
            }
        }
    }

    // -- storage -------------------------------------------------------------

    data class Share(val total: Long, val used: Long, val known: Boolean)

    /**
     * How the internal storage is split, mirrored from the Linux side.
     *
     * Android can measure its own userdata because it is mounted here; it
     * cannot see inside linuxroot's ext4, so only that partition's size is
     * honest and the UI says so rather than drawing a guess.
     */
    fun storage(): Map<String, Share> {
        val out = mutableMapOf<String, Share>()

        // Android's df is toybox: it has no -B, and reports 1K blocks.
        val df = Root.run("df -k /data | tail -1").output.trim().split(Regex("\\s+"))
        if (df.size >= 4) {
            val total = df[1].toLongOrNull()
            val used = df[2].toLongOrNull()
            if (total != null && used != null && total > 0) {
                out["android"] = Share(total * 1024, used * 1024, known = true)
            }
        }

        val sectors = Root.run("cat /sys/class/block/sda35/size 2>/dev/null || echo 0")
            .output.trim().toLongOrNull() ?: 0L
        // /sys counts 512-byte sectors whatever the disk's logical size is.
        if (sectors > 0) out["linux"] = Share(sectors * 512, 0, known = false)

        return out
    }

    // -- writing -------------------------------------------------------------

    sealed interface Progress {
        data class Step(val message: String) : Progress
        data class Failed(val message: String) : Progress
        data object Done : Progress
    }

    /**
     * Writes one set, verifying every partition by reading it back.
     *
     * Nothing reboots here.  A caller that has seen [Progress.Failed] must be
     * able to stop, because a tablet with three of four partitions replaced
     * still runs the system it is on — but only until it is restarted.
     */
    fun write(set: BootSet, log: (Progress) -> Unit): Boolean {
        if (!set.complete) {
            log(Progress.Failed("El juego de ${set.label} está incompleto o tiene tamaños raros."))
            return false
        }

        for (part in PARTITIONS) {
            val file = set.file(part)
            val expected = set.hashes[file]
            log(Progress.Step("Escribiendo ${part.name}…"))

            val write = Root.run("dd if=\"$file\" of=\"${part.device}\" bs=4M", "sync")
            if (!write.ok) {
                log(Progress.Failed("No pude escribir ${part.name}: ${write.output.take(200)}"))
                return false
            }

            val got = parseSums(Root.run("sha256sum ${part.device}").output, listOf(part.device))[part.device]
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
