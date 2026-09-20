# symonengine

What the serving build can actually do, asked of the build.

This page describes what is **running**: the unit answers on 8821, and every figure below was
read out of the installed runtime before this was written.

## Why this is not a feature list in a document

A capability written down is correct for the version it was written against. This build —
vLLM 0.27.1 — supports **367 model architectures** and **31 quantization methods**. The next
version supports a different set, and a document saying otherwise is confidently wrong at
exactly the moment somebody relies on it.

So this asks the installed package, in its own interpreter, every time.

## The question worth asking

Not "what does it support" in the abstract, but **can this build serve this checkpoint**. That
has a real answer, and both halves are checkable: the architecture is in the registry or it is
not, and the quantization method is in the list or it is not.

Against symon:

    architectures declared   GptOssForCausalLM       supported
    quantization declared    mxfp4                   supported
    serves                   true

A checkpoint that declares neither is reported `null`, not `true`. **A checkpoint that says
nothing about itself has not been approved by silence.**

It also states what it did *not* check: whether the checkpoint fits the card, which is memory
and belongs to ravencalc and symonprobe, and whether the weights are intact, which belongs to
model-store. A capability answer that quietly implied those would be the more dangerous kind of
wrong.

## A feature flag says where it looked

The first version of the feature probe named one module per feature and reported three features
**absent** that this build plainly has — `prefix_caching`, `speculative_decoding` and
`structured_outputs` all moved to `vllm.v1.*` in 0.27.1. It also used `find_spec`, which
**raises** when a parent package is missing rather than returning `None`, so "`vllm.core` is
gone" was caught by an `except` and became "prefix caching is not supported".

A capability report that says `false` because it looked in the wrong place is worse than one
that says nothing. So every candidate path is recorded beside the answer:

    prefix_caching   present  found_at vllm.v1.core        looked_in [vllm.v1.core, vllm.core.block...]

All eight features are present here, and a `false` can be checked rather than believed.

## Not duplicated

Tool-call and reasoning parser names are capabilities of this same build, and
[symonprobe](../symonprobe/symonprobe.md) already reads them. Asking twice in two components is
how two answers start disagreeing, so this defers and says where to look.

## Routes

    GET /api/symonengine/health     public; answers before the unit is configured
    GET /api/symonengine/surface    everything: architectures, quantization, features, versions
    GET /api/symonengine/summary    the same as counts, when the full lists are not the question
    GET /api/symonengine/supports   is one architecture or method in this build, by exact name
    GET /api/symonengine/serves     can this build serve this checkpoint, and why
    GET /api/symonengine/pinned     what this build carries, against its pin in SymonSaySource

Every route is a GET. It starts nothing and serves nothing; it reports on a build that would.

## The build it reads is asserted against its pin (§3.1b-iii)

Everything above is read out of a vLLM and a torch this estate did not write, in an interpreter
it did not build. Invoking them is allowed — it is what keeps their licences out of our
artifacts. Invoking them **blind** is not, and every count on this page is a property of one
specific vLLM: the day it moves underneath us, the architecture list, the quantization list and
every feature flag change with nothing to say so.

`GET /api/symonengine/pinned?venv=…` asks the same build what it carries and compares it to
`SymonSaySource`. It re-uses `surface()` rather than starting a second interpreter, because the
version that governs is the one belonging to the build that answered the capability question.
It is **per venv**, like `surface()` itself, because the two vLLM environments on this host
disagree with each other and one module-level answer would be quietly wrong about one of them.

Measured 2026-09-20 against `~/.venvs/vllm-0271-cu130`, the default:

| Reads | Pin | Observed | State |
|---|---|---|---|
| `vllm.__version__` | `llm/pins/vllm.json` → v0.29.0 | 0.27.1 | **DRIFT-RECORDED** |
| `torch.__version__` | `common/pins/pytorch.json` → v2.14.0 | 2.13.0+cu130 | **DRIFT-RECORDED** |
| the venv interpreter | none | CPython 3.12.13 | **NO-PIN** |

### Drift is preserved, not resolved

A pin records the **intended** reproducible revision; a checkout records the **observed** one.
Where they disagree, neither is edited to match the other — provenance settles that, and until
it does the disagreement is a fact to carry rather than a mess to tidy. No pin was rewritten and
no checkout was moved to produce the table above.

So the assertion is not "everything matches". It is **"nothing moved without being recorded"**.
`KNOWN_DRIFT` in `capability.py` carries each disagreement with its date and its reason, and a
version that moves to a value not in that table comes back `DRIFT-NEW` and fails a test. A
permanently red suite is one nobody reads; a green one over unrecorded drift is the blind
invocation the rule forbids. This is the shape that is neither.

**The gap: CPython has no pin.** None of the 108 pins in `SymonSaySource` records an
interpreter, and the probe's own results depend on one — `importlib.util.find_spec` semantics
are interpreter behaviour, and getting them wrong is what once reported three present features
as absent. Closed by a cpython pin under `SymonSaySource`.

**Why this lives in `capability.py` and not in a `pins.py`.** It was written as `pins.py` first
and `no-divergent-copy` refused every commit in the estate for it: the gate compares by
basename across all four trees, and a second component carrying the same obvious filename is
exactly the divergence it exists to catch. Every unit here keeps its pin comparison inside its
own uniquely named domain module — `board.py`, `toolchains.py`, `imager.py` — and no component
imports another.

## Placement

    placement-triage prospect symonengine --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

vLLM is invoked as a separate interpreter and never imported here, so it is not a component of
this artifact.

## Testing

15 tests, asserting invariants rather than today's counts — asserting 367 architectures would
fail the day vLLM is upgraded, which is the day these should still work. So: every feature
records the paths it looked in, the three features that moved are still found and were looked
for in more than one place, counts match the lists they count, the surface names how it was
obtained, parsers are deferred rather than duplicated, an unsupported architecture is refused
with the registry size, an unsupported quantization is refused by name, and a checkpoint
declaring nothing returns null rather than true.

## Releases

Tagged `symonengine/v<version>`.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonengine`](symonengine/symonengine.md) | the capability this unit provides — `capability.py`, `pins.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symonengine`](symonengine/symonengine.md), [`tests`](tests/tests.md).
