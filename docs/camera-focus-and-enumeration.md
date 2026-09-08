# Camera enumeration and autofocus investigation — 2026-09-08

## Status

Work in progress. The stable-ID rule is prepared but its live installation is
waiting for PolicyKit authentication. The autofocus candidate is built and tested
privately, **not installed**. The accepted GPU/idle runtime remains unchanged.
No reboot, OBS configuration change or OBS binary patch has been performed.
Private camera images are not included in this repository.

## V4L2 properties crash

Installed Ubuntu OBS version: `30.0.2+dfsg-3build1` (arm64).
`scripts/probe-v4l2-properties.py` creates a disposable private V4L2 source and
requests its properties through the installed libobs API, without Qt or saved
scene changes. It reproduces SIGSEGV during device enumeration.

The Ubuntu source package contains
`debian/patches/linux-v4l2-Save-device-by-id-or-path.patch`. Its directory scanner
declares an uninitialized `struct dirent **namelist`, calls `scandir()`, then
unconditionally calls `free(namelist)` even when scanning failed. On this tablet
`/dev/v4l/by-id` is absent. AddressSanitizer identifies an invalid free in that
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
Live, un-interposed property enumeration and normal OBS UI testing remain pending.

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
Do not activate 0006 in the production package recipe or replace the live runtime
until those checks and regression/idle tests are completed.
