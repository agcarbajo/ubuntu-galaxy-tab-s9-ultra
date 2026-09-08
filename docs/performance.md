# Galaxy CPU/GPU frequencies and efficiency

The SM-X910 uses Snapdragon 8 Gen 2 for Galaxy (SM8550-AC). Its CPU targets are
2.016 GHz for CPUs 0–2, 2.8032 GHz for CPUs 3–6, and 3.36 GHz for CPU 7. The
Adreno 740 target is 719 MHz. These are factory operating points, with normal
thermal/current limits; they are not frequencies to force continuously.

## Evidence and cause

The physical pre-change kernel on 2026-09-08 exposed:

| Resource | Available maximum | Factory target |
|---|---:|---:|
| CPU 0–2, Cortex-A510 | 2.016 GHz | 2.016 GHz |
| CPU 3–4, Cortex-A710 | 2.8032 GHz | 2.8032 GHz |
| CPU 5–6, Cortex-A715 | 2.8032 GHz | 2.8032 GHz |
| CPU 7, Cortex-X3 | 2.9568 GHz | 3.36 GHz |
| Adreno 740 | 680 MHz | 719 MHz |

The seven lower CPUs reached their respective policy maximum in individual
affinity-pinned CPU tests. CPU 7 topped out at 2.9568 GHz. Under simultaneous
all-core load, the intermediate cluster sometimes reported 2.7072 GHz even
with 2.8032 GHz requested. Thermal/current throttling must remain operational.

`dmesg` reported `cpu cpu7: Voltage update failed freq=3360000`. This is a
missing OPP description: `qcom-cpufreq-hw` reads the firmware's frequency and
voltage LUT, disables the DT OPPs, and re-enables only matching entries. The
reference `sm8550.dtsi` lacks 3.36 GHz. Its 3.1872 GHz node does not describe
the firmware's last boost entry, so the usable maximum falls to 2.9568 GHz.
The board addition supplies the existing top-end LLCC/DDR/L3 bandwidth votes;
the CPU voltage and boost classification still come from the hardware LUT.

Samsung's locally extracted X910 stock `vendor_boot` DTB, SHA-256
`40b5cb5e7b1d0f3c2378559cec462fa391fb8352ae6a05744505e8acad4d8ead`,
describes GPU bin 0 at 719,000,000 Hz with RPMh level 224 (SVS_L2), DDR table
entry 9 (16,500,000 kB/s) and ACD `0x882e5ffd`. The port uses those values.
Do not substitute the ACD values from another Qualcomm board's generic table.
The existing lower GPU OPPs remain available.

[Samsung's specifications](https://www.samsung.com/za/tablets/galaxy-tab-s/galaxy-tab-s9-ultra-5g-graphite-256gb-sm-x916bzaaafa/)
list the marketed CPU speeds as 3.36/2.8/2 GHz.
[Qualcomm's launch announcement](https://www.qualcomm.com/news/releases/2023/07/snapdragon-powers-samsung-s-new-galaxy-lineup-globally)
confirms the Galaxy-specific processor and accelerated GPU in the Tab S9.
The exact GPU electrical parameters above come from this device's stock DT.

## Bootloader-compatible implementation

The release build intentionally pins its ABL-facing base DTB to the previously
validated fingerprint baseline. Editing the board DTS alone does not change
that build. An additional physical check confirmed that changing only the DTB
appended to `boot` leaves the live DT unchanged: ABL uses `vendor_boot` here.
The appended-only test was rolled back to the original boot image.

`kernel/dts/gts9u-performance.dtso` adds only the two OPP nodes.
`scripts/stage-performance-overlay.sh` embeds it in a small built-in board
helper. Its `core_initcall` applies the overlay to Linux's live tree, after
OF initialization and before cpufreq and DRM can consume their OPP tables.
It runs only for `samsung,gts9uwifi`. No firmware RPC, memory ownership change,
Gunyah hook, reserved-memory modification or bootloader DT replacement occurs.
The full board DTS also records the OPPs for a future unpinned build.

The overlay application is transactional and the overlay remains for the boot
lifetime. `CONFIG_OF_OVERLAY=y` is already required by the port's Gunyah
integration. It must be built in; loading this helper after the GPU/cpufreq
drivers probe would be too late.

Two cpufreq fixes are also needed in this kernel:

- `arm-topology-use-boost-frequency-reference.patch` derives the scheduler's
  frequency reference from the complete valid frequency table. At policy
  creation boost is disabled; caching the non-boost maximum left `schedutil`
  unable to request 3.36 GHz even after userspace enabled it. Dynamic scaling
  and policy/QoS limits still apply.
- `cpufreq-recompute-software-boost-limit.patch` recalculates the software
  boost maximum on every transition. Linux 7.2-rc3's table helper preserves
  a pre-existing higher `cpuinfo.max_freq`; without resetting it in the
  software boost handler, disabling boost changed both sysfs flags to zero
  but left the effective maximum at 3.36 GHz. The error path restores the
  previous maximum. This fixes actual Power Saver behavior.

## Desktop policy and efficiency

`ubuntu-gts9u-cpu-boost.service` connects the generic cpufreq boost control to
Ubuntu 24.04's existing Power Profiles daemon:

- **Balanced / Performance:** the firmware boost OPP can be selected.
- **Power Saver:** CPU boost is disabled.
- **Older kernels without the 3.36 GHz boost OPP:** it exits successfully
  without writing any frequency control.

The helper listens for D-Bus changes; it has no periodic polling. A missing or
temporarily unavailable profile property preserves the last selection. With
no Power Profiles daemon owner at startup it defaults to Balanced and watches
for the daemon to appear. An explicit service stop restores its initial boost
setting if nobody has changed that setting since its last update.

This only changes the boost switch. CPU governors stay `schedutil`, GPU stays
`simple_ondemand`, all low-frequency OPPs and CPU idle states remain present,
and cooling devices keep their limits. GPU boost is part of its OPP table and
is not controlled by the CPU boost switch.

The baseline audit also found working energy-aware scheduling, deep CPU idle,
8 GiB of compressed zram ahead of disk swap, and dynamic UFS frequency scaling.
During a 15-second idle sample, total CPU busy time was 3.15% and every core's
deep-idle residency counter advanced. The earlier camera-relay idle fixes are
already installed. There is no evidence here for changing their behavior,
forcing minimum clocks, disabling idle, or altering storage power management.
Battery current while charging measures charge flow, not system power; these
tests do not establish an energy-per-task or battery-life improvement.

## Reproduce the checks

On the build host, using a known-good base DTB:

```sh
bash scripts/test-performance-overlay.sh /path/to/validated-base.dtb
```

This checks OPP properties, repeat application and staging, and that every
other node/property is unchanged. No device is written by that test.

On the tablet:

```sh
python3 scripts/gts9u-frequency-audit.py
python3 scripts/gts9u-frequency-audit.py --exercise --seconds 1.5 --require-galaxy-max
python3 scripts/gts9u-frequency-audit.py --exercise --seconds 2 --workload burst --require-observed-max
powerprofilesctl set power-saver
cat /sys/devices/system/cpu/cpufreq/boost
powerprofilesctl set balanced
cat /sys/devices/system/cpu/cpufreq/boost
```

The audit is read-only unless `--exercise` is explicitly requested; exercise
adds bounded SHA-256 CPU workloads without writing sysfs. It pins each core,
then exercises all eight, sampling requested and hardware-reported policy
frequencies and temperatures. It cools between runs, stops at 75 C by default,
and cleans up its workers. `--require-galaxy-max` checks that the target OPPs
are registered and allowed. For the stricter, workload-dependent requirement
that every core reports its target in its own run, add `--require-observed-max`.
That check may fail legitimately under hardware thermal/current limiting,
even when the requested clock and permitted maximum are correct.
`--workload burst` alternates 12 ms of SHA-256 with 3 ms of idle. During
individual-core tests the observer runs on another core and restores its
original affinity afterwards; sampling on the tested core can fill its idle
gaps and change the result.
The readings are cpufreq policy telemetry, not independent clock metrology.

For an off-screen GPU workload in an existing Wayland session:

```sh
glmark2-es2-wayland --off-screen --size 1920x1080 \
  -b shading:shading=phong:duration=6.0 -b terrain:duration=6.0
```

Sample `/sys/class/devfreq/3d00000.gpu/cur_freq` concurrently. The baseline
reached 680 MHz, with 2,425 FPS in `shading` and 193 FPS in `terrain`, using
Mesa 25.2.8. Those scene results are not a whole-system performance score.

## Physical validation, 2026-09-08

The candidate was built from an independent copy of the active Gunyah
runtime9 source and object tree. Its kernel release remains
`7.2.0-rc3-dirty`, with the identical config and module signing certificate.
Both Gunyah source directories compare byte-for-byte with the original.
The installed modules, `vendor_boot`, `init_boot`, firmware and saved dual-boot
Ubuntu image were not replaced. `/dev/gunyah`, fingerprint device `/dev/esfp0`,
NetworkManager and GDM remained available after the test boots.

The original active boot image is backed up at
`/var/lib/gts9u-kernel-backups/pre-galaxy-frequencies-20260908/boot.img`,
SHA-256 `c0f3d7bd8066acb688ea0bb6224b90d011b71a5bf64fe36edd1394d5aa4ee23a`.
Test images used a five-minute automatic rollback guard until host health
was verified. The guard is disabled after successful validation.

The final running image is kernel build **#7**, boot partition SHA-256
`33643c8c9c4d26da8988d133b1c3b5af8e3999f02cd3e0d40e7fbf12bdfaf811`.
The full per-core burst audit passed with `--require-observed-max`. A separate
continuous SHA-256 audit also observed each target during its own core's run:

| Individually exercised cores | Requested and reported peak |
|---|---:|
| 0, 1, 2 | 2.016 GHz each |
| 3, 4, 5, 6 | 2.8032 GHz each |
| 7 | 3.36 GHz |

With all eight cores loaded together, the intermediate cluster reported
2.7072 GHz and the prime core 2.9568 GHz, despite higher requested clocks.
The maximum sensor reading was 68.6 C in the burst audit and 74.2 C in the
continuous audit. These limits are preserved; peak frequency availability
does not imply that all cores can sustain their maximum simultaneously.

Live profile tests verified Balanced → Power Saver → Balanced, restarting
Power Profiles while in Power Saver, and restarting the bridge in Balanced.
Power Saver produced boost=0 and a 2.9568 GHz prime limit; Balanced produced
boost=1 and a 3.36 GHz limit. The governors remained unchanged throughout.

In a same-boot GPU comparison with the same GDM Wayland compositor, governor,
Mesa version and 1920x1080 off-screen scenes, the cap was changed in ABBA
order and restored afterwards. Each run started below 45 C:

| GPU cap | Shading FPS | Terrain FPS | Observed peak | Peak SoC sensor |
|---|---:|---:|---:|---:|
| 680 MHz, A | 2758 | 200 | 680 MHz | 54.5 C |
| 719 MHz, A | 2980 | 217 | 719 MHz | 64.3 C |
| 719 MHz, B | 2880 | 204 | 719 MHz | 58.1 C |
| 680 MHz, B | 2652 | 199 | 680 MHz | 57.7 C |

This ABBA comparison used build #6, before the final software-boost-disable
fix; its GPU code and OPPs are identical to build #7.
Both 719 MHz runs improved these scenes, with meaningful run-to-run variation.
This is a short validation of the usable GPU OPP, not a battery-life test or
a general application performance guarantee. The earlier baseline used a
different desktop session and is not a controlled comparison with these runs.

After the CPU audits, a longer GPU validation on build #7 reached 719 MHz
but was stopped by the test's 75 C guard (76.1 C at the sampled crossing).
The test terminated its render process. No thermal thresholds or cooling
devices were disabled to make the benchmark finish.

After cooling, a final build #7 run completed both scenes at three seconds
each, reached 719 MHz and peaked at 54.5 C (3232/212 FPS). Its shorter duration
makes it unsuitable for comparison with the six-second ABBA results.
The final 15-second idle sample showed 3.14% total CPU busy time and advancing
deep-idle counters on all eight cores. The profile bridge had consumed 52 ms
of CPU time and about 9 MB of memory. These checks confirm that idle and
dynamic scaling still work; they do not measure battery-life gains.
