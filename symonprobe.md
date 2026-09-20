# symonprobe

The card, the builds, and whether they can run on each other.

This page describes what is **running**: the unit answers on 8817 and everything below was
exercised against this host's real hardware before it was written.

## What this is

Two questions that get confused with each other, answered separately and labelled:

    compute capability   12.0  (sm_120)   a property of the SILICON. Fixed. The RTX 5070 Ti.
    CUDA toolkit         13.0  (cu130)    a property of the BUILD. Chosen when torch was built.

Neither is the other and neither implies the other. On 2026-09-19 a virtual environment named
`vllm-0271-cu130` was read as saying the card was CUDA 13.0 when the card was remembered as
"120". Both numbers were right. Reading one as the other is how a build gets blamed for a card's
limit, or a card for a build's, and the two have opposite fixes.

`fit` answers the only question that settles it:

    does the build's compiled arch list contain this device's compute capability?

Measured here: device `sm_120`, build arch list `sm_75 sm_80 sm_86 sm_90 sm_100 sm_120`,
`runs_here: true`. A name like `cu130` says nothing about that; the arch list is the only thing
that does.

## Finding a parser name by hand took eleven minutes

That is why the rest of this exists. Establishing which tool-call parsers a vLLM offers
required, in order: an import of `vllm.entrypoints.openai.tool_parsers` that failed because the
module moved in this version; an empty registry, because parsers register lazily and importing
the package lists nothing; an `rglob` for files named `*tool_parser*`; and finally reading a
dict out of `__init__.py` by line number.

The answer was three lines. Every step to reach it was version-specific, and documentation for
a different version would have been confidently wrong.

`parsers` reads it out of the installed package statically — no import, so it also describes an
environment too broken to import. And the registered name is not the file name: the parser in
`gptoss_tool_parser.py` is selected as **`openai`**, and guessing from the filename gives a flag
the server rejects.

Measured here: vllm 0.27.1, **45** tool-call parsers, **29** reasoning parsers.

## It suggests, and says so

`suggest` matches a checkpoint against what the runtime registers and returns **candidates**,
never an answer. Asked about `/models/symon` it matched on `gptossforcausallm` out of the
checkpoint's own `config.json` and offered `openai` / `openai_gptoss` — the same pair found by
hand, arrived at independently.

It stops there on purpose. Matching a checkpoint to a parser is a judgement, and a wrong flag
is rejected loudly by the server at start-up, which is a better place to learn it than from a
module that asserted one confidently.

## Nothing here changes anything

Eight routes, all GET. It does not install, configure or start anything, and it never imports
the runtime it is probing into its own process — a probe that needs the thing it is probing
already working cannot describe the environment that is broken, which is when it is most
needed. A test asserts every route is read-only.

    GET /api/symonprobe/health      public; answers before the unit is configured
    GET /api/symonprobe/devices     every GPU, compute capability labelled as silicon
    GET /api/symonprobe/venvs       python environments on this host
    GET /api/symonprobe/build       what an environment was built against
    GET /api/symonprobe/fit         can this build run on this card, and why
    GET /api/symonprobe/packages    installed distributions, filterable
    GET /api/symonprobe/parsers     registered parser names a serving runtime offers
    GET /api/symonprobe/suggest     candidate parsers for a checkpoint, with the evidence
    GET /api/symonprobe/pinned      every version this probe rests on, against its pin

Health is public; the rest need `SYM_PROBE_TOKEN`, and an unset token closes the unit rather
than opening it.

## The probe's own inputs are asserted against their pins (§3.1b-iii)

Every module here exists to stop somebody believing a stale number. `devices()` refuses to let
a compute capability be read as a CUDA version; `fit()` refuses to let a `cu130` in a directory
name stand for "runs on this card". All of those answers come out of programs this estate did
not write — and until now the probe reported their output without ever asking what version
produced it. That is the one failure this unit is least entitled to: a probe whose own inputs
can move underneath it reports yesterday's machine with today's confidence.

`GET /api/symonprobe/pinned?venv=…` runs each one and compares. Measured 2026-09-20 against
`~/.venvs/vllm-0271-cu130`:

| Reads | Where | Pin | Observed | State |
|---|---|---|---|---|
| `nvidia-smi` driver version | `device._nvidia_smi()` | `platform/pins/open-gpu-kernel-modules.json` → 615.71.09 | 615.71.09 | **MATCHES** |
| `torch.__version__` | `device.build()` — the arch list `fit()` decides from | `common/pins/pytorch.json` → v2.14.0 | 2.13.0+cu130 | **DRIFT-RECORDED** |
| `vllm.__version__` | `runtime.parsers()` — the parser names are version-specific | `llm/pins/vllm.json` → v0.29.0 | 0.27.1 | **DRIFT-RECORDED** |
| `torch.version.cuda` | `device.build()` — reported as `cuda_built_against` | none | 13.0 | **NO-PIN** |
| the venv interpreter | `device._venv_python()` | none | CPython 3.12.13 | **NO-PIN** |

**The pin that governs `nvidia-smi` does not nominally name it.** `open-gpu-kernel-modules` is
the open GPU *kernel module* source; `nvidia-smi` is driver userspace. They ship on one release
train and the strings are identical — `nvidia-smi --version` reports the same KMD version —
which is why this pin governs it. Written down because a reader checking the pin file will not
find the word `nvidia-smi` in it.

**The sharpest gap is the CUDA toolkit.** This unit's entire reason for existing is that the
toolkit version and the card's compute capability are different numbers that must never be read
as each other — and one of those two numbers has no record in `SymonSaySource` at all. Closed
by a cuda-toolkit pin. CPython is the second gap, on the same terms.

### Drift is preserved, not resolved

A pin records the **intended** reproducible revision; a checkout records the **observed** one.
Neither was edited to match the other. The assertion is therefore not "everything matches" but
**"nothing moved without being recorded"**: `KNOWN_DRIFT` in `runtime.py` carries each
disagreement with its date and reason, and a version moving to a value not in that table comes
back `DRIFT-NEW` and fails a test.

One source failing does not silence the census: a venv with no importable vLLM still yields a
driver answer and a torch answer, because a census that dies on its first failure turns one
missing package into "nothing is checked". A test asserts exactly that.

**Why this lives in `runtime.py`.** It was written as `pins.py` first and `no-divergent-copy`
refused every commit in the estate for it — the gate compares by basename across all four
trees. It sits in `runtime.py` rather than `device.py` because `runtime.py` already depends on
`device.py`, so the census can read the card and the build without a circular import.

## Placement

    placement-triage prospect symonprobe --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

The standard library plus FastAPI, with `nvidia-smi` and the probed environment's own
interpreter invoked as commands. Nothing copyleft.

## Testing

14 tests, asserting invariants and refusals rather than today's numbers — asserting 16303 MiB
would fail the day the card changes, which is the day these should still work. So: compute
capability is labelled as silicon and not as a CUDA version; `fit` reports both numbers
separately and asserts they differ; `fit` decides on the arch list rather than the name; a build
missing this arch is reported unfit with the reason; a registered parser name is never a file
name; a candidate is offered only if the runtime actually registers it; every route is read-only.

## Releases

Tagged `symonprobe/v<version>`.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonprobe`](symonprobe/symonprobe.md) | the capability this unit provides — `device.py`, `runtime.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symonprobe`](symonprobe/symonprobe.md), [`tests`](tests/tests.md).
