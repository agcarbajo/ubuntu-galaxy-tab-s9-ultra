# Reliable tablet audio startup

## Failure and cause

On 2026-10-01 the development tablet reproduced Dummy Output on the baseline
kernel and Device 2.78. ALSA card 0 and the ADSP were available, but WirePlumber
had cached only off/pro-audio profiles. The desktop-user helper restarted it
once and waited ten seconds to select HiFi, then logged failure and exited.
No later trigger retried audio recovery. A control node existing does not prove
that the UCM card object and its playback output are ready.

## Packaged recovery (Device 2.81)

The desktop-user helper retains ALSA restore before user-manager startup and
queues ubuntu-gts9u-audio-session@UID.service. The UID comes from the account
created by the owner, including first-boot setup; there is no baked-in account.
The separate oneshot does not block camera startup, polls for at most 120
seconds and attempts no more than three WirePlumber restarts, spaced apart.
It never restarts the ADSP or PipeWire and does not clear user configuration.

Success requires HiFi to be exposed and a real sink belonging to the board's
card. PipeWire's actual Noble pactl JSON identifies the sink through
properties.device.name; unlike PulseAudio it may omit the top-level card index.
A successful set-card-profile command alone is insufficient. If the card is
off with HiFi available, select HiFi and wait for its output. An already working
session is left alone, preserving the active profile, mute, volume and default
output. After success the oneshot remains exited; it performs no ongoing polling
or restarts. Each boot creates a new service run. Exhausted recovery fails with
a journal message rather than repeatedly disrupting clients.

The 2.80 development package initially used only the top-level sink card index.
Physical inspection revealed Noble's different JSON shape; its monitor was
stopped and 2.81 corrects the health check. The regression includes that actual
shape. Neither development package was uploaded to a public release.

## Verification

- Nine behavioral cases cover cached early profiles, delayed user bus, bounded
  retries, output creation, existing sessions, query failure and real PipeWire
  JSON. Speaker routing regression, shell syntax and ShellCheck pass.
- The actual ARM64 package was built and installed through APT with one upgrade,
  zero new packages/removals and matching transferred hash. Live package SHA-256:
  a1bce3a6ca4eb81d0a1799bb07fd3090b9360f89914c86caa7fb98a3ee691284.
- The live package retains the exact installed signed IRQ/TUN modules and native
  fingerprint/presentation helpers. Its payload differs from 2.78 only in the
  desktop-user helper, audio helper/unit and the separately validated 2.79 ext4
  initramfs setting. No kernel or partition was changed.
- Two authorized real reboots returned on boot IDs
  63abd2b3-c8ef-43c3-8e12-5d71e920b2a2 and
  ac50e25a-7caa-4d55-bcb7-77f5866ff8bd. Each recovered after one WirePlumber
  restart in approximately four seconds, exposed HiFi and the default board
  speaker sink, retained right-channel ASP_RX2 and active ADSP/pd-mapper/GDM/
  camera relays, four V4L2 endpoints and the Fprint device. Package audit is clean.
- After the second reboot the owner confirmed audible speaker playback and a
  working camera without recovery commands. The reboot reported immediately
  after login coincided with the second scheduled test reboot; the boot history
  contains the two expected boot IDs, with no additional boot.

Rollback package and the original helper/ALSA state were saved root-only in
/var/lib/gts9u-diagnostics/audio-startup-20261001. A stale, incomplete September 30
update download had no running updater or prepared installation; it was cancelled
using the official updater before APT installation. The hidden 1.3.0 candidate
must be rebuilt with the current Device package before publication. New clean images and APT updates
consume this same package source.

## Camera enumeration after session recovery (Device 2.83)

The owner reported four non-working duplicate camera choices suffixed (V4L2),
while the four native sources worked. The PipeWire graph confirmed eight video
sources: four libcamera inputs plus this port's four compatibility loopbacks.
The latter already consume the native inputs and should not be reimported into
PipeWire. Device 2.83 filters exactly the four named board relays on virtual
V4L2 device paths; the /dev/video20-23 devices remain available to direct V4L2
applications. Other virtual cameras and external USB cameras are not matched.
The audio recovery helper is byte-identical to the reboot-tested 2.81 helper.

The 2.82 development iteration matched api.v4l2.cap.* keys, but WirePlumber fills
those after its initial device-rule evaluation. It failed to remove duplicates.
The final rule instead uses device.name and device.description, populated before
rulesApplyProperties in the installed 0.4 monitor. After loading the final rule,
the live graph exposes exactly four native video sources, and /dev/video20
successfully delivers five frames through the compatibility relay. No image data
was retained. A Lua 5.4 regression evaluates the actual configuration and covers
all four relays, native sources, other loopbacks and USB paths. Device 2.83 passes
package verification and audit; its live package SHA-256 is
14fcd6a3ce49f6c6d128ff4341dac955a4a05a6d842bfe4729dfe9c30e33d9f0.
The owner confirmed the duplicate choices are gone and the usual cameras work.
No new kernel or reboot was
needed for this enumeration change; WirePlumber was restarted with Camera closed.
