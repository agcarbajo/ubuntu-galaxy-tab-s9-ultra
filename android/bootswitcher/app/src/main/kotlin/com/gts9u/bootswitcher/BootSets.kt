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
        /** Where its images actually live; may be on the read-only Linux mount. */
        val dir: String,
    ) {
        fun file(part: Partition): String = "$dir/${part.name}.img"
    }

    /**
     * The two places a set can live.
     *
     * The installer seeds the sets inside Ubuntu's own root filesystem, and
     * that partition is plain ext4 that root can mount from here — the app
     * already does it to read Ubuntu's name.  So there is nothing to copy:
     * Android reads the same images Ubuntu uses.
     *
     * `/sdcard/BootSets` stays as the place to override or add one by hand.
     * Android cannot be given files there from recovery anyway, because that
     * partition is metadata-encrypted and TWRP only sees noise.
     */
    const val ROOT_DIR = "/sdcard/BootSets"
    const val LINUX_MOUNT = "/mnt/gts9u-linuxroot"
    const val LINUX_SETS = "$LINUX_MOUNT/var/lib/gts9u-boot-sets"

    /**
     * Mounts Ubuntu's root read-only, if it is not mounted already.
     *
     * Read-only throughout: this is the other system's filesystem and nothing
     * here has any business writing to it.  A plain `ro` mount still replays
     * the journal, which fails on a filesystem left dirty by a hard power-off,
     * so `noload` is the fallback — it skips recovery and reads what is there.
     */
    fun mountLinuxRoot(): Boolean {
        val result = Root.run(
            "mkdir -p $LINUX_MOUNT",
            "if grep -q ' $LINUX_MOUNT ' /proc/mounts; then exit 0; fi",
            "mount -o ro -t ext4 /dev/block/by-name/linuxroot $LINUX_MOUNT 2>/dev/null || " +
                "mount -o ro,noload -t ext4 /dev/block/by-name/linuxroot $LINUX_MOUNT",
        )
        return result.ok
    }

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

    /**
     * Records a set's name, leaving it alone when nothing has changed.
     *
     * Sets that live on Ubuntu's root are mounted read-only, so this quietly
     * does nothing for them — and it should: the installer already wrote their
     * name from the system that owns it, and this app has no business writing
     * into the other system's filesystem.
     */
    fun writeName(set: BootSet, name: String) {
        if (name.isBlank()) return
        if (set.dir.startsWith(LINUX_MOUNT)) return
        val file = "${set.dir}/name.txt"
        val existing = Root.run("cat \"$file\" 2>/dev/null || true").output.trim()
        if (existing == name) return
        Root.run("printf '%s\\n' \"$name\" > \"$file\"")
    }

    // -- reading -------------------------------------------------------------

    /**
     * Whether a set is the Linux side.
     *
     * Only used to pick an icon and to know who to ask for a name: this app
     * cannot run on that system, so it is never the one running.
     */
    fun isLinux(set: BootSet): Boolean {
        val id = set.id.lowercase()
        return id.contains("ubuntu") || id.contains("linux") || id.contains("debian")
    }

    /** sha256 of every boot partition as the tablet holds it right now. */
    fun liveHashes(): Map<String, String> {
        val result = Root.run(*PARTITIONS.map { "sha256sum ${it.device}" }.toTypedArray())
        if (!result.ok) return emptyMap()
        return parseSums(result.output, PARTITIONS.map { it.device })
    }

    /**
     * Every set the tablet can see, from either place.
     *
     * Ubuntu's copy is read first and Android's own second, so a directory
     * placed by hand in `/sdcard/BootSets` wins over the seeded one: that is
     * the only copy the owner can actually edit from here.
     */
    fun discover(): List<BootSet> {
        mountLinuxRoot()

        val where = LinkedHashMap<String, String>()
        for (base in listOf(LINUX_SETS, ROOT_DIR)) {
            Root.run("ls -1 $base 2>/dev/null || true").output.lineSequence()
                .map { it.trim() }
                .filter { it.isNotEmpty() && !it.contains('/') }
                .forEach { where[it] = base }
        }

        return where.keys.sorted().map { id ->
            val dir = "${where[id]}/$id"
            val fallback = KNOWN_LABELS[id.lowercase()] ?: id.replaceFirstChar { it.uppercase() }
            val hashes = hashesOf(dir)
            BootSet(
                id = id,
                label = readLabel(dir) ?: fallback,
                complete = hashes.size == PARTITIONS.size,
                hashes = hashes,
                dir = dir,
            )
        }
    }

    /** An optional `name.txt` lets a set say what it wants to be called. */
    private fun readLabel(dir: String): String? {
        val r = Root.run("cat \"$dir/name.txt\" 2>/dev/null || true")
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
    private fun hashesOf(dir: String): Map<String, String> {
        val files = PARTITIONS.map { "$dir/${it.name}.img" }
        val checks = PARTITIONS.map { part ->
            val f = "$dir/${part.name}.img"
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

    /**
     * Progress is reported as partitions, not as sentences.
     *
     * The set of partitions is fixed and known before anything starts, so the
     * UI can draw all four up front and light them up one by one instead of
     * growing a list of lines.  Messages carry string resource ids because
     * this object has no Context and the app is translated.
     */
    sealed interface Progress {
        data class Writing(val part: String) : Progress
        data class Verified(val part: String) : Progress
        data class Failed(val text: Int, val arg: String = "", val detail: String = "") : Progress
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
            log(Progress.Failed(R.string.progress_incomplete, set.label))
            return false
        }

        for (part in PARTITIONS) {
            val file = set.file(part)
            val expected = set.hashes[file]
            log(Progress.Writing(part.name))

            val write = Root.run("dd if=\"$file\" of=\"${part.device}\" bs=4M", "sync")
            if (!write.ok) {
                log(Progress.Failed(R.string.progress_write_failed, part.name, write.output.take(200)))
                return false
            }

            val got = parseSums(Root.run("sha256sum ${part.device}").output, listOf(part.device))[part.device]
            if (got == null || got != expected) {
                log(Progress.Failed(R.string.progress_mismatch, part.name))
                return false
            }
            log(Progress.Verified(part.name))
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
