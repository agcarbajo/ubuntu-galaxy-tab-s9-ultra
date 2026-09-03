# NPU investigation — 2026-09-04

The Hexagon NPU is **not available in the currently running Ubuntu port**.
This is a software integration finding, not evidence of defective hardware.

## Live evidence

Read-only SSH inspection of the Samsung Galaxy Tab S9 Ultra Wi-Fi running
Ubuntu 24.04.4 LTS and kernel `7.2.0-rc3-dirty` found:

- `/proc/device-tree/soc@0/remoteproc@32300000/compatible` is
  `qcom,sm8550-cdsp-pas`, and its `status` is `disabled`.
- The registered remote processors are ADSP and SPSS, both running. CDSP is
  absent from `/sys/class/remoteproc`.
- `/dev/fastrpc-adsp` exists; `/dev/fastrpc-cdsp` does not.
- `CONFIG_QCOM_FASTRPC=y`, `CONFIG_REMOTEPROC=y` and
  `CONFIG_QCOM_Q6V5_PAS=y` are present in the running kernel configuration.
- The firmware search found `qcom/sm8550/cdspr.jsn`, a service registry
  description, but no CDSP firmware image under the inspected firmware paths.
- No QNN/SNPE/QAIRT package or runtime was found in the package inventory or
  the inspected `/usr/lib`, `/usr/local` and `/opt` paths. `hexagonrpcd` 0.4.0
  is installed and its ADSP sensors protection-domain service is running.

The board DTS enables `remoteproc_adsp` but contains no CDSP enablement.
The sensor packaging starts `hexagonrpcd` against `/dev/fastrpc-adsp`.
Neither working sensors nor the GPU validate NPU inference.

Raw inspection output is saved locally in `work/npu-audit-20260904.txt`
(not versioned). No firmware was loaded, no device-tree setting was changed,
and no reboot was performed for this investigation. An inference test could
not run through CDSP because that device is disabled.

## Work required before claiming support

1. Integrate the appropriate Samsung-authenticated CDSP firmware and board
   configuration, including memory, power and interconnect requirements.
2. Validate CDSP boot and the CDSP FastRPC device on the physical tablet.
3. Integrate a compatible Linux userspace inference stack and its required
   DSP libraries; Android binaries alone do not establish Linux compatibility.
4. Execute a small model explicitly on the HTP backend, check numerical
   results against a reference, and inspect profiling to rule out CPU fallback.
5. Check repeated execution and suspend/resume before declaring support.

Simply changing `status` to `okay` is not sufficient evidence of support.

References: [upstream SM8550 device tree](https://raw.githubusercontent.com/torvalds/linux/master/arch/arm64/boot/dts/qcom/sm8550.dtsi)
and [ONNX Runtime QNN backend and profiling documentation](https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html).
