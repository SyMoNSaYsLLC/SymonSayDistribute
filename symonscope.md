# symonscope

What this estate actually is, read from disk.

This page describes what is **running**: the unit answers on 8815, its three connectors are
registered with the agents runtime, and both were exercised end to end before this was written.

## What this is

Every list of this estate's components has gone stale, because a list is written once and the
estate changes afterwards. symonscope does not hold a list. It walks the four trees and answers
from what is there, so it is wrong only when disk is wrong — and then it is reporting a real
problem rather than an old opinion.

It was built because a four-agent survey was run by hand to answer "what are the components and
how do they layer". That survey was right, took six minutes, cost 362,000 tokens, and was
obsolete the moment a branch was renamed — which happened while it was still running. This is
the same job as a function that takes about a second.

## It does not write

Every route is a GET and there is no code path that creates, modifies or deletes anything. That
is not an omission to be filled in later: a surveyor that can change what it surveys is a
surveyor whose answers cannot be trusted. A test asserts it, so a writing route cannot be added
without the test failing.

## What it answers

    GET /api/symonscope/health           public; answers before the unit is configured
    GET /api/symonscope/trees            the four trees, present or absent, units and tags
    GET /api/symonscope/units            every unit: what it says it is, its kind, port, releases
    GET /api/symonscope/subcomponents    the components INSIDE each unit
    GET /api/symonscope/edges            every dependency, with the file and line proving it
    GET /api/symonscope/layers           layers derived from those edges
    GET /api/symonscope/live             what is running against what is declared
    GET /api/symonscope/survey           all of it, in one call — this is the one symon calls

Health is public; the rest need `SYM_SCOPE_TOKEN`, and an unset token closes the unit rather
than opening it.

## Layers are derived, never declared

A hand-written layer list is correct on the day it is written and drifts every day after. A
unit's layer here is one more than the deepest thing it depends on, recomputed on every call.
There is nothing to keep in step because there is nothing written down to fall out of step
with. Layer 0 is a **provider**: it depends on no other unit, so everything may rest on it.

**A cycle is a refusal, not a diagram.** If A depends on B and B on A, the estate is not
layered and no honest number exists. symonscope reports the cycle and leaves those units
unplaced rather than picking a layer and making the architecture look sound.

## An edge carries its evidence or it is not an edge

An architecture diagram is a claim. An edge here is a file and a line number. Anything without
that is not reported, which is how an intention ends up drawn as a wire — and this unit found
exactly that on its first run: `symonpayload.md` says "the arithmetic belongs to ravencalc",
and there is no edge. A sentence is not a wire.

## What it found the first time it ran

Recorded because a tool that finds nothing on its first run is usually a tool that cannot find
anything:

- **`symonpayload` has no edges in either direction.** Built, tested, tagged, renamed, and
  never wired in. The gateway still relays straight to the engine, which is the bypass that
  unit exists to prevent.
- **A cycle between `agents` and `symoneural-learn`.** It is not a cycle in the software: the
  web interface calls `agents`, `agents` calls the gateway, and web and gateway are two
  different components sharing one branch. `subcomponents` exists because of this — a cycle
  that disappears when you look closer was never a cycle in the design, only in the naming.
- **The gateway on 9001 is running from `/home/google/symonsaylearn/work/runtimes/api/app`,
  not from the released tree.** What is serving is not what is released.
- **`gates` has no edges at all.** No unit runs a gate; the gates run as git hooks.

## Wired to symon

Three connectors are registered with the agents runtime, so a model can reach this as a tool
rather than being told the architecture in a prompt that goes stale:

    estate_survey    everything, in one call
    estate_layers    what rests on what, and any cycle
    estate_live      what is running against what is declared

`estate_survey` is deliberately one call rather than six. A question a model has to know the
shape of in advance is a question it will not ask.

## Placement

    placement-triage prospect symonscope --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

The standard library, plus FastAPI for the surface, plus `git` and `ss` invoked as commands.
Nothing copyleft, so the default applies.

## Testing

19 tests. The ones that matter are the refusals and the invariants, not today's unit list —
asserting the current components would make the tests fail every time the estate changes, which
is the opposite of what this unit is for. So: an unknown tree is refused and the real four are
named, a directory with no `.bare` is not an estate tree, every route is a GET, every edge
carries a file and a line, no edge points at itself, a synthetic cycle is detected and leaves
its units unplaced, and a synthetic chain layers cleanly to 0/1/2.

## Releases

Tagged `symonscope/v<version>`.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonscope`](symonscope/symonscope.md) | the capability this unit provides — `edges.py`, `layers.py`, `live.py`, `survey.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symonscope`](symonscope/symonscope.md), [`tests`](tests/tests.md).
