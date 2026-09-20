# ravencalc

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

The estate's computation runtime. Symbolic and numeric evaluation — simplify, solve, arbitrary
precision, linear systems, integration — and the model arithmetic every serving decision rests on.

## Why it matters that this exists

Arithmetic was being done in throwaway interpreter one-liners scattered across the estate. A
sweep of both disks found **82 calculations**, none of which had a route into this runtime. The
consequences were not theoretical:

- the same 16 GB card was recorded four different ways — 16 GB, 15.56 GiB, 15.92 GiB, and
  "15.8 of 16.3" — and the GPU lock arbitrated on one figure while the launcher sized against
  another
- one script computed the median two different ways, in the same file
- one file converted bytes to human units two different ways, in the same file, one of them
  printing GiB as GB
- elapsed time was implemented five times across two languages

A number computed in a one-liner has no route, no record, no version, and cannot be reproduced.
That is what this runtime is for.

## The model arithmetic

`model.py` sizes a checkpoint from the checkpoint, never from its name or its advertised size.

**Tensor sizes come from the safetensors header** — the real dtype and byte offsets of every
tensor. Verified against the index's declared total on the 20B checkpoint: 459 tensors,
13,761,264,768 bytes, exact to the byte.

**KV cache accounts for two things that are usually missed.** It is sized by
`num_key_value_heads`, not `num_attention_heads` — using the attention count overstates it
eightfold under grouped-query attention. And a layer marked sliding never caches more than
`sliding_window` positions however long the context is: on this checkpoint twelve sliding layers
cost 3 MiB against the twelve full layers' 384 MiB.

**`gpu_fraction` takes the reserve and the ceiling as arguments with no defaults**, because they
are policy about a machine and not properties of a model. It also answers `fits`, which the
fraction alone cannot: a fraction can be perfectly computed and still name less memory than the
model requires.

## What it refuses to do

It does not estimate. A quantity that cannot be derived from the files is an argument the caller
must supply, and a missing one raises rather than defaulting.

`transfer_ms` has no default bandwidth at all. Bandwidth is a property of the machine and the
moment, and a plausible constant there manufactures a token-rate figure with nothing behind it.
That is exactly how a confident and unfounded number reached a report earlier the same day.

## Recorded substitution (rules 3.10)

`compute.py` intends to resolve every import to an estate package — `symoneural-sympy`,
`symoneural-mpmath`, `symoneural-numpy`, `symoneural-scipy`, `symoneural-scikit-learn`, built
from pinned source against `symoneural-openblas`. On this host they resolve to the
distribution's own packages under `/usr/lib/python3/dist-packages`. The estate packages are not
built.

`backends()` reports the real path of every backend it loaded, so the substitution is visible in
the answer and not only in a comment. No result should be described as computed by an estate
package until those paths change. The condition that ends this substitution is those five
packages existing in the deploy set.

## Testing

Ten tests, and the ones that matter are the refusals: a config missing what it needs, a sliding
layer with no window declared, layer types that do not match the layer count, a nonsense context
or concurrency, a bandwidth of zero, a directory with no tensors, more active experts than exist.

## Releases

This branch cuts its own releases, tagged `ravencalc/v<version>`. Expect many: the calculations
get adjusted as the estate learns what it actually costs to serve.

## Over HTTP

Thirteen routes on `127.0.0.1:8801`, the port `/models/control.board` assigns to `ravencalc`.
Health and backends are public; every calculation needs `SYM_RAVENCALC_TOKEN`.

    GET  /api/ravencalc/health                public; answers before anything is configured
    GET  /api/ravencalc/backends              which computation backends are actually present
    POST /api/ravencalc/simplify              symbolic simplification
    POST /api/ravencalc/solve                 solve for a symbol
    POST /api/ravencalc/precise               arbitrary-precision evaluation
    POST /api/ravencalc/matrix-solve          linear systems
    POST /api/ravencalc/integrate             definite and indefinite integration

The model arithmetic is separate because it reads a checkpoint rather than an expression:

    POST /api/ravencalc/model/tensors         shapes and dtypes from the safetensors headers
    POST /api/ravencalc/model/kv-cache        cache size from num_key_value_heads, not heads
    POST /api/ravencalc/model/experts         which experts are resident, and what that costs
    POST /api/ravencalc/model/transfer        page-in time; refuses without a measured bandwidth
    POST /api/ravencalc/model/budget          what fits, given a card and a context
    POST /api/ravencalc/model/gpu-fraction    (free - reserve) / total, with no default reserve

None of these carries a default for a quantity that must be measured. A missing bandwidth, a
missing reserve or a config that does not declare its layer types is a refusal with a reason,
never a number produced from an assumption — that is the whole point of the unit existing.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symoneural_ravencalc`](symoneural_ravencalc/symoneural_ravencalc.md) | the capability this unit provides — `compute.py`, `model.py`, `service.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 2 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symoneural_ravencalc`](symoneural_ravencalc/symoneural_ravencalc.md), [`tests`](tests/tests.md).
