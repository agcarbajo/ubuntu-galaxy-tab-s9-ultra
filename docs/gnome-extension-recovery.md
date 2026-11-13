# Quick-settings recovery, 2026-10-26

The owner reported missing Flashlight and Dualboot tiles. Both UUIDs were in
`enabled-extensions`, both installed extensions supported GNOME 50, and neither
had an individual disable. The global `disable-user-extensions` setting was
true. Clearing it reactivated both extensions without replacing Shell or
closing the session; the owner confirmed both tiles appeared.

## What triggered it

Boot `001094dc1b0d47c69a30165ccdfd2290` records a genuine Shell SIGSEGV on
2026-10-23, at monotonic 48.957 seconds, shortly after session startup. The
extension-disable service ran at 48.994 seconds and persisted the global
switch. The kernel also reported an Adreno lockup/recovery before this event.
This is correlation, not a demonstrated native crash cause. No matching saved
Apport crash report was available for the targeted backtrace reader. Do not
attribute the SIGSEGV to a particular extension or claim to have fixed it.

The earlier stop-timeout safeguard had a separate packaging defect. It was
installed only for `org.gnome.Shell@wayland.service` and `@x11.service` and
the helper accepted only those names. GNOME 50's installed template uses
session modes: the active desktop is `org.gnome.Shell@ubuntu.service` and
the greeter uses `@gdm.service`. The active desktop had no recovery drop-in.

## Packaged correction and limits

The device package moves the drop-in to `org.gnome.Shell@.service.d/` and
accepts only valid Shell template instances. The build measured below was
numbered 2.92 for Resolute (2.91 for Noble); the committed package is 2.93 and
2.92, because the same revision also carries the libfprint pin correction from
issue 13, and the measured 2.92 is already installed on the tablet.
The existing classification is retained: successful exits, exit status 1 and
timeouts after readiness may clear the runtime failure marker; signals,
core dumps, OOM kills, startup timeouts and unknown results preserve GNOME's
safety behavior. The change prevents the mode-name coverage regression from
causing false extension disables. It does **not** prevent the native crash
above or override legitimate recovery after another real crash.

The normal Device package builder consumes both changed files for clean images
and upgrades. Public port 2.0.0 and Companion 1.0.0 versions are unchanged.
No boot images, release assets or Companion code were changed.

## Validation

- Five focused regression tests passed in WSL, including legacy and mode-based
  units, false-failure cleanup, genuine-crash preservation and invalid units.
- The real arm64 Device package was built from immutable snapshot hash
  `c149d32af195a00daf2b0478a3b310f55ca0209b6968bc99b827eb177f874fdd`.
  Package SHA-256:
  `add3d9df456343d5830b3622a294af1b5ddbc3e7e305fb52449c5c3f2338dd3d`.
- Compared with the physically accepted 2.91 payload, only the helper and
  recovery drop-in paths differ; native binaries and signed modules match.
- Tablet transfer hash matched. APT simulation selected one upgrade, zero new
  packages and zero removals. On-device administrator authentication installed
  Device 2.92, ending in `install ok installed`.
- User-manager reload, without restarting Shell, showed the template drop-in
  and helper in the active `@ubuntu.service`'s `ExecStopPost`. Both tiles were
  ACTIVE and the global switch false afterward.
- The installed helper passed timeout cleanup and signal-marker preservation
  using temporary markers and the live unit's readiness timestamps. A first
  isolation attempt redirected systemctl's runtime bus as well as the marker;
  its connection failure retained the marker as designed. The corrected
  harness isolates only marker storage and uses the actual user manager.

No logout, reboot or deliberate Shell/GPU crash was performed. Persistence
across a future session is packaged and checked through the loaded unit; an
actual future-session physical check remains pending. Private build/deployment
inputs are retained in `work/toggles-20261026/` and the native WSL build under
`/root/gts9u-toggles-20261026/`.
