# Office-use efficiency, 2026-09-09

The tablet was running Chrome and ChatGPT with hardware ANGLE/Vulkan. This
investigation preserves GPU acceleration, CPU/GPU frequency policies, display
refresh, sensor timing, automatic brightness smoothing and suspend behavior.
The tablet was charging, so charge current is not a system-power measurement.
No battery-runtime gain is inferred from these short CPU samples.

## Baseline

A 25-second process CPU-time sample found the ChatGPT GPU process using 0.56%
of one core. GPU frequency was 220 MHz; UFS was at 75 MHz. CPU policies remained
schedutil, with normal minimum frequencies. Memory and I/O pressure were zero,
8.4 GiB RAM was available and swap was unused. There was no evidence supporting
higher minimum clocks, swap changes or reduced browser acceleration.

The notable background costs were D-Bus (3.52% of one core), logind (2.28%),
Tab Companion hardware (2.56%), S Pen pairing (1.56%) and fingerprint availability
(1.08%). Browser/render workload varied with the owner's use; these are short
observations rather than controlled whole-system performance comparisons.

## Redundant operations

An eight-second system-bus profile counted 348 method calls, including 58
SetBrightness calls. A separate ten-second brightness-only trace found 68
calls requesting exactly the same panel value, 588. The upstream GNOME ambient
callback always submits the rounded target after updating its moving average,
even if that brightness is already applied.

The GNOME patch retains every moving-average update and skips only an automatic
write whose percentage already matches the observed backlight value. It does
not cache the last requested target or alter smoothing coefficients. A changed
observed brightness can still be corrected. The compiled callback regression
test fails on the original source and passes on the patch: 100 repeated targets
produce no writes, time/averaging continue advancing, changed targets are
applied, and an externally changed backlight is still handled.

Tab Companion now shares one BlueZ object snapshot between its two checks
within a sample. Event-triggered refresh still queries fresh state. Pairing
sets Trusted only when it is not already true. Polling intervals and pen
connection/recovery behavior are retained.

The fingerprint availability broker uses its known D-Bus interface directly,
avoiding two introspection round trips per Pulse. Every Pulse still verifies
the sender UID and reads live session authorization properties. All 17 broker
authorization/lifecycle tests pass on Linux. Running those tests on Windows is
unsupported because their lease-file checks require os.fchmod.

After the helper-only changes, a second 25-second sample measured the broker
at 0.56% of one core. The subsequent eight-second bus trace contained no seat
or session introspection calls (previously 32), while live Get/GetAll and Pulse
calls remained. Total method calls were 272; brightness redundancy was still
present pending the separate GNOME deployment. Other process deltas are too
small or workload-dependent to claim a general speed-up.

## Build integration

Tab Companion 1.3.11 and device 2.52 carry the helper changes. The new
build-gnome-power-package.sh rebuilds the exact Ubuntu Noble source
46.0-1ubuntu1.24.04.1 with the local suffix +gts9u1. The rootfs builder checks
source-input hashes and includes both the daemon and matching common package.
The full upstream daemon suite is built; only the ambient callback is patched.
Full upstream hardware/integration tests are not run in the build chroot;
the targeted compiled regression test and live measurements are separate checks.

Primary code reference: [GNOME's ambient controller](https://github.com/GNOME/gnome-settings-daemon/blob/gnome-46/plugins/power/gsd-power-manager.c).

## Live result after the GNOME correction

Immediately before the GNOME change, a 25-second sample measured system D-Bus
at 2.359%, logind at 1.679%, and gsd-power at 0.760% of one core. Afterward the
same sampler measured 1.280%, 0.200%, and 0.560%, respectively. These are
sequential active-session samples, not a fixed-workload benchmark or a battery
measurement. The direct method-call evidence establishes the removed work.

A first ten-second trace after exercising the slider contained nine writes
alternating between two different values, with no consecutive duplicate
requests. A later eight-second system-bus trace contained only one
SetBrightness call and 107 total method calls. The filter permits real changes;
it is not intended to suppress all brightness writes.

A live control test moved the percentage from 27 to 28 and back to 27, verified
each observed value, and restored the original enabled state of automatic
brightness. The compiled regression also checks changed ambient targets.

The GNOME service refuses manual start/stop by default. A temporary runtime
drop-in allowed restarting just this daemon and cleared its session stop-check
for that controlled restart; the drop-in was removed and the user manager
reloaded immediately afterward. No reboot or browser restart was needed.
The previous binary is saved at `/var/lib/gts9u-power-efficiency.ntYbYP/gsd-power`.

Both matching GNOME packages are now installed via apt, together with Companion
1.3.11 and device 2.52. The running gsd-power executable was byte-compared with
the installed package file. Power and Companion services are active, automatic
brightness remains enabled, and dpkg reports no broken or unfinished packages.

A final ten-second trace after package installation recorded zero brightness
write requests. The original repeated-write trace contained 68 identical
requests over ten seconds.
