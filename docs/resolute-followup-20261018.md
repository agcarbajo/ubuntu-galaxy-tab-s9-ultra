# Resolute follow-up: work in progress, 2026-10-18

The owner requested functional fixes without changing either project's version.
The existing release drafts and ZIP have not been regenerated for this work.
The running system is Ubuntu 26.04.1 with Linux 7.2.9-dirty. Compilation,
enumeration and service activation below are not physical acceptance.

## Implemented and exercised

- Galaxy Companion hides cover diagnostics and air-pointer references according
  to the device profile's keyboard-cover and S Pen remote capabilities.
- The released Android APK crashed in JobScheduler before asking for root:
  ACCESS_NETWORK_STATE was missing. An API 35 emulator reproduced the old
  SecurityException; the corrected, identically signed APK opened successfully.
  Physical Samsung/root-prompt validation remains pending.
- Nintendo, PlayStation and Sony HID drivers and joydev are now built in, rather
  than relying on modules absent from the shipped module set. The owner confirmed
  Switch Pro inputs in Eden. Chrome 155/hardwaretester still fails after granting
  bounded hidraw uaccess and fully exiting Chrome. A user read/write open succeeds;
  Chrome itself opens hidraw. A bounded read sees 49-byte report 0x30 at about
  66 Hz and repeated 49-byte subcommand replies 0x21/0x30 about every 3 seconds.
  Chromium excludes Nintendo from its joydev path and initializes it through HID.
  Chrome Beta 157 contains the upstream correction and the owner confirmed inputs
  there. At the owner's request, browser diagnosis is closed pending the fix
  reaching stable. Beta is diagnostic only and excluded from the ZIP/dependencies.
  DS4 is not physically tested.
- S Pen BatteryProvider publishes only live BlueZ/GATT readings and removes stale
  objects on disconnect. The owner confirmed the percentage in GNOME Settings.
- Cover relay releases forwarded keys on disconnect, SYN_DROPPED and read errors,
  and reconciles lost releases against EVIOCGKEY while keys are held. Synthetic
  regressions pass; intermittent physical repetition still needs a typing trial.
- PM8xxx RTC is built in. Ubuntu keeps its own UTC/raw-counter anchor without
  writing Android's RTC. A subsequent real reboot logged successful restoration
  from the continuing counter. Full shutdown/offline acceptance is pending.
- The selected accepted root's boot set is published through the original base
  filesystem's canonical Ubuntu path. Android boot sets are preserved. The new
  Android APK also prioritizes this selected root over stale shared-storage sets.
  An Android-to-Ubuntu round trip remains pending.
- Previous-system cleanup has a displayed footprint, a confirmation button and
  an automatic threshold of seven accumulated healthy Ubuntu uptime days. Failed
  health checks and unclean reboots reset the trial; Android/off time does not
  count. Temporary-tree tests preserve shared home, selected slot, Android boot
  images, private root recovery and `/var/lib/gts9u-boot-backups`. No real previous
  system has been deleted. Its initial measured footprint was about 89 GiB.
- BlueZ inventory calls are cached for 30 seconds and invalidated on topology,
  connection and owner changes. Tests cover invalidation. No battery-life or
  throughput improvement has been claimed from this change.

## HDMI and keyboard haptics: current evidence

The missing DP sound backend is supplied by a Linux runtime overlay, preserving
the accepted DTB/vendor_boot. Eight-byte DTBO array alignment is required for
libfdt. DP0 Jack and MultiMedia6 register in the running matched kernel.

The UCM predicate must search CARD, not MIXER. Independent HDMI/HiFi verbs keep
an unplugged or unpowered DP codec from invalidating internal audio. The owner
confirmed audible sound through both the tablet speakers and HDMI capture.
Switching profiles pauses browser media; resuming it restores playback.

Adding RTKit in an existing session exposed a stale desktop portal advertising
zero realtime budget while RTKit offered 200000 us. PipeWire's effective
RLIMIT_RTTIME became zero, causing repeated SIGKILL during sound. Refreshing the
portal and recreating audio processes restored 200000 us and stable playback;
the already running browser needed restarting. The bounded audio startup helper
now repairs precisely this mismatch. Twelve focused tests pass.

Device audio6 attempted to share the Mic device but moved its frontend/backend
route too late, into device enable. Listing UCM verbs accepted the syntax but did
not test PCM probing: the actual ACP probe rejected both profiles. That revision
is rejected. Audio7 restores the capture route in both verb EnableSequences and
shares the remaining Mic settings. A real ACP probe with the corrected temporary
UCM tree and WirePlumber stopped exposes HiFi and HDMI. Installation and the
post-install microphone check are tracked below; probing alone is not listening.

The earlier USB-C orientation recovery followed a real suspend-abort PHY failure.
A later apparent failure followed physical unplugging, clarified by the owner;
reconnecting then exposed valid ELD and video. No speculative PHY patch was made.
HDMI rediscovery after a boot without a monitor and resume still need checks.

The OSK3 Companion extension uses native Key pressed signals, including dynamic
keys; the system-bus broker enforces the enabled preference and local active seat.
After reboot the owner confirmed vibration in an application and on the lock
screen. Initial GDM login and a separate polkit prompt still need physical checks.

## Build and recovery evidence

- Aligned kernel Image.gz:
  `a05a79c19077a1700974eb401a3ed730ce9b3c1f2e85b416cb6bc80fc79aa87e`.
- Boot written/read back in the second deployment:
  `d94fd6125cbfc428a6dfc7060208d8121d57f33f03f612bc8f5330e9ead271e9`.
- Config: `7dea338f0a3d062c29ede8535b444bf43f583764e25f7888309d9a0589746cef`.
- Accepted vendor_boot retained unchanged:
  `92332a3d028c355c3c52ba4cc304670fa777dfa8560a35e868041995f1e948ed`.
- Device audio4 source snapshot:
  `72ce878f8a67146ca3608009d2382f14da2f6bbb6b0686b2c8ebf6909d3a50ee`.
- Device audio4 Debian package (2.91, no version increment):
  `0ca6137ee6270004d0e5ecdbcf07fb47d4c94c66460ca76d5fb9935fa581352d`.
- Root-only prior boot/modules backup in current Resolute root:
  `/root/gts9u-followup-audio2/backup`; first migration-follow-up recovery lives
  under the retained base's `/root/gts9u-followup-20261018/backup`.

Native WSL build inputs are immutable numbered source snapshots under
`/root/gts9u-followup-20261018-source*`; Companion's own snapshot is copied into
isolated build trees only. The working submodule is not edited.

## Issue audit limits

Further live evidence:

- Rotating the USB-C plug recovered video (owner-confirmed), without recovering
  audio. After that, the active EDID advertises stereo LPCM at 32/44.1/48 kHz.
  A temporary off/on of the external display through Mutter preserves the exact
  previous layout but does not restore DP0 Jack or PCM preparation.
- The PHY runtime policy is `on`, so the upstream runtime-PM Type-C callback
  patch found during research is not demonstrated to explain this incident.
  No speculative PHY patch was applied. The aborting wake IRQ was pmic_pwrkey,
  not the newly enabled RTC alarm. The selected DP pin assignment is D.
- Bounded strace of only the Chrome process's existing threads and its hidraw
  descriptor proves that Chrome receives the 49-byte 0x21 responses too.
  Its exact installed tag 155.0.8059.84 rejects reports shorter than the 63-byte
  USB structs in ContinueInitSequence; upstream main uses Bluetooth-specific
  lengths. This confirms a browser bug rather than missing Linux inputs or an
  access-permission failure. No browser binary/kernel protocol workaround was
  installed to conceal it.
- Kernel lockdown prevents the requested ftrace function filter. The attempted
  diagnostic instance/probes were removed; protection was not disabled. No
  successful function-return trace is claimed.
- The installed Companion OSK3 package uses the native OSK Key `pressed` signal
  instead of stage touch hit-testing, including dynamically added keyboard
  children. Its source snapshot is
  `e10cd0d51a44edc8a9326fdb2da0f7a7e3c4823036d6e46ef9eb1fb4b0fc9e8e`,
  package SHA-256
  `c6841393a3f5ea8f33f83693835ed0e1b32e37472c32ab871b3930a5e23591c2`.
  After reboot, the extension is ACTIVE and the owner confirmed vibration in an
  application and in the lock screen. The temporary stage-event diagnostic saw
  normal-session touches but no lock-screen touches. It is now disabled.
  GDM's initial-login OSK and a separate polkit authentication prompt still need
  explicit physical checks; these were not part of the owner's two-place test.
- RTKit 0.14-1 is installed and required by Device in both suites. After restarting
  the user audio services, PipeWire data-loop threads use SCHED_RR priority 1;
  the D-Bus realtime ceiling is 20. This verifies scheduling, not a measured
  throughput or battery-life gain.

The open other-device requests (#1 S9+, #10 X710) cannot be validated on SM-X910.
Fingerprint provisioning work relates to #8/#9 but does not prove another unit's
calibration/runtime works. EF-DX925 backlight and automatic-brightness oscillation
reports in #8 need the relevant hardware/reproduction; this owner's cover is
EF-DX920. A passive brightness capture with automatic brightness disabled cannot
validate an automatic-brightness fix. #3 concerns One UI OEM unlock/download mode,
not a runtime Ubuntu repair. No issue is closed on this evidence.

Latest HDMI check: after reconnecting the cable, the display exposes a valid
stereo LPCM ELD and video works. The owner clarified it was physically unplugged
before that test. HDMI is selectable, unmuted at 35%, and a short PipeWire tone
completes without controller errors, but the owner did not hear it. Audio remains
unaccepted. The separate HDMI profile also needs the shared internal microphone
and hotplug reprobe integration; neither is physically validated yet.

Owner-confirmed acceptance update: after restarting Chrome following the portal
repair, music is audible through both tablet speakers and HDMI capture. Changing
outputs pauses playback; resuming it restores sound. The perceived loss when
switching back was the paused browser, not a demonstrated speaker-routing fault.
The portal repair and shared Mic are packaged in Device audio6 (same version).
See the chronological log for the measured zero-limit SIGKILL cause and hashes.

2026-10-19 current deployment: audio8 (2.91) is installed and package audit is
clean. Its packaged user hotplug service is active/enabled; the transient test
service is stopped. A real connected/enabled display with a missing ACP HDMI
profile was reproduced and the helper restored HDMI plus the Mic node once.
The owner is checking reconnect/listening with the packaged service. Boot with
no display followed by connection and full USB-C suspend/resume still need
physical acceptance. The former is represented by the reproduced failed probe,
not yet by a new tablet reboot. No beta browser is part of this package or ZIP.

Owner acceptance update (2026-10-19): the full five-second USB-C disconnect,
reconnect, HDMI selection/listening and return-to-speakers cycle works with the
packaged audio8 service. No new reboot or suspend test is implied. The internal
microphone node is present in both profiles; no voice sample was retained.
