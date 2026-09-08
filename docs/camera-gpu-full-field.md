# GPU cameras: full field of view and idle lifetime

## Cause of the cropped image

`DebayerCpu::configure()` centres an output-sized rectangle inside the raw
sensor frame. It does not scale the full sensor into a smaller output. With
the relay's 640x480 output and a 4000x3000 input, this selects only 16% of the
raw width and height (not 16% of the optical field angle). Changing the CPU
compiler optimization level cannot fix that crop.

Our existing patch `0003-software-isp-preserve-full-field-of-view.patch` changes
the EGL backend to scale/letterbox rather than crop. It could not affect the
installed cameras while GPU support was disabled. Enabling the GPU path makes
that patch effective for the normal PipeWire/V4L2 camera path. The CPU fallback
still uses the upstream centre-crop implementation; do not claim that it has
been rewritten to scale.

## Visual and capture checks on 2026-09-08

The user provided the monitor as a fixed test scene. Rear-main 1280x720 captures
with the same staged release build, CPU then GPU, show a much wider scene with
GPU. Screen text is legible; the CPU image shows only a small central portion.
We did not reliably read the dark HDMI label and do not claim otherwise.
The GPU path retains the complete sensor aspect ratio, adding side bars at
16:9. No camera firmware, lens calibration or exposure tuning was changed.

The two front cameras and rear ultra-wide also completed 180-frame captures at
640x480 ABGR8888 (RGBA memory ordering, as requested by the relay input).
The front ultra-wide shows the wider room view and the main front a narrower
optical view; both are distinct cameras. Rear ultra-wide captures include the
monitor and surrounding desk. These observations do not establish perfect
autofocus in every lighting condition.

Private inspection frames are in
`/home/agcar/performance-lab/camera-fov.H48RT51d`; they are not committed or
uploaded. File-output captures are not performance measurements.

## Release GPU resources when closing a camera

The upstream `DebayerEGL::stop()` dropped texture caches and a shader program,
but retained its EGL context. `start()` created another context, overwriting
the old handle. This risks accumulating resources in long-lived PipeWire
processes as cameras are opened and closed.

Patch `0005-release-gpu-context-on-camera-stop.patch` deletes GL objects on the
ISP worker, unbinds its current context, destroys it and resets handles before
the worker exits. A repeated release is harmless. It also cleans up a shader
initialization failure. It does not terminate the shared EGL display or unbind
another client's current context. Context release ordering follows the
[EGL specification](https://registry.khronos.org/EGL/specs/eglspec.1.4.pdf).

The production function body passed a mock-EGL C++ test covering 100 lifetimes,
idempotence, detach-before-destroy and preserving an unrelated current context:

```sh
python3 scripts/test-camera-egl-lifecycle.py PATH/TO/PATCHED/src/libcamera/egl.cpp
```

This mock test does not replace live PipeWire reopen/idle tests.

## Candidate and transaction

Recipe revision gts9u8 enabled release optimization and EGL/GLES support,
declares EGL/GLES dependencies, and applies all five libcamera patches. The
existing no-reader relay patch remains unchanged. GPU acceleration still uses
CPU statistics and texture uploads where input DMA-buf import is unsupported;
it is not entirely zero-copy.

The rebuilt private stage is
`/home/agcar/performance-lab/camera-gpu-idle-stage.Q9YA98Bj`.
Its main library hash is
`c113d774c287cf60d2fcc69449517d8b917cc40926bef149a740269ed0f3a60b`.
It completed another 90-frame GPU probe and identified the Adreno 740.

`scripts/install-camera-gpu-live.sh` stages six pinned runtime files in a root
backup, stops the camera/audio stack, atomically replaces those files and
restarts the stack. It preserves the tuning files, V4L2 relays, PipeWire plugin,
kernel and modules. A seven-minute rollback timer restores the old files unless
explicitly accepted after live validation. No tablet reboot is performed.
The live-copy transaction does not update dpkg's package revision; the next
normal package build now uses gts9u9, adding the validated autofocus changes
documented in [camera-focus-and-enumeration.md](camera-focus-and-enumeration.md).

The first unanswered polkit attempt was cancelled without changes. After the
user explicitly authorized a retry, the six runtime files were installed and
the live transaction was accepted on 2026-09-08. Backup:
`/var/lib/gts9u-camera-backups/gpu-20260908.PXmS9JxE`.
The seven-minute rollback timer was stopped after validation. The backup and
its `transaction.sh rollback BACKUP` command are retained. Only the camera/audio
stack restarted; the tablet was not rebooted by this operation.

## Live acceptance

PipeWire loaded the pinned main library hash above and logged
`GL_RENDERER: Adreno (TM) 740`. All four normal V4L2 relays passed two sequential
open/capture/close cycles, with the same PipeWire PID throughout:

| Device | First cycle frames / distinct nonuniform samples | Second cycle |
| --- | ---: | ---: |
| video20 | 148 / 139 | 150 / 140 |
| video21 | 153 / 144 | 146 / 136 |
| video22 | 148 / 141 | 137 / 124 |
| video23 | 152 / 141 | 137 / 127 |

The saved last-frame PNGs were inspected locally. Front ultra-wide has the wide
room view and rear-main includes the monitor plus surrounding desk instead of
the old central crop. Rear-main sharpness varies between the short captures;
this is not a formal autofocus or all-lighting quality certification. Output
remains 640x480 YUY2 through the existing relays. Private images are under
`/home/agcar/performance-lab/camera-fov.H48RT51d/live-gpu`, not in GitHub.

After closing all test readers, a 20.003-second sample measured:

- PipeWire CPU: 0.0019% of one core (383 microseconds of CPU in the interval).
- PipeWire DRM client 34 GPU engine counter: 1849065352 ns both before and
  after, i.e. no added GPU work in the measured interval. Duplicate DRM file
  descriptors were deduplicated by client ID.
- PipeWire cgroup memory: stable at 42139648 bytes, down from approximately
  136 MB while capturing. This short test is not proof of absence of every
  possible long-term leak.
- A separate 20-second idle sample: camera relays 0.257% of one core,
  iio-sensor-proxy 0.719%, sensor FastRPC 0.000%.

The previous no-reader relay patch was not replaced (binary SHA-256 remains
`9a77b4c889c3a4f84300dfa8c69642b5853d7fa2b0942f55feba58fe0b4b0b93`).
There is still small supervisor/relay polling overhead: do not describe the
whole stack as consuming literally zero resources. Neither these counters nor
the processing benchmarks establish battery-life savings.

Reproduce the counters without changing the workload:

```sh
python3 scripts/measure-pipewire-camera-idle.py --seconds 20
python3 scripts/measure-camera-sensor-idle.py --seconds 20
```

Camera, sensor and fingerprint services remained active; SensorProxy reported
`normal` orientation and the user service manager had no failed units.
