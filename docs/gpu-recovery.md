# GPU freeze and combined GPU/UFS candidate, 2026-09-09

## Physical failure

The owner reported an illuminated, unresponsive screen. Wi-Fi and SSH still
worked. The tablet ran kernel `7.2.0-rc3-dirty` build 8 with Mesa
`25.2.8-0ubuntu0.24.04.2`. Root remained `rw,noatime`, about 7.8 GiB of memory
was available, and the local ordinary-suspend safeguard was still installed.
This capture is a GPU recovery failure, not another demonstrated UFS failure.

The first GMU bandwidth-vote response timeout appeared at monotonic time
4704.977, followed by hangcheck recovery. Later failures culminated at
8872–8879 seconds in a fault from the ChatGPT GPU process, a CP translation
read at IOVA zero, and a preemption timeout. This identifies a failing submit,
not the cause of the earlier GMU failures or proof of an application bug.

The blocked kernel stacks establish the recovery dependency:

| Task | Blocked path |
| --- | --- |
| GPU recovery worker | `recover_worker -> a6xx_recover -> runtime_suspend -> a6xx_gmu_stop -> a6xx_gmu_set_oob`, waiting for `fault_coredump_done` while recovery holds `gpu->lock` |
| SMMU fault IRQ thread | `adreno_fault_handler -> msm_gpu_fault_crashstate_capture`, waiting for `gpu->lock` before completing the fault capture |
| GNOME Shell | `adreno_get_param -> rpm_resume`, waiting for GPU runtime PM |
| GPU submission workers | Waiting for the same GPU lock |

GPU runtime status remained `suspending`. The
[upstream review of the completion wait](https://www.mail-archive.com/freedreno@lists.freedesktop.org/msg39108.html)
also explicitly raised this lock dependency. The separate memory-reclaim
deadlock fix is already present in this source and does not address these
captured stacks.

Logs and stacks were saved on the tablet under
`/var/lib/gts9u-diagnostics/gpu-freeze-20260909T134554Z/`, with a copy in the
PC's ignored `work/gpu-freeze-diagnostic.tar.gz` and
`work/gpu-blocked-stacks.txt`. Do not publish raw process command lines or
GPU memory dumps. The owner authorized reboot; normal reboot was requested
after syncing, but SSH did not return during preparation. Physical recovery
was requested. No experimental kernel has been flashed.

## Candidate change

`msm-adreno-bound-fault-coredump-wait-gts9u.patch` changes both the GMU OOB
and HFI response loops. Successful transactions retain their existing path.
After a transaction times out while a fault capture is pending, it waits
at most one second for that capture and permits at most one transaction
retry. If capture cannot finish, the existing timeout error propagates to
the recovery code. Repeated faults cannot restart the wait indefinitely.

This bounds the demonstrated deadlock path; **hardware recovery and the
initial GPU fault remain unvalidated**. It does not disable acceleration,
change Mesa, alter clock tables, or claim to eliminate all GPU hangs.

Default builds do not enable the candidate. Use
`GPU_FAULT_WAIT_EXPERIMENTAL=1` to opt in through the kernel build recipe or
`scripts/stage-gpu-recovery-experiment.sh`. Default staging rejects a tree
with the candidate already present. Repeated opt-in verifies the complete
two-file patch; partial application is rejected. Reverse verification uses
`patch --force` so GNU patch cannot silently change direction on one file.

`scripts/test-gpu-recovery-experiment.py PRISTINE_ADRENO_DIRECTORY` stages
the patch and compiles the actual two retry loops with mocked MMIO and
completion operations. Five cases per loop passed: immediate success,
timeout without pending capture, capture blocked on the recovery lock,
successful retry, and recurrent faults exhausting the retry budget.
Default/repeated/stale/partial staging checks also passed. These are
control-flow tests, not a physical GPU fault-injection test.

## Combined build for the next test session

The three incoming commits through `66c832a` were fast-forwarded into the
local repository. The earlier kernel #9 UFS candidate and its #8 backup
were found and their recorded hashes verified before building on that work.

The new #10 combines **only the two-file GPU patch and the existing opt-in
UFS PCS reset candidate**, on the existing #8 performance/fingerprint base.
Source and objects are still at
`/root/ubuntu-gts9u/build/linux-src-performance-20260908` and
`/root/ubuntu-gts9u/build/linux-performance-20260908` in WSL Ubuntu.
They now contain both experiments; neither directory is a pristine #8 tree.

Backups, compile log, and new outputs are preserved in
`/root/ubuntu-gts9u/build/gpu-ufs-combined-20260909.GhW28n/`:

- `before/` preserves the previous #9 Image, vmlinux, System.map, config,
  Module.symvers, and both unchanged GPU sources.
- `candidate-kernel10/` contains Image, Image.gz, vmlinux, System.map and
  version metadata. Build uses LLVM 22, eight jobs, `LOCALVERSION=-dirty`,
  `KBUILD_BUILD_VERSION=10`, and fixed build timestamp
  `Wed Sep 9 16:00:00 CEST 2026`.
- Configuration, Module.symvers, signing key and certificate hashes were
  checked unchanged after compiling. No modules or keys were replaced.

| Artifact | SHA-256 |
| --- | --- |
| Kernel #10 Image | `2105964b0e7b1cdb89da621793e298e8cc8a0d8651eb80839dfccaf767e58fcc` |
| Kernel #10 Image.gz | `2fd64e419667e766b109b10662394fbc83e151e462fe295011240007aec1d594` |
| Packed experimental boot image | `b193714fea21c4d0aa926c89d0e9a77403c6cfe5286d37480c958353b4b8a9cc` |

`scripts/prepare-gpu-ufs-kernel10-boot.py` reproduces the packed candidate
from the audited #8 boot and #10 Image. It checks both input hashes,
preserves the appended DTB and all boot header fields except kernel size,
and verifies the existing unsigned AVB hash-footer format. The output is
`artifacts/boot-gpu-ufs-kernel10-experimental.img`, 100663296 bytes. It has
**not been installed** and is not itself a RAM-root diagnostic image.

## Pending physical acceptance

Keep ordinary suspend disabled until the combined candidate passes storage
validation. First establish a recovery path and prepare a diagnostic RAM-root
with all internal UFS filesystems unmounted. Preserve the current Ubuntu boot
set and do not repurpose the owner's WINPE microSD. The packed boot above
alone still uses the installed normal-root ramdisk, so it does not provide
that protection.

In one supervised session, first test repeated real deep-suspend/RTC-wake
cycles from RAM-root and UFS reads; a platform PM test is insufficient.
Only after that succeeds, test normal-root reads/writes, Wi-Fi, display,
brightness, fingerprint and lid/button/idle suspend. Exercise the desktop
with its usual GPU clients and capture any renewed GMU timeouts, faults,
stuck runtime-PM transitions or uninterruptible workers. A controlled GPU
fault-recovery test must show that recovery returns, not merely that an idle
desktop boots. The initial GMU timeout may need a further fix even if the
permanent deadlock is eliminated.
