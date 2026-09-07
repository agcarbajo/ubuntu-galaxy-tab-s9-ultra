# macOS ARM64 VM experiment

> Personal, experimental and opt-in. This is not included in default Ubuntu
> builds. No Apple firmware, IPSW, installed image, auxiliary storage, machine
> identity or credential may be committed to this repository.

## Target architecture

The intended long-term display path is macOS ARM64 using
`AppleParavirtGPU`, a Reims virtual device, `metal2vulkan`, Vulkan, Mesa Turnip
and the Adreno 740. Reaching a desktop and proving Turnip GPU work are separate
milestones: a window alone is not evidence of acceleration.

The bring-up order is firmware/AVPBooter, XNU serial, kernel, root filesystem,
`launchd`, stable userspace, WindowServer, desktop, then Reims. Software Vulkan
is permitted as a diagnostic backend before Turnip, but cannot satisfy the
final acceleration criterion.

## Known-good reference and portability gap

The closest public reference currently boots macOS Ventura 13.6 (22G120) with
QEMU vmapple, KVM and Reims on an Apple Silicon Asahi host. It needs Apple-only
PAuth VM-key register context in KVM, an Apple private HVC service, and a narrow
XNU GIC-instruction workaround. Those host assumptions do not transfer
directly to the SM8550: Gunyah owns EL2, upstream QEMU has no Gunyah accelerator
and Qualcomm CPUs do not implement Apple's private PAuth registers.

Consequently, Linux-on-Gunyah must work first. The macOS phase then needs a
vmapple-capable VMM execution backend over the generic Gunyah VM UAPI plus a
demonstrated solution for the Apple boot/PAuth contract. Reims cannot solve a
CPU or boot-chain incompatibility.

## Isolation from normal builds

The deployment model is a clean, generic Ubuntu build followed by a separate,
explicit personal installation step on this tablet. Normal kernel, device,
rootfs and release builds must never stage macOS launchers, AVPBooter, Apple
patches, Reims's Apple-specific integration, guest identities or guest disks.
Only reusable virtualization improvements belong in those builds.

The personal setup must eventually be reproducible from that same clean Ubuntu
installation, without relying on hidden state in the development tablet.
The final guide must cover prerequisites, pinned public sources, obtaining and
verifying private inputs locally, installation, first boot, normal start,
shutdown, restart, snapshot/backup and recovery. Each procedure must be tested;
the current experimental notes are not a completed installation guide.

Expected private layout, covered by the repository's ignored `artifacts/` and
`work/` trees:

```text
artifacts/macos-vm/firmware/   # AVPBooter obtained from an owned Mac
artifacts/macos-vm/guest/      # disk, auxiliary storage and machine identity
work/virtualization/sources/   # pinned external source checkouts
work/virtualization/logs/      # serial, QMP, VMM and Reims traces
```

The initial guest reference should remain Ventura 13.6 build 22G120 because it
is the public ARM64 vmapple/Reims configuration with end-to-end evidence. Use a
legitimately obtained UniversalMac restore IPSW and verify its published build
and local hash. Provisioning presently requires access to macOS and
Virtualization.framework; the public Linux restore path is explicitly
unfinished.

## Required acceptance evidence

- AVPBooter and XNU milestones have timestamped serial logs.
- The guest disk is snapshot-backed and clean shutdown/restart is repeatable.
- WindowServer reaches the desktop without modifying the guest driver.
- Reims reports its Vulkan backend and device-memory path.
- `vulkaninfo` on the host identifies Turnip and the Adreno 740 for the process
  used by Reims; CPU renderers such as llvmpipe are rejected for the final test.
- Frame timing, CPU overhead, VM exits, memory copies and synchronization errors
  are recorded before calling the result usable.

The day-to-day start, stop, restart and from-scratch restore procedures will be
written only after the corresponding paths have been exercised on the physical
tablet. Commands inferred from another host are not presented as working
instructions.

## TCG investigation after the shipping RM restriction

The shipping Resource Manager currently prevents the tested unsigned-Gunyah
route from initializing a guest; see `virtualization.md` for the live trace
and policy analysis. Do not claim that a Linux-side KVM facade removes it.

The separate public
[VMApple TCG experiment](https://github.com/steelbrain/experiment-macOS-arm64-on-linux-x86/tree/vmapple-tcg),
pinned at `509a4ce52bc703dfc79eb8b4283f51acd88b8594`, documents headless macOS 13
execution through software CPU translation. Its scope does not include GPU
acceleration. It is an experimental CPU/platform reference, not a ready-made
solution for this tablet or a replacement for Reims/Turnip integration.

Its repository-owned VMApple firmware smoke test passed on the x86-64
development PC on 2026-09-08. This is not an AVPBooter or macOS boot result.
The same fixture also passed using a native ARM64 build on the physical
SM-X910, including the virtual counter-frequency and installer-selector checks.
That binary's SHA-256 is
`54153532637b6ff5cdcfd6aad220f525674d3ab50f6f4d476f19cfa9ca9adc71`.
The ARM64 tablet build is isolated under the user's `macos-vm-lab` directory;
it does not replace `/usr/bin/qemu-system-aarch64` and is not a dependency of
any normal build. CPU performance, macOS provisioning and accelerated graphics
all still need physical validation.

The reference TCG implementation does not validate the implementation-defined
pointer-authentication cipher. Its reported headless success must not be
mistaken for full guest hardening or production readiness. This limitation
must remain explicit in any personal deployment using that implementation.

### Release isolation checks

The release rootfs sanitizer rejects personal files under `/home`, including
`macos-vm-lab`, before creating a shipping image. It also rejects the reserved
personal namespaces `/opt/ubuntu-gts9u-macos`, `/var/lib/ubuntu-gts9u-macos` and
`/var/lib/gts9u-project-archive` (including empty directories or dangling links).
The last location may contain recoverable archives of completed experiments on
the owner's tablet; it is never a source for a release. Generic QEMU, Gunyah and
Turnip package contents remain allowed. These checks do not install macOS or
turn a live personal installation into a distributable rootfs.
