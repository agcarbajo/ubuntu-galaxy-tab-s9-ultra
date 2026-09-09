# Kernel #10 RAM-root diagnostic

This is a device-specific engineering diagnostic, not a release ramdisk.
The ordinary suspend safeguard was retained during the initial tests. See
the installed-state section below for its later removal. A successful short test
would not establish long-duration reliability or GPU fault recovery.

On 2026-09-09, the combined kernel #10 and a diagnostic init_boot were
written and read-back verified on the test SM-X910. Reboot was requested.
The user observed a boot loop and entered TWRP. Both diagnostic partition
hashes were still present and the on-root status remained `ARMED`: automatic
fallback restoration had not completed, and no suspend cycle is validated.
TWRP pstore was empty. Its last_kmsg contained old Android and bootloader
records, without a diagnostic Linux panic explaining this failure.

The original kernel #8 and init_boot were restored from independently hashed
PC backups and read-back verified in TWRP. Normal reboot was requested.
Do not reuse this diagnostic image until the early boot failure is isolated.

The diagnostic replaces the original initramfs-tools init-premount call
with `exec /gts9u-ramroot-test`, before mounting the normal root. It copies
verified kernel #8 and original init_boot backups into RAM from a read-only,
no-journal-replay mount of Ubuntu, unmounts it, then restores both boot
partitions and verifies their hashes **before attempting suspend**. If a
hang occurs after that point, a forced reset can return to normal kernel #8.
A preflight failure before restoration stops for recovery instead of looping.

All block-backed filesystems must be unmounted during the tests. Ubuntu's
partition is additionally marked read-only. Three real deep/RTC cycles
(15, 30, 60 seconds) check elapsed RTC time, suspend failure counters,
uncached storage reads against an 8 MiB reference, and kernel storage errors.
Only after all checks pass is Ubuntu mounted writable to save `RAMROOT_PASS`,
results and dmesg. The diagnostic then unmounts it and returns to kernel #8
for inspection. Error paths do not remount Ubuntu to save logs.

Backups and status on the tablet:
`/var/lib/gts9u-diagnostics/kernel10-ramroot/` (root-only).
The ordinary saved Ubuntu boot set is unchanged during the diagnostic.
No Android userdata, vendor_boot, DTBO or microSD partition is written.

## Inputs and implementation

- `scripts/diagnostics/kernel10-ramroot-test`: actual early-init diagnostic.
- `scripts/diagnostics/prepare-kernel10-ramroot.py`: packs and verifies the
  original init_boot header and unsigned AVB footer; it never flashes.
- Diagnostic init_boot SHA-256:
  `3c019939c5af32efb4377ce03a539d422cdf754bf8141b892624b8da82bc21dd`.
- Original init_boot SHA-256:
  `7881d5859f223a2bfdcc6be0fe12edf561b71c02d7c6ab854ab7e14dcf0e1705`.
- Added signed `rtc-pm8xxx.ko` SHA-256:
  `689a0f356c4fd8d74e1fcaa080323b692f6b9abeb8b705394be2d7162d390094`.

The RTC module was built with the existing matching configuration and signing
key, and loaded successfully on live #8. An alarm armed for five seconds
expired while awake. This does not prove suspend wake-up. The RTC has a
hardware epoch offset; its clock was not rewritten.

The diagnostic cpio was derived from the verified original init_boot ramdisk,
with native ARM64 sha256sum, dd and timeout added alongside the RTC module.
Required shared libraries were retained from the original archive. The
sha256 and dd binaries were exercised with qemu-aarch64-static. The original
vendor_boot was retained. Local construction tree:
`/root/ubuntu-gts9u/build/kernel10-ramroot/init` in WSL Ubuntu.

## Host verification

The lifecycle harness executes the diagnostic shell with mocked device,
mount and power operations against temporary regular files. It checks the
success path and two failure paths (early wake and UFS error), verifies
restoration of both original boot images, and verifies that failures never
remount root writable. All three cases passed. These are simulated tests.

Run on Linux with the audited local images:

```sh
python3 scripts/diagnostics/test-ramroot-lifecycle.py \
  --kernel8 /path/to/kernel8.img \
  --init-boot /path/to/original-init_boot.img \
  --kernel10 /path/to/boot-gpu-ufs-kernel10-experimental.img \
  --diagnostic-init /path/to/init_boot-kernel10-ramroot-test.img
```

### Recovery after the failed diagnostic session

TWRP read-back verified all four original boot partitions (#8 boot,
init_boot, vendor_boot and DTBO). Offline e2fsck replayed the pending journal;
a subsequent read-only check reported the Ubuntu filesystem clean.

The recovered persistent journal identifies the last normal boot as kernel
#8. It ends during the panel recovery helper's second platform PM attempt.
The pogo firmware service was concurrently programming the STM32 controller
and had not finished. Thus this black-screen incident must not be reported
as a kernel #10 suspend test or evidence that the diagnostic ran.

Temporarily masking panel recovery restored SSH on #8. Stopping GDM and
running the platform test after startup completed succeeded: panel ID changed
from `00 00 00` to `80 00 04`, GDM restarted, Wi-Fi and HTTPS returned, and
root remained writable. This isolates the boot-time concurrency as a suspect,
without proving that it explains all earlier GPU/UFS failures.

The panel unit now explicitly pulls in and orders itself after
`ubuntu-gts9u-pogo-firmware.service`, so it cannot freeze userspace or suspend
the controller during that service's firmware write. systemd-analyze verify
accepted the installed unit and its dependency graph. The ordinary deep-sleep
safeguard remains enabled; kernel #10 acceptance is still pending.

The subsequent normal reboot passed on kernel #8: the pogo unit finished
first (V37 already present), then panel recovery returned on its first
attempt and reported ID `80 00 04`. GDM's greeter session, NetworkManager and
iio-sensor-proxy were active; HTTPS returned 204 with successful TLS checking,
root was writable, and no failed units or matching UFS/ext4/GPU fault messages
were found. This verifies ordinary boot ordering and recovery with existing
firmware; a fresh firmware-write boot has not yet been repeated.

### Kernel #10 normal boot and diagnostic preflight

With the verified original init_boot and corrected panel service ordering,
kernel #10 booted normally. The panel platform cycle passed on the first
attempt, GDM, networking and the light sensor were available, root remained
writable, and HTTPS returned 204 with valid TLS. This validates ordinary boot,
not deep suspend or GPU fault recovery.

The diagnostic packer now requires legacy LZ4, matching the original
ramdisk format, and rejects the gzip format that failed the earlier boot. A preflight-only variant using LZ4 booted kernel #10,
restored both original boot partitions, wrote `PREFLIGHT_PASS`, and returned
to kernel #8. Read-back hashes and the preflight result were verified over
SSH. That variant exits before loading the RTC module or suspending.

- Preflight LZ4 init_boot SHA-256:
  `bd2396acca6b1d1a496a2e00d7ea35c90e37108828cef392769797a7e15a7d94`.
- Full diagnostic LZ4 init_boot SHA-256:
  `b0d50911ab75dc0a896e626d4abb588501c05410cedd392148eee578b02a09e8`.

The full LZ4 diagnostic passed all three real deep-suspend cycles with no
block-backed filesystems mounted. RTC elapsed times were 18, 32 and 62 seconds
for requested sleeps of 15, 30 and 60 seconds. Suspend failure counters did
not increase. Each uncached 8 MiB read matched SHA-256
`7b33169e965b2f9ef76b55bf8cfffaac3f8f0db5acd770854cf564e8134cd4e2`.
`RAMROOT_PASS`, the results and dmesg were retrieved after automatic return
to kernel #8. The normal kernel #10 was then installed again.

A normal-root 20-second systemd suspend cycle returned after 22 RTC seconds.
Root remained writable; a 4 MiB probe retained its hash, and post-resume writes
with fsync succeeded. GDM, NetworkManager and the light sensor stayed available.
Wi-Fi re-associated after approximately ten seconds; an initial DNS lookup
failed during reconnection, then retry and a separate HTTPS check succeeded.
No matching UFS/ext4/GPU errors were detected. Longer normal-root cycles and
user-triggered lid/button/idle coverage remain to be checked.

The harness must wait for `systemctl start suspend.target`, rather than just
queueing `systemctl suspend`, before removing its temporary sleep override.
Two initial harness attempts did not perform a validated sleep because the
ordinary suspend safeguard was still effective. They are excluded from the
successful-cycle counts.

### Normal-root validation and installed state

Three validated normal-root systemd suspend cycles (20, 60, 120 seconds)
returned after 22, 62 and 122 RTC seconds. Each passed the read/hash and
post-resume write/fsync checks, recovered GDM and the light-sensor service,
and recovered HTTPS after Wi-Fi re-association. The initial DNS request was
early enough to catch the roughly ten-second reconnect window; retries
succeeded. No matching UFS/ext4/GPU fault errors were found.

The live boot partition and saved Ubuntu dualboot `boot.img` now contain
kernel #10 (`b193714f...b8a9cc`). The original init_boot, vendor_boot and DTBO
remain unchanged. Kernel #8 and the former sleep safeguard are preserved in
the root-only diagnostic directory. The temporary local sleep-disable file
was removed after these checks; login1 now reports `CanSuspend=yes`.

This is an installed experimental kernel, not a new release or evidence of
long-term reliability. Physical lid/button and extended idle coverage, plus
actual GPU fault recovery, remain separate acceptance work. Build experiment
flags remain opt-in.

## Keyboard-folio opening wake-up (kernel #11)

The user confirmed that lid-close suspend and automatic brightness survived
kernel #10, but opening the folio did not wake it. The journal showed the
power-key press and the delayed lid-open report at the same resume. GPIO107's
Book Cover IRQ had no events: that route serves a different cover. This
keyboard folio sends its lid notifications through the Wacom controller on
I2C 12-0056, whose GPIO154 has SM8550 PDC wake mapping 53.

The Wacom driver reported SW_LID but did not register a wake IRQ. A temporary,
signed test module enabled IRQ wake on the live Wacom data interrupt, guarded
by board compatibility and hardware IRQ154. The user then confirmed that
opening the cover woke the tablet without pressing the power button. The
journal recorded lid-close at 19:18:49, suspend at 19:18:50 and lid-open/resume
at 19:19:17, without a power-key event.

The permanent driver change initializes device wake-up and associates its
data IRQ with `dev_pm_set_wake_irq()`. A managed cleanup action clears the
association and wake-up state. This uses the PM core to arm the interrupt
during suspend and exposes the normal device power/wakeup policy.

Kernel #11 adds only this Wacom change to #10. The build preserved configuration,
Module.symvers and signing-key hashes. Build artifacts and #10 backup are in
`/root/ubuntu-gts9u/build/wacom-wake-kernel11.KailU5/`. The packer
`scripts/prepare-lid-wake-kernel11-boot.py` preserves the #10 DTB and header,
checks input hashes and verifies the AVB hash footer.

- Image SHA-256: `81c703681cb871449dc3349e5a8f01d4657d2851fd62676f608b8033fa19e063`.
- boot SHA-256: `2be3ad53a009465458153eaa76e6d89d0466e6127adf5d70b047099490fc0f44`.

The candidate was written and verified, and booted successfully as #11.
Wacom power/wakeup reports enabled without the test module; GDM, networking
and light-sensor services are active and root is writable. Post-reboot
physical lid-opening acceptance passed: the user confirmed automatic wake
without the power button, and the journal records suspend at 19:23:58 and
lid-open/resume at 19:24:16. Root stayed writable, HTTPS returned 204 with
valid TLS, and no systemd units were failed. The saved Ubuntu dualboot boot
image was updated to the verified #11 image after this check.
The test module is not installed for automatic loading and does not persist
across reboot. The #10 boot backup is retained on the tablet under
`/var/lib/gts9u-diagnostics/kernel11-lid/kernel10.img`.
