# Camera enumeration and autofocus investigation — 2026-09-08

## Status

The stable-ID rule is installed; the user confirms OBS cameras work. The first
AF candidate was rolled back after an optical false positive. A third candidate,
combining confidence checks with a less noise-sensitive metric, passed the
continuous monitor/remote/monitor optical test and is now installed and accepted.
Post-install camera, OBS-property and idle checks passed; the safety rollback
timer is inactive and the previous runtime is retained as a backup.
No reboot, OBS configuration change or OBS binary patch has been performed.
Private camera images are not included in this repository.

## V4L2 properties crash

Installed Ubuntu OBS version: `30.0.2+dfsg-3build1` (arm64).
`scripts/probe-v4l2-properties.py` creates a disposable private V4L2 source and
requests its properties through the installed libobs API, without Qt or saved
scene changes. Before the stable-ID rule, it reproduced SIGSEGV during enumeration.

The Ubuntu source package contains
`debian/patches/linux-v4l2-Save-device-by-id-or-path.patch`. Its directory scanner
declares an uninitialized `struct dirent **namelist`, calls `scandir()`, then
unconditionally calls `free(namelist)` even when scanning failed. On this tablet
`/dev/v4l/by-id` was absent. AddressSanitizer identified an invalid free in that
scanner; unsanitized runs can instead corrupt the loader and crash later.

Source: [Ubuntu source package directory](https://archive.ubuntu.com/ubuntu/pool/universe/o/obs-studio/),
archive `obs-studio_30.0.2+dfsg-3build1.debian.tar.xz`.

An isolated diagnostic interposer redirected only the missing directory scan to
the existing by-path directory. The exact same property probe then completed
successfully. That interposer is **not** a proposed fix and was never installed
or added to the environment of OBS.

The device-side mitigation adds standard `/dev/v4l/by-id/platform-gts9u-...`
aliases for the four processed cameras through the existing udev rule. This
benefits every V4L2 client that stores persistent camera names, preserves the
existing aliases and permissions, and avoids the missing-directory failure.
It does not repair the underlying Ubuntu OBS memory-management bug, and should
not be described as such. Raw CAMSS nodes remain unchanged.

`udevadm verify` passes. After authenticating:

```sh
pkexec bash scripts/install-camera-stable-ids.sh
python3 scripts/probe-v4l2-properties.py
```

The installer backs up the old rule under
`/var/lib/gts9u-camera-backups/stable-ids.*`, reloads udev rules and emits change
events only for video20–23. It does not restart audio or camera services.
After user authentication, all four by-id aliases resolve to video20–23 as
expected. Five consecutive property probes pass with the installed, unmodified
OBS libraries and no diagnostic interposer. Normal OBS UI confirmation remains
pending; the exact API operation that previously crashed now succeeds.
Live rule backup: `/var/lib/gts9u-camera-backups/stable-ids.eCEo2cDj`.
A subsequent relay regression cycle delivered 145, 147, 147 and 144 frames
from video20–23, respectively, with multiple distinct nonuniform frames on
every camera. All four captures completed successfully.

## Experimental autofocus patch 0006

The GPU path passed full raw buffers to statistics processing, but discarded the
x/y offsets of the statistics rectangle. The rectangle also depended on the
requested output resolution. Patch 0006 uses an aligned central-third sensor
rectangle and preserves its offsets. This changes metering, not output framing.

The old continuous AF waited up to 450 valid statistics (about 60 seconds at
30 fps with statistics every fourth frame) unless contrast fell by 30% for five
valid samples. The candidate:

- Detects sustained contrast increases as well as decreases.
- Checks nearby lens positions after 45 valid statistics, approximately six
  seconds, and does a full scan only for a clear improvement or scene change.
- Preserves single-shot lock until explicitly retriggered.
- Gives the initial lens movement a settling sample and does not call zero
  contrast successful focus.

All this work is frame-driven; there is no new background timer or idle capture.
The earlier GPU context-release patch remains in the build.

`scripts/test-camera-autofocus.py` compiles the actual production state-machine
methods against synthetic contrast curves. Initial lock, stable-scene probing,
near/far reacquisition, single-shot lock and featureless-input failure pass.
These tests do not certify optical sharpness or real lens settling latency.

Candidate source on PC-ARTURO:
`/root/ubuntu-gts9u/buildroot/build/camera-gpu-experiment.5clKaeCb/source`.
The two pre-change source files were saved in the sibling `af-source-backup.*`
directory. Build output is `stage-af`; tablet staging directory is
`/home/agcar/performance-lab/camera-af-stage.H3TCqKhs`.

Candidate hashes:

```text
eecd58d796e530cb7069110ce448835c55d593c3c6728a84a40892b086c20c78  libcamera.so.0.7.2
df379999e177042c264eca269185b69a02f02ab9f31b74b165998307f70603f2  ipa_soft_simple.so
```

Staged GPU captures at 640×480: all four cameras completed 90/90 frames.
Indicative ISP times for cameras 1–4 were 5696, 6361, 6266 and 2707 µs/frame,
respectively; these uncontrolled short runs are not battery measurements.
Rear-main 1920×1080 captures completed 360 frames with both baseline and candidate.
Metadata first reported focus at frame 92 (baseline) and 96 (candidate).
Focus metric numbers must not be compared directly because the sampled region changed.

A separate 450-frame candidate capture monitored the physical V4L2 lens control:
it scanned, settled at 512 around 3.74 seconds, checked 464 and 560 around
9.77–10.08 seconds and returned to 512 at 10.39 seconds without a full-range hunt.
This confirms actual periodic actuator activity, not just metadata changes.

The monitor text is legible in both current samples. Linux still has more shadow
noise and less usable dark-bezel detail than the supplied Android photograph;
image-quality parity and changed-scene optical reacquisition are **not verified**.
Those early results alone did not justify activation. See the final candidate
validation below; the production recipe now includes patches 0006 and 0007 together.

## Further optical testing and rollback

The first candidate passed a controlled physical-lens perturbation test:
after initial focus at lens position 512, a normal V4L2 control moved the lens
to 768 at frame 240. AF restarted at frame 252 and returned to focused position
512 at frame 348 (about 3.6 seconds after perturbation). This does not substitute
for changed-scene testing.

It was installed with a 15-minute rollback timer and tested with a handheld
remote control. One capture declared Focused with a visibly blurred remote.
A fresh capture of the same object acquired readable text, demonstrating that
the first accepted position was not a reliable result. The first scan's contrast
curve was nearly flat (roughly 6909–7351), consistent with an ambiguous/noisy
measurement. Hand motion was not measured and must not be asserted as the cause.

The first candidate was rolled back using its saved transaction:
`/var/lib/gts9u-camera-backups/af-20260908.GsYSL8VN`.
Rollback completed, its timer is inactive and the restored live libcamera SHA256
is `c113d774c287cf60d2fcc69449517d8b917cc40926bef149a740269ed0f3a60b`.
No reboot was needed; PipeWire and camera relays were restarted for each swap.

The revised patch tracks the minimum score over the full scan and requires the
winning score to exceed it by more than one twelfth (an experimental confidence
threshold, not a calibrated optical guarantee). Ambiguous results report Failed,
with at most three immediate full scans separated by 15 valid statistics.
Normal scene-change checks and periodic local probes remain active afterward.
Synthetic tests also cover a nonzero flat noise floor, bounded retries, and
recovery when a previously ambiguous scene becomes usable.

Revised stage: `/home/agcar/performance-lab/camera-af-confidence.Y7NdNmju`;
remote installation staging directory: `stage-af-confidence` beside the existing
experimental source. Revised IPA hashes:

```text
7ff0a5af6149788b8f7ee5d081d94961caf424e425f23af1ebe9fca50958c8f8  ipa_soft_simple.so
e6609c92e1c4e43738dbbedd98cf306f026c02c382fd606adfe3b22933093142  ipa_soft_simple.so.sign
```

The library hash remains `eecd58d796e530cb7069110ce448835c55d593c3c6728a84a40892b086c20c78`.
This confidence-only candidate was not deployed. The installer was subsequently
repinned to the final candidate documented below.

The revised candidate correctly reported Failed on a low-detail shelf scene.
A second perturbation run in that scene did not pass (there was no initial focus
lock); the test now explicitly refuses to perturb unless initial focus exists.
A 3600-frame staged capture stayed operational while the view moved from the
shelf to a monitor at the far right edge. It did not obtain a focus lock with
the text outside the central statistics region. A stationary text target within
the metering region is needed next, followed by a continuous near/far transition
without restarting capture. Off-centre target selection also remains a limitation.
Private snapshots/logs reside in `camera-af-live.iMl2PYl5` and the revised stage;
subsequent rolling frames were written to user runtime tmpfs, not persistent disk.

## Noise-resistant metric and continuous optical validation

The confidence-only candidate acquired the repositioned monitor at frame 96 of
a 450-frame capture, with visibly legible text. In a subsequent continuous capture,
the remote's labels became legible but the confidence heuristic still reported
Failed. The original statistic gave too much weight to fine sensor noise in this
dark scene; a fixed peak-ratio threshold alone was not sufficient.

Patch 0007 averages four horizontal statistics samples before computing the
second derivative used for focus. It changes only the focus numerator, not the
RGB sums, luminance total, histogram, Bayer conversion or output pixels. It is
**not an image denoiser** and does not fix shadow noise in the delivered video.
`scripts/test-camera-focus-metric.py` compiles the actual production macros and
checks reduced noise contribution, sharp/blurred separation and unchanged
colour/exposure statistics. AF state-machine tests also pass.

Final staging directory: `/home/agcar/performance-lab/camera-af-metric.S7yQ2ZAr`.
Remote stage: `stage-af-metric`, beside the existing experimental source.

```text
2bebd6e5d819421f1a50778c432ae947bc290de39b9f3fc24d1ac2ec5151779e  libcamera.so.0.7.2
7ff0a5af6149788b8f7ee5d081d94961caf424e425f23af1ebe9fca50958c8f8  ipa_soft_simple.so
e6609c92e1c4e43738dbbedd98cf306f026c02c382fd606adfe3b22933093142  ipa_soft_simple.so.sign
```

The controlled physical-lens perturbation test passed again: frame 240 moved
512→768, AF restarted at frame 252 and reacquired 512 at frame 348.
The user then moved a remote into and out of the central field while one capture
remained open. Both the remote's numbers/labels and the monitor text were
visibly legible in their respective snapshots, with AfState=Focused. The lens
was observed at 608 for the remote and 512 after its removal. State transitions:
0→96, 368→464, 1152→1248 and 2976→3072 (Scanning→Focused; approximately 3.2 seconds
per scan). No Failed state occurred in this capture. It was deliberately stopped
after frame 4394 once the check was complete, rather than leaving it capturing.
Private snapshots: `near.png`, `far.png`; log: `near-far.log` in the final stage.
This is validation of this scene and distance change, not all lighting conditions
or Android-quality parity. The central metering-region limitation remains.

Before deployment, all four cameras completed 90/90 staged GPU frames at 640×480.
Indicative ISP times for cameras 1–4: 5187, 4364, 6341 and 1110 µs/frame. These
short uncontrolled measurements are not battery comparisons.

Production recipe revision `gts9u9` applies patches 0001–0007 in order, retaining
release optimization, full-field GPU processing and stop-time GPU context release.
The live transaction uses the same six-file ABI-compatible replacement and does
not replace tuning, kernel, relays or camera identities. Its backup is
`/var/lib/gts9u-camera-backups/af-20260908.nGQtMMKM`.
Post-install acceptance completed and the 15-minute safety timer is inactive.
Installed library/IPA hashes match the final stage above. The staged optical
capture explicitly logged `GL_RENDERER: Adreno (TM) 740`.

Two live relay cycles passed on all four cameras: frame counts were
142/140/136/134 and 134/142/140/132 for video20–23, with at least 117 distinct
nonuniform frames per capture. The unchanged OBS V4L2 property probe also passed.
In the subsequent 20.0027-second idle sample, PipeWire PID 24518 used 327 µs of
CPU (0.00163% of one core). Its matching DRM client 87 stayed at 1638173705 ns of
GPU engine time before and after; memory stayed around 42.5 MB. This confirms no
measurable GPU camera work in that idle sample, not zero whole-system consumption
or a quantified battery-life improvement. Supervisory relay processes remain.

Rollback, if required, uses the retained root-owned transaction:

```sh
pkexec bash /var/lib/gts9u-camera-backups/af-20260908.nGQtMMKM/transaction.sh rollback /var/lib/gts9u-camera-backups/af-20260908.nGQtMMKM
```

This restores the previously accepted GPU runtime and restarts camera/audio
services. No kernel reboot or change to the OBS/stable-ID fix is involved.
