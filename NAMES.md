# ravenbatch — the name map

Sixty well-known names for pieces of an inference batching and scheduling layer, each given a
SyMoNeuRaL name. Three of the seventy-three lines supplied were repeats (`DynamicBatcher`,
`InferenceBatchScheduler`, `RequestAggregator`), leaving sixty distinct names.

## What the SyMoNeuRaL name means, and what it does not

Rule 31: the `symoneural-*` namespaces are **our own integration layer, not replacement names
for upstream repositories**. Rule 6: renaming a thing does not discharge its upstream licence.
So a name in the right-hand column below is not a claim that we own an idea — a dynamic batcher
is a dynamic batcher, and vLLM, llama.cpp and Triton each have one. It names **our
implementation of it**, which is first-party code in this branch.

## Placement

    placement-triage prospect ravenbatch --sources python-stdlib@PSF-2.0

    name      ravenbatch
    verdict   SymonSayDistribute
    licence   SymonSaysLLC Proprietary License
    why       every named source is non-copyleft, so the default applies
    evidence  python-stdlib@PSF-2.0 -> permissive

Sources were named before the licence was chosen, per §3.1b-i.

**One source, and it is the standard library.** The first draft of this section also listed
vllm@Apache-2.0, llama.cpp@MIT and triton@MIT. Those three are on this host and all three are
permissive, so the verdict would not have changed — which is exactly why listing them was
wrong. Nothing here copies a line from them and nothing links against them, so they are not
sources of this artifact; they are prior art that was read. A source list that names things
the artifact does not contain inflates the census the ship gate runs and makes a true record
into a roughly-true one.

Checked rather than assumed while establishing that: OpenAI Triton's LICENSE is verbatim MIT
(triton-lang/triton, Tillet and OpenAI) — it had been labelled MIT from the shape of its
copyright header, which is not the same as reading it.

## Honest column: several of these sixty names are the same thing

A name that is a configuration of another is marked so rather than given its own class. Sixty
classes for sixty names would be sixty places for the same bug.

## A. Admission — `symoneural_ravenbatch/admit.py`

**BUILT.** Code and tests on disk; 50 tests pass across A and B together.

Everything that happens before a request is allowed to cost anything.

| Given name | SyMoNeuRaL name | What it is here |
|---|---|---|
| RequestIngressBuffer | `symon-ingress` | `Ingress` — the bounded arrival buffer; full means refuse, never grow |
| RequestAggregator | `symon-aggregator` | `Aggregator` — collects arrivals over a window into one candidate batch |
| RequestCoalescer | `symon-coalescer` | `Coalescer` — one in-flight call serves identical concurrent requests |
| RequestTriageGate | `symon-triage-gate` | `TriageGate` — admit or refuse, with the reason |
| WorkloadTriageDispatcher | `symon-triage-dispatch` | `TriageGate.route()` — a configuration of the gate, not a second gate |
| InferenceQueueManager | `symon-queue` | `Queue` — the admitted work, and only the admitted work |
| InferenceQueuePrioritizer | `symon-prioritizer` | `Prioritizer` — the ordering policy the queue reads |
| PriorityQueueGatekeeper | `symon-gatekeeper` | `Gatekeeper` — `Queue` + `Prioritizer` + `TriageGate` as one object |

## B. Batch formation — `symoneural_ravenbatch/form.py`

**BUILT.** Code and tests on disk.

Turning admitted requests into one call the engine can take.

| Given name | SyMoNeuRaL name | What it is here |
|---|---|---|
| DynamicBatcher | `symon-batcher` | `DynamicBatcher` — forms on whichever bound trips first |
| LatencyBoundBatcher | `symon-latency-batcher` | `DynamicBatcher(bound="latency")` — a configuration |
| MicroBatchCoordinator | `symon-microbatch` | `MicroBatch` — splits a formed batch to fit the device |
| TokenBatchManager | `symon-token-batch` | `TokenBudget` — the token ceiling a batch may not cross |
| BatchAggregationLayer | `symon-batch-layer` | `Batch` — the formed unit itself, with its provenance |
| PayloadBundler | `symon-bundler` | `Bundler` — request bodies into one wire payload |
| PayloadStagingArea | `symon-staging` | `Staging` — formed-but-not-dispatched, so a stall is visible |
| InputConcatenator | `symon-concat` | `Concatenator` — joins sequences with their boundaries recorded |
| InputVectorPacker | `symon-packer` | `Packer` — packs to a width without padding waste |
| TensorStacker | `symon-stacker` | `Stacker` — equal-shape stacking; refuses ragged input |
| SequencePadders | `symon-padder` | `Padder` — pads to a common length and reports the waste |
| TokenReservoir | `symon-reservoir` | `Reservoir` — tokens available to spend this window |

## C. Scheduling and dispatch — `symoneural_ravenbatch/dispatch.py`

**NAMED AND SOURCED, NOT BUILT.** See the note at the end.

Deciding what runs next, and sending it.

| Given name | SyMoNeuRaL name | What it is here |
|---|---|---|
| InferenceBatchScheduler | `symon-scheduler` | `Scheduler` — picks the next batch under the flow limits |
| GPUWorkloadScheduler | `symon-gpu-scheduler` | `Scheduler(device=...)` — a configuration |
| PipelineParallelScheduler | `symon-pipeline-scheduler` | `PipelineScheduler` — stages that overlap |
| SequenceOrchestrator | `symon-sequencer` | `Sequencer` — order within one batch |
| InferencePipelineOrchestrator | `symon-pipeline` | `Pipeline` — admit → form → dispatch as one path |
| TensorAssemblyLine | `symon-assembly` | `AssemblyLine` — the staged form of that path |
| ExecutionMatrixRouter | `symon-exec-router` | `ExecRouter` — request to execution cell |
| DistributedBatchRouter | `symon-batch-router` | `BatchRouter` — batch to one of several engines |
| MultiTenantInferenceRouter | `symon-tenant-router` | `TenantRouter` — per-tenant fairness and isolation |
| ModelVariantDispatcher | `symon-variant-dispatch` | `VariantDispatcher` — request to a model variant |
| BatchEgressController | `symon-egress` | `Egress` — results back to the callers that asked |
| ParallelComputeRunner | `symon-parallel-runner` | `ParallelRunner` — bounded concurrent execution |
| VectorInferenceEngine | `symon-vector-engine` | **Not built here.** This is the engine itself — the chat unit on 8802. ravenbatch is in front of it, not a second one |

## D. Flow control — `symoneural_ravenbatch/flow.py`

**NAMED AND SOURCED, NOT BUILT.** Needs measured latency and token rate.

What stops the estate from accepting work it cannot serve.

| Given name | SyMoNeuRaL name | What it is here |
|---|---|---|
| ConcurrencyThrottle | `symon-concurrency` | `Concurrency` — the hard in-flight ceiling |
| AdaptiveThrottleController | `symon-throttle` | `AdaptiveThrottle` — moves the ceiling on measured latency |
| ThroughputMaximizer | `symon-throughput` | `Throughput` — the observed rate, and what bound it |
| SLAComplianceController | `symon-sla` | `SLA` — deadlines, and what to shed when they cannot be met |
| InferenceLoadShifter | `symon-load-shift` | `LoadShifter` — moves work between engines under pressure |
| ComputeResourceAllocator | `symon-allocator` | `Allocator` — shares of the device across tenants |
| WindowSizeTuner | `symon-window-tuner` | `WindowTuner` — the batching window, from measurement |
| DynamicWindowStager | `symon-window-stager` | `WindowStager` — applies a tuned window without a restart |

## E. Residency and buffers — `symoneural_ravenbatch/residency.py`

**NAMED AND SOURCED, NOT BUILT.** Needs per-device residency measurement.

What is held, where, and for how long. The arithmetic belongs to ravencalc; this is the
bookkeeping around it.

| Given name | SyMoNeuRaL name | What it is here |
|---|---|---|
| StreamBuffer | `symon-stream-buffer` | `StreamBuffer` — per-stream token buffering |
| SlidingWindowBuffer | `symon-sliding-window` | `SlidingWindow` — the window this checkpoint's layers use |
| FramePooler | `symon-frame-pool` | `FramePool` — reusable buffers, so steady state stops allocating |
| VRAMPrefetcher | `symon-prefetch` | `Prefetcher` — brings an expert in before it is selected |
| VRAMLoadBalancer | `symon-vram-balance` | `VramBalancer` — residency across devices |
| TensorSlicingEngine | `symon-slicer` | `Slicer` — splits a tensor across a boundary |
| SequenceSplitter | `symon-splitter` | `Splitter` — splits a sequence too long for one pass |
| DataChunker | `symon-chunker` | `Chunker` — fixed-size chunking with the remainder named |
| DataPipelineStager | `symon-stager` | `Stager` — moves data between stages without copying twice |

## F. Sweeps and evaluation — `symoneural_ravenbatch/sweep.py`

**NAMED AND SOURCED, NOT BUILT.** Buildable without measurement; not started.

Running the same thing many ways on purpose, and recording what happened.

| Given name | SyMoNeuRaL name | What it is here |
|---|---|---|
| ModelConfigMatrix | `symon-config-matrix` | `ConfigMatrix` — the cross product of configurations |
| ConfigMatrixEvaluator | `symon-matrix-eval` | `MatrixEvaluator` — runs a matrix and scores each cell |
| HyperparameterGrid | `symon-grid` | `Grid` — a `ConfigMatrix` over numeric ranges |
| HyperparameterSweepRunner | `symon-sweep` | `SweepRunner` — a `MatrixEvaluator` over a `Grid` |
| ExecutionRunMatrix | `symon-run-matrix` | `RunMatrix` — the results, addressable by cell |
| ModelInstantiationMatrix | `symon-instantiation-matrix` | `ConfigMatrix` over model loads — a configuration |
| QuantizationVariantMatrix | `symon-quant-matrix` | `ConfigMatrix` over quantisations — a configuration |
| BulkJobRunner | `symon-bulk` | `BulkRunner` — many independent jobs, bounded |
| AsynchronousJobPool | `symon-job-pool` | `JobPool` — the bounded worker pool underneath it |
| EvaluationTestSuite | `symon-eval` | `EvalSuite` — cases, expectations and a pass rate |

---

## Status, plainly

| | Names | State |
|---|---|---|
| A. Admission | 8 | **Built**, tested |
| B. Batch formation | 12 | **Built**, tested |
| C. Scheduling and dispatch | 13 | Named and sourced, not built |
| D. Flow control | 8 | Named and sourced, not built |
| E. Residency and buffers | 9 | Named and sourced, not built |
| F. Sweeps and evaluation | 10 | Named and sourced, not built |
| **Total** | **60** | **20 built, 40 named** |

## Why C, D and E are not built

They need **measured** inputs this host cannot supply while the engine holds the card: observed
latency, observed token rate, per-device residency. `AdaptiveThrottle` moving a ceiling on an
invented number is the "number produced from an assumption" that ravencalc exists to refuse.
Built against guesses they would pass their own tests and be wrong on the machine.

F needs no measurement and is simply not started. It is the cheapest of the four to do next.

Every one of the forty has its licence already settled — same sources, same verdict,
SymonSayDistribute under the proprietary licence — so none of them is blocked on a placement
question. They are blocked on a measurement window, and F is blocked on nothing.
