# NPU release validation

This matrix defines the seven checks used to decide whether the SM8550 Hexagon
support is ready for normal use. A pass means it was exercised on the physical
Galaxy Tab S9 Ultra, not inferred from a successful build.

| Area | Acceptance condition | Current evidence | State |
| --- | --- | --- | --- |
| Long soak | Repeated real HTP inference, shared-client transitions, idle-wake checkpoints, no memory or kernel failure | One CLIP process completed 50,000 two-input/two-output QNN executions over 35 min 45 s; client-transition tests and teardown checks also passed | Pass |
| Native idle wake | A session remains usable after the firmware idle timeout | The 250 ms power-vote keeper sustained the complete 35-minute CLIP run and model transitions | Pass via managed workaround |
| Suspend policy | Deep suspend does not bounce, corrupt UFS or retain stale NPU allocations | Board-scoped UFS, IPCC and VCM fixes passed 31.2 s, 112.2 s and 259.2 s physical cycles with IRQ 21 and zero PM failures. An active session is recycled only after resume and returned HTP to service automatically | Pass |
| Power and thermal | No thermal runaway, throttling failure or unsafe battery drain under sustained inference | The 50,000-run CLIP soak stabilized below 68 °C while charging; an independent 75 °C watchdog remained armed and never intervened | Pass |
| Generic graph runtime | Typed multi-input/output and dynamic ONNX graphs execute only on QNN | Two-input/two-output dynamic Add/Multiply graph passed 25 runs at 0.537 ms | Pass |
| Real multimodal model | A nontrivial vision-language encoder runs on HTP and gives a meaningful result | OpenAI CLIP ViT-B/16 w8a16 ranked the dog image correctly; 10 runs averaged 38.968 ms | Pass |
| Reproducible integration | Drivers, service, runtime and validation tool rebuild from the repository | Current kernel tree rebuilt all signed modules and session binaries; hashes recorded in the status document | Pass |

The operational definition accepts a documented workaround for a firmware power
state that Linux cannot currently restore. It does not relabel that limitation as
a native wake fix. Active inference clients block sleep. The shared service keeps
CDSP ready between models and is stopped automatically when sleep begins.

Run the safe lifecycle suite on the tablet with:

```sh
sudo gts9u-validate-npu
```

It performs ten independent inference clients in one hardware session by default,
checks that the managed service is ready,
executes 1,000 HTP operations, verifies CDSP shutdown, memory release, writable
storage, temperatures and kernel alerts. It never enters system suspend and never
changes the boot target. The latest shared-session physical run passed ten clients
and 1,000 HTP executions in 17 seconds, with zero kernel alerts and 20 KiB of
shared-memory growth after full teardown.

CDSP firmware does not make a stopped GLINK transport reliably reusable. Two
restarts passed with a 60-second interval, but an extended test failed on the
fourth firmware boot, so a delay alone is not presented as a fix. Ordinary model
clients now share one hardware session for the boot and release their own model
processes immediately. That path passed 1,000 direct HTP executions followed by
Qwen 3.5 2B, Gemma 3 4B and Qwen 3.5 9B, all on HTP, without restarting CDSP.
After the final service stop, CDSP was offline, DMA-heap module references were
zero, available memory recovered to 13.7 GB and root remained writable.
Individual inference clients hold a sleep block only while a graph is executing.
The base session may remain active while the tablet enters deep suspend. The
firmware resets FastRPC during that sleep, so the system-sleep hook leaves CDSP
untouched before PSCI, then recycles and asynchronously restarts the session
after resume. The empirically required 60-second transport-settling interval is
enforced without delaying the lock screen. The recovered session completed 100
HTP executions; its later teardown left CDSP offline and shared memory 12 KiB
below the pre-stop reading.

A larger bounded run passed 100 successive clients and 10,000 HTP executions in
85 seconds. Peak CDSP/CPU temperatures were 40.6/44.2 °C, the kernel recorded no
alerts, shared memory changed by 40 KiB and DMA references returned to zero.
OpenAI CLIP then passed ten two-input/two-output runs at 40.66 ms, followed in the
same hardware session by Whisper tiny producing the expected JFK transcript.

The long real-model soak used profiling-free mode to avoid creating a multi-GB
ORT trace after exclusive QNN placement had already been verified. OpenAI CLIP
completed 50,000 executions in 2,145.4 seconds (42.91 ms each), with two inputs,
two outputs and CPU fallback disabled. CDSP/CPU stayed below 68 °C. Final teardown
returned CDSP offline, `system_heap` references to zero and available memory to
13.7 GB; root ext4 remained writable with no UFS, I/O or kernel alert.

Rapid process creation exposed a downstream DSP limit at the 48th FastRPC/QNN
client; adding two seconds between opens did not change it. The user frontends
therefore count hardware clients under a separate render-group lock and refresh
the idle CDSP at 40, leaving eight slots of headroom. Concurrent active clients
still share the session. A forced threshold test stopped and restarted CDSP,
reset the counter to one, completed another CLIP inference and then returned all
DMA references to zero. This policy is model-independent.
