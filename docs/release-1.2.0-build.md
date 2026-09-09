# Release 1.2.0 build inputs

The release uses a fresh kernel source/output tree and a fresh Ubuntu Noble root filesystem. The UFS PCS reset and bounded GPU fault recovery patches validated in kernel #11 are enabled by default. Set the corresponding staging variables to `0` only with a fresh source tree when deliberately building without those fixes.

## NPU support package

`build-ubuntu-rootfs.sh` includes `ubuntu-gts9u-npu` in the local package set used by both the root filesystem and the offline update payload. Its kernel modules are rebuilt and signed for the release kernel; the packager verifies their vermagic and signing certificate before accepting them.

Inputs are staged outside Git:

- `NPU_RUNTIME_DIR` (default `$UBUNTU_WORKDIR/npu-release-inputs`): the `opt/gts9u-npu` and `opt/gts9u-npu-bionic` runtime trees, matching `configs/npu/release-runtime.json`. The pinned source recipes are `stage-npu-runtime.py` and `stage-npu-bionic.py`.
- `NPU_FIRMWARE_DIR` (default `$UBUNTU_WORKDIR/npu-release-firmware`): the stock CDSP firmware under its final `usr/` paths, verified against `configs/npu/stock-cdsp.sha256`. Stage it with `stage-npu-firmware.py`.
- `ANDROID_NDK` and `QNN_HEADERS`: build the power helper with the pinned Android toolchain. Alternatively, `NPU_POWER_KEEPER` accepts that helper compiled on another build host; modules are still built locally against the release kernel.

No AI application, model catalogue, model downloader or model files enter this package. The service remains on demand and is not enabled at boot. Its startup self-test executes a generated MatMul/Relu graph on the HTP; it does not require a downloaded model. `test-npu-package.py PACKAGE.deb` checks the packaged boundary.

Fingerprint firmware is staged separately through `GTS9U_FINGERPRINT_FIRMWARE_DIR`, as in previous releases. No SSH password, user account or SSH identity is included in the release image.

## App languages

Both apps support English, Spanish, French, German, Italian and Portuguese. `test-companion-translations.py` covers translation calls throughout Tab Companion plus catalogue formatting. `test-dualboot-translations.py` checks every Android language catalogue, placeholders and links. Brand and operating-system names use their unchanged source spelling.
