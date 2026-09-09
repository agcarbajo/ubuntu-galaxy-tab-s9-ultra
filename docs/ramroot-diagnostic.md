# Kernel #10 RAM-root diagnostic

This is a device-specific engineering diagnostic, not a release ramdisk.
The ordinary suspend safeguard remains enabled. A successful short test
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
