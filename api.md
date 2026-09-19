# ravenbatch — the API, in our names

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

ravenbatch has no third-party client. Nothing outside the host speaks to it. So it has no
business in that namespace, and it follows the convention every other unit here already uses:

    board       /api/board/...
    store       /api/store/...
    agents      /api/agents/...
    ravencalc   /api/ravencalc/...
    ravenbatch  /api/ravenbatch/...        <- this unit

Garrett's ruling, 2026-09-19: *"if it was up to me we would not use that naming convention we
would make our own."* It is up to him, and we already had our own.

Recorded because it was checked and found false: `/v1/models/instantiation/matrix` was
believed to collide with the gateway's `/v1/models/{model_id}`. It does not — a path parameter
does not cross a `/`, so the pattern is `^/v1/models/([^/]+)$` and a two-segment tail never
matches. The namespace decision stands on the reasons above, not on a collision that is not
there.

## Port and credential

    ravenbatch = 8814        # recorded in /models/control.board
    SYM_RAVENBATCH_TOKEN     # unset closes the unit (503), it does not open it

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
| `POST /v1/requests/submit` | `POST /api/ravenbatch/requests/submit` | **amended** |
| `POST /v1/requests/batch` | `POST /api/ravenbatch/requests/batch` | **amended** |
| `POST /v1/payloads/coalesce` | `POST /api/ravenbatch/payloads/coalesce` | **amended** |
| `POST /v1/requests/triage` | `POST /api/ravenbatch/requests/triage` | **amended** |

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
ravenbatch.md for why identity is never inferred.

**prioritize — amended.** The reference takes an explicit `priority_level` per item. Ours
orders by **deadline**, and reports the resulting order. An explicit level that can be set
per-call is a way for one caller to jump every queue by asking; a deadline is a claim that can
be checked against the clock.

## Scheduling and queues

| reference | SyMoNeuRaL | verdict |
|---|---|---|
| `GET /v1/inference/queue/status` | `GET /api/ravenbatch/queue/status` | **as declared** |
| `POST /v1/inference/queue/prioritize` | `POST /api/ravenbatch/queue/prioritize` | **amended** |
| — | `POST /api/ravenbatch/batches/form` | **new** — the core of what is built |

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
| `POST /v1/tensors/stack` | `POST /api/ravenbatch/shapes/stack` | **amended** |
| `POST /v1/tensors/concatenate` | `POST /api/ravenbatch/shapes/concatenate` | **amended** |
| `POST /v1/tokens/batch/sequence` | `POST /api/ravenbatch/tokens/plan` | **amended** |
| `POST /v1/tokens/reservoir/fill` | `POST /api/ravenbatch/tokens/reservoir` | **as declared** |
| — | `POST /api/ravenbatch/shapes/pack` | **new** — packing against padding |

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
similar names; NAMES.md keeps them apart.

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
[NAMES.md](NAMES.md) — that is the record, and it is the right one, because it describes work
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

`ravenbatch.proto` in this branch carries the same surface under
`package symoneural.ravenbatch.v1`, service `RavenBatchService`.

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
    protoc --proto_path=/mnt/SymonSayDistribute/ravenbatch \
           --descriptor_set_out=/dev/null /mnt/SymonSayDistribute/ravenbatch/ravenbatch.proto

Until that runs, treat the syntax as unproven.