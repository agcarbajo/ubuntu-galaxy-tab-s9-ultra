# Chromium graphics: preserve Mesa's driver identity

## Cause and controlled reproduction, 2026-09-08

The board's `99-gts9u-adreno-name.conf` globally forced GL_VENDOR to Qualcomm
for the MSM/FD740 driver. That is not a cosmetic-only field: applications
choose driver workarounds from it. The late board rule also overrode the
upstream Mesa `00-mesa-defaults.conf` vendor workaround for Chromium and
several Electron applications (ANGLE issue 431097618).

The running ChatGPT GPU process repeatedly logged Skia shader failures:
`overlapping component is assigned to fragment shader outputs`, with
`_usk_FragColor` and `_ufsSecondaryColorOut`. This caused repeated compilation
and journal/syslog work. This investigation does not assign all Chromium
visual bugs to that one cause.

An isolated, windowed Chrome 152.0.7977.82 profile rendered local text and a
canvas using hardware ANGLE/OpenGL on Mesa 25.2.8. It did not access the
owner's tabs or profile. In sequential five-second observation windows:

| Driver identity supplied to the new process | Skia/overlap errors | Text |
| --- | ---: | --- |
| Existing Qualcomm + Adreno (TM) 740 override | 10 / 10 | Most lines missing |
| freedreno + FD740, process-local diagnostic override | 0 / 0 | Visible |
| freedreno vendor only, friendly Adreno name retained | 0 / 0 | Visible |
| Installed correction, no environment override | 0 / 0 | Visible |

In the installed case Chrome sees Mesa's upstream `angleisbroken` vendor
workaround; ordinary `glxinfo` sees freedreno. This is expected, not a new
global spoof. The acceleration feature-status maps were identical: GPU
compositing, rasterization, OpenGL and WebGL remained enabled. No software
renderer or disabled-GPU flag was used. The initial headless experiment
could not initialize accelerated EGL and is excluded from this comparison.

The correction removes only the board-wide `force_gl_vendor` option. The
friendly GL_RENDERER remains `Adreno (TM) 740`. It applies across applications
using this Mesa configuration without per-app launch flags, and preserves
Mesa's existing application-specific rules. It does not change Vulkan,
frequencies, shaders, extension support, rendering quality or log filtering.

Relevant primary sources are the installed Mesa 25.2.8
`/usr/share/drirc.d/00-mesa-defaults.conf` MSM section and
[ANGLE issue 431097618](https://issues.angleproject.org/issues/431097618).
The exact failing internal code path was not traced; the controlled identity
comparison establishes this configuration regression independently.

## Follow-up

The applications have since been restarted and the remaining gradient/canvas
corruption addressed with hardware ANGLE/Vulkan. See the
[2026-09-09 validation and deployment](chromium-vulkan-rendering.md).
The deployment notes below describe the earlier 2.49 intervention.

## Deployment and recovery

Only `/usr/share/drirc.d/99-gts9u-adreno-name.conf` was updated on the tablet.
The prior file is at
`/var/lib/gts9u-graphics-backup.RBYVei/99-gts9u-adreno-name.conf`.
The device package source is version 2.49; dpkg's installed version was not
changed for this direct, single-file deployment.

Existing application/GPU processes keep their old configuration until fully
closed and reopened. The owner session was not terminated. The active
ChatGPT process therefore still needs a restart and a post-restart CPU/log
sample. No measured battery-life gain is claimed, and the camera GPU ISP
backend remains disabled pending separate quality/latency/energy testing.

A 15-second active-office sample of the still-running old processes measured
54.33% of one core for the ChatGPT GPU process, 17.00% for rsyslogd and 12.67%
for systemd-journald (CPU-time deltas, not lifetime `ps` percentages). These
are a pre-restart reference, not an attribution of every CPU cycle to this
bug or a controlled battery comparison.

Recovery is to install the backed-up file over the same drirc path and reopen
affected applications. No kernel or system reboot is necessary.

## Repeat the graphics check

Use Node with native WebSocket support (the bundled Node runtime works):

```sh
node scripts/test-chromium-freedreno.mjs spoofed /absolute/path/to/test-output
node scripts/test-chromium-freedreno.mjs vendor-only /absolute/path/to/test-output
node scripts/test-chromium-freedreno.mjs installed /absolute/path/to/test-output
```

The harness opens and closes a separate local test window, uses a fresh
profile for each run and records GPU capabilities, screenshots and stderr.
Inspect the screenshots as well as reported error counts; merely obtaining
WebGL or exiting successfully does not establish correct text rendering.
Profiles/results are intentionally retained in the specified output directory.
