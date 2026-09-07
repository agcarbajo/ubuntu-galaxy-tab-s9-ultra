# Virtualization on the SM-X910

## Scope

The reusable virtualization path is Qualcomm Gunyah, not KVM. Samsung's
firmware already owns EL2 and runs Ubuntu as the primary VM, so Linux correctly
reports that KVM hyp mode is unavailable. The port exposes the firmware
Resource Manager through `/dev/gunyah` and builds the VM, vCPU, memory,
ioeventfd and irqfd interfaces into the kernel.

This document covers only generic host functionality. macOS-specific firmware,
machine identities, restore images, vmapple changes and Apple virtual devices
are separate, opt-in personal experiments documented in `macos-vm.md`. They
must not enter a normal Ubuntu image.

## Validation ladder

Each step is a prerequisite for the next one:

1. the runtime firmware overlay registers `/dev/gunyah`;
2. `GH_CREATE_VM` returns an anonymous VM descriptor;
3. shared userspace memory and a proxy-scheduled vCPU can be registered;
4. a minimal Linux Image, initramfs and generated DTB reach a serial shell;
5. CrosVM supplies virtio block, network, console and clean shutdown;
6. shared-memory coherency, ioeventfd and irqfd tests pass;
7. only then should a non-Linux experimental guest be attempted.

The physical runtime8 kernel has completed steps 1–3. Guest execution has not
been demonstrated. Build the non-starting ABI probe on the development host:

```sh
scripts/build-gunyah-tools.sh
```

Copy `out/gunyah-tools/gunyah-smoke` to the tablet and run it as root. It opens
the manager, creates a VM, registers 16 MiB of anonymous RAM, creates vCPU 0,
maps its run page and closes everything. It deliberately has no code path that
issues `GH_VM_START`, so it cannot execute untrusted guest bytes:

```sh
sudo ./gunyah-smoke
```

`--manager-only` limits the test to `GH_CREATE_VM`; `--memory-mib` and `--vcpu`
change the disposable memory size and vCPU label.

## VMM choice

CrosVM is the first generic VMM target. Its AArch64 Gunyah backend uses the
same upstream VM-manager UAPI carried by this port, automatically selects
`/dev/gunyah`, generates the `gunyah-vm-config` DT description, registers
memory, creates proxy-scheduled vCPUs and implements irqfd/ioeventfd-backed
virtio devices. It also tolerates kernels without the newer
`GH_VM_SET_BOOT_CONTEXT` ioctl when the payload begins at offset zero.

QEMU upstream does not currently ship a Gunyah accelerator. QEMU therefore
remains useful through TCG for device-model development, but it is not the
hardware-accelerated Linux-guest path. A KVM compatibility layer should only be
considered if it faithfully supports multiple existing VMMs; it must not be a
macOS-only facade.

## Memory model

The unprotected Linux-guest path registers page-aligned host mappings with
`GH_VM_SET_USER_MEM_REGION`. Those pages remain host accessible and are shared
with the guest by the Resource Manager when the VM starts. Protected guests use
the Android lend operation instead, removing host access for the lifetime of
the parcel. Device shared-memory regions must remain explicit and bounded;
exposing all private guest RAM to a device backend is not the design target.

The Linux guest test must record, for each region, whether the host can read and
write while the VM runs, cache-coherency results in both directions, supported
alignment and sizes, and cleanup/reclaim behaviour after normal and forced VM
termination.

## Current external baselines

- CrosVM source: `https://chromium.googlesource.com/crosvm/crosvm`, revision
  `cfe44050850dfaf8e132bce1805579d7ceb212fb` inspected on 2026-09-07.
- Linux Gunyah UAPI/backport baseline: Android Common commit
  `9f6af9a6c2cc38808a531ba76b47a1bc6e4fe47e`, recorded in
  `kernel/PROVENANCE.md`.
- QEMU upstream was inspected before choosing CrosVM and had no Gunyah
  accelerator in its supported-accelerator list.

Pin exact revisions in build metadata. Do not silently build whatever happens
to be at the tip of an external branch.

## CMA bring-up (experimental, 2026-09-07)

Runtime8 accepts the QTVM authentication-description ioctl and RM allocates
VMID 45. That only configures the requested authentication mechanism; it is
not proof of successful guest authentication. With the Qualcomm platform hook
loaded, CrosVM's lend attempt fails in `qcom_scm_assign_mem()` with `-EINVAL`
before RM configures the image. Anonymous/THP RAM has not resolved this error.

The CMA experiment tests whether a single physically contiguous extent changes
that result. Contiguity is a hypothesis, not an established explanation of the
firmware rejection. The Android CMA UAPI is backported by
`kernel/patches/gunyah-qtvm-cma.patch`, applied after the host, QTVM-auth and
runtime-overlay patches with `ENABLE_GUNYAH_CMA=1`. This is generic guest memory
infrastructure, unrelated to Apple guest components. It remains opt-in during
bring-up. A default build refuses a reused source tree containing the CMA
experiment; use distinct source/object directories when comparing variants.

The backport follows Android Common's CMA fd/mapping interface at commit
`65994b7471f1fd37242ff4a5032a812f5c168ae6`, with explicit file/device lifetime
references, serialized fd creation/allocation, bounds and overflow checks,
zeroing before userspace exposure, and retention of memory if reclaim fails.
Later Android fixes for CMA file references and offset validation were also
reviewed (`220923cf9f76`, `5bd7edfa25bd` in the 2026-07-13 merge
`18aeb866a2f912a3d993fbe5946edc61cad8e8fe`).

The physical SM-X910 tests must keep the known-good base DTB byte-identical:
ABL has previously rejected modified base trees. The offline 128 MiB CMA DT
overlay is therefore **not a deployable tablet artifact**. Instead, the
experimental kernel permits root to activate a small pool from the existing
default CMA area after boot:

```sh
# Only on a kernel explicitly built with the CMA experiment.
echo 16 | sudo tee /sys/module/gunyah/parameters/cma_test_pool_mib
sudo ./gunyah-cma-smoke
```

Activation is limited to 1–32 MiB and once per boot, publishes a root-only
`/dev/gunyah-vm-cma`, and does not reserve additional RAM or alter firmware
carveouts. Allocation begins at mmap. The smoke test checks eight concurrent
descriptor requests, three zeroing/reuse cycles, overflow/range rejection,
duplicate mapping rejection, and retention after the original fd and VMA
close. It never starts a VM or transfers memory ownership to the hypervisor.
The VM retains its file reference until asynchronous teardown completes.

Physical runtime9 validation on 2026-09-07 passed the complete CMA smoke test:
both eight-thread creation rounds and all three zeroing/bounds/lifetime/reclaim
cycles. Wi-Fi and GDM remained active, `/dev/esfp0` was present, the root
filesystem remained writable, and the kernel journal had no storage errors.
This validates sensor presence and PAM configuration, not a physical finger
authentication attempt. The exact runtime7/8 kernel configuration and module
signing certificate were retained; no module files were replaced.

The subsequent 16 MiB shared-CMA configuration probe reached
`gh_rm_mem_share()` → `qcom_scm_assign_mem()` → `gh_rm_vm_configure()` →
`gh_rm_vm_init()`. The first failure was VM_INIT (`-EINVAL`), followed by an
unsupported VM_RESET (`-EOPNOTSUPP`). The tablet was rebooted after the test to
clear firmware state. The probe used disposable bytes and a proxy-scheduled
DTB, and never created or ran a vCPU; this is **not a Linux boot result**.
The existing 59 MiB Linux Image does not fit in this small pool.

The QTVM 45/PAS 28 CMA-lend comparison still fails at the Qualcomm SCM memory
assignment, before RM image configuration. Thus CMA does not fix that route's
rejection. Generic shared-memory VM_INIT returns raw RM error 6
(`ARGUMENT_INVALID`) for both proxy and classic affinity-map configurations.
A compact guest DTB returned raw error 10 (`MEM_INVALID`); padding the DTB back
to the original 2 MiB restored error 6. Preserve DTB capacity/alignment during
guest-configuration A/B tests instead of mistaking a `fdtput` truncation for a
scheduler difference. None of these results proves that the firmware can run
an arbitrary unsigned guest, nor that this capability is impossible.

Generic CMA LEND with the padded classic-affinity DTB also reaches VM_INIT and
returns raw error 6, so the tested SHARE/LEND choice is not sufficient to fix
initialization. A guest DTB adding the legacy parser's CPU `config`,
`enable-method`, and interrupt-node metadata also returned error 6.
Do not count repeated successful memory transfers as successful VM execution.

The installed stock firmware was inspected from a local copy of
`hypvm.mbn` (SHA-256
`6249c495ff8c63f45450496c36dfba34e664b49cf5447a5168a600591ddb824c`).
Its diagnostic strings include the older mandatory CPU fields found in the
public Resource Manager revision `0accef9`, unlike the 2026 parser which
ignores some of those fields. This comparison guides further tests; it does
not establish that the public revision exactly matches Samsung's binary.

### Shipping RM policy restriction (2026-09-08)

An argument-level kprobe/kretprobe run, with the padded legacy DTB, recorded:

```text
gh_rm_alloc_vmid(request=0) -> 45
gh_rm_vm_configure(vmid=45, auth=0, handle=0,
                  image_offset=0, image_size=0,
                  dtb_offset=8388608, dtb_size=2097152) -> success
gh_rm_vm_init(vmid=45) -> raw RM 6 / Linux -EINVAL
```

A separate allocation-only test requested VMID 64 and received raw RM error 2
(`-ENODEV`), without assigning RAM or starting a VM. Both tests were followed
by a reboot and host health validation. Local evidence is
`cma-route-share-legacy-args-ftrace.log` and the corresponding kernel log.

Read-only disassembly of the **same hash-pinned Samsung firmware**, not an
assumed public RM revision, explains this combination. Its RM is a nested ELF
at file offset `0x1145c0` within `hypvm.mbn`. Relative to that embedded ELF:

- The allocation handler at `0x39288` rejects VMIDs above 63; automatic
  allocation selects from a 64-bit platform bitmap.
- Image configuration stores the requested authentication mechanism at VM
  structure offset `0x100` (instruction `0x46a24`).
- Platform initialization checks that field at `0x4703c`. Mechanism 1 takes
  the authenticated-image path; other mechanisms enter the path at `0x470fc`.
- That non-authenticated path rejects VMIDs below 64 at `0x47100`–`0x47104`,
  eventually returning raw RM error 6 at `0x47324`.

Thus the tested public allocation/configuration route cannot simultaneously
satisfy this firmware's allocation and unsigned-image initialization policies.
This is not a remaining DTB-padding or physical-contiguity issue. It does not
prove that every possible firmware interface is unusable; the authenticated
QTVM route is separate and has not passed SCM assignment/authentication.
Changing the Linux UAPI or implementing a KVM facade would not remove this
firmware check. Firmware replacement, flashing Qualcomm partitions and disabling
security policy are not part of the permitted recovery strategy.

The public RM log request (`0x00000005`) also returns raw error -1
(`-EOPNOTSUPP`) on this firmware. Do not rely on it for diagnostics.

QEMU TCG remains a non-destructive alternative for Linux guest/device-model
bring-up while the hardware-virtualization restriction is investigated. TCG
emulates the guest CPU; a TCG boot must not be reported as Gunyah or KVM success.

### Guard private firmware discovery on generic guests

Running the port kernel as a QEMU `virt` guest exposed an unconditional SMC in
`qcom_hyp_bootinfo_init()`: the guest panicked with an undefined instruction
before reaching init. The host tablet remained unaffected.
`gunyah-qcom-runtime-overlay-platform-guard.patch` restricts that private
firmware-discovery call to the verified `samsung,gts9uwifi` machine compatible.
The build script applies the guard to both fresh and reused source trees.
This correction is generic port hygiene, not a macOS-only workaround.

The next boot exposed the same issue in the Qualcomm platform-hook UUID query.
`gunyah-qcom-platform-scm-guard.patch` requires a probed SCM provider before
issuing that SMC. SCM initializes at the subsystem initcall level, before the
platform-hook module/device initcall. The guarded hook was also loaded and
unloaded on the real tablet, and the VM/memory/vCPU non-starting smoke passed.

With both guards, the port kernel booted to the Ubuntu initramfs BusyBox shell
under QEMU 8.2.2 TCG on the physical tablet. The shell reported `aarch64`,
mounted procfs, printed the guest kernel version and powered down through PSCI.
One CPU and 512 MiB RAM completed the full process in 5.61 seconds; this is a
smoke-test duration, not a macOS performance prediction. No host disk, network
interface or hardware passthrough was attached. The host kernel/boot partition
was not replaced for these tests.

Guest Image SHA-256 (both guards, exact host configuration retained):
`19fabe5c5e34e6e8137a21736446fd7ac7cf3528134f2055e6b7cf91fb9a4b84`.

The bounded regression harness is `scripts/test-qemu-tcg-linux.py`. Run it as
an ordinary user with an ARM64 Linux Image and Ubuntu initramfs containing
BusyBox `/bin/sh`, the usual shell utilities, and `/usr/bin/poweroff`:

```sh
python3 scripts/test-qemu-tcg-linux.py --kernel /path/to/Image \
  --initrd /path/to/initrd --log /path/to/new-test.log
```

The log must not already exist. Success requires guest-produced markers,
`aarch64`, successful procfs commands and guest poweroff, not merely QEMU exit
code zero (which also occurs with `-no-reboot` after a guest panic).

Runtime9 boot SHA-256:
`c0f3d7bd8066acb688ea0bb6224b90d011b71a5bf64fe36edd1394d5aa4ee23a`.
Unchanged base DTB SHA-256:
`613b3bb7729d55d1c60aaeda348a098163b79aed1efbf24cdcc582ff0d58ccc4`.
Local evidence: `gunyah-lab/cma-smoke-latest.log`,
`cma-route-share-latest.log`, `cma-route-share-ftrace.log`, and
`cma-route-share-kernel.log` on the tablet.
