package com.gts9u.bootswitcher

import org.junit.Assert.*
import org.junit.Test

class BootSafetyTest {
    private fun set(id: String, value: String) = BootSets.BootSet(id, "Ubuntu 24.04.5 LTS",
        true, BootSets.PARTITIONS.associate { "/sets/$id/${it.name}.img" to value }, "/sets/$id")
    private val android = set("android", "a".repeat(64))
    private val linux = set("ubuntu", "b".repeat(64))
    private val sets = listOf(android, linux)
    private fun live(set: BootSets.BootSet) = BootSets.PARTITIONS.associate {
        it.device to set.hashes.getValue(set.file(it))
    }

    @Test fun wrongLabelsNeverMakeAndroidRunUbuntu() {
        assertEquals("android", BootSets.runningAndroid(sets, "One UI 8")?.id)
        assertEquals("One UI 8", BootSets.runningAndroid(sets, "One UI 8")?.label)
    }
    @Test fun unchangedBackupNeedsNoCopy() {
        assertEquals(BootSets.BackupDecision.UNCHANGED, BootSets.backupDecision(sets, live(android)))
    }
    @Test fun stagedUbuntuMustNeverBecomeAndroidBackup() {
        assertEquals(BootSets.BackupDecision.LINUX_STAGED, BootSets.backupDecision(sets, live(linux)))
        assertEquals("android", BootSets.runningAndroid(sets, "One UI 8")?.id)
    }
    @Test fun interruptedSwitchIsRejectedForEveryPartition() {
        for (part in BootSets.PARTITIONS) {
            val mixed = live(android) + (part.device to linux.hashes.getValue(linux.file(part)))
            assertEquals(BootSets.BackupDecision.MIXED, BootSets.backupDecision(sets, mixed))
        }
    }
    @Test fun changedAndroidRequiresVerifiedCapture() {
        val updated = live(android) + (BootSets.PARTITIONS.first().device to "c".repeat(64))
        assertEquals(BootSets.BackupDecision.CHANGED, BootSets.backupDecision(sets, updated))
    }
    @Test fun incompleteReadAndMultipleAndroidSetsAreRejected() {
        assertEquals(BootSets.BackupDecision.AMBIGUOUS, BootSets.backupDecision(sets, emptyMap()))
        assertEquals(BootSets.BackupDecision.AMBIGUOUS,
            BootSets.backupDecision(sets + set("lineage", "c".repeat(64)), live(android)))
    }
}
