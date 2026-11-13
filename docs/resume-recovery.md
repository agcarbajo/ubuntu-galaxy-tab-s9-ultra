# Resume failure and recovery, 2026-09-09

## The failure caught in the act, 2026-11-13

The tablet was in the fault while it was being used for this work, so for the
first time the resume itself is in the journal rather than missing from it.
Suspend was ordinary and clean. The whole fault is on the way back:

```
PM: suspend entry (deep)                                       20:00:11
Filesystems sync: 0.086 seconds
... 73 seconds asleep ...
qcom-qmp-ufs-phy 1d80000.phy: phy initialization timed-out
ufshcd-qcom 1d84000.ufshc: Failed to calibrate PHY: -110
ufshcd-qcom 1d84000.ufshc: Enabling the controller failed
ufshcd-qcom 1d84000.ufshc: ufshcd_host_reset_and_restore: Host init failed -5
ufs_device_wlun 0:0:0:49488: ufshcd_wl_resume failed: -5
ufs_device_wlun 0:0:0:49488: PM: dpm_run_callback(): scsi_bus_resume returns -5
sd 0:0:0:0: [sda] tag#26 UNKNOWN(0x2003) Result: hostbyte=0x07
I/O error, dev sda, sector 1054046096 op 0x0:(READ)
```

The timeout is in `qmp_ufs_phy_calibrate()`, polling `PCS_READY` after the
SerDes start. What follows is a consequence: every read and write to `/dev/sda`
fails, ext4 leaves the root mounted `rw,noatime,emergency_ro`, and the session
stays up without being able to save anything. The PCIe and Wi-Fi resumed
normally in the same cycle, so this is the UFS PHY alone.

Three things this rules out:

- **It is not a transient PLL lock.** `ufshcd` retried the host reset three
  times, each retry calling the power-up sequence three times, so the PHY
  regulators and clocks were cycled nine times inside that one resume and
  every calibration timed out. A retry loop would add nothing.
- **It is not the missing upstream fix.** The log is line for line the one in
  commit 7bac656 ("scsi: ufs: qcom: Power off the PHY if it was already
  powered on in ufs_qcom_power_up_sequence()"), which is in this kernel: the
  `if (phy->power_count) phy_power_off(phy);` it adds is in the tree. Its
  `phy_exit()` is not, because the later power-up refactor removed it along
  with the driver's `.exit` operation, so there is nothing to restore.
- **It is not a configuration this port chose.** `ufs-qcom` sets
  `spm_lvl = UFS_PM_LVL_5` for every `qcom,sm8550-ufshc`, because its drvdata
  declares `no_phy_retention = true`: device powered down and link off on
  every system suspend, which is what makes resume re-calibrate the PHY at
  all. Lowering `spm_lvl` to 3 would leave the link in hibern8, and on a board
  that cannot retain the PHY the hibern8 exit fails and lands in this same
  recovery path -- which is what the milos backport reports.

What is still open is why the calibration itself does not complete on this
board, intermittently. The two board patches already in the tree
(`qmp-ufs-assert-pcs-reset-before-calibration-gts9u.patch` and
`qmp-ufs-reset-serdes-before-power-down-gts9u.patch`) were candidates for
exactly this and are shipped in the default build although their own headers
say to keep them out until an offline-root resume test passes. Neither has
been validated, and the fault predates both.

Two things to try next, in this order, both of which an owner can run for days
because the fault is intermittent and no single boot proves anything:

1. **Light sleep instead of deep.** `echo s2idle | sudo tee /sys/power/mem_sleep`
   keeps the rails up and never tears the PHY down, at a real cost in standby
   battery. It is the only mitigation that needs no rebuild, and it is how to
   tell a PHY teardown fault from everything else: if the storage survives a
   week of s2idle and dies on the first deep sleep, the teardown is the cause.
2. **Slow the UFS down.** The sm8150 ports carry a one-line DTS patch that
   lowers `freq-table-hz` from 300 MHz to 201.5 MHz for the same class of UFS
   failures. This board's node specifies no `freq-table-hz` at all -- the
   kernel says `freq-table-hz property not specified` on every boot -- so
   there is a table to add rather than a value to change, and it needs a DTB
   rebuild and a flash.

Until one of them is accepted, the port does the one thing it can do without
a kernel change: say so. `ubuntu-gts9u-storage-health` runs on every resume,
recognises the `emergency_ro` state (the mount line still says `rw`, so a
plain read-only test misses it) and ext4's error counter, writes the reason to
`/run/gts9u-storage-failed` and raises a notification in the owner's session.
It reads only procfs and sysfs and writes only to tmpfs, because by then
nothing can be loaded from the disk.

The capture is `work/ufs-20261113/resume-failure.log`, kept outside the
repository with the other private evidence.


## Recurrence on Ubuntu 26.04 / Linux 7.2.9, 2026-10-19

The owner observed repeated `I/O error, dev sda` reads and journald
`Read-only file system` errors after opening the cover. The saved system
journal ends at entry to deep suspend; it does not contain the initial
controller/PHY resume failure. The precise failing sequence is still unknown.
The accepted kernel source already contains the board-specific PCS assertion
and TX pull-down patches described below; reapplying them is not a new fix.

With explicit owner approval, recovery ran in TWRP on the identified SM-X910.
The unmounted `linuxroot` partition first passed the five read-only fsck phases
apart from unreplayed journal state and optional extent optimizations. A
hash-verified backup of its first 4 MiB was retained privately; this is not a
whole-filesystem backup. Journal-only replay succeeded. A subsequent read-only
check found a free-block summary discrepancy of 589 blocks. After separate
authorization, preen corrected that summary. The final forced read-only check
returned zero, with no remaining count errors or recovery flag. Optional
extent optimizations were declined. No boot images were written and no root
slot or owner data was deleted. The owner subsequently confirmed Ubuntu boot
and desktop unlock. SSH returned with the expected host key; the selected
26.04 root was mounted `rw,noatime`, GDM was active, and a temporary file
write/fsync/readback under `/var/tmp` succeeded and was removed. This boot has
no matching kernel storage errors. Its running GNU build ID
`c70af389c9c7df41a8626562cc549295c359a7a4` matches the accepted build, as do
the installed Image.gz, configuration and DTB hashes. The current boot also
records an ordinary successful deep-sleep exit; this demonstrates the
intermittent nature of the problem, not a fix. A bounded 30-minute diagnostic
sleep inhibitor was used and explicitly stopped at the end of checks, without
changing permanent sleep policy.

Incident captures are private under `work/resume-20261019/`. Recovery's
`last_kmsg` belongs to Android and must not be cited as the failed Linux boot.
Do not repeat real-root suspend merely to reproduce this fault. A kernel fix
and repeat physical acceptance remain pending; neither filesystem repair nor
the earlier short sleep tests establishes reliable deep suspend.

The sections below record historical investigations and builds. In particular,
the former opt-in PCS policy was superseded: the current staging script enables
it by default following the later kernel validation.

Automatic brightness was validated by changing the room lighting, and the
owner confirmed that it still worked after a power-button suspend. That
cycle nevertheless exposed an intermittent **storage resume failure**.
Deep suspend must not be described as reliable on this build.

## Captured failure

The running kernel was `7.2.0-rc3-dirty`, build 8. Kernel timestamps:

| Seconds since boot, excluding sleep | Event |
| --- | --- |
| 968.994 | Deep suspend starts; filesystem sync succeeds |
| 970.367 | ath12k reports Wi-Fi firmware initialization |
| 970.371 | QMP UFS PHY initialization times out; calibration returns -110 |
| 971.328 | UFS resume fails with -5 |
| 972.446 | System resume completes despite the device failure |
| 973.735 | ext4 aborts the journal and enters emergency read-only mode |
| 1072.956 | Wi-Fi reassociates |

SSH returned, but root was `rw,noatime,emergency_ro`; uncached reads and
writes failed. The root filesystem is internal UFS `/dev/sda35`, partition
label `linuxroot`, ext4 label `UBTS9U_UFS`, not the microSD. Memory pressure
was not the cause. The owner also reports occasional black-screen resumes
after idle or lid closure while charger sounds still work. That symptom
has not yet been proven to share the same cause.

## Offline repair and local safeguard

With the owner's help, the tablet entered TWRP. The Ubuntu partition was
verified unmounted before checking it. A read-only e2fsck found pending
journal recovery. The first 2 MiB were backed up locally before writing.
Journal-only preen recovered the journal and cleared already-unlinked
orphan inodes; full preen corrected free-space counters. A final read-only
five-pass check reported no remaining consistency errors. No Android
userdata or partition-table changes were made.

The original Ubuntu boot set remains installed, including boot SHA-256
`a48a7d1b81e27641683fc930b5f9c712990e3748121b09b1cc82bd33e5d9ac8f`.
After reboot, root was writable, a 4 MiB fsync/readback check passed,
Wi-Fi connected, HTTPS returned 204 with successful TLS verification,
and libssc again delivered light samples. Sensor packages remain
`libssc 0.4.4-gts9u3` and `iio-sensor-proxy 3.9-gts9u3`.

The test tablet has a **temporary local** file
`/etc/systemd/sleep.conf.d/90-gts9u-ufs-recovery.conf` setting all four
`AllowSuspend`, `AllowHibernation`, `AllowSuspendThenHibernate`, and
`AllowHybridSleep` options to `no`. Logind reports `CanSuspend=no`.
This prevents ordinary idle/lid/power-button suspend from reproducing the
failure unattended, but increases standby power consumption and disables
the short power-button suspend action. It is a safeguard, not a UFS fix,
and is not silently included in future images. Keep it until controlled
resume validation is possible; remove that one file when deliberately
resuming those tests. Direct kernel PM test writes bypass this policy.

## Separate cold-boot panel failure

On the first boot after repair, GDM was running but the panel ID remained
`00 00 00`. The existing platform-test recovery helper had exited with EIO:
the userspace freezer was aborted after 2.1 seconds, before device suspend.
Repeating the helper succeeded and restored panel ID `80 00 04`, without
UFS errors. This is different from the storage failure above.

The helper now retries at most three times **only when the kernel's
`failed_freeze` counter increases**. It restores `pm_test=none` between
failed attempts and on exit, waits two seconds between attempts, and does
not retry a device suspend/resume failure. The service timeout is 90 seconds.
Four shell-harness tests cover success, transient freezer abort, retry
exhaustion, and refusal to retry a device failure. Both changed files are
in the device package source and installed on the tablet.

The final reboot completed the platform cycle on its first attempt, recovered
panel ID `80 00 04`, and reached an active GDM Wayland greeter. Mutter reported
`PowerSaveMode=0`, panel brightness was 628/2047, root was `rw,noatime`,
SensorProxy advertised ambient light, HTTPS returned 204, and systemd had
no failed services. The retry branch is covered by the harness; it did not
need to run on that final boot. This confirms the handoff state, not a fix
for intermittent deep-resume failures.

## UFS investigation still pending

The Samsung Kalama driver explicitly asserts PCS `SW_RESET` before writing
PHY calibration tables and clears it afterwards. The running mainline
driver only clears PCS reset during calibration. On PHYs with PCS reset,
its separate external reset handle is not acquired. This is a concrete
sequence difference worth testing, **not a validated fix**. Do not deploy
an experimental kernel or repeat deep suspend with writable UFS merely
because the platform PM test passes.

The upstream SM8550 policy already selects UFS power level 5 because PHY
retention is unsupported. Simply selecting a lower UFS power level is
not an established workaround; the clock-off path also powers down the
PHY. See the [upstream suspend-fix series](https://patches.linaro.org/project/linux-scsi/cover/20241219-ufs-qcom-suspend-fix-v3-0-63c4b95a70b9%40linaro.org/).

Private diagnostic captures, offline fsck transcripts, the original boot
backup, and copies of both PHY implementations are under the ignored
`work/als-oneui-20260909/` directory. No SSH password belongs in this document
or any published artifact. Release 1.2.0 preparation has not been started
as part of this recovery.

## PCS reset candidate, 2026-09-09 (not deployed)

The pinned upstream source confirms that `qmp_ufs_phy_init()` does not acquire
the external reset on PHYs with PCS reset. Calibration therefore clears PCS
reset without explicitly asserting it first. The published
[Kalama implementation](https://github.com/LineageOS/android_kernel_oneplus_sm8650/blob/638ecc42531912963b2a0d9eddf6b1ae3be9bb37/drivers/phy/qualcomm/phy-qcom-ufs-qmp-v4-kalama.c)
asserts PCS reset before its tables. Upstream commit
[`a079b2d71534`](https://github.com/torvalds/linux/commit/a079b2d715340482e425ff136b55810ab8279800)
deliberately removed reset and SerDes stop from **power-off** according to the
hardware programming guide; this candidate does not restore that sequence.

`kernel/patches/qmp-ufs-assert-pcs-reset-before-calibration-gts9u.patch` instead
asserts PCS reset immediately before calibration tables, only for the SM8550
PHY on `samsung,gts9uwifi`. The existing readback in `qphy_setbits()` completes
that write before table programming. No PHY tables, polling timeouts, UFS
power levels, device tree, wake sources or other drivers are changed.
The missing assertion is a hypothesis, **not proof of the failure's cause**.

The build recipe enables this only with `UFS_PCS_RESET_EXPERIMENTAL=1`.
Default builds do not gain an unvalidated storage change. Reusing a tree
containing the candidate without opting in fails instead of silently keeping
it. For an already prepared kernel tree, stage it with:

```sh
UFS_PCS_RESET_EXPERIMENTAL=1 bash scripts/stage-ufs-resume-experiment.sh /path/to/kernel-tree
```

`scripts/test-ufs-resume-experiment.py PRISTINE_QMP_UFS_C` applies both patches
with zero fuzz, checks default/no-op and repeated staging, rejects a stale
experimental tree, and compiles the actual calibration function with mocked
MMIO. It checks reset-before-tables ordering, platform isolation, repeated
calibration and error propagation. These tests passed against the pinned
`a13c140cc289c0b7b3770bce5b3ad42ab35074aa` source; they cannot validate physical
power sequencing or resume. The baseline RX-state patch also needed a trailing
context repair for strict application; its build marker now uses the helper
name rather than a comment changed in the previous commit.

The next physical test must have a recovery path and keep internal UFS
filesystems unmounted (for example a diagnostic RAM-root boot). Do not format
the owner's currently inserted WINPE microSD or use it as a disposable root.
Before enabling normal suspend, validate repeated real deep cycles and UFS
reads, then normal-root filesystem writes and existing hardware functions
under supervision. A platform PM test alone is insufficient. The local sleep
safeguard remains in place and no reboot is implied by staging or building.

### Build-only result on PC-ARTURO

The existing runtime9 source snapshot (`5e34b887d`, with the validated #8
performance and fingerprint edits) was built incrementally with only the
additional PCS reset candidate. Backup and candidate artifacts are under
`/root/ubuntu-gts9u/build/ufs-resume-20260909.9EDJeS/` on PC-ARTURO:

- `validated-kernel8/` preserves the original Image, vmlinux, System.map,
  configuration, Module.symvers, PHY source/object and version metadata.
- `candidate-kernel9/Image` SHA-256:
  `0bbfe08b67d976044f37ebaaf095665e369da913f3b5f0d8ac37fee85c083a23`.
- Build identity: `#9 SMP PREEMPT Wed Sep 9 10:46:40 CEST 2026`, release
  `7.2.0-rc3-dirty`. LLVM 22.1.8, `ARCH=arm64 LLVM=1 LOCALVERSION=-dirty
  KBUILD_BUILD_VERSION=9 KBUILD_BUILD_TIMESTAMP='Wed Sep 9 10:46:40 CEST 2026'`,
  target `Image`, eight jobs, existing source and object directories.
- Configuration SHA-256 remains
  `474a26a731694fb6838f463e21a057ff3e272fe27fc42b3d6b9d3b628070fcb3`;
  signing key, certificate and Module.symvers hashes also remained unchanged.
  No modules were replaced or signing keys regenerated.
- The first compile omitted `LOCALVERSION=-dirty`, producing an incompatible
  `7.2.0-rc3+` release. That output is isolated in
  `rejected-release-mismatch/` and **must not be installed**. The second,
  matched compile above is the candidate. Both logs are retained locally.

The build tree now contains the experimental PHY source and #9 objects;
it is no longer an untouched #8 build directory. No boot image was packed,
flashed or installed, and the tablet still runs #8 with suspend disabled.
Physical validation and a RAM-root diagnostic boot are still pending.

### Subsequent GPU/UFS combined candidate

The later desktop freeze exposed a GPU recovery deadlock with root still
writable. Kernel #10 now combines the #9 UFS candidate with a bounded GMU
fault-capture wait; it has now passed three RAM-root deep/RTC cycles and is installed for
normal desktop validation. See [RAM-root results](ramroot-diagnostic.md);
long-duration and lid/idle acceptance remain pending. See
[GPU recovery](gpu-recovery.md) for the traces, tests, hashes, preserved #9
backup and remaining requirements for a combined physical test session.
