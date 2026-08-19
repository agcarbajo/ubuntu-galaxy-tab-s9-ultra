package com.gts9u.bootswitcher

import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * A root shell.
 *
 * Commands are written to `su`'s stdin rather than passed as `su -c "..."`.
 * Quoting a command through an argument survives neither shell nesting nor a
 * path with a space in it, and this app's whole job is to run `dd` against
 * block devices: a mangled argument there is not a cosmetic bug.
 */
object Root {

    data class Result(val code: Int, val output: String) {
        val ok: Boolean get() = code == 0
    }

    /** Runs the given lines in one root shell and returns everything it printed. */
    fun run(vararg lines: String): Result = try {
        val process = ProcessBuilder("su")
            .redirectErrorStream(true)
            .start()

        process.outputStream.bufferedWriter().use { writer ->
            // Stop at the first failure instead of ploughing on: a `dd` that
            // follows a failed check must never run.
            writer.write("set -e\n")
            lines.forEach { writer.write(it + "\n") }
            writer.write("exit 0\n")
        }

        val output = BufferedReader(InputStreamReader(process.inputStream)).use { it.readText() }
        Result(process.waitFor(), output.trim())
    } catch (e: Exception) {
        Result(-1, e.message ?: "no se pudo abrir un shell de root")
    }

    /**
     * Whether root is actually usable, which is not the same as `su` existing:
     * Magisk answers the request with a denial when the app has been rejected
     * before, and a request that timed out is remembered as a denial.
     */
    fun available(): Boolean {
        if (granted) return true
        val ok = run("id -u").let { it.ok && it.output.trim() == "0" }
        // Only the yes is remembered.  A denial is the owner's to reverse, and
        // caching it would leave the app insisting it has no root long after it
        // was granted; a grant, once given, holds for the life of the process.
        if (ok) granted = true
        return ok
    }

    @Volatile
    private var granted = false
}
