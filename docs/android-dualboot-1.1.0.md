# Android Dualboot 1.1.0

The Android application now identifies the running Android independently of
partition hashes and saved labels. Hashes describe the next boot only. Ubuntu's
status helper no longer stamps its own name on a staged Android set.

Automatic checks run after Android boot (after unlock), package replacement,
app resume, and before partition switching. JobScheduler performs the boot check
without a foreground notification; results are retained in the app console.
There is no periodic polling. Root access must remain granted.

For the installed layout, the shared Android set lives at
`/var/lib/gts9u-boot-sets/android` on linuxroot. When hashes change, the app checks
that no partition exclusively matches a saved Linux image, unpacks the live boot
image using Magisk's magiskboot, and requires the embedded Linux version to match
the running Android kernel. It checks partition sizes, copies all four images,
verifies SHA-256, and rereads the live hashes before committing the complete set.
A directory replacement keeps the previous set in
`/var/lib/gts9u-boot-backups/android.previous`. Interrupted directory commits are
recovered on the next check. Linuxroot is returned to read-only on success or
failure; noload mounts are rejected for writes. No boot partition is written by
the automatic backup operation. vbmeta, super, and userdata are excluded.

Multiple Android sets, manual sdcard overrides, mixed partitions, and an unknown
kernel are not silently adopted. Details remain in the console. This deliberately
avoids turning a staged Linux kernel into the Android backup. A failed refresh
blocks a subsequent partition write. Manual overrides that already match the
live Android partitions remain usable.

## Validation on 2026-09-09

- APK versionCode 110 / versionName 1.1.0 built and installed with adb, preserving
  app data and the existing signing identity.
- Six Kotlin unit tests cover incorrect labels, unchanged images, staged Linux,
  every partial-switch combination, changed Android, and ambiguous/read failures.
- Seven Python/shell tests exercise the shipped transaction using files: complete
  update, hash rejection, foreign kernel rejection, failed commit rollback,
  label-only update, interrupted commit recovery, and Linux label protection.
- Device UI reports One UI 8; shared Android name repaired from Ubuntu to One UI 8.
- A saved Android boot image was temporarily moved aside (live partitions were
  never altered). The app rebuilt and verified all four backup images. The moved
  image was then returned to the previous set, leaving both sets complete.
- Live Android, refreshed Android, and previous Android hashes match. Saved Ubuntu
  hashes remained unchanged. linuxroot was read-only after the operation.
- Linux boot_core.py was patched offline on the tablet as well as in packaging,
  with its original retained in the backup directory.

No actual OTA or OS reboot was needed for this validation. The kernel identity
check was exercised against the tablet's running One UI kernel.

Build with JDK 17+ and Gradle 8.10.2:

```sh
gradle -p android/bootswitcher assembleDebug testDebugUnitTest
python3 scripts/test-android-backup.py # Linux/WSL, file fixtures only
```
