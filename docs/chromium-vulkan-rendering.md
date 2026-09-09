# Chromium rendering on SM-X910, 2026-09-09

## Result

Chrome 152.0.7977.82 and ChatGPT now use hardware ANGLE/Vulkan on Mesa
25.2.8 (Turnip Adreno 740). ChatGPT also selects native Wayland when its
socket is available. No GPU-disable flags, software renderer, global Mesa
vendor spoof, or forced driver flush are installed.

The owner confirmed that Discord and Sheets now look correct and both Chrome
and ChatGPT feel substantially smoother. This is qualitative feedback, not a
controlled FPS, CPU or battery measurement. Other Electron applications are
not automatically covered by these two launcher integrations.

## Evidence and rejected configuration

An isolated Chrome profile reproduced the damaged Discord gradient with
ANGLE/OpenGL and rendered it cleanly with ANGLE/Vulkan. Synthetic canvas,
text, gradients and scrolling fixtures provide a repeatable local check.
The authenticated Sheets session could not be reused in the isolated profile;
Sheets validation therefore comes from the owner's actual browser session.

Chrome and the separate ChatGPT Wayland/Vulkan probe reported accelerated
canvas, GPU compositing, rasterization and WebGL. The renderer identified
Turnip Adreno 740 through ANGLE Vulkan. Chromium's separate native Vulkan
compositor status remains disabled; that field does not describe ANGLE's
selected backend.

ChatGPT with Vulkan on X11 failed EGL configuration selection and disabled
GPU compositing. That configuration was rejected. Native Wayland plus Vulkan
passed the GPU check and was then deployed to the normal ChatGPT launcher.
The running applications were restarted and the owner tested those sessions.

Missing colour emoji were a separate font issue: installing
`fonts-noto-color-emoji` restored the emoji font match. It is now a device
package dependency and part of the rootfs package list.

Keep the earlier [Mesa identity correction](chromium-freedreno-identity.md).
Restoring the global Qualcomm vendor spoof recreates a different Skia shader
failure. The precise driver defect behind the remaining GL corruption has
not been traced; the backend comparison establishes a working configuration.

## Persistent integration and recovery

Device package source 2.50 installs `ubuntu-gts9u-chromium-launchers`. It uses
package-owned dpkg diversions for the Chrome and ChatGPT vendor shell launchers,
retaining their originals as `.gts9u-original`. Sourcing the vendor scripts
preserves their executable discovery and Chrome's public PWA launcher path.
Package file triggers also cover installation and updates of those apps.

The launcher flags apply only to `samsung,gts9uwifi`. Explicit `--use-angle`
and `--ozone-platform` arguments take precedence. Foreign diversions and
edited launchers are not overwritten. Removing the device package restores
the vendor launchers. For a temporary comparison, fully close the relevant
application and launch it with `--use-angle=gl`.

The helper and fonts were deployed directly to the tablet; this did not
install the entire rebuilt device package or change the running kernel.
The full package build was attempted but stopped at its existing IRQ module
signing-key consistency check: the available module does not match the selected
kernel build certificate. No mismatched package was produced or installed.
The launcher lifecycle and shell/JavaScript syntax checks passed separately.
A reboot is not required. The package builder marks all libexec helpers
executable. Lifecycle tests cover repeated installation, original arguments,
explicit flags, vendor updates, Wayland selection and removal.

## Reproduce

On Linux, run `python3 scripts/test-chromium-launchers.py` for the isolated
launcher tests. In the tablet's graphical session, use Node with native
WebSocket support:

```sh
node scripts/test-chromium-rendering.mjs wayland-gl /absolute/test-output
node scripts/test-chromium-rendering.mjs wayland-vulkan /absolute/test-output
```

The harness uses separate profiles and a synthetic fixture, retaining GPU
reports, screenshots and stderr. Inspect the screenshots as well as feature
status. The earlier identity harness explicitly selects GL so the new default
does not mask its original regression test. Personal browser profiles and
screenshots are excluded from the repository.
