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

Every route is a GET. It starts nothing and serves nothing; it reports on a build that would.

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
