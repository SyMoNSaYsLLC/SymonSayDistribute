# ravenbatch

Admission and batch formation for the estate's inference path.

This page describes what is **built**: the two modules below have tests that run, and the
four named in "Not built yet" are named and sourced and have no code.

## What this is

The gateway on 9001 relays each request straight to the engine on 8802. There is no queue, no
ordering, no ceiling on what is in flight, and no way to refuse work before it costs anything.
That holds until two callers arrive at once, and then the failure surfaces as a timeout
somewhere downstream with nothing to say which request caused it or why it was accepted.

ravenbatch is the layer that goes in front: work is refused at the door with a reason, or it is
admitted and accounted for. There is no third state where something is in the building and
nobody knows.

## Placement

    placement-triage prospect ravenbatch --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

One source, and it is the standard library. vLLM, llama.cpp and OpenAI Triton are on this host
and all three are permissive, so naming them would not have changed the verdict — which is why
naming them would have been wrong. Nothing here copies a line from them or links against them.
They are prior art, and a source list that names things the artifact does not contain inflates
the census the ship gate runs.

## Built: admission — `symoneural_ravenbatch/admit.py`

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

## Built: formation — `symoneural_ravenbatch/form.py`

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

50 tests, and most of them are refusals: ingress at capacity naming the number, a token ceiling
naming both numbers, a request too large to ever batch saying it belonged at admission, ragged
stacking, padding below the longest member, a missing body named by id, an empty batch that
cannot be constructed at all.

    cd /mnt/SymonSayDistribute/ravenbatch && python3 -m pytest tests/ -q

## Not built yet

Four modules are named in [NAMES.md](NAMES.md) with their sources recorded, and have no code:
dispatch (C), flow control (D), residency (E), sweeps (F).

They are not built because they need **measured** inputs this host cannot give while the engine
holds the card: observed latency, observed token rate, per-device residency. An
`AdaptiveThrottle` that moves a ceiling on an invented number is exactly the "number produced
from an assumption" that ravencalc exists to refuse. Building them against guesses would have
produced four modules that pass their own tests and are wrong on the machine.

## No HTTP surface yet

ravenbatch is a library at this version. The surface belongs with dispatch, because the routes
worth exposing are "what is queued", "what is forming" and "what was sent" — and the last of
those does not exist yet. A service exposing two of three would need a port and a token to
answer half a question.

## Releases

Tagged `ravenbatch/v<version>`.
