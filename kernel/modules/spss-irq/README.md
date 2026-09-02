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

This is **not enabled at boot or included in the normal deployment workflow**.
It lacks SPSS subsystem-reset notification (the stock device reports
`POLLRDHUP`). The current libfprint consumer remains gated by the historical
`EL721_QIS_DIAGNOSTIC=1` option and caps polling at five seconds. A production
listener still needs coordinated SPU startup, cancellation, reset handling and
safe ownership of the Keymaster DMA lease. Do not stop or unload the running
SPSS transport to retry a failed initialization; use a controlled Ubuntu reboot.

Receiving an IRQ proves transport only. Current HwVault restoration still fails
with StrongBox `-40`; this module is not evidence of successful enrollment.
