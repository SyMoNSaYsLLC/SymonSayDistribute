# symonpayload

Admission and batch formation for the estate's inference path.

This page describes what is **built**: the two modules below have tests that run, and the
four named in "Not built yet" are named and sourced and have no code.

## What this is

The gateway on 9001 relays each request straight to the engine on 8802. There is no queue, no
ordering, no ceiling on what is in flight, and no way to refuse work before it costs anything.
That holds until two callers arrive at once, and then the failure surfaces as a timeout
somewhere downstream with nothing to say which request caused it or why it was accepted.

symonpayload is the layer that goes in front: work is refused at the door with a reason, or it is
admitted and accounted for. There is no third state where something is in the building and
nobody knows.

## The name

Cut once as `ravenbatch` and renamed before anything depended on it.

`raven` was never a considered choice. `ravencalc` existed in the estate, this was a second
infrastructure unit, and the name was extended to it so the two would read as a family —
pattern-matching, not a decision. Nothing in the repository ever recorded what `raven` meant;
it came from `RavenCalcServer`, dated 2025-12-24, nine months before this estate existed, and
it is Garrett's.

His ruling, 2026-09-19: **ravencalc is a one-off and keeps its name — it is the estate's
provider of arithmetic.** It is not a family and this unit is not a member of it. Renamed to
`symonpayload`, which says what the unit does: it forms the payload the engine is given.

The rename was done immediately and the `ravenbatch/v1.0.0` and `v1.1.0` tags and releases were
removed rather than left behind, on his instruction to prevent dead tags. Nothing imported the
unit, no connector reached it and its token was never provisioned, so there was nothing to
break — which is exactly why it was done now rather than after module C lands.

## Placement

    placement-triage prospect symonpayload --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

One source, and it is the standard library. vLLM, llama.cpp and OpenAI Triton are on this host
and all three are permissive, so naming them would not have changed the verdict — which is why
naming them would have been wrong. Nothing here copies a line from them or links against them.
They are prior art, and a source list that names things the artifact does not contain inflates
the census the ship gate runs.

## Built: admission — `symonpayload/admit.py`

`Ingress` `Prioritizer` `Coalescer` `TriageGate` `Queue` `Aggregator` `Gatekeeper`

Every refusal names the limit it hit. "Rejected" with no reason is the failure mode this
replaces: an operator reading logs cannot tell an over-long prompt from an over-full queue, and
those call for opposite responses.

Three things it refuses to do:

**Guess a token count.** `Request.tokens` is counted by the caller before it arrives. The
gateway already serves `count_tokens`. A batch formed on a token count estimated from character
length is a batch that does not fit, discovered at the engine.

**Grow instead of refusing.** An unbounded queue does not remove the limit, it moves it:
requests accumulate until something downstream runs out of memory, and the refusal arrives as
a crash rather than a 429.

**Decide what "the same request" means.** `Coalescer` keys on the caller's `fingerprint` and
nothing else. Hashing bodies to decide identity means two requests that differ in a way we did
not think to hash would silently receive each other's answer — a correctness bug wearing the
costume of an optimisation. An empty fingerprint means "never coalesce me".

## Built: formation — `symonpayload/form.py`

`TokenBudget` `Batch` `DynamicBatcher` `MicroBatch` `Padder` `Stacker` `Concatenator`
`Packer` `Bundler` `Staging` `Reservoir`

A batch is formed against a **token** ceiling, not a request count. Four requests can be four
hundred tokens or forty thousand.

### The bound is as much the product as the batch

Every `Batch` carries `bound`: what ended formation. Four values, and they call for opposite
responses:

| bound | meaning | what it says to do |
|---|---|---|
| `tokens` | the ceiling was reached | raise the ceiling, or lower the served context |
| `count` | the request limit was reached | raise the request limit |
| `window` | the wait expired with work still pending | shorten the window, or add capacity |
| `drained` | the pending list ran out | nothing — the unit is under-loaded, not saturated |

`drained` earns its own value because reporting it as `count` or `window` makes an idle unit
look like a saturated one. It was added while writing the tests, which is where the gap showed.

### Padding is a decision, so it is never made for you

`Stacker` refuses ragged input instead of padding it. `Padder` pads and **returns the waste**:
one 8k sequence among three 200-token ones allocates 32,000 token-slots to carry 8,600. That
number is why `Packer` exists — it reorders into rows and wastes less, at the cost of changing
the order, which matters when order is fairness. The caller chooses.

### No defaults for policy

Capacity, window, ceilings and concurrency are arguments with no defaults. A default here is a
number nobody chose, silently deciding what the estate accepts. The clock is injected too, so
the behaviour at the window boundary is testable rather than a race.

## Testing

78 tests, and most of them are refusals: ingress at capacity naming the number, a token ceiling
naming both numbers, a request too large to ever batch saying it belonged at admission, ragged
stacking, padding below the longest member, a missing body named by id, an empty batch that
cannot be constructed at all. Over HTTP: an unset token answering 503 rather than opening, a
missing policy variable named in the 503, a refusal answering 429 rather than 400, and eight
unbuilt routes asserted to be 404 so a stub cannot appear without a test failing.

    cd /mnt/SymonSayDistribute/symonpayload && python3 -m pytest tests/ -q

## Built: sweeps and evaluation — `symonpayload/sweep.py`

`ConfigMatrix` `Grid` `MatrixEvaluator` `SweepRunner` `RunMatrix` `JobPool` `BulkRunner`
`EvalSuite`, plus the instantiation and quantisation matrices, which are `ConfigMatrix` over
different axes rather than three separate ideas.

**A sweep's danger is not failing, it is succeeding enormously.** Four axes of five values is
625 runs, and nothing about writing that down looks like 625. So a matrix states its size
before anything runs and refuses one larger than a limit the caller has to name — a default cap
would be somebody else deciding how much of the card's day to spend.

**Failures are kept.** Every cell holds its configuration and its outcome, including the ones
that crashed, because *"these four combinations all failed"* is the most useful thing a sweep
produces and it is the first thing a summary of the winner throws away. `best()` refuses when
everything failed rather than returning nothing, and says the failures are still there.

An `EvalSuite` expectation is a **predicate, not an expected value** — most things worth
evaluating are not equality: *is shorter than the input*, *cites a source*, *does not name a
competitor*. A suite that can only check equality quietly becomes a suite of the easy things.
A suite with no cases is refused, because it would always pass.

## Not built yet

Four modules are named in [the name map](#symonpayload--the-name-map) with their sources recorded, and have no code:
dispatch (C), flow control (D), residency (E), sweeps (F).

They are not built because they need **measured** inputs this host cannot give while the engine
holds the card: observed latency, observed token rate, per-device residency. An
`AdaptiveThrottle` that moves a ceiling on an invented number is exactly the "number produced
from an assumption" that ravencalc exists to refuse. Building them against guesses would have
produced four modules that pass their own tests and are wrong on the machine.

## Over HTTP

Thirteen routes on `127.0.0.1:8814`, the port `/models/control.board` assigns to `symonpayload`.
Health is public; everything else needs `SYM_PAYLOAD_TOKEN`, and an unset token closes the
unit rather than opening it.

    GET  /api/symonpayload/health              public; answers before the unit is configured
    POST /api/symonpayload/requests/submit     admit one; `tokens` is required and counted
    POST /api/symonpayload/requests/batch      admit many; partial success is reported
    POST /api/symonpayload/requests/triage     which lane, and why
    POST /api/symonpayload/payloads/coalesce   group by the caller's declared fingerprint
    GET  /api/symonpayload/queue/status        depth, tokens pending, refusals since start
    POST /api/symonpayload/queue/prioritize    the resulting order, and the policy behind it
    POST /api/symonpayload/batches/form        form one, and report which bound tripped
    POST /api/symonpayload/shapes/stack        will these stack, and to what shape
    POST /api/symonpayload/shapes/concatenate  the total, and the boundaries to split it again
    POST /api/symonpayload/shapes/pack         rows, and what packing wastes
    POST /api/symonpayload/tokens/plan         the padding plan, and what it wastes
    POST /api/symonpayload/tokens/reservoir    fill level and remaining — two numbers, not one

Not `/v1/`. That namespace is the Messages dialect the gateway serves to third-party clients
and its paths are fixed by them; nothing outside this host speaks to symonpayload. See
[the API section](#symonpayload--the-api-in-our-names) for the full mapping from the generic reference, with a verdict on every
route.

**Policy has no defaults over HTTP either.** `SYM_PAYLOAD_MAX_TOKENS` and
`SYM_PAYLOAD_CAPACITY` are read from the environment and the unit answers 503 naming the
missing variable rather than picking a number. A 503 that names a knob is something an
operator can fix; a default is a decision nobody made.

**The API is derived from the components, never the other way round.** The reference document
has twenty-seven routes; sixteen describe components that do not exist, and those are not
carried anywhere — no stub, no 501, no declared contract. Their components stay named and
placed in [the name map](#symonpayload--the-name-map), and each gets a route designed against what it actually does
once it is built, which is a better route than one designed against what it was imagined to
do.

## Releases

Tagged `symonpayload/v<version>`.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonpayload`](symonpayload/symonpayload.md) | the capability this unit provides — `admit.py`, `dispatch.py`, `flow.py`, `form.py` … +2 |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 7 test file(s) |

## symonpayload — the name map

*Folded in from `NAMES.md` on 2026-09-20: §3.7 allows one
document per directory. Nothing was lost — the original file is at
`/home/google/Desktop/claude/quarantine-3.7-2026-09-20/mnt/SymonSayDistribute/symonpayload/NAMES.md`.*

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

    placement-triage prospect symonpayload --sources python-stdlib@PSF-2.0

    name      symonpayload
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

## A. Admission — `symonpayload/admit.py`

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

## B. Batch formation — `symonpayload/form.py`

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

## C. Scheduling and dispatch — `symonpayload/dispatch.py`

**BUILT** (12 of 13). The sender is injected, so nothing here knows where an engine is —
in the estate that callable goes through the fabric. `symon-vector-engine` remains unbuilt
because it is the engine itself, not a component of this unit.

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
| VectorInferenceEngine | `symon-vector-engine` | **Not built here.** This is the engine itself — the chat unit on 8802. symonpayload is in front of it, not a second one |

## D. Flow control — `symonpayload/flow.py`

**BUILT.** The measurement it waited for was taken on 2026-09-19: 6.8 tok/s at concurrency 1,
11.2 aggregate at 2, latency p50 19.02 s.

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

## E. Residency and buffers — `symonpayload/residency.py`

**BUILT.** The residency measurement came from ravencalc against the real checkpoint:
32 experts with 4 active, 12.62 MiB per expert per layer, 9.467 GiB for all of them.

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

## F. Sweeps and evaluation — `symonpayload/sweep.py`

**BUILT.** Code and tests on disk. It needed no measurement, which is why it went first of the four.

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
| C. Scheduling and dispatch | 13 | **Built** (12; the 13th is the engine) |
| D. Flow control | 8 | **Built**, tested, against a real measurement |
| E. Residency and buffers | 9 | **Built**, tested, against a real measurement |
| F. Sweeps and evaluation | 10 | **Built**, tested |
| **Total** | **60** | **59 built, 1 not ours** |

## Why C and E are not built

D is built. The measurement it was waiting for was taken once the card came free: a 60-second
benchmark through the gateway at 32k context. The headline is the ratio — concurrency 2 bought
**1.65x, not 2x**, and each stream slowed from 6.84 to 5.6 tok/s. A throttle written against
the assumption of linear scaling would have climbed into a configuration where everyone waits
longer for no more work done.

## All six modules are built

The sixty names are done, bar one. `symon-vector-engine` stays unbuilt because it is the
engine itself — this unit sits in front of it, and building a second one here would be building
the thing the estate already serves.

Three of the six waited on measurements, and all three measurements were taken rather than
assumed:

| module | what it waited for | what was measured |
|---|---|---|
| D. Flow control | observed latency and token rate | 6.8 tok/s at concurrency 1, 11.2 at 2, p50 19.02 s |
| E. Residency | per-device residency | 32 experts, 4 active, 12.62 MiB each per layer |
| C. Dispatch | somewhere to dispatch to | the gateway, reached through an injected sender |

The one that changed the design most was D's: concurrency 2 bought **1.65x, not 2x**, and each
stream slowed from 6.84 to 5.6 tok/s. Written against an assumption of linear scaling, the
throttle would have climbed into a configuration where everyone waits longer for no more work.

## symonpayload — the API, in our names

*Folded in from `api.md` on 2026-09-20: §3.7 allows one
document per directory. Nothing was lost — the original file is at
`/home/google/Desktop/claude/quarantine-3.7-2026-09-20/mnt/SymonSayDistribute/symonpayload/api.md`.*

The supplied API document is a **generic reference**. This page is the SyMoNeuRaL version of
it: our route namespace, our names, and — the part that matters — an honest verdict per route
saying whether the built code can serve the declared shape, or whether serving it would mean
inventing state.

## The namespace is ours, not `/v1/`

The reference puts everything under `/v1/...`. We do not.

`/v1` on this estate is already the **Messages dialect** served by the gateway on 9001:
`/v1/messages`, `/v1/messages/count_tokens`, `/v1/models`, `/v1/models/{model_id}`. That is a
public wire format with independent implementations, and its paths are fixed because clients
expect exactly those. It is the estate's front door for third-party clients.

symonpayload has no third-party client. Nothing outside the host speaks to it. So it has no
business in that namespace, and it follows the convention every other unit here already uses:

    board       /api/board/...
    store       /api/store/...
    agents      /api/agents/...
    ravencalc   /api/ravencalc/...
    symonpayload  /api/symonpayload/...        <- this unit

Garrett's ruling, 2026-09-19: *"if it was up to me we would not use that naming convention we
would make our own."* It is up to him, and we already had our own.

Recorded because it was checked and found false: `/v1/models/instantiation/matrix` was
believed to collide with the gateway's `/v1/models/{model_id}`. It does not — a path parameter
does not cross a `/`, so the pattern is `^/v1/models/([^/]+)$` and a two-segment tail never
matches. The namespace decision stands on the reasons above, not on a collision that is not
there.

## Port and credential

    symonpayload = 8814        # recorded in /models/control.board
    SYM_PAYLOAD_TOKEN     # unset closes the unit (503), it does not open it

8814 was confirmed free before it was taken. Recording the port in `control.board` in the same
change is deliberate: the eight-site documentation defect fixed earlier today was caused by a
service taking a port the map did not record.

## The two verdicts

Every route on this page is served by code that exists. There is no third verdict for a route
that is planned, because a planned route is not carried here at all.

| verdict | meaning |
|---|---|
| **as declared** | the built code serves the reference shape unchanged |
| **amended** | served, but the shape differs — the reason is given, every time |

The reference's shapes assume a **stateful tensor store**: requests carry `tensor_ids` and
responses return new `tensor_ids`. This unit holds no tensors. Serving those shapes would mean
minting uuids for objects that do not exist — a placeholder wearing a 200, which is the thing
that was explicitly banned. Where the underlying arithmetic is real, the route is **amended**
to take and return the shapes themselves.

## Ingress

| reference | SyMoNeuRaL | verdict |
|---|---|---|
| `POST /v1/requests/submit` | `POST /api/symonpayload/requests/submit` | **amended** |
| `POST /v1/requests/batch` | `POST /api/symonpayload/requests/batch` | **amended** |
| `POST /v1/payloads/coalesce` | `POST /api/symonpayload/payloads/coalesce` | **amended** |
| `POST /v1/requests/triage` | `POST /api/symonpayload/requests/triage` | **amended** |

**submit — amended.** The reference takes `{model_id, prompt, parameters}` and returns
`{request_id, status, queued_at}`. Ours requires **`tokens`**, counted by the caller. The
gateway already serves `count_tokens`; a batch formed on a token count estimated from prompt
length is a batch that does not fit, discovered at the engine. `queued_at` is omitted rather
than filled with a timestamp nobody asked for — the queue position is the useful answer and it
is returned.

**triage — amended.** The reference returns `{assigned_priority, estimated_wait_ms,
target_queue}`. We return the lane and the reason, and **not** `estimated_wait_ms`: an
estimated wait is a queue depth divided by a **measured** service rate, and this host has no
measured service rate while the engine holds the card. A wait estimate computed from a guessed
rate is worse than no estimate, because callers act on it.

**coalesce — amended.** The reference returns `{coalesced_payload_id, unified_tensor_shape}`.
We return the **leader request id** and its followers. There is no unified tensor because there
are no tensors here. Coalescing is by the caller's declared fingerprint and nothing else — see
symonpayload.md for why identity is never inferred.

**prioritize — amended.** The reference takes an explicit `priority_level` per item. Ours
orders by **deadline**, and reports the resulting order. An explicit level that can be set
per-call is a way for one caller to jump every queue by asking; a deadline is a claim that can
be checked against the clock.

## Scheduling and queues

| reference | SyMoNeuRaL | verdict |
|---|---|---|
| `GET /v1/inference/queue/status` | `GET /api/symonpayload/queue/status` | **as declared** |
| `POST /v1/inference/queue/prioritize` | `POST /api/symonpayload/queue/prioritize` | **amended** |
| — | `POST /api/symonpayload/batches/form` | **new** — the core of what is built |

**`batches/form` is not in the reference and is the most useful route here.** It forms a batch
and returns which **bound** ended formation — `tokens`, `count`, `window` or `drained`. The
reference has no equivalent, and without it a caller cannot tell a saturated unit from an idle
one. `drained` exists because falling off the end of the pending list is not a limit being hit.

**throughput/metrics is deliberately absent, not forgotten.** It returns `tokens_per_second`,
`requests_per_second` and `vram_utilization_percent`. All three are measurements. Serving them
from anything other than measurement is the defect the whole estate is built to refuse.

## Tensors and tokens

| reference | SyMoNeuRaL | verdict |
|---|---|---|
| `POST /v1/tensors/stack` | `POST /api/symonpayload/shapes/stack` | **amended** |
| `POST /v1/tensors/concatenate` | `POST /api/symonpayload/shapes/concatenate` | **amended** |
| `POST /v1/tokens/batch/sequence` | `POST /api/symonpayload/tokens/plan` | **amended** |
| `POST /v1/tokens/reservoir/fill` | `POST /api/symonpayload/tokens/reservoir` | **as declared** |
| — | `POST /api/symonpayload/shapes/pack` | **new** — packing against padding |

The first three are renamed from `tensors/` to **`shapes/`** because that is what they operate
on. They take shapes and lengths and return shapes, boundaries and costs. They do not take
`tensor_ids` and do not return new ones, because this unit stores no tensors — it answers
"will these stack, and what will it cost", which is the question worth asking before a batch is
formed rather than after it fails.

`tokens/plan` returns the **padding waste**: how many token-slots get allocated to carry how
many real tokens. One 8k sequence among three 200-token ones allocates 32,000 slots to carry
8,600. `shapes/pack` is the alternative — it reorders into rows and wastes less, at the cost of
changing the order, which matters when order is fairness. The caller chooses; neither is the
default.

`data/stage` is **not** the built `symon-staging`. The reference's `{source_data_id,
destination_memory}` is `symon-stager` in module E, which moves data between stages.
`symon-staging` in module B holds formed-but-not-dispatched batches. Different components with
similar names; the name map in this document keeps them apart.

## What is not here, and why it is not

The reference document has twenty-seven routes. Sixteen of them describe components that do
not exist yet, and those routes are **not carried here in any form** — not as a table row, not
as a declared contract, not as a commented-out stub.

Garrett's ruling, 2026-09-19: *"its just a reference — create based off components. If it's an
API and you can't relate it to a component right now, or prospect a component to it, just drop
the API prospect and we will naturally remember it later when the component actually becomes
something we need."*

The direction only runs one way. A component gets built, and then it gets a surface. An API
written first is a promise made by a document, and the thing it promises is judged finished
because the route is written down. The sixteen components are named, sourced and placed in
[the name map](#symonpayload--the-name-map) — that is the record, and it is the right one, because it describes work
rather than an interface to work that has not happened.

When one of them is built, its route gets designed against what it actually does, which is a
better route than one designed against what it was imagined to do.

## Count

Thirteen routes, all of them served by code that exists.

| | routes |
|---|---|
| as declared | 2 |
| amended, with the reason stated on each | 7 |
| new, no reference equivalent | 2 |
| **served** | **11 from the reference, plus 2 of our own** |

Sixteen reference routes are dropped rather than declared. See above.

## gRPC

`symonpayload.proto` in this branch carries the same surface under
`package symoneural.symonpayload.v1`, service `SymonPayloadService`.

**It is a definition and there is no server.** Nothing in this estate speaks gRPC, no consumer
asks for it, and a `.proto` that reads as a live surface is the same phantom the image unit was
just marked for. It is here because the shape is worth recording in a form other tooling can
read, not because anything answers it.

It declares the **thirteen** methods that have code behind them, not the reference's
twenty-seven. An rpc for a component that does not exist is the same phantom in a
machine-readable file, where it is worse.

The supplied proto was reformatted and completed rather than copied: its source ran tokens
together (`serviceAiBatchingService`, `rpcDispatchInference`, `messageIngressFramesResponse`)
and was truncated mid-message across two code fences. It would not have compiled. Saying so
here rather than letting the result look like it arrived clean.

**Not machine-verified.** There is no `protoc` on this host and no `grpc_tools`, and installing
a compiler for a definition-only file was not worth doing unasked. The file is written and
read, not compiled. To check it:

    sudo apt install protobuf-compiler
    protoc --proto_path=/mnt/SymonSayDistribute/symonpayload \
           --descriptor_set_out=/dev/null /mnt/SymonSayDistribute/symonpayload/symonpayload.proto

Until that runs, treat the syntax as unproven.

## Where this leads

Onward, in the order the code runs: [`symonpayload`](symonpayload/symonpayload.md), [`tests`](tests/tests.md).
