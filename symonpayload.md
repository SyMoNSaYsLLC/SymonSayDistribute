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

## Not built yet

Four modules are named in [NAMES.md](NAMES.md) with their sources recorded, and have no code:
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
[api.md](api.md) for the full mapping from the generic reference, with a verdict on every
route.

**Policy has no defaults over HTTP either.** `SYM_PAYLOAD_MAX_TOKENS` and
`SYM_PAYLOAD_CAPACITY` are read from the environment and the unit answers 503 naming the
missing variable rather than picking a number. A 503 that names a knob is something an
operator can fix; a default is a decision nobody made.

**The API is derived from the components, never the other way round.** The reference document
has twenty-seven routes; sixteen describe components that do not exist, and those are not
carried anywhere — no stub, no 501, no declared contract. Their components stay named and
placed in [NAMES.md](NAMES.md), and each gets a route designed against what it actually does
once it is built, which is a better route than one designed against what it was imagined to
do.

## Releases

Tagged `symonpayload/v<version>`.
