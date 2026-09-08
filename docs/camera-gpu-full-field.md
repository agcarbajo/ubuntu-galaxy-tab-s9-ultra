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

Recipe revision gts9u8 enables release optimization and EGL/GLES support,
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
normal package build uses gts9u8.

At the time of preparing this note, installation is awaiting the local polkit
authorization; the system library remains at its original hash. Do not treat
the recipe change or staged capture results as proof of live deployment.
