# NPU status — 2026-09-06

**Real image classification, multimodal embedding, local chat and audio transcription
pass on Ubuntu using the HTP NPU, with an experimental startup and power workaround.**
The generic QNN interface accepts multiple numeric inputs and outputs, dynamic-shape
overrides and Qualcomm AI Hub ONNX exports. OpenAI CLIP ViT-B/16 is the first real
multi-input multimodal model validated through this path. Transformer models from
1.7B through 14B, MobileNetV2, ResNet18 and Whisper have also completed physical
tests. See [the validation matrix](npu-validation.md) for the seven release criteria.

Native CDSP deep-sleep wakeup remains unresolved. A dedicated QNN process renews
the sleep-disable vote while a session is active. Firmware logs show that an
unrenewed vote is reset after roughly 500 ms. Intervals of 500 ms, 1 s, 5 s and
20 s all failed after an idle period; 250 ms passed the bounded 45-second wake
test and is undergoing the long soak. CPU usage at the original 100 ms interval
measured about 0.4% in a short test; this does **not** measure DSP/battery power.
On-demand startup after a fresh Ubuntu boot passes. The user-facing CLI starts
and stops the service automatically, with a logind sleep inhibitor held only
while the session is active. Boot activation is intentionally unnecessary.
System suspend is blocked while inference owns the CDSP and is available after
the last client closes; this policy avoids resuming a live FastRPC session. The
dangerous low-level storage-resume experiment described below is not repeated.

The storage-resume fault is now fixed in the board kernel. A system-suspend-only
reset clears UFS PHY PCS/SERDES state before power-down on `samsung,gts9uwifi`.
With boot SHA-256
`2c802a54fbb8e3a4fd262a1d673bf809de6a70f58daf52f478f800938476699a`,
the tablet resumed from a 56-minute deep-suspend cycle with root ext4 writable,
zero UFS/PHY/I/O/ext4 errors and exact 16 MiB direct-I/O readback. A later clean
reboot also returned to the same kernel with writable storage and no storage
errors. After the NPU soak and teardown validation completed, the temporary boot
failsafe was removed; normal system suspension is enabled again.

Repeated CDSP starts exposed a separate firmware teardown limitation: a restart
can attach to stale GLINK endpoints and fail with a broken pipe. Two restarts
passed at 60-second intervals, but the fourth firmware boot in an extended test
failed, so cooldown alone is not treated as a complete fix. The operational path
now shares one boot-long hardware session across model processes, which is also
how an accelerator runtime normally serves multiple applications. In one physical
session, 1,000 direct HTP executions and three successive GGUF models (Qwen 3.5
2B, Gemma 3 4B and Qwen 3.5 9B) passed. The 9B model loaded all 33 layers through
the windowed HTP path and generated 4.02 tokens/s. Closing each model removed its
large userspace allocation; stopping the shared session returned `system_heap`
references to zero and recovered 13.7 GB available memory.

The base session has only a delay inhibitor and conflicts with `sleep.target`, so
system sleep stops CDSP. Each active ONNX, GGUF or Whisper client obtains its own
block inhibitor through logind. The `render` group is authorized only for this
sleep block and the NPU service. A boot-time monotonic marker enforces a bounded
60-second interval only after an explicit CDSP shutdown; suspended time counts
toward it. The underlying downstream firmware restart defect remains documented,
but routine model switching no longer exercises it.

Long-run validation on boot `32e84ab8-3a9b-49f1-b5c2-f54ba687515c` completed
50,000 OpenAI CLIP QNN executions in 2,145.4 seconds (42.91 ms/inference) with
CPU fallback disabled. The independent thermal watchdog did not fire; sustained
CDSP/CPU readings stayed below 68 °C. Teardown left CDSP offline, zero
`system_heap` references, 13.7 GB available RAM and writable root storage.

A separate churn test found a deterministic downstream DSP resource ceiling:
the 48th rapidly created QNN process fails `qnn_open` with `0x80000406`, even with
a two-second gap. The ONNX, GGUF and Whisper frontends now share a locked client
counter and refresh an idle CDSP at 40 clients, leaving eight slots of headroom.
The threshold path was forced physically: it performed the stop, observed the
60-second firmware-settle interval, restarted, reset the counter and completed a
new CLIP inference. This applies to every model rather than matching model names.

Current physically installed integration hashes:

```
2945466e5b268826c21ad095bba57b2263d3796552d2d63978b3bfcffa46eae6  run-npu-session.py
7c7c7bb6df743110b3329818d45c9e55a2e3447de8455ce99850148dce0b2f12  onnx-run
1ec578537d4d9fe2bd51639f7e63e252ebb1328d6b15ea072795c8dc148f0b4f  gts9u-ai
e149a314c591bbb9fbe06473dcbd485001b4175183b496d9b5b6061af103845c  gts9u-npu-app
dde769b2e3d8289d32c077b560f1ccacda0663ff5efea19c55a47a00341b44f2  gts9u-validate-npu
```

## Model-close memory retention (fixed and tested, 2026-09-05)

The prepared FastRPC module could retain DMA buffers after the last application
closed. The initial report had about 7.0 GiB used with no inference process left,
and 255 `system_heap` module references. This was not just Linux file cache.
An interrupted/timed-out invocation held a user reference while its pending host
reference was only released by user destruction, creating a reference cycle.
Remote references belonging to already-closed files also escaped channel removal.
A debugfs DMA attachment dump exposed a stale device pointer and caused a kernel
Oops; the subsequent shutdown required a forced reboot. Do not use that diagnostic
on a session affected by the old module.

`fastrpc-prepared-cdsp-module.patch` now releases abandoned host references at final
file release, transfers each outstanding remote reference exactly once on reply
or transport removal, and frees interrupted DMA mappings before destroying their
DMA devices. A read/write semaphore allows concurrent sends while preventing
transport removal during a send. This changes request ownership, not model names,
quantization or a fixed amount of RAM; it does not flush the system page cache.
The patch was applied with zero fuzz and reproduced the compiled source exactly.

Physical validation of the signed module
`74461abd341761a50c19ff7ccefff4296db33a2d122efc4aebc21d1bfa7b537c`:

- Before cleanup reboot, complete 4B and 9B chat cycles did not increase the 11
  DMA-heap references left by the earlier diagnostic module.
- A normal reboot returned to Ubuntu, boot
  `545f007e-5dae-4fc7-b398-23a246a1137a`, with zero DMA-heap references.
- Closing the real GTK launcher during startup and during model loading each
  returned the service to inactive with zero DMA-heap references.
- The 9B windowed model loaded 33/33 layers, correctly answered the arithmetic/
  geography check, and returned to zero references when the window closed.
- Closing the window during a separate 9B generation also returned to zero
  references. No new kernel Oops, refcount warning or filesystem I/O error was
  found in this boot; the filesystem remained read/write.

The final system had about 3.9 GiB used and 10 GiB available, with Chrome and the
desktop still running. File-cache memory may remain reclaimable after model close;
`MemAvailable` and absence of retained DMA allocations are more informative than
requiring `MemFree` to match the pre-load reading. Existing GLINK cleanup timeout
and remote unmap messages still occur; this fix does not claim to resolve those
or CDSP deep-sleep wakeup. These are bounded teardown tests, not a long soak test.
The optional NPU build recipe includes the updated driver; the personal GUI and
models remain outside default image builds.

## Usable inference interface

As the ordinary user in the `render` group:

```sh
gts9u-ai classify /path/to/image.jpg --runs 10
gts9u-ai run /path/to/model.onnx /path/to/input.f32 /path/to/new-output.f32
gts9u-ai run-graph /path/to/model.onnx /path/to/inputs /path/to/outputs \
  --dim batch=1
```

The legacy `run` form accepts one float32 input and output. `run-graph` supports
multiple tensors, numeric ONNX types, multiple outputs, dynamic input shape files
and named dimension overrides. Tensor files use `INDEX-SANITIZED_NAME.raw`; a
dynamic input may include a matching `INDEX-NAME.shape`. It is a generic graph
runner rather than an LLM or speech frontend. Optional `--report NEW_DIRECTORY`
retains logs, ORT/QNN profiles and result JSON. The command rejects CPU fallback
and checks that the execution profile exclusively reports QNN. Concurrent clients
share the service; the last client stops CDSP. A forced deadline failure followed
by a successful inference verified recovery. Polkit grants `render` only start/stop
of this specific service. It does not grant general administrative access.

The isolated model runtime uses ONNX Runtime Android 1.26.0, QNN EP 2.5.0 and QNN
Maven 2.49.0. The older 2.45 runtime remains the separately loaded power keeper.
ORT's unused `libandroid.so` dependency is removed only after auditing imported
symbols. A board-checked public EP-factory adapter supplies Linux FastRPC discovery
to the official Android QNN plugin; actual execution remains in Qualcomm's HTP
backend. All downloads are hash-pinned in `configs/npu/onnx-artifacts.json`.

Build on x86 Linux with Python 3, patchelf and Android NDK r26d:

```sh
python3 scripts/stage-npu-onnx.py --ndk /path/to/android-ndk-r26d \
  --downloads /path/to/cache --output /path/to/new-bundle
# On the tablet, after the base Bionic runtime and session service are installed:
sudo apt-get install python3-numpy python3-pil python3-dbus
sudo bash scripts/install-npu-onnx.sh /path/to/new-bundle
```

Physical results on the supplied dog image, batch 1, HTP FP16:

| Model | Runs | Mean inference | CPU comparison |
| --- | ---: | ---: | --- |
| MobileNetV2 opset 12 | 100 after clean reboot | 1.289 ms | Same top 5; cosine 0.999982 over 1,000 logits |
| ResNet18 opset 7, batch fixed to 1 | 100 | 2.541 ms | Same top 5; cosine 0.999997 over 1,000 logits |
| OpenAI CLIP ViT-B/16 w8a16 | 10 | 38.968 ms | Real dog image ranked dog above four alternative texts |
| Dynamic two-input/two-output graph | 25 | 0.537 ms | Add/multiply outputs matched within FP16 tolerance |

Timings exclude model preparation, image preprocessing and service startup.
ResNet's original dynamic `N` batch required a dimension override. The new runner
applies this at session creation without rewriting the model. The synthetic
two-input/two-output graph separately validates dynamic-shape plumbing and typed
tensor I/O. CLIP validates the same path with a real 600 MB Qualcomm AI Hub model:
image `uint16 [1,3,224,224]`, text `int32 [1,5,77]` and two outputs. Its zero-shot
scores ranked dog 29.51, person 25.33, cat 22.59, tablet 21.65 and car 19.11.
Two concurrent MobileNet clients also passed 100 runs each. Clean Ubuntu reboot
`44d9f919-7238-4439-bc6a-dbb5babbe932` preserved filesystem read/write status and
fingerprint service readiness. No new I/O error or kernel Oops was observed.
Local raw evidence is in ignored `work/npu-onnx`, `work/npu-ai-after-reboot.log`
and tablet `$HOME/npu-model-test` report directories.

## Integrated multimodal and agentic application (verified)

The personal **IA local** GTK4 application contains chat directly in its window;
opening llama.cpp's web UI is no longer part of its normal flow. A sidebar exposes
chat, speech/image tasks, a model catalog and runtime information. The active-model
badge reports the measured placement returned by the engine: Hexagon NPU, Adreno
Vulkan GPU, Kryo CPU, or a layer split. The app can keep multi-turn history, attach
an image to a VLM, unload weights explicitly and stop all children when it closes.

Agent mode provides structured tool calling with four deliberately bounded local
tools: date/time, memory/runtime status, installed-model listing and an arithmetic
evaluator. It does not expose a shell. A physical end-to-end test used Qwen 3 4B
on HTP0, invoked the calculator tool for `123 * 7`, returned `861`, closed the
window and left the service inactive with zero DMA-heap references.

The Hugging Face catalog stores exact filenames, byte sizes, direct source pages
and SHA-256 digests. Downloads show progress, retain a `.part` file for resumption,
verify both length and hash, and only then become selectable. A real 1.28 GB Qwen
3.5 2B download passed this complete flow. Catalog recommendations are data, not
model-name branches in either inference backend; every runtime mode remains
manually selectable. The catalog and application are personal additions on the
test tablet and are not enabled in default images.

- Chat: Qwen3-1.7B Q8_0, 4,096-token context, 29/29 layers offloaded to HTP0.
  The local API and HTML/assets are served at `http://127.0.0.1:18080` only.
  Test answers in Spanish were “La capital de Francia es París” and “56”. Short
  generation tests measured 15–16 tokens/s (not a broad model-quality benchmark).
- Speech: Whisper tiny multilingual. An 11-second English reference clip took
  0.851 seconds total, with matching transcript text against the CPU reference
  (1.967 seconds before the graph rewrite). Timestamps differed slightly.
  This validates file transcription; live microphone streaming has not been tested.
- Vision: MobileNetV2 classification as documented above, plus Gemma 3 4B with
  its matching F16 projector for conversational image understanding. The Gemma
  VLM correctly identified the supplied golden retriever on CPU. Its Hexagon
  image encoder stalled and Vulkan lost the device, so the catalog selects CPU
  for this VLM; text-only Gemma inference still works on NPU.

The redesigned app's physical UI tests cover construction of all four pages,
catalog recommendations, integrated NPU chat, tool calling, ONNX image
classification and Whisper transcription. Every lifecycle test ended with the
NPU service inactive and zero `system_heap` references.

### Relationship to Arduino VENTUNO Q

VENTUNO Q is not the same SoC: Arduino specifies an IQ-8275 with up to 40 dense
TOPS, while this tablet uses SM8550 Hexagon v73. Its public generative build also
uses upstream llama.cpp compiled as separate Hexagon and CPU variants:
<https://github.com/arduino/app-bricks-py/blob/main/.github/workflows/build-llamacpp.yml>.
Arduino adds curated Qualcomm AI Hub/Edge Impulse runners and a model lifecycle;
it does not make every arbitrary GGUF operator execute on NPU.

This port now follows the same generic separation: current upstream llama.cpp
for GGUF, ONNX Runtime with QNN EP for conventional graphs, model metadata kept
outside the runtime, and verified fallback. It additionally offers a native
Vulkan engine. NPU and Vulkan cannot share transformer layers inside one process
here because the Hexagon runner uses the staged Bionic/FastRPC environment while
Mesa Turnip is a native glibc driver. NPU+CPU and GPU+CPU are supported; a claimed
NPU+GPU split would require a common runtime/ABI that is not present.

The model catalog mirrors the useful part of Arduino's model lifecycle: remote,
partially downloaded, verified and installed states. It does not yet reproduce
the breadth of Arduino's packaged AI Hub runners for detection, pose, TTS and
robotics. Adding those is a model/runtime packaging task rather than a FastRPC
kernel limitation.

## Verified generative-model range

All measurements below use the same 2026-09-04 llama.cpp revision. Rates come
from short deterministic functional prompts and do not establish model quality.
The commercial comparison is a parameter/use tier, not an equivalence claim.

| Model | Approximate tier | Verified placement | Prompt tok/s | Generation tok/s | Result |
| --- | --- | --- | ---: | ---: | --- |
| Qwen3 1.7B Q8_0 | below Phi-3 Mini | 29/29 NPU | — | 15–16 | pass |
| Qwen3.5 2B Q4_K_M | below Phi-3 Mini | 25/25 NPU | 25.38 | 6.44 | pass; simple answer had a wording error |
| Qwen3 4B Instruct Q4_0 | Gemma 3 4B / Phi-3 Mini tier | 37/37 NPU | 132.89 | 11.03 | best tested balance |
| Gemma 3 4B IT Q4_K_M | Gemma 3 4B multimodal tier | text 35/35 NPU; vision CPU | 11.10 | 3.35 text; 7.05 VLM output | pass by modality |
| Qwen3.5 9B Q4_0 | Llama 3 8B tier | 33/33 NPU, dynamic window | 17–20 | 3.56–4.16 | pass |
| Qwen3 14B Q3_K_M | Phi-4/Qwen 14B tier | 16 NPU + 25 CPU recommended | 2.63 | 1.69 | pass, slow |

For Qwen 4B, the same build and prompt measured 9.13 tok/s on Adreno and 6.69
tok/s on CPU; NPU delivered 11.03 tok/s and processed the prompt roughly seven
times faster. For Qwen 9B, GPU measured 3.04 tok/s versus 3.56–4.16 on NPU.
Qwen 14B also completed with all 41 layers on NPU at 1.46 tok/s; a generic
16-layer NPU split improved generation to 1.69 tok/s. Full Vulkan did not become
ready within 180 seconds, while CPU reached 2.16 tok/s but produced invalid HTTP
output in that check. The reliable hybrid configuration is therefore the catalog
default; full NPU remains available manually.

The machine-readable record is `configs/npu/verified-models.json`. Successful
large-model teardown repeatedly returned to zero DMA references, including 14B.
A final mixed lifecycle sequence ran 4B, 9B, 4B and the 14B hybrid configuration,
performing a real completion in every session. Each individual stop returned to
zero DMA-heap references. The final service state was inactive, ext4 remained
read/write and the boot contained no new Oops, refcount warning or filesystem I/O
error.

The initial Qwen3-0.6B test reached 37–42 tokens/s, with DSP profiles showing
nonzero accelerator cycles. Its incorrect Spanish answers reproduced identically
on CPU with the same deterministic requests; the larger model was selected for
usability. It is not claimed that NPU generation always outperforms CPU.

Chat and speech use upstream ggml Hexagon kernels, with ordinary CPU work for
such tasks as tokenization, sampling and audio preprocessing. Their scope differs
from the ONNX graph test, which explicitly disables CPU node fallback. Whisper's
copy operations needed conversion and reshape split into separate graph nodes;
the small source patch is `configs/npu/whisper-split-conversion-copy.patch`.
The Bionic FastRPC library's log/math dependencies are explicitly preloaded for
these clients. The QNN/ONNX runtime is untouched by this workaround.

A concurrent chat plus transcription test passed: the service stayed active while
chat retained its shared lease, then stopped when the last client exited. The
filesystem remained read/write, with no lingering llama-server process.

The optional desktop launcher now includes **Elegir modelo GGUF…**. Choosing a
local model uses a 2,048-token context; the CLI exposes `--model`, `--context`
and `--port`. Startup verifies all model layers were offloaded using the actual
reported layer count, instead of assuming the original model's 29 layers.
This does not certify every operator in an arbitrary GGUF as NPU-compatible.
Q4_0 and Q8_0 are supported by the installed ggml Hexagon matrix kernels;
other common quantizations must not be assumed equivalent.

A subsequent Qwen3-4B-Instruct-2507 Q4_0 test passed through `--model`, with
37/37 layers loaded into HTP0, a 2,048-token context and a coherent Spanish
answer about ice buoyancy. The 75-token completion measured 9.51 tokens/s while
the user's existing 1.7B server remained running. HTP buffers reported 1,955.75 MiB
of weights, 288 MiB of KV cache and 19.25 MiB of compute space. The test server
was stopped afterward; the user's original server remained active and ext4 rw.
The optional model is installed only on the tablet in
`$HOME/Modelos/Qwen3-4B-Instruct-2507-Q4_0.gguf`.
The [quantizer's artifact](https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/blob/main/Qwen_Qwen3-4B-Instruct-2507-Q4_0.gguf)
was verified against SHA256
`b2198e1e35b98e2e126a00d9e853a53bc3a4bcca5f82cfbf2a03b38a91f2662c`.

### Qwen3.5-9B and shared CPU/NPU memory

The optional `Qwen3.5-9B-Q4_0.gguf` from
[Unsloth's conversion](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/blob/main/Qwen3.5-9B-Q4_0.gguf)
was downloaded only to the user's tablet (`$HOME/Modelos`), size
5,379,417,312 bytes, SHA256
`17670346b4260ddcb0173965145155885024f3c9a4a24389a3370751edbcde24`.
This is the standard Qwen3.5-9B model, not the DavidAU fine-tune.

Physical inference passed at 16/33 and 24/33 offloaded layers, with the remaining
layers on CPU. The same 47-token coherent Spanish ice-buoyancy answer measured
3.91 and 4.15 tokens/s respectively, context 2,048. At 24 layers, HTP0 held
2,518.40 MiB of weights, 48 MiB KV, 142.38 MiB recurrent state and 31.25 MiB
compute buffers. These are short generation tests, not broad performance or
numerical-equivalence benchmarks.

The app exposes CPU/NPU sharing and an editable NPU layer count (16 as a uniform
initial manual setting, not a performance prediction). The CLI exposes
`--npu-layers`; readiness verifies the requested offload count. The newer memory
window option described below now allows all 33 layers of this 9B on Hexagon.
An isolated GTK test selected the actual 9B file, confirmed the automatic
24-layer setting, launched the installed wrapper and checked a Spanish API
answer containing both 56 and París (3.47 tokens/s for that short answer).
Closing the window stopped the child and left the NPU service inactive.

The 3,000 MiB Hexagon setting is a simultaneous DSP virtual mapping budget,
not a universal maximum model file size or total tablet RAM limit. Upstream
can evict unused DSP mappings between operation batches, but the Linux FastRPC
context bank still maps buffers into a 32-bit DMA address space (`sid_pos=32`).
The full model, and a 32-layer attempt, failed in `fastrpc_mmap` while ordinary
RAM remained available. Two virtual devices were also rejected: the installed
Android backend forces a single session for architectures below v75. Simply
raising the virtual-memory option cannot fix either limitation. The verified
initial workaround used additional RAM through CPU layers. The attempted failures cleaned up without a
reboot, and the successful tests ended with the service inactive and ext4 rw.

### FastRPC memory window (implemented and tested)

`configs/npu/llama-hexagon-iova-window.patch` adds opt-in host-side windowing to
the pinned ggml Hexagon backend. Non-pinned buffers are allocated in RAM but
registered with FastRPC only when an operation batch needs them. Before eviction,
all outstanding batches are drained; DSP references are released before the
FastRPC mapping. A failed mapping gets one drained-window defragmentation retry.
The DSP kernels, weights and kernel driver are unchanged. The patch is included
by the optional app build recipe and the installed backend retains its previous
library as `libggml-hexagon.so.before-iova-window`.

The mode uses a 2,800 MiB mapping budget and caps weight buffers at 256 MiB
(individual tensors still obey ggml allocation constraints). Smaller buffers
reduce alignment gaps in the 32-bit IOVA space. The app now starts one chat slot,
reducing the 9B recurrent-state buffer from 201 MiB to 50.25 MiB. The backend
option supports one Hexagon session only; it does not add support for new tensor
operations or quantization formats.

Qwen3.5-9B Q4_0 completed real inference with **33/33 layers offloaded**, 3,514.42
MiB of HTP weights, 64 MiB KV, 50.25 MiB recurrent state and 24.50 MiB compute.
Ordinary CPU tasks and any unsupported graph operations can still use CPU;
the layer count does not establish that every graph node executes on the DSP.
In a two-prompt run, window statistics recorded 3,830,882,304 bytes allocated,
2,799,001,600 bytes peak registered and 1,296 evictions, demonstrating actual
reuse of the smaller address window rather than merely raising a size limit.

Controlled short prompts (same UTF-8 text, seed 1234, temperature 0, context 2,048,
one chat slot) produced these ranges:

| Configuration | Prompt tokens/s | Generated tokens/s |
| --- | ---: | ---: |
| Qwen3.5-9B, 24 layers + CPU | 10.21–11.13 | 3.95–4.06 |
| Qwen3.5-9B, 33 layers, memory window | 19.56–20.02 | 3.56–3.90 |
| Qwen3-4B, ordinary NPU | 114.65–118.97 | 9.16–9.39 |
| Qwen3-4B, memory window | 115.40–117.17 | 9.36–9.43 |

Both models answered 7×8 and the capital of France correctly. The 4B's text
matched across both modes. This improves large-model loading and 9B prompt
processing, **not** 9B generation throughput; window remapping has a cost.
It is not evidence of a quality improvement over the 4B.

In IA local choose **NPU · memoria por bloques**, or use
`gts9u-npu-app chat --model MODEL.gguf --context 2048 --memory-window`.
The selector suggests windowing for files larger than 3 GiB; this is a memory
heuristic, not an architecture/quantization compatibility guarantee. Normal NPU
and NPU+CPU modes remain available. The app/model installation remains optional
and is not included in default images.

An audit removed the earlier GUI exception that selected 24 layers by matching
the Qwen3.5 filename and exact file size. The backend patch has no model-name,
artifact-hash or Qwen-specific branches: working sets come from actual ggml
buffer sizes and batch dependencies. The v73 window and buffer limits are
platform tuning parameters, not model-specific values. `--memory-window-mib`
exposes the tested 1024–2800 MiB range; the default remains 2800. The bundled
default model is still named explicitly as a user convenience, with no special
execution path. Automatic architecture-aware performance tuning is not yet
implemented; neither the file-size heuristic nor the default manual layer count
claims to maximize throughput for every model.

The normal per-client stop/start lifecycle passed with ext4 rw. A stress sequence
that deliberately retained the service across several different model processes
hit a subsequent 4B mapping failure; resetting the service restored operation.
Shared-service reuse after a windowed model therefore remains an unresolved
limitation, alongside the previously observed intermittent base-service bootstrap
failure. No reboot or Android transition was needed for recovery.

Source and model pins:

| Component | Revision / SHA256 |
| --- | --- |
| llama.cpp | `427291b5b34cd914a31b3fd3b61a68f6184f4b9f` |
| whisper.cpp | `52a939a2a762224e255d366c1182b2af4dd1a032` plus copy patch |
| Snapdragon Android toolchain v0.7 | `sha256:91714433626f0d94a926538a1e46ec43756c5b8e3262b91b95df1e812940aed1` |
| Qwen3-1.7B Q8_0 | `061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a` |
| Whisper tiny | `be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21` |
| llama-ui archive | `5c06c8aebfc61f694c29d54f6d80e4460ee9040c7dfec456047cef02703e9b1d` |

`scripts/build-npu-apps.sh` captures the build recipe for the pinned toolchain
(NDK r29, Hexagon SDK 6.6.0.0, tools 19.0.07); its required environment variables
are documented at the top of the script. Model and UI hashes are checked before
building. `scripts/install-npu-apps.sh` installs its bundle after obtaining the
exclusive application lease. The model licenses are Apache 2.0 (Qwen) and MIT
(Whisper). Upstream source licenses accompany the runtime packages.

CLI equivalents:

```sh
gts9u-npu-app chat --open-browser
gts9u-npu-app chat --model /path/to/model.gguf --context 2048 --open-browser
gts9u-npu-app transcribe /path/to/audio.wav
gts9u-ai classify /path/to/image.jpg
```

An existing alternative GUI is [Open WebUI](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/),
which can connect to an OpenAI-compatible local server. It was researched but is
not installed: llama.cpp's own GUI is the tested chat interface here.

## Current reproducible implementation

- `kernel/patches/fastrpc-prepared-cdsp-module.patch` builds an opt-in FastRPC module
  from the matching kernel source. It creates the eight CDSP context banks before
  DSP boot and blocks prepared RPCs until GLINK connects. A dedicated unbound
  workqueue releases completed contexts; DMA devices remain until the final open
  file closes and module teardown drains that queue. The queue has high priority
  and context allocation waits for completed IDs under pressure: a later burst
  exposed intermittent ENOSPC even with the original unbound queue.
- `kernel/drivers/gts9u_cdsp_intents_probe.c` supplies the stock 64 × 100-byte reply
  intent pool through a reversible, board-specific OF changeset.
- `scripts/npu-bootstrap-traffic.c` supplies bounded, read-only capability traffic
  during startup. It is terminated as soon as the power owner is ready.
- `scripts/npu-power-keeper.c` owns the temporary QNN sleep-disable vote.
- `scripts/run-npu-session.py` owns startup, the daemon and keeper, validates 100
  actual HTP executions before reporting ready, and stops CDSP before terminating
  the power owner and unloading transient modules.
- `scripts/build-npu-session.sh` builds and signs those helpers against the exact
  existing kernel; it neither flashes nor installs them.
- `configs/npu/gts9u-npu.service` provides explicit systemd start/stop control. It
  is installed on the test tablet but is not enabled at boot.
- `configs/npu/70-gts9u-npu.rules` grants the existing `render` group access to
  non-secure CDSP and the system DMA heap. A real 100-run client passed as the
  ordinary `agcar` user without root. The secure CDSP node is not broadened.
- `configs/npu/fastrpc-shell-search-path.patch` repairs upstream FastRPC shell
  lookup to honor the configured DSP library directory. The fixed library is
  installed in the isolated Bionic runtime and incorporated into the staging script.

The current test kernel preserves the original five-argument exported GLINK probe
ABI for existing SPSS modules. The earlier fingerprint regression was repaired;
SPSS applications started and a real fingerprint match succeeded afterwards.
The shipping DTB is unchanged. No Android reboot is needed for these tests.

## Suspend validation limitation

The service passed a 15-second idle test and explicit `systemctl restart`. A
subsequent `pm_test=devices` cycle did stop CDSP before suspending and restarted
the service afterwards, but the whole-device test **failed**: UFS PHY calibration
timed out (-110), UFS resume returned -5, and ext4 entered emergency read-only mode.
The first storage error occurred while CDSP was offline, before the post-resume
NPU bootstrap. This locates the immediate failure in storage resume; it does not
establish whether earlier NPU activity contributed. No further suspend tests are
appropriate until this is understood. The test mode was reset to `none` and an
Ubuntu reboot requested for recovery. Shutdown stalled and the owner forced a
reboot. On the new boot (`d08dcc2c-ffa3-4b95-8337-c8a0e225d91a`) ext4 completed
journal recovery and mounted read/write; no failed services or new I/O errors
were observed. Fingerprint cache hashes still matched and its secure service
reported ready. The experimental sleep hook was removed from the active system.
There is no RTC device for an unattended wake alarm, so real deep suspend has
not been validated either.

## Latest physical checkpoint

After that recovery, a fresh service startup passed 1,000 consecutive HTP graph
executions (1,024,000 numerical comparisons, zero error), then another 100 after
20 seconds idle. Following the context-pressure fix, ten complete service
start/stop cycles each passed the 100-run startup self-test; ext4 stayed read/write
and no new kernel I/O error, Oops or BUG was observed. Normal-user execution also
passed after installing the narrow device access rules.

Direct firmware process-QoS requests at 40 us and 1 us both returned success but
did not prevent CDSP from entering the unresponsive sleep state. These diagnostic
changes were not installed in the service. A configurable keeper test subsequently
showed that 500 ms, 1 s, 5 s and 20 s renewal intervals all fail after idle, while
250 ms passes the same 45-second idle checkpoint. The repository keeps the prior
100 ms default until the battery-bounded soak validates the lower-frequency value.

The safe validator then completed ten service lifecycles and 1,000 real HTP
executions in 66 seconds. It found zero kernel alerts, zero shared-memory growth,
a maximum CDSP temperature of 40.2 °C and a maximum CPU temperature of 43.0 °C.
Every stop returned CDSP to `offline`, and every active cycle held the logind
sleep inhibitor. `scripts/validate-npu.sh` deliberately does not enter suspend.

The complete session bundle was also rebuilt from the exact current kernel tree.
The signed output included the CDSP bootstrap, prepared FastRPC, intent probe and
DSP statistics modules plus the bootstrap, keeper and supervisor binaries. The
build recipe now dry-runs the zero-fuzz FastRPC patch before compiling and rejects
an unrelated or unprepared kernel tree with a clear error.

Reproducible build SHA-256 values:

```text
2c922765e5a2a7ee334fb794502819663e04173de33eb7018bb6f5d39e5af3f8  npu-bootstrap-traffic
6cd492c8b636b6204a9e6bb55b19a5dc15ac301d20ed77d5e8c71d50e2e530d1  npu-power-keeper
314084a185eae015c72e4a8840e82f851afae6f040af0b6c3b4f549f6943e3a4  run-npu-session.py
5da7e3e96fd48476992cec7820964a8795db973b528dda389bb3c92a26b679ac  gts9u_cdsp.ko
1c264eb8e65c91d95a5ffba64580ddc937e28cdea407d525cad2fea65921474b  gts9u_cdsp_intents_probe.ko
3c3d0292b5b7aaa861ac76e69f14822db9d29d3fd4a2ae63b4eba9d26a753516  gts9u_dsp_stats.ko
64f15bdf8fa320ceedf9f414f46875c7bca2508b5d38014426ff13e719506465  gts9u_fastrpc_prepared.ko
e62102b5e98b94d967742e5ef5de1795a4bcd6daaebc15ffe7dd06388fe05fca  system_heap.ko
```

To use the currently installed experimental session:

```sh
sudo systemctl start gts9u-npu.service
/opt/gts9u-npu-bionic/bin/test-htp 100
sudo systemctl stop gts9u-npu.service
```

Stop the session when finished; do not infer battery efficiency from the low CPU
usage of its power owner. Rebuild with `scripts/build-npu-session.sh`, providing
`UBUNTU_WORKDIR`, `ANDROID_NDK`, and compatible `QNN_HEADERS`; install the output
with `scripts/install-npu-session.sh`. The staged Bionic runtime must include the
shell-search patch. The installer intentionally does not enable boot activation
or install the unvalidated sleep hook.

## Earlier investigation (historical results)

The following records describe earlier checkpoints, including failures before the
prepared transport and power owner were implemented. They are retained as evidence
of what was tested; they do not override the current successful results above.

## Implemented

- `kernel/drivers/gts9u_cdsp.c`: opt-in runtime OF changeset, limited to
  `samsung,gts9uwifi` and `qcom,sm8550-cdsp-pas`. Checks the two reserved-memory
  regions and firmware presence before enabling CDSP. Uses the existing PAS
  driver and Samsung-authenticated firmware.
- `scripts/build-cdsp-module.sh`: builds and signs the bootstrap and system
  DMA-buffer heap against an existing kernel build. Also builds the read-only
  `gts9u_dsp_stats` module. Does not rebuild boot images.
- `kernel/drivers/gts9u_dsp_stats.c`: reads ADSP/CDSP sleep counters through
  the existing SMEM API, using the upstream `qcom_stats.c` layout. It does not
  change power states, firmware memory or configuration.
- `scripts/check-npu.sh`: discovers CDSP by name, records its boot ID/state and
  optional sleep counters, and runs 100 HTP executions with a deadline. Success
  requires exit status zero, correct numerical results and nonzero accelerator
  cycles. It does not activate CDSP. Exit 2 means prerequisites are absent;
  exit 1 means inference failed; exit 0 means the inference test passed.
- `scripts/stage-npu-firmware.py`: extracts the owner's decompressed stock BL
  `NON-HLOS.bin` and `dspso.bin`, checks all 43 files against the pinned
  X910XXS5CYG1 manifest, and checks MDT load addresses and split-segment sizes.
- `scripts/stage-npu-runtime.py`: stages pinned Ubuntu Qualcomm PPA packages in
  an isolated `/opt/gts9u-npu` tree, checks SHA256, and compiles the HTP test.
  **This package set is diagnostic, not a compatible SM8550 runtime.**
- `scripts/stage-npu-bionic.py`: stages an isolated Android-ABI runtime with
  pinned Qualcomm QAIRT 2.45.0, an NDK-built upstream FastRPC library and the
  owner's Bionic/DSP files. Includes the system DMA-buffer allocator. Builds
  without changing the host or tablet. Its complete staging has been checked.
- `scripts/probe-npu-htp.c`: explicitly loads the HTP backend, creates a quantized
  32×32 MatMul + Relu graph, varies input data, compares every result against a
  scalar reference (tolerance one quantization unit), and requires nonzero HTP
  accelerator cycles. Defaults to 100 executions. CPU/GPU backends are not
  bundled. The graph now passes on both Android and Ubuntu; see the current
  experimental-session requirements above.

The shipping DTB is deliberately unchanged: the build uses a pinned DTS because
Samsung ABL is sensitive to changes in the input DTB. The bootstrap has no
autoload configuration and deliberately cannot be unloaded; reboot restores the
original disabled node. Do not enable it automatically until inference and
suspend/resume have passed.

## Physical results

Tested over SSH on Ubuntu 24.04.4 LTS, kernel `7.2.0-rc3-dirty`, with its original
module-signing key. Initial inspection found a disabled CDSP node, no CDSP
firmware image, no CDSP FastRPC device, and no inference runtime.

After staging firmware and loading the signed bootstrap:

```text
remoteproc remoteproc2: powering up cdsp
remoteproc remoteproc2: remote processor cdsp is now up
```

`/dev/fastrpc-cdsp`, `/dev/fastrpc-cdsp-secure` and eight FastRPC context banks
appeared. The separately signed system heap also provided `/dev/dma_heap/system`.
This establishes remoteproc boot and device registration, not inference.

### Blocker 1: CDSP stops answering GLINK

CDSP negotiates GLINK, opens IPCRTR and FastRPC channels, and exchanges early QMI
traffic. It does not advertise receive intents on FastRPC. When the host requests
an intent for a 40-byte RPC message, no answer arrives:

```text
intent request timed out
Error: dsp information is incorrect err: -110
```

The platform validator reports DSP prerequisites present, then stalls querying
DSP capabilities. A Linux CDSP listener also times out. Shutdown itself reports
missing QMI/GLINK responses before PAS finally stops the processor. The failure
precedes RPC payload delivery; model conversion or tensor layout cannot explain
this observation.

Experiments that did not resolve it:

- Archived X910XXS5CYG1 firmware and the current tablet's own firmware, extracted
  from read-only `apnhlos` and `dsp` mounts. Both boot and show the same stall.
- Stock FastRPC receive-intent sizes/counts.
- Binding a diagnostic CDSP resource-manager endpoint before boot; it receives
  protocol version 3, but this is not a complete resource-manager implementation.
- Holding power domains and interconnect bandwidth before and after CDSP boot.
- Disabling all compute context banks before boot to isolate their IOMMU setup.

These observations narrow the failure but do not establish its root cause.
The next kernel investigation is the firmware's remaining initialization and
IPC dependencies, using stock-driver behavior and CDSP diagnostics.

### Blocker 2: packaged QAIRT rejects this SoC

The standalone HTP probe exits with status 1 during log/provider initialization:

```text
Dsp startup: Unsupported SoC model (SnapdragonModel): 43
Htp startup on load failed
api.logCreate(logger, QNN_LOG_LEVEL_INFO, &log) failed: 0xfa0
HTP test exit=1
```

This was QAIRT `2.46.0-0ubuntu1~bpo24.04.1` from the Ubuntu Qualcomm IoT PPA,
with native ARM64 libraries and v73 DSP skeletons. Merely having v73 binaries
does not establish SM8550 support. Native Linux QAIRT 2.45 also rejects SoC 43.
The isolated Bionic runtime described below avoids that provider rejection
without changing the reported SoC. The graph and numerical output have now
passed on Android. They have not passed on Ubuntu; sustained Ubuntu inference
and its suspend/resume validation remain outstanding.

## Additional isolation and Android reference

The native Linux QAIRT 2.45 build also rejects SoC 43. In contrast, the official
Android QAIRT 2.45.0 AAR initializes `QnnBackend_create` successfully on Ubuntu
using a separately staged Bionic linker and upstream FastRPC compiled with the
NDK. No SoC identity override is used. `QnnDevice_create` still fails after the
CDSP communication timeout; backend initialization alone is not inference.

A read-only dump of the reserved CDSP memory, taken after stopping remoteproc,
contains ULog records showing completed firmware initialization followed by
`cpu_vdd.full_pc`. The sleep solver selected L2 non-retention, PDC wakeup and
full power collapse. A heuristic decoder finds zero wakeup records, including
after a probe allowed to run for 65 seconds; the logged timer deadline was about
30 seconds. This narrows the failure to entering or leaving deep sleep, rather
than proving which register or driver causes it. Holding XO, the three proxy
power domains and interconnect bandwidth did not resolve it. The stock CDSPRM
version/configuration exchange was also reproduced and acknowledged by DSP.

The user subsequently booted Android with root ADB. On the same SM-X910 running
`X910XXS5DZA1` / kernel `5.15.178-android13-8-32143072-abX910XXS5DZA1`:

- The current CDSP firmware SHA256 matches the variant already tested on Ubuntu.
- The same QAIRT AAR, probe and stock Android FastRPC executed 100 iterations:
  `elements=102400 max_quantized_error=0 accel_cycles=7341`, process exit 0.
- A controlled stop/start of CDSP succeeded; another 100 iterations passed with
  zero numerical error and `accel_cycles=6040`, process exit 0.
- CDSP sleep counters advance and record successful exits from low-power mode.
- The probe initially crashed at process exit after `dlclose(libQnnHtp.so)`.
  Keeping the runtime mapped until process teardown, after freeing all QNN
  handles, resolves that crash. It no longer prints a passing result followed
  by a failing process exit in the reference test.

Firmware, Bionic libraries, the live DTB, regulator/clock/interconnect summaries,
and a CDSP restart trace are retained locally under ignored `work/`. No Android
firmware or boot image was changed for these tests. The user allows one return
to Ubuntu and will not be available to unlock Android again; collect all needed
Android evidence before that switch. That switch has since been completed:
the tablet is back in Ubuntu and must not be returned to Android unattended.

### Further Ubuntu isolation after the Android reference

The new Ubuntu boot was found by scanning the local subnet
and matching the saved SSH Ed25519 host key. Do not assume a fixed address or
remoteproc index: CDSP became `remoteproc1`, while `remoteproc2` is SPSS.
Always locate CDSP by its `name` attribute before starting or stopping it.

Additional unsuccessful experiments, all removed after their bounded tests:

- Loading the bootstrap early in systemd (about 17 seconds after boot).
- Holding an open `/dev/cpu_dma_latency` request across CDSP boot and inference.
- Preloading the QNN backend and using only the first compute context bank.
  This exposed a transient `No session available` during device registration,
  followed by the original timeout; it did not establish inference.
- Sending the stock resource manager's NPU-activity notification before its
  default process-kill configuration. The configuration was acknowledged;
  the activity notification was not.
- Repeating the acknowledged default configuration in a bounded request/reply
  loop. Only 21 replies arrived before communication stopped. This did not
  keep CDSP available for inference.
- Resetting the AP-owned GLINK queue indices while CDSP was offline, before
  firmware boot, matching Android's prepare ordering. The timeout persisted.

The stock GLINK header defines zero-copy as bit 3, whereas the observed firmware
advertises `0x7`. Zero-copy is therefore not a negotiated capability of this
firmware; no speculative zero-copy driver was installed. The IPCC destination,
SMP2P IDs and PAS authentication call arguments match the inspected stock source.
The in-memory PAS context also confirms the existing AOSS load-state client
is present and named `cdsp`.

Read-only SMEM sleep counters further distinguish this from a general DSP
failure. In two samples three seconds apart, ADSP advanced from 97,577 to 97,735
sleep cycles and continued recording exits. CDSP remained at count 0 with
`entered=30398852763`, `exited=0`, `accumulated=0`. Together with the offline
firmware ULog this indicates a stall during the first full power-collapse
transition. It does not identify a proven register-level correction.

The archived in-tree FastRPC source is not necessarily identical to Android's
external `frpc-adsprpc` module. Qualcomm's separate `dsp-kernel` source was also
retrieved for comparison at commit `191748d8116ea054c9267aa4f77caad025fa218f`.
It has not been installed in Ubuntu. None of these investigations establishes
full NPU functionality on the current kernel.

An offline comparison also found exact matches between the loaded image and the
owner's current firmware for the main read-only executable segments (`b03`,
`b04`, `b08`, `b11`, `b13`) and read-only data (`b07`). The small boot segment
`b01` differs at byte 72 (0 to 12), and writable segments have runtime changes.
This does not indicate corruption of the main sleep-code image; the boot-byte
change has not been attributed to a specific firmware function.

Build the Bionic diagnostic runtime with Linux, NDK r26d, autoconf, automake,
libtool and a local checkout of Qualcomm FastRPC at
`9d409211527f5c853351a8c014c2bcb271bc6f2d`:

```sh
python3 scripts/stage-npu-bionic.py \
  --ndk /path/to/android-ndk-r26d \
  --fastrpc-source /path/to/fastrpc \
  --qnn-headers /path/to/qnn-api/include \
  --aar /path/to/qnn-runtime-2.45.0.aar \
  --bionic /path/to/owners-bionic-libraries \
  --dsp /path/to/owners-cdsp-files \
  --output /tmp/gts9u-npu-bionic
```

The AAR SHA256 is pinned in the script. Headers used for the tested build came
from Qualcomm `geniex-qairt-plugin` commit
`9b98a3899a59ec39a943b0c122eabdcb5a88d2a6`. The output includes a per-file SHA256
manifest and retained upstream license files. Deployment is separate.

## Reproduce the native Linux diagnostic build and staging

Run in Linux/WSL with Python 3.9+, `mtools`, `e2fsprogs`, `dpkg-deb`, an ARM64 GCC
cross-compiler, and the LLVM toolchain used for the kernel. Paths below are
examples; output staging directories must not already exist.

```sh
python3 scripts/stage-npu-firmware.py \
  --non-hlos /path/to/decompressed/BL/NON-HLOS.bin \
  --dspso /path/to/decompressed/BL/dspso.bin \
  --output /tmp/gts9u-npu-firmware

python3 scripts/stage-npu-runtime.py \
  --firmware /tmp/gts9u-npu-firmware \
  --cache /path/to/package-cache \
  --output /tmp/gts9u-npu-runtime

UBUNTU_WORKDIR=/root/ubuntu-gts9u-release-1.1.0 \
  bash scripts/build-cdsp-module.sh
```

Use the build directory and private signing key matching the **running** kernel,
not just one with an identical release string. The physically tested kernel's
signing certificate serial is
`07:F4:1A:A3:36:BC:3D:33:72:30:49:6F:B9:F2:DB:2C:41:87:1F:35`.
The script prints module metadata and hashes for verification.

After manually deploying the staged files and modules to a matching tablet,
`/opt/gts9u-npu/bin/test-htp` preserves failure status and enforces a 120-second
deadline with forced termination after a further five seconds. Run as root for
the current device permissions. Do not interpret device existence, validator
prerequisite checks or remoteproc `running` as a passing inference test.

Validation performed: firmware staging verified all 43 files; module build and
signature checks succeeded; the ARM64 probe compiled with
`-Wall -Wextra -Werror`; complete runtime staging succeeded; live bootstrap boot
succeeded; live HTP probe failed as documented above.

For repeatable physical checks after activating the experimental bootstrap:

```sh
sudo insmod /path/to/gts9u_dsp_stats.ko
sudo bash scripts/check-npu.sh /opt/gts9u-npu-bionic
sudo rmmod gts9u_dsp_stats
```

The check prints a private report directory under `/tmp` containing the test log,
process exit status and snapshots. A `running` CDSP with a failing test is still
a failure. The stats module is optional and must match the running kernel's
build and signing key, just like the bootstrap.

The final module set rebuilt and signed successfully. The read-only stats
module was loaded and read on the tablet, then unloaded. The check script was
installed as `/usr/local/sbin/gts9u-npu-check`; its offline prerequisite gate
returned the expected exit 2 and generated a report. This gate check is not an
additional inference pass. Earlier physical inference failures remain the
applicable result.

## Additional MX supply diagnostic

The stock GCC driver and mainline SM8550 GCC enable the same eight critical
clock bits and both clear `GDSC_SLEEP_ENA_VOTE`. No missing critical clock was
identified in that comparison. Stock's clock controller also holds an MX supply
vote, whereas Ubuntu's MX genpd was off. A temporary signed module used the
standard genpd API to hold MX at nominal performance state 256 before CDSP boot.
The live genpd summary confirmed the vote was active throughout the test.

This did not resolve the hang: CDSP sleep count remained zero, with entry tick
114087326556 and no exit tick. ADSP advanced from 310679 to 312891 sleep cycles.
The 40-second bounded Bionic HTP probe stopped in device creation and required
the timeout's kill escalation (exit 137). CDSP was stopped and the temporary MX,
RM and stats modules removed. Evidence: ignored `work/npu-mx-test.log` and
`work/npu-live-mx.sh`. This result rules out the tested missing nominal MX vote;
it does not establish the cause of the power-collapse failure.

## Tablet state at the end of testing

Following the Android reference and subsequent Ubuntu experiments, CDSP is
stopped (`offline`), and temporary diagnostic modules are removed. ADSP and SPSS
remain `running`. The one-shot early-boot experiment was removed. No new kernel,
DTB or boot image was flashed for NPU experiments. Returning from Android used
the user's existing Dualboot application and existing Ubuntu boot set; Ubuntu
was also rebooted once to test early CDSP activation.
The final live state was captured at 18:36:59 CEST. The transient system-sleep
inhibitor used during diagnostics was then stopped.

The experimental bootstrap and system heap remain loaded until reboot. Firmware
files remain under `/usr/lib/firmware/qcom/sm8550`, stock DSP files under
`/usr/share/qcom/sm8550/Samsung/gts9uwifi/cdsp`, and diagnostic libraries under
`/opt/gts9u-npu`, `/opt/gts9u-npu-alternate` and `/opt/gts9u-npu-bionic`. There
is no persistent CDSP service or module autoload entry.
The live firmware is the tablet's current variant; the reproducible importer
intentionally accepts only the archived X910XXS5CYG1 variant.

Original `cdspr.jsn` and boot-id were saved under
`/var/lib/gts9u-npu-backup.80nb8t`. Reboot returns the runtime DT to its original
disabled state; this does not delete the staged firmware/runtime files.

Raw local evidence is retained in ignored `work/npu-glink-restart.txt`,
`work/npu-cb-trace.txt`, `work/npu-htp-final.log`, and `work/npu-final-state.txt`.
Android reference evidence is in `work/npu-android-final-reference/` and
`work/npu-android-htp-pass.txt`; later Ubuntu logs include
`work/npu-keepalive.log`, `work/npu-prepare-smem.log` and
`work/npu-latest-state.txt`.

## UFS resume repair validation

Deep system suspend exposed a separate platform fault: after power collapse the
SM8550 QMP UFS PHY sometimes left SerDes running, timed out during calibration,
and caused the root filesystem to abort its journal. Retaining the UFS link at
system power-management levels 0, 1 or 3 did not provide a reliable solution.

The board patch now exposes the QMP stop-and-reset sequence through `phy_reset()`
and calls it only from the SM-X910 `UFS_SYSTEM_PM` suspend path. An earlier
version placed the sequence in `phy_power_off()`; an A/B boot test proved that
was too broad because the same operation is used during initial host bring-up
and clock gating. A rebuilt baseline without the change booted, and the scoped
version subsequently booted with the exact known-good config and DTB. Its boot
image SHA-256 is
`2c802a54fbb8e3a4fd262a1d673bf809de6a70f58daf52f478f800938476699a`.

A `pm_test` suspend/resume cycle and repeated real deep-suspend cycles passed
with a writable root and zero UFS PHY, UIC, suspend, resume or I/O errors. The
final kernel also masks the IPCC summary interrupt during system suspend on this
board, preventing ordinary ADSP SMP2P traffic from causing an IRQ-less firmware
return. Physical cycles of 31.2 s, 112.2 s and 259.2 s remained asleep until the
PMIC power key (`IRQ 21`). All normal device wake sources remain enabled.

The camera focus motor's forced runtime resume was the last device PM failure;
using the same runtime-only PM pattern as upstream VCM drivers removed it. The
final cycle recorded zero failures in every suspend and resume phase, with Wi-Fi
and fingerprint available after wake.

Deep sleep resets the proprietary FastRPC/QNN transport even though remoteproc
still reports CDSP as running. Stopping CDSP before PSCI is unsafe on this
firmware, so the NPU sleep hook records an active session on entry and recycles
it only after resume. Restart is asynchronous and observes the existing
60-second firmware settling interval, leaving the lock screen responsive. A
physical test suspended for 31.2 s with NPU active, recovered the service and
then passed 100 HTP executions at 5,300 accelerator cycles. Final teardown left
CDSP offline and shared memory 12 KiB below its pre-stop reading.

## Sources

- [Upstream SM8550 device tree](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/qcom/sm8550.dtsi)
- [Upstream Qualcomm FastRPC driver](https://github.com/torvalds/linux/blob/master/drivers/misc/fastrpc.c)
- [Qualcomm external DSP kernel driver](https://git.codelinaro.org/clo/la/platform/vendor/qcom/opensource/dsp-kernel)
- [Qualcomm Linux runtime setup](https://github.com/qualcomm/sample-apps-for-qualcomm-linux/blob/main/GenAI-Solutions/GenAI-Studio/docs/setup/DEVICE_SETUP.md)
- [Pinned packages' repository index](https://ppa.launchpadcontent.net/ubuntu-qcom-iot/qcom-ppa/ubuntu/dists/noble/main/binary-arm64/Packages.gz)

Stock DT and `cdsprm.c`/`adsprpc_rpmsg.c` were also inspected from the owner's
Samsung source/archive files. Proprietary firmware and runtime binaries are not
added to this repository.
