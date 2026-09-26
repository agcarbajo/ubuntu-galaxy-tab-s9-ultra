# Virtualization on the SM-X910

## Scope

The current reusable virtualization path targets Qualcomm Gunyah, not native
ARM KVM. Samsung's
firmware already owns EL2 and runs Ubuntu as the primary VM, so Linux correctly
reports that KVM hyp mode is unavailable. The port exposes the firmware
Resource Manager through `/dev/gunyah` and builds the VM, vCPU, memory,
ioeventfd and irqfd interfaces into the kernel. A separate KVM-on-Gunyah RFC
can delegate from EL1, but its firmware requirements are not met here; see
the source and dispatcher audit below.

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

Directly issuing Gunyah object-creation hypercalls is not a demonstrated
bypass. The [public Gunyah API](https://github.com/quic/gunyah-hypervisor/blob/develop/docs/api/gunyah_api.md)
requires existing Partition and CSpace capability IDs to create objects, and
the [project's changelog](https://github.com/quic/gunyah-hypervisor/blob/develop/CHANGELOG.md)
states that RM controls the rights to create secondary VMs. The live SM-X910
`/hypervisor` device-tree inventory publishes the HLOS identity, watchdog and
RM RPC queues, not an owner-visible partition-creation capability. **Inference:**
without separately demonstrated donated rights, replacing `GH_CREATE_VM`
with raw HVCs does not make HLOS the privileged RM. No object-creation HVC was
issued as a probe.

The public RM log request (`0x00000005`) also returns raw error -1
(`-EOPNOTSUPP`) on this firmware. Do not rely on it for diagnostics.

QEMU TCG remains a non-destructive alternative for Linux guest/device-model
bring-up while the hardware-virtualization restriction is investigated. TCG
emulates the guest CPU; a TCG boot must not be reported as Gunyah or KVM success.

### Android protected-VM alternative and live image verification

The [Snapdragon pvmfw guide](https://github.com/polygraphene/gunyah-on-sd-guide/blob/main/PVMFW.md)
describes a protected guest boot path distinct from QTVM. Its published test
environment is a Lenovo Snapdragon 8 Elite tablet; its recommendation for
earlier Snapdragon generations is not proof of compatibility with this Samsung.
Qualcomm likewise distinguishes Android firmware-verified guests from
[QTVMs authenticated by TrustZone](https://www.qualcomm.com/developer/blog/2024/08/learn-about-gunyah--qualcomm-s-open-source--lightweight-hypervis).

The port's `GH_VM_ANDROID_SET_FW_CONFIG` selects authentication mechanism 2.
Before VM initialization it requires RM `VM_SET_FIRMWARE_MEM` (`0x56000032`).
Read-only inspection of this Samsung RM's nonzero-client dispatch follows that
message to the unsupported-message response, raw RM -1. This is **static
evidence**, not a newly issued live RPC. The private hash-gated policy checker
now verifies 35 instruction checkpoints, including this dispatch path. An
in-guest `pvmfw` rebuild or different guest AVB signatures cannot supply a
missing host RM message handler.

A fresh read of the first 10 MiB of `/dev/disk/by-partlabel/hyp` on 2026-09-08
produced SHA-256
`dc03857f02055531c221476fa68e6e76006797c20b8e884a1ebd01cee3043b52`,
not the archive hash quoted above. This difference was investigated before
reusing the analysis: all outer ELF and embedded RM `PT_LOAD` bytes are
identical, and the 981 differing bytes are outside those loadable segments.
All 35 checkpoints pass against **both** complete, hash-pinned inputs.
This verifies the current partition copy, not an independent dump of EL2 RAM.
The firmware bytes and inspection artifacts remain private.

The same live read-only inventory found `/dev/gunyah`, no `/dev/kvm`, and no
`pvmfw`-named DT node/property or partition in the inspected inventories.
That absence alone would not establish impossibility; the missing RM handler
is the more specific obstacle. No partition, kernel, module or service was
changed for this audit, and the host health/boot-image checks passed.

The remaining authenticated QTVM branch must be investigated separately:
the existing VMID 45/PAS 28 test fails SCM memory assignment and has never
reached successful guest authentication. Neither this branch nor a
KVM-compatible API is a demonstrated hardware execution backend yet.

### Authenticated input audit and hardware-backend stop condition

The stock Samsung source archive's `gh_secure_vm_loader.c` requests a
`<vm-name>.mdt`, reads Qualcomm authentication metadata, loads the image
segments and supplies the metadata's actual offset/length. Its `gh_main.c`
then invokes `VM_AUTH_IMAGE` with the PAS ID before `VM_INIT`. The earlier
QTVM probe supplied a raw Linux Image plus an initramfs, not such an
authenticated image. Its SCM failure must not be described as a failed test
of an otherwise valid QTVM guest, or as evidence that fixing SCM alone would
enable arbitrary Linux/macOS execution.

On 2026-09-08 the live firmware-directory/name inventory found no `trustedvm`,
`cpusys`, `pvmfw` or `qtvm` files. The archived Samsung `NON-HLOS.bin` contains
`cpusys_vm` components but no `trustedvm`-named entry. The stock DT assigns
`cpusys_vm` VMID 50/PAS 35 and the reserved `0x80a00000` region; its image
identifies itself as CPUSYS-VM, not a generic Linux guest image. It was only
inspected offline and was not loaded, authenticated, started or modified.
This inventory does not establish the contents of every possible external
firmware release or an OEM's signing policy.

There is currently **no demonstrated or identified compatible hardware CPU
route for an owner-supplied guest on this installation**:

| Route | Unresolved requirement or verified restriction |
| --- | --- |
| Native KVM | Ubuntu lacks access to EL2; `/dev/kvm` is absent. |
| Generic Gunyah | The tested VMID allocation and unsigned initialization policies conflict. |
| Android protected VM | This RM lacks the required firmware-memory RPC handler. |
| QTVM | SCM assignment fails and no compatible authenticated generic-guest image is available. |

Resuming hardware guest bring-up needs new evidence: for example, a supported
device-compatible firmware configuration that permits owner-supplied guests,
or an accepted QTVM boot chain capable of launching the intended payload.
Neither is presently available. Replacing Qualcomm firmware, changing system
VM roles, or assuming another manufacturer's image is interchangeable is not
a validated recovery plan. TCG results cannot satisfy this stop condition.

### KVM-on-Gunyah RFC and community reports (2026-09-08)

Linaro's [KVM-on-Gunyah RFC](https://www.spinics.net/lists/kvm/msg375545.html)
is a real hardware-backed design: KVM runs at EL1 and delegates guest execution
to Gunyah. It does not require Linux to own EL2. The inspected
[source revision](https://github.com/karim-manaouil/linux-next/commit/81e88bfca90c73cb2d754672b4b538e7e09edea8)
is pinned, not an assumption that any ordinary KVM build can do this.
Its VM setup requires RM boot-context (`0x56000031`), demand-paging
(`0x56000033`) and address-layout (`0x56000034`) messages as well as VM_INIT.

An offline ARM64 dispatcher test using Unicorn 2.1.4 executed unmodified
loadable RM code from both hash-pinned firmware inputs described above.
ALLOC and TIME_BASE reached their expected handlers (stopped before their
bodies). Each of the three RFC messages and pvmfw's `0x56000032` reached
the unsupported reply with raw error -1. All six cases passed on each input.
The test starts after the PAC prologue, stubs only diagnostic printf and
intercepts the reply call; it neither runs the full RM nor sends live RPCs.
This corroborates the dispatch restriction, not successful hardware execution.
Porting this RFC unchanged would therefore not resolve this installation's
firmware contract. A legacy adaptation would still need to resolve VM_INIT.

The user's [Tab S9 Ultra issue](https://github.com/quic/gunyah-hypervisor/issues/24)
was checked including all 24 comments available on this date. It contains
failed Tab S9 VM creation reports, not a confirmed working configuration.
Qualcomm's comment also distinguishes its public hypervisor source from
firmware deployable on commercial devices. A failed `cat /dev/gunyah` is not
a meaningful VM test: the device is controlled through ioctls.

The pvmfw guide's author explicitly says in the
[OnePlus 11 discussion](https://github.com/polygraphene/gunyah-on-sd-guide/issues/1#issuecomment-3015616428)
that they had not tested an 8 Gen 2 device. Later comments identify an older
ioctl interface on those devices. This is distinct from our post-CONFIG RM
failure; fixing a userspace ioctl mismatch does not supply absent RM handlers.

There is a more relevant positive [Galaxy S24 / SM8650 report](https://github.com/polygraphene/gunyah-on-sd-guide/issues/5)
with linked source, but not evidence for SM8550. Its inspected changes are
[vmalloc fallback for large auxiliary arrays](https://github.com/Andy312432/android_kernel_samsung_sm8650_gunyah/commit/3d8767092fa186b77dfcbc5fd14b53ae17b04bb2)
and [SCM VMID handling](https://github.com/Andy312432/android_kernel_samsung_sm8650_gunyah/commit/b2ffff284b1f8b6cd79c280fb746b27fb6f0cbae).
The latter derives the share source from the caller's RM VMID and retains
HLOS as reclaim destination. These changes do not add RM firmware handlers or
change VM authentication policy. Our small contiguous generic test already
passes memory transfer and CONFIG before failing INIT. Do not substitute S24
firmware, change system VM roles, or copy its memory-pressure workarounds into
release defaults on the strength of that report. None of these reports
demonstrates macOS ARM or a macOS accelerated graphics driver.

### One UI firmware provenance and lifecycle-gate audit

The locally retained hybrid One UI 8 package
`BL_X910XXS5DZA1_con_abl_de_CYG1.tar` has SHA-256
`99cb28f6bc323111ebb38d287d3394e0638ed4cf8ac5ace653b524dc70d1fdce`.
Its extracted, decompressed `hypvm.mbn` matches the live 10 MiB partition copy
**exactly**, SHA-256 `dc03857f02055531c221476fa68e6e76006797c20b8e884a1ebd01cee3043b52`.
The preserved older ABL and the current hypervisor are therefore distinct:
the host is not simply waiting for that available One UI 8 hypervisor update.
Preserve the working hybrid boot chain used for the unlocked installation.
This comparison was entirely offline; the package was not flashed.

Additional private Unicorn tests exercise 26 narrowly bounded gate cases on
each pinned input (52 passing cases total):

- Auto allocation with synthetic single-free-bit pools selects 45 or 63,
  while explicit 64, 65 and 65535 are rejected; empty pools reject allocation.
- The successful-CONFIG tail selects state 1 for auth 0, but state 6 for auth
  1 or 2. The INIT state gate accepts only state 1 in the tested lifecycle.
- The unsigned platform gate rejects VMID 45 and 63; synthetic VMID 64
  reaches the next unsigned branch. Auth 1 selects the authenticated branch.

These tests use synthetic allocator/VM data, stop before constructor,
notification or platform-initialization bodies, and stub diagnostic printf.
They do not allocate live VMIDs, authenticate an image, or start a guest.
Together with the existing live failure, they show why choosing a different
unsigned VMID or merely enabling QTVM authentication is not a demonstrated fix.
No claim is made that synthetic state 1 proves an authenticated image exists.

The newer [DroidVM project](https://github.com/Droid-VM/DroidVM) documents
Qualcomm support starting at SM8650; its
[UEFI guest firmware](https://github.com/Droid-VM/edk2-gunyah/blob/droidvm/README.md)
lists SM8750 and SM8850 as tested SoCs. These are useful later-stage VMM/guest
references, not evidence that they replace the incompatible SM8550 RM contract.

Further physical testing of a **different hypervisor firmware** would require
writing outside the ordinary Ubuntu boot image, notably the `hyp` partition.
That is outside the user's current unattended-flashing authorization. No
compatible replacement has been validated; this is not a recommendation to
flash another model's firmware or to upgrade the complete BL package.
An owner-usable authenticated QTVM boot chain would be an alternative, but
none has been identified in the audited inputs. The hardware CPU and GPU
acceptance criteria remain unmet.

### Cross-check against DroidVM and community issues (2026-09-26)

This check pinned DroidVM at `5c896915789294e3dbb9af81d6a53ee5f436887b`
and the pvmfw guide at `61ac570c2d467274d1d7d73605dcc685af6945b8`.
DroidVM's `VMHypervisor` selects Gunyah when `/dev/gunyah` exists; its
`gunyah.yaml` SoC table omits SM8550, but that table supplies capability
defaults and is **not** a firmware enable switch. Adding SM8550 there would
not make RM accept `VM_INIT`. The crosvm backend normally passes
`--hypervisor gunyah --protected-vm-without-firmware`; it offers
`--protected-vm` and a pseudo-unprotected mode as alternatives. The latter
changes guest/host memory sharing **after** VM setup; it is not a way around
Samsung's VMID allocation and initialization policy. The project's
[UEFI firmware](https://github.com/Droid-VM/edk2-gunyah/blob/droidvm/README.md)
has only SM8750/SM8850 listed as tested.

The [pvmfw instructions](https://github.com/polygraphene/gunyah-on-sd-guide/blob/main/PVMFW.md)
say 8 Gen 2/3 need `--protected-vm`, but their demonstrated host is actually
an 8 Elite Lenovo. Signing a *guest* kernel using its embedded AOSP test key
only addresses pvmfw's **later** AVB verification, once the protected VM and
pvmfw have already started. It cannot replace the unsupported host-side
`VM_SET_FIRMWARE_MEM` message observed in DZA1 and EZI2. In the guide's
[OnePlus 11 / 8 Gen 2 issue](https://github.com/polygraphene/gunyah-on-sd-guide/issues/1),
both protected modes fail to create a VM; the author explicitly says this
generation was untested and suggests its older ioctl interface as another
obstacle. That ioctl mismatch is distinct from our later RM failure.

The [Galaxy S24 / SM8650 success](https://github.com/polygraphene/gunyah-on-sd-guide/issues/5)
required host kernel memory-array and SCM VMID fixes plus huge pages; it
shows a real Samsung Gunyah route on different firmware, but those patches
do not add the missing SM8550 RM handlers. DroidVM's
[8 Gen 3 failure report](https://github.com/Droid-VM/DroidVM/issues/4)
similarly reaches RM `VM_INIT` before a memory/start failure. Qualcomm's
[Tab S9 issue](https://github.com/quic/gunyah-hypervisor/issues/24)
contains failed VM creation, and Qualcomm says its public hypervisor source
omits the commercial-platform BSP. Building or replacing it from that repo
is therefore not a drop-in SM-X910 solution.

These reports establish *technical possibility on some Snapdragon devices*,
not a working SM-X910 configuration. A discriminating next test, if Android
is made available later, is a **read-only** inventory of its AVF feature
properties, pvmfw image source, `/dev/gunyah` UAPI and RM/driver logs. It
must not be interpreted as permission to flash `hyp`, modify the Android
system, or run a VM that could trigger the known RM/SCM reset behavior.

#### Stock Android cross-check (2026-09-26)

The owner booted stock Android and granted root for read-only inspection over
ADB. It reports SM-X910, Android 16 and kernel
`5.15.178-android13-8-32143072-abX910XXS5DZA1`. Reading the first 10 MiB
of its `hyp` partition gives SHA-256
`dc03857f02055531c221476fa68e6e76006797c20b8e884a1ebd01cee3043b52`:
**the same firmware** inspected from Ubuntu. The Android host has
`/dev/gunyah` but no `/dev/kvm`. Its `ro.boot.hypervisor.protected_vm.supported`
and `ro.boot.hypervisor.vm.supported` properties are unset; `pm list features`
does not list an AVF/virtualization feature; `service list` has no
`virtualizationservice`; and the mounted `com.android.virt` APEX has Java/JNI
resources but no `bin/crosvm` or `bin/vm`. No `pvmfw`-named partition or
image was found in the inspected Android partition and filesystem inventories.
The loaded vendor `gunyah` module exposes `gh_vm_ioctl_set_fw_name` and
`gh_vm_ioctl_get_fw_name` symbols, while `gh_rm_drv` exports
`gh_rm_vm_auth_image`. The mounted firmware directory contains signed
`cpusys_vm` and `oemvm` images, but no general-purpose guest or pvmfw image.
These symbols and images are consistent with the authenticated QTVM path;
they are not evidence that a caller may supply an arbitrary guest.
These negative inventories do not prove every possible private interface is
absent, but they rule out following the published AVF/pvmfw commands as-is on
this stock Android installation. No VM was created or started and no Android
file, service or partition was changed.

### Early EL2 switch research (2026-09-26)

Qualcomm's [U-Boot v4 series](https://www.mail-archive.com/u-boot@lists.denx.de/msg579504.html)
introduces an early TrustZone SMC (`0x02000121`, parameter `0x23`, exit-Gunyah
selector `1`) that asks to exit Gunyah and enter EL2, potentially allowing
native KVM instead of a Gunyah RM guest. Crucially, the series explicitly
targets **Dragonwing** platforms and enables the option for **QCS9100**, not
SM8550. The [v4 implementation](https://www.mail-archive.com/u-boot@lists.denx.de/msg579505.html)
runs at U-Boot entry before normal EL register setup. Its availability had
not been established for Samsung SM-X910, nor has an owner-controlled U-Boot
entry been verified on this boot chain. Calling an exit SMC
from a running Ubuntu/Android kernel is not equivalent and risks terminating
the active hypervisor and its system VMs. It has **not** been attempted here.

The live firmware now gives a stronger, device-specific answer to the
*availability* question. The installed kernel already has `CONFIG_KVM=y` but
logs `kvm [1]: HYP mode not available`. A temporary copy of the existing
`gts9u-tzlog` diagnostic module was rebuilt using the **matching** WSL
`Ubuntu` object tree, `/root/ubuntu-gts9u/build/linux-release-1.2.0`, and
Clang 22. Its `.config` SHA-256
`67930b1997348bca2d8f1210667fa58b848872f2b1611bf29a84ac4969aaa651`
equals `/boot/config-7.2.0-rc3-dirty` on the tablet, and its build certificate
subject-key ID `43e6c46f99336df9048b40081adf38b1e40d6477` is the one
announced by the live kernel. The signed diagnostic module SHA-256 was
`999cbcbf3a682fbefb773bed651253c17213882423a9275b68b89ae3ff2778bc`.
No private signing key or module binary is checked into Git.

The module issued only Qualcomm SCM's information-service
`IS_CALL_AVAIL` query (service 6, command 1, one value argument), **not** the
exit SMC itself. Querying the known working PIL `PAS_IS_SUPPORTED` service
(`0x02000207`) returned success with availability `a1=1`, establishing a
positive control for this query path. Querying the proposed early-EL2 service
(`0x02000121`) returned success with availability **`a1=0`**. A query of the
diagnostic-log call (`0x02000602`) also returned `a1=0`, so it was not used
as the control. The result proves this stock TrustZone does not advertise the
QCS9100 exit service to HLOS through the standard availability interface; it
does **not** prove every private firmware mechanism absent. The temporary
module and tablet `/tmp` copy were unloaded/removed. No exit request, reboot,
partition write or guest start occurred; Wi-Fi and GDM remained active.

This is not a usable workaround on the stock SM-X910 firmware. A
boot-image-only U-Boot experiment invoking `0x02000121` is **not justified**
after the negative controlled availability result. Any different EL2 route
would first require device-specific support evidence and a recovery path, and
must account for Samsung peripherals/security services that may depend on
Gunyah. Preservation of Ubuntu, Wi-Fi, fingerprint and normal Android boot
takes precedence over an unvalidated EL2 switch. The stock-firmware Gunyah
and KVM gates above are unchanged.

### SM-X910 EZI2 offline firmware audit (2026-09-26)

The live tablet was checked **read-only** over host-key-verified SSH: it is
the SM-X910 Wi-Fi, runs `7.2.0-rc3-dirty`, exposes `/dev/gunyah` but not
`/dev/kvm`, and its `hyp` partition still hashes to
`dc03857f02055531c221476fa68e6e76006797c20b8e884a1ebd01cee3043b52`.
There was no reboot, partition write, service change or VM start.

Samsung FUS returned the newer EUX version
`X910XXS6EZI2/X910OXM6EZI2/X910XXS6EZI2/X910XXS6EZI2` for `SM-X910`.
The official archive was downloaded to private PC scratch space and only
its BL container and `hypvm.mbn.lz4` were extracted for offline analysis.
The decompressed 10 MiB `hypvm.mbn` SHA-256 is
`83673420c2d7dafe2abb960563b7b13ad6c863bdfef28f35d8f36a1d645c6644`.
No Samsung firmware binary is committed or deployed to the tablet.

`scripts/diagnostics/compare-gunyah-firmware.py` finds three embedded ARM64
ELFs at the same offsets as DZA1; each has changed loadable content, including
the nested RM at `0x1145c0`. Therefore EZI2 needed a fresh policy audit.
`scripts/diagnostics/compare-gunyah-rm-gates.py` confirms that all 35 checked
instructions in the allocation, authentication and firmware-RPC gates are
byte-identical between DZA1 and EZI2. More directly, the hash-pinned offline
Unicorn test `scripts/diagnostics/audit-gunyah-rm-dispatch.py` executes the
EZI2 RM dispatcher prefix with a synthetic HLOS sender: ALLOC `0x56000001`
and TIME_BASE `0x56000030` reach their known handlers; SET_BOOT_CONTEXT
`0x56000031`, SET_FIRMWARE_MEM `0x56000032`, SET_DEMAND_PAGING `0x56000033`
and SET_ADDRESS_LAYOUT `0x56000034` all reach the common unsupported reply
with raw RM error `-1`. The same six-case regression passes on DZA1. The
emulator stops before recognized handlers and stubs only diagnostic printf;
this is not full RM execution or a live firmware call.

EZI2 thus does not supply the missing pvmfw or KVM-on-Gunyah RFC messages in
the audited HLOS path. Flashing it would be a non-boot-partition experiment
with no demonstrated benefit and risks the owner's hybrid unlocked boot chain;
do **not** flash it based on this evidence. The signed QTVM route, CPU backend
for an owner-supplied macOS guest, and macOS GPU acceleration remain separate
unresolved requirements. Generic diagnostics may enter future builds, but
macOS-specific guest assets/configuration must remain installation-local.

The EZI2 `NON-HLOS.bin` FAT image also contains signed `cpusys_vm` and
`oemvm` MDT/segment sets, but no `trustedvm`- or `pvmfw`-named image. An
`oemvm` file is not an owner-supplied guest loader or proof that its signed
payload can boot macOS; this package was inventoried offline only.

An additional read-only check of the locally retained stock `NON-HLOS.bin`
(SHA-256 `1aa9de73c4977ebd65caddd22e3afdba642d8b792f0b4153c9cec4e985f29845`)
found `oemvm.mdt` plus five `oemvm.b00`–`b04` segments. The large `b03`
segment (SHA-256
`db6592747a89d780d0fcf515124432128019bc31cfeba92257b09156a4f5b1c0`)
contains repeated `TEEGRIS_5` identifiers; the matching stock Android
`teegris_oemvm.rc` starts TEEGRIS services. This is evidence that the signed
`oemvm` image is tied to Samsung's security workload, not evidence of a
general-purpose loader for owner-supplied guests. Do not launch a second copy
as an experiment: that could disturb services used by the host. The current
live `/hypervisor` device-tree subtree publishes the HLOS VM identity,
watchdog and RM RPC queues; it does not advertise a separate guest-creation
capability that could avoid the RM lifecycle gate. The latter is a limited
device-tree inventory, not proof that no undiscovered interface exists.

Even a future CPU backend would not solve the display requirement. Apple's
[macOS VM platform documentation](https://developer.apple.com/documentation/virtualization/virtualize-macos-on-a-mac)
describes macOS guests on Apple silicon Macs with a Mac hardware model and
Apple-provided boot loader. Its
[paravirtualized graphics framework](https://developer.apple.com/documentation/paravirtualizedgraphics)
uses a macOS host-side Metal implementation, not an Adreno/Linux one. These
sources do not prove a third-party solution impossible, but they do not
provide an off-the-shelf accelerated graphics path for this Snapdragon tablet.

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
