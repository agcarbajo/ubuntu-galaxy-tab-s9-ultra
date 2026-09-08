# Camera and sensor efficiency audit — 2026-09-08

The tablet runs the accepted fingerprint-contact kernel #8. This audit does
not replace the kernel, change sensor sampling, restart the session or enable
the experimental GPU ISP in the desktop. Remaining Chromium visual bugs are
still unresolved; do not infer a performance improvement from the earlier
vendor-identity change.

## Sensors and idle cameras

Two 20-second samples during normal Chrome/ChatGPT use, with no camera readers:

| Service | First sample, % of one CPU core | Second sample |
| --- | ---: | ---: |
| iio-sensor-proxy | 0.441 | 0.835 |
| camera relays and supervisor | 0.380 | 0.264 |

The second sample also measured the sensor FastRPC service at 0.000%.
These are cgroup CPU deltas, not hardware wakeup counts or energy savings.
The battery was charging: battery current cannot establish tablet discharge
power in this session. SensorProxy reports an accelerometer and orientation
`normal`; this is not a physical rotation/suspend acceptance test.

The existing libssc busy-wait fix remains installed (`0.4.4-gts9u2`). Source
inspection shows that the sensor selects the first positive advertised sample
rate. This does not establish that the rate is excessive, or even its live
value. No sampling reduction, batching, rotation debounce change or service
shutdown policy change is justified by these measurements alone.

Repeat the read-only sample with:

```sh
python3 scripts/measure-camera-sensor-idle.py --seconds 20
```

## Working camera baseline

All four V4L2 relays delivered changing, nonuniform frames after sequential
opening and closing. Sample luminance hashes were distinct 44/45/41/45 times
for `/dev/video20` through `/dev/video23`; image data was discarded, not saved.
This checks streaming, not focus accuracy, colour fidelity or field of view.
The first physical camera captured 90 frames at both 640x480 and 1280x720,
approximately 30 fps, with XRGB8888 output. Its raw input was
4000x3000 GRBG-10-CSI2P, stride 5008. One 640x480 run reported 13205 us/frame
for the ISP. Workload/scene were not controlled, so this is a baseline sample,
not a comparative speedup claim.

A subsequent 1280x720 XRGB8888 baseline using the repeatable benchmark captured
all 90 frames successfully for each camera:

| `cam` index | ISP us/frame | Child CPU seconds | Wall seconds |
| --- | ---: | ---: | ---: |
| 1 | 23442 | 3.748 | 3.381 |
| 2 | 22236 | 3.660 | 3.403 |
| 3 | 23172 | 3.871 | 3.424 |
| 4 | 22755 | 3.795 | 2.519 |

Capture cadence is not explicitly forced by this probe; do not compare these
wall times across different sensors as though the input frame rates matched.

`cam` originally could not launch: libevent and libevent_pthreads were missing.
Installed the two runtime packages plus their libevent-core dependency
(867 kB total, no upgrades/removals). `cam --help`, `cam -l` and captures now
work. The production package builder declares these dependencies, plus the
direct TIFF/DW/unwind dependencies visible in `ldd`, as package revision gts9u6.
Revision gts9u7 additionally selects an optimized release build explicitly;
the production GPU option remains disabled.
The installed libcamera package itself is still gts9u5; no library was replaced.

```sh
python3 scripts/benchmark-camera-isp.py --camera 1 --width 1280 --height 720
```

This discards 90 frames, requires the requested output format, bounds capture
time, and reports child CPU time separately from ISP timing. It does not close
other applications. Do not run it during a call or another camera capture.

## Experimental GPU path — not deployed

The production builder still uses `-Dsoftisp-gpu=disabled`. The pinned source
has an EGL/GLES debayer backend; camera statistics still execute on the CPU.
Enabling it defaults to GPU selection when an EGL display can be probed, with
a CPU fallback at that stage. It is not a blanket guarantee of runtime error
recovery, zero-copy operation, lower energy or improved output quality.

`scripts/build-camera-gpu-experiment.sh` archives the pinned commit
`62d4bfc450798cbd57722fa349a245b93b11d1cd` from the existing PC repository,
applies the same four production patches, and builds into a unique small
camera-only directory in the existing arm64 chroot. Dirty source/build trees,
installed libraries, kernel modules and signing keys are untouched. It only
stages the candidate, preserving tuning files and disabling direct GStreamer
camera enumeration. No experimental package is installed or published as the
production default.

Run on PC-ARTURO as root, with the repository available:

```sh
bash scripts/build-camera-gpu-experiment.sh
```

Once the complete stage is copied to a private tablet directory, compare the
same build's CPU and GPU modes using `benchmark-camera-isp.py --stage PATH
--mode cpu` and `--mode gpu`. Check logs for actual GPU initialization/fallback
and errors. Require four-camera streaming/reopen/handover, autofocus, colour,
full field of view, orientation, frame pacing and latency before deployment.
Energy comparisons require comparable unplugged workload/brightness/scene;
CPU time alone is not a battery-life result.

The [upstream ISP benchmark documentation](https://docs.libcamera.org/master/software-isp-benchmarking.html)
likewise distinguishes processing time from capture/output time and requires
separate power measurements. Its suggested isolated laboratory setup is not
applied automatically to the user's live office session.

## Completed staged CPU/GPU probe

The experimental build completed on PC-ARTURO in
`/root/ubuntu-gts9u/buildroot/build/camera-gpu-experiment.5clKaeCb` and its stage
was copied to `/home/agcar/performance-lab/camera-gpu-stage.ZUiZZW12`.
The candidate libcamera SHA-256 matched on both machines:
`932322f7b388edc6b72af81dd6532845932c60c5252cb196f146d151e6507732`.
All four cameras completed 90-frame 1280x720 XRGB8888 captures in both modes:

| Camera | Release CPU ISP us/frame | GPU ISP us/frame | CPU-mode child CPU seconds | GPU-mode child CPU seconds |
| --- | ---: | ---: | ---: | ---: |
| 1 | 8533 | 6364 | 1.403 | 0.632 |
| 2 | 7200 | 6100 | 1.089 | 0.651 |
| 3 | 6900 | 5740 | 1.113 | 0.686 |
| 4 | 3768 | 2166 | 0.767 | 0.326 |

These single passes were sequential, with live desktop activity and an
uncontrolled scene. They establish successful captures and promising lower
CPU cost, not battery savings, repeatability, or equivalent image quality.
The GPU runs report `GL_RENDERER: Adreno (TM) 740`, OpenGL ES 3.2 Mesa 25.2.8.
The three hi1337 cameras report input DMA-buf import failure and texture-upload
fallback: GPU processing works, but this path is not zero-copy. The hi847 run
did not report that fallback.

An important independent finding: the previous PC build's Meson options are
`buildtype=debug`, `optimization=0`, `softisp-gpu=disabled`. Merely using
`release` substantially reduces CPU-mode processing time in these probes.
The production recipe now selects release explicitly, keeping its CPU backend.
Do not attribute the entire installed-vs-GPU gap to GPU acceleration.

Neither release libraries nor GPU mode have been deployed to desktop services.
Before doing so, validate actual pixels, autofocus and full field of view with
a fixed test scene, then relay/PipeWire compatibility and recovery. Those
quality checks cannot be inferred from successful frame completion alone.
