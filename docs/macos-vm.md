# macOS ARM64 VM experiment

> Personal, experimental and opt-in. This is not included in default Ubuntu
> builds. No Apple firmware, IPSW, installed image, auxiliary storage, machine
> identity or credential may be committed to this repository.

## Target architecture

The final target requires **both hardware-virtualized ARM64 CPU execution and
real GPU acceleration on the physical tablet**. Gunyah is the current hardware
backend candidate; KVM is acceptable only if hardware-backed guest execution
is actually made available. A KVM-shaped userspace API alone is not evidence
of hardware virtualization. TCG is a diagnostic tool, never a final fallback.

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

- The running macOS ARM64 guest uses a verified hardware CPU backend on the
  physical tablet: Gunyah vCPU execution, or genuinely available KVM execution.
  Record the selected backend and successful guest execution through it;
  reject TCG and silent software fallback, even if the desktop or GPU works.
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

### Obtaining the Ventura VM firmware without a Mac (verified on the tablet)

On 2026-09-08 the personal tablet downloaded the official
[Ventura 13.6 / 22G120 restore image](https://updates.cdn-apple.com/2023FallFCS/fullrestores/042-55833/C0830847-A2F8-458F-B680-967991820931/UniversalMac_13.6_22G120_Restore.ipsw)
and verified its SHA-256:
`9bf095739b8b2d5ebd20f7e8de938f10bc449f9843de21c4a41ae54d73526728`
(12,893,555,341 bytes). Keep the download and all extractions private, outside
the release rootfs. Allow at least 31 GB for the IPSW plus both intermediate
images; provisioning a guest needs additional space.

The verified extraction chain was:

1. Extract only `097-48281-025.dmg` from the IPSW (7,482,223,922 bytes).
2. Extract only `4.apfs` from that DMG (9,544,138,752 bytes).
3. From the APFS image, extract
   `System/Library/Frameworks/Virtualization.framework/Versions/A/Resources/AVPBooter.vmapple2.bin`.

The distribution's 7-Zip 23.01 could extract the intermediate images and list
the firmware, but failed to decode that firmware with `Data Error`.
[Upstream 7-Zip 26.03 for Linux ARM64](https://github.com/ip7z/7zip/releases/download/26.03/7z2603-linux-arm64.tar.xz),
run from a private directory without replacing the system tool, successfully
extracted it. The downloaded tool archive's observed SHA-256 was
`2389ba20e4d8295e8709c20b6263b69bd1ec4972fe38a04ad7a1badbf595b996`.

The successfully extracted firmware is 214,904 bytes with SHA-256
`e562cb7eb497903df23a58a61fe3809c1ffd9e5c9b4b32d2e98be80e13651318`.
This is Ventura's firmware, not the later 304,352-byte firmware used by the
public Asahi experiment. No Apple firmware is committed or shipped in builds.

A bounded, disk-isolated native ARM64 TCG test with this firmware, one vCPU,
4 GiB RAM, `run-installer=on` and fresh 16 KiB dummy AUX/ROOT files executed
firmware code, then produced QMP `SHUTDOWN` with `guest=true` and
`reason=guest-reset`. Its UART log was empty. QEMU exited zero because
`-no-reboot` terminates the emulator on a guest reset: **this is not a successful
macOS boot or a proven DFU session**. Only the emulator exited; the tablet's
host boot was untouched. Real guest provisioning and graphics remain open.

### DFU transport and signing checkpoint (2026-09-08)

The reset above was traced to the missing virtual USB transport: the booter
read the USB configuration register and received the generic block-device
configuration. Importing the public Asahi experiment's
`vmapple-usb-chardev.patch` into the **personal** TCG build allowed the same
Ventura firmware to remain in DFU and exchange actual USB control requests.
The updated native ARM64 binary's SHA-256 is
`a58b981d25dc3e0357152e2214ae735eee10412365d7ec49cb0451725197e64a`.
The repository-owned VMApple fixture still passes after this change.

The physical tablet answered device/configuration descriptor requests,
SET_ADDRESS, SET_CONFIGURATION and DFU GETSTATE, with VID/PID `05ac:1227`
and actual state `02`. This is firmware DFU, not the macOS installer.

The tablet kernel does not enable `CONFIG_USBIP_CORE`. A separate disposable
TCG instance in WSL was therefore used to test the complete USB/IP/VHCI path
without altering the tablet kernel. The unmodified `irecovery` client at
`1c495c5aa1ba7fd82cd22f054092fde7979d8532` identified `VirtualMac2,1`,
`vma2macosap`, CPID `0xfe00`, BDID `0x20`, DFU mode and `iBoot-8422.141.2`.
The owned emulator/bridge processes were stopped and their VHCI port released
after each bounded test; no physical USB restore target was used.

Apple TSS returned signing tickets for the disposable VM and Ventura 13.6.
The private restore client is based on
`45145e9fdc8458022c61a4b87bd029b866d5bcdc`, with a narrowly scoped change that
skips payload-file presence checks **only for `--shsh`/ticket-only requests**.
This avoids copying the whole IPSW just to request signatures. A real restore
against the incomplete payload tree was separately verified to fail its
original required-component checks. Tickets and personalized images remain
private and are not release assets.

The next test wrapped the original iBSS payload with the returned IMG4 ticket
and attempted transfer. The first 2,048-byte block was followed by an actual
six-byte DFU status `09 32 00 00 0a 00` (nonzero status, state 10). No second
DNLOAD block was sent. Despite that, the `irecovery -f` command exited zero.
Thus CLI exit status is insufficient: the harness must reject nonzero DFU
status bytes and must not invent successful replies when firmware responses
are empty or time out. The local strict transport retries empty status
responses, then fails rather than synthesizing download-idle or wait-reset.
That first transfer was **not successful**. The following checkpoint fixes its
transport cause; XNU, installation and GPU acceleration remain unverified.

### iBSS / iBootStage1 Recovery on the physical tablet (2026-09-08)

The private USB bridge now sends control OUT as one type-1 packet containing
the eight-byte USB SETUP followed by its data. The inner payload length includes
both; a 2,048-byte DFU block therefore has inner length 2,056 and a 2,062-byte
packet including the six-byte transport header. Its actual acknowledgement is
type 1, status zero. Sending SETUP separately followed by type 3 was incorrect:
only eight bytes reached the control-data receiver. Tests with zeroes and
nonuniform data reproduced this independently of image signatures. A deliberately
wrong combined length also reproduced the real status-9 rejection.

With correct framing, all 112 blocks transferred: 229,273 image bytes plus the
16-byte DFU suffix. Actual GETSTATUS responses progressed through states
5, 6, 7 and 8 with status zero, without synthesizing any reply. The type-2
transport event, acknowledged as type 4, forwards the USB reset once real
WAIT_RESET has been observed. Type 0 is not a valid reset event for this
transport and caused a firmware panic in a disposable test.

A second missing contract was USB channel control at register offset `0x404`:
stopping the channel must acknowledge zero and retire the outstanding RX DMA
buffer. Without it, the firmware waited indefinitely at channel shutdown.
The private QEMU checkpoint `1685f5e` implements this and extends the
repository-owned, non-Apple smoke fixture to check enable/stop readback.
The updated native ARM64 binary has SHA-256
`bc4f7bfa32a264e8382e2a2f596e182b7c027da68bb7efffd096ed170028b643`.

Both the disposable PC VM and the physical SM-X910's native ARM64 QEMU then
produced an iBootStage1 UART banner and entered its recovery command prompt.
The unmodified USB client independently reported Recovery, and the real USB
descriptor changed from `05ac:1227` to `05ac:1281`. **This proves iBSS execution,
not an XNU boot or a macOS installation.**
Two independent physical runs reproduced it. The bounded harness now requires
both the Recovery USB query and the iBootStage1 UART marker; an exit code or a
completed download alone cannot pass. Nine host-only bridge tests cover packet
framing, length/direction checks, real error preservation, empty/timeout rejection
and reset gating on actual WAIT_RESET. The extended non-Apple channel-control
fixture also passes with the native tablet binary.

For the physical test, QEMU ran as the tablet owner using fresh private AUX/ROOT
files. USB and monitor sockets listened only on tablet loopback; the WSL
restore client reached them through host-key-pinned SSH forwarding. Thus the
tablet needed neither USB/IP kernel support nor a host reboot. Owned processes
were terminated after the bounded test; logs and temporary disks stay inside
the personal lab, outside all normal builds.

### iBEC / iBootStage2 Recovery on the physical tablet (2026-09-08)

The personal bridge now supports Recovery bulk OUT on endpoint 4. A type-1
data packet is acknowledged by bytes `01 04`: the second byte identifies the
endpoint, rather than being a generic success code. A 65,792-byte nonuniform
probe transferred in three chunks and the unmodified recovery library's
`getenv` returned `filesize=0x10100`, `loadaddr=0x72e00000` and `boot-stage=1`.
The bridge regression suite has twelve passing tests, including rejection of
wrong bulk endpoints, acknowledgements and oversized packets.

Before sending iBEC, the probe requests fresh tickets for the current Recovery
nonce and sends the empty local policy using its separate TSS signature,
following the open-source restore client's ordering. Ticket-only supplemental
exports are private, non-overwriting and owner-readable only; the real restore
path keeps its payload-presence checks. No signing bypass is used.
The private restore-client checkpoint is `a840551`; its opt-in
`GTS9U_TSS_EXTRAS_DIR` exports the already-fetched supplemental tickets only in
ticket-only mode. An incomplete real restore was re-tested and still rejected.

The stage2-only sequence sends the signed policy (`lpolrestore`), volatile boot
settings, RestoreLogo and signed iBEC, then the `go` command. The policy, logo
and iBEC containers measured 3,039, 13,985 and 265,261 bytes respectively in the
verified runs. `saveenv` returned a real USB stall with the blank disposable AUX
store, so that command is explicitly omitted from this **nonpersistent probe**.
Persistent environment storage and complete provisioning remain unverified.

Both the PC reference and native ARM64 QEMU on the physical tablet reached the
iBootStage2 recovery command prompt. The library independently returned
`boot-stage=2`; the harness requires both that response and the Stage2 UART
marker. An early two-second reconnect attempt failed while the CPU was still
initializing the next stage; allowing ten seconds succeeded. This is progress
toward restore-kernel loading, **not XNU, an installed macOS system or guest GPU
acceleration**. The tablet's host kernel and boot images remain unchanged.

The selected Ventura restore ramdisk (`097-48350-027.dmg`) has also been
extracted privately from the verified IPSW: 155,189,275 bytes, SHA-256
`11944d3e93773e5ab4bf38d9a452e12726a8e303c2eb2333c3d33347d8e0a045`.
This prepares the next kernel-loading probe; it is not evidence of kernel boot.
