# Experimental SPSS interrupt bridge

This out-of-tree module supplies `/dev/qsee_ipc_irq_spss` for the SM-X910 SPL
listener (`0xb000`). The stock device tree routes it to IPCC client **16**,
signal **1**, rising edge. Signal 0 belongs to SPSS GLINK and is not interchangeable.
The node is root-only and allows a single reader. `poll()` acknowledges a pending
IRQ, matching the stock bridge; it exposes no secure memory or key material.

Build against the existing experimental kernel:

```sh
bash scripts/build-spss-irq-module.sh
```

The script builds only this module and signs it using that kernel build's existing
key. It does not rebuild or flash a boot image. Before manually loading the result,
check that `modinfo -F vermagic` matches `uname -r` and its signer is trusted by the
running kernel. The validated build used Linux `7.2.0-rc3-dirty` under lockdown.

Device package **2.46** embeds the matching signed module and loads it through
the boot-only `ubuntu-gts9u-fingerprint-secure.service`. The native owner
registers the global SPL listener before initializing the Keymaster DMA context
and restoring authenticated HwVault credentials. A full Ubuntu reboot has
validated automatic startup and a subsequent fprintd Claim without manual
initialization. Enrollment and both saved-print matching paths were physically
validated before this boot; the user subsequently confirmed post-boot login
and resume, with secure matches for both saved slots recorded in the journal.

The bridge still lacks SPSS subsystem-reset notification (`POLLRDHUP`). The
supervisor withdraws readiness on observed remoteproc state loss or child exit,
but does not attempt in-place recovery or claim to detect every fast SSR. SPL
polls remain bounded to five seconds. Only this boot owner may own the listener;
normal fprintd must not enable `EL721_QIS_DIAGNOSTIC`. Do not stop or unload the
running SPSS transport to retry a failure; use a controlled full Ubuntu reboot.
