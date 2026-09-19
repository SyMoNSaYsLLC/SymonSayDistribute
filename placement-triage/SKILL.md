---
name: placement-triage
description: Decide where a thing belongs in the SyMoNeuRaL estate — which licence it carries and which repository holds it. Use when anything new is built, acquired, found unclassified, or is about to be released, and whenever a licence question arises about existing work. Applies the placement procedure: proprietary by default, open source only when copyleft is forced, and a question to Garrett when neither fits.
license: SymonSaysLLC Proprietary License 1.0
---

# Placement triage

Every thing in this estate has to answer two questions before it can move: which of the two
SymonSaysLLC licences does it carry, and which repository holds it. This skill answers both
from what is on disk, and refuses to answer when the evidence does not support one.

## Ask these, in order, in writing

1. What is it?
2. What does it do?
3. Is it built?
4. If not built, what will building it take?
5. If built, was it built to a release under a SymonSaysLLC licence?
6. Which licence was it built with?
7. Does building it need copyleft sources?
8. If so, how can those be avoided?
9. If they cannot be avoided, has Garrett been told that copyleft appears to be the only path?
10. Where should it live — for now, and permanently?
11. Does a release of it already exist?

The order matters. A later answer usually depends on an earlier one being honest, and the
commonest failure is answering ten before seven.

## Then apply the flow

**A release is anything that does something.** There is no further test — not whether it is a
runtime, not whether it is large or interesting. The only requirement is that it carries a
SymonSaysLLC licence.

**L2, the licence.** The SymonSaysLLC Proprietary License by **default**. The SymonSaysLLC
Open Source License **only** when the sources needed to build it are copyleft and that cannot
be avoided. Proprietary is the default, not the fallback. Usefulness, generality and
generosity are **not** reasons to choose open source — that is the mistake this skill exists
to stop.

**L3, the repository.** `SymonSayDistribute` for proprietary, `SymonSayOSS` for open source.
It gets a branch and that branch cuts its own releases. `SymonSaySource` records what we build
from and `SymonSayOpen` holds builds whose output is copyleft; **neither is a destination for
a new thing.**

**Neither fits?** Present it to Garrett. Do not guess, and do not stop other work while
waiting for the answer.

**L1, both targets.** `github.com/symonsaysllc/` holds the code as a branch with releases, and
`symoneural.com/` is where a person outside the machine reaches it — download, description,
updates, demo, payment. A thing with a repository and nothing on the site is a thing nobody
can get, so the assignment is not finished until both halves are named.

## The distinction that decides everything

A copyleft component used to **build** something does not make the output copyleft. A copyleft
component **linked into** the shipped artifact does.

A GPL compiler, a GPL build system, a GPL code generator: none of them travel. A GPL library
in the binary does. Getting this backwards puts a product in the open source tree or a genuine
obligation in the proprietary one, and both are expensive to undo after a release.

For LGPL specifically, ask how it is linked. Dynamic linking does not force the combined work
open; static linking does.

## Run it

    scripts/triage.py <path> [<path> ...] [--name NAME] [--json]

It reads licence files, SPDX headers, recipe `LICENSE` and `DEPENDS` fields, Python imports and
ELF `NEEDED` entries, classifies each finding by obligation rather than by name, and separates
what is linked from what is only used to build. Then it applies the flow.

It reports one of four outcomes:

- **SymonSayDistribute**, proprietary, because nothing copyleft is linked in
- **SymonSayOSS**, open source, because copyleft is linked in and that is forced
- **PRESENT_TO_GARRETT**, because something declares copyleft but nothing shows it reaching a
  shipped artifact, or because no licence evidence was found at all
- **ALREADY PLACED**, because the path is inside Source or Open, which are not destinations

`--json` gives the same verdict with the full evidence, for feeding into a larger sweep.

## What it will not do

It does not move, write or commit anything. It does not decide what it cannot evidence.
Absence of a licence is never read as permission. Where it says PRESENT_TO_GARRETT it means it:
a guess there is worse than a question, because a wrong placement is only discovered when
somebody's counsel reads it.

## Files

- `scripts/triage.py` — the engine
- `scripts/licences.json` — SPDX identifier to obligation class, and the build-tool list
- `REFERENCE.md` — worked examples, and the failures each rule came from
