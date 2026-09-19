---
name: copyleft-trace
description: Determine whether a copyleft obligation actually reaches a shipped artifact, by walking what a binary really links rather than what a recipe declares. Use before placing anything in a repository, before any release, whenever a licence audit flags something, and whenever someone claims a component "is GPL" — because building with a copyleft tool and shipping a copyleft library are different facts with different consequences.
license: SymonSaysLLC Proprietary License 1.0
---

# Copyleft trace

## The distinction this exists for

A copyleft component used to **build** something does not make the output copyleft. A copyleft
component **linked into** the shipped artifact does.

A GPL compiler, a GPL build system, a GPL code generator: none of them travel into what you
ship. A GPL library inside the binary does. Every licence argument in this estate is downstream
of that one fact, and getting it backwards is expensive in both directions — it either drags a
product into the open source tree for no reason, or hides a real obligation inside a
proprietary release until somebody's counsel finds it.

## Evidence, not declaration

A recipe's `DEPENDS` line is not evidence of linkage. It says what was needed to build. The
evidence of linkage is the `NEEDED` entry in the binary, because that is what the loader will
actually go and find at run time.

    scripts/trace.py <binary-or-directory> [...] [--json]

It walks the dependency graph transitively, resolves each library the way the loader would,
and reports the obligation of each one.

## Two exceptions that defeat an obligation

**The GCC runtime.** `libgcc`, `libstdc++`, `libgomp` and `libgfortran` are GPL-3.0-or-later
*with the GCC runtime exception*. That exception exists precisely so compiling with GCC does
not make your work GPL. Seeing GPL-3 beside `libstdc++` and concluding the artifact is
copyleft is the single commonest false positive in a licence audit.

**LGPL, dynamically linked.** Dynamic linking against LGPL does not force the combined work
open. Static linking does. The difference is visible in exactly the place you would expect: a
dynamic dependency appears in `NEEDED`, a static one does not appear at all because it is
already inside the binary.

## What it cannot see, and says so

A statically linked library leaves no trace in `NEEDED`. If a build statically links LGPL or
GPL code, this tool cannot find it, and it prints that caveat every run rather than letting a
clean report be mistaken for a complete one. When static linking is possible, read the build
flags.

## Unknown is not clean

A dependency whose licence cannot be established is reported as unresolved and routes to a
human. It is never folded into "no copyleft found". Absence of evidence is not evidence of a
permissive licence, and a default applied over an unknown is how a wrong placement gets made
confidently.

## Feeding it into placement

The verdict here is the input to the `placement-triage` skill: copyleft genuinely linked in
means the open source licence and `SymonSayOSS`; nothing linked in means the default,
proprietary and `SymonSayDistribute`; unresolved means neither, and a question.
