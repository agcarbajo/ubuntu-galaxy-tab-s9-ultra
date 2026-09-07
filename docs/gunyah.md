# Gunyah virtual machines

## Current state

The port carries the complete Linux host stack needed to talk to Qualcomm's
Gunyah hypervisor: arm64 hypercalls, message queues, Resource Manager RPC, VM
lifecycle and memory assignment, proxy-scheduled vCPUs, irqfd, ioeventfd, and
the Qualcomm memory-permission hooks. The stack is built into the kernel and
exposes `/dev/gunyah` when firmware publishes a compatible Resource Manager.

The code has been clean-build validated against the port's pinned Linux
7.2-rc3 tree with LLVM 22. Runtime5 was then booted on the physical tablet with
its matching module set: the kernel identified legacy-v1 Gunyah, recovered and
applied the per-boot Resource Manager overlay, translated both interrupts and
registered `/dev/gunyah`. Wi-Fi, SPSS and the EL721 fingerprint path remained
operational. Guest creation and execution remain the next validation stage.

## Hardware evidence

Samsung's stock SM-X910 DTBs reserve `0x80000000..0x809fffff` as
`gunyah_hyp_region` and describe secure VM loaders for `trustedvm` (VMID 45)
and `cpusys_vm` (VMID 50). This establishes that the shipping SM8550 firmware
uses Gunyah. A captured Android live tree additionally proves that firmware
generates a `qcom,resource-manager-1-0` child with two message-queue capability
IDs and SPI 928/929 beneath `/hypervisor`. Capability IDs are scoped to the
VM's capability space and are randomized on every boot, so they must never be
copied into a static DT.

On physical hardware the standard Gunyah identify hypercall and info-area call
return `-1`, but the Qualcomm vendor UID SMC returns
`19bd54bd-0b37-571b-946f-609b54539de6`. This is a shipping legacy-v1 Gunyah
implementation. ABL's read-only `HYP_INFO_GET_HYP_DTB_ADDRESS` SMC
(`0x02000609`) succeeds and returns a valid `HypBootInfo` structure. The single
DTBO referenced by that structure contains the current boot's RM capability
IDs and the complete `/hypervisor` node.

The captured DTBO also explains why it cannot be handed to ABL together with
the mainline tree: it fixes up `arch_timer` and three downstream-only paths.
Both a structurally modified base DTB and a selector DTBO containing inert
anchors were rejected by this tablet's ABL and entered recovery/Download Mode.
Those paths are therefore diagnostic only and are not enabled by the normal
build.

The working boot path keeps the byte-identical, physically validated base DTB
and the deliberately invalid DTBO image that selects ABL's appended-DTB
fallback. At `subsys_initcall` time Linux calls the read-only Qualcomm
`HYP_INFO_GET_HYP_DTB_ADDRESS` SMC, copies the firmware DTBO and applies only
its Resource Manager fragment as a live overlay. The firmware uses the legacy
three-cell GIC interrupt format while mainline SM8550 uses the optional fourth
PPI-partition cell, so the runtime importer expands SPI 928/929 to four cells
with a zero partition selector before applying the overlay.

## Kernel configuration

The device fragment enables these built-in options:

```text
CONFIG_VIRT_DRIVERS=y
CONFIG_GUNYAH=y
CONFIG_GUNYAH_PLATFORM_HOOKS=y
CONFIG_GUNYAH_QCOM_PLATFORM=y
CONFIG_GUNYAH_VCPU=y
CONFIG_GUNYAH_IRQFD=y
CONFIG_GUNYAH_IOEVENTFD=y
```

## Physical validation

After booting the new kernel, run:

```sh
sudo /usr/libexec/ubuntu-gts9u-gunyah-check
```

A usable host reports a live `gunyah-resource-manager` node, Gunyah/RM probe
messages and `/dev/gunyah`. Absence of the device is not enough to conclude
that the hypervisor is missing: the report distinguishes missing live-DT data,
driver probe failure and a kernel built without the required options. The
first physical runtime-overlay boot reached the driver and identified legacy
Gunyah, but failed at `IRQ index 1 not found`; runtime5's three-to-four-cell
conversion corrected that failure and allowed `/dev/gunyah` to register.

Do not load a guest until this read-only probe succeeds. The first guest test
must use disposable RAM only, no assigned physical devices and no persistent
tablet partitions. A userspace VMM must target the UAPI in
`include/uapi/linux/gunyah.h`; KVM ioctls are not interchangeable with it.

A clean kernel build generates a new module-signing key even when the release
string remains `7.2.0-rc3-dirty`. Install the `modules-root` output from that
exact build before booting it; reusing the previous build's identically named
ath12k/SPSS/QCOMTEE modules can leave the tablet without Wi-Fi or fingerprint.
Any unattended rollback test must cover both `boot.img` and the module tree,
and its systemd unit must set a start timeout longer than its rollback delay.

## Source baseline

The backport is pinned to Android Common Kernel commit
`9f6af9a6c2cc38808a531ba76b47a1bc6e4fe47e`. Its origin and the adaptations
made for Linux 7.2 are recorded in `kernel/PROVENANCE.md`.
