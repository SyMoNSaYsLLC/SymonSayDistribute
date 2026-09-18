# SymonSayDistribute

The distribution. One branch per runtime, each cutting its own releases.

SyMoNeuRaL builds a multi-runtime estate from pristine upstream source. The runtimes do not
move together: one can be shipping while another is mid-rebuild, on hold for a licence
ruling, or waiting on hardware. A single trunk forces them to, and the slowest one sets the
pace for all of them.

So each runtime owns a branch, and a branch cuts its own releases. A hold on one runtime
stops that runtime and nothing else.

## How it is laid out

| Branch | Holds |
|---|---|
| `main` | this index, and nothing else — no code ever lands here |
| `workflow` | the release machinery every runtime branch uses: the ship gate, the wheel builder, the archiver, the cutter, the installer |
| one per runtime | that runtime's source, its own documentation, its own history |

`main` carries no code on purpose. A reader arriving at the repository needs to know which
branch to go to before they need anything else, and an index that also holds source drifts
from the branches it describes.

## Releases

A release belongs to a runtime, so its tag names one:

```
<runtime>/v<major>.<minor>.<patch>
```

`symoneural-learn/v1.3.0` is the fourth release of that runtime and says nothing about any
other. Two runtimes may sit at the same version number and mean entirely different things;
the prefix is what makes the number readable.

Every release is cut by the machinery on `workflow`, which refuses to publish unless the
ship gate passes: licence class for every component, secrets by content and by path,
weights, trademarks, known vulnerabilities, and the identifiers a build record can leak.

## Runtimes

Thirteen runtimes and seventeen recipe groups exist in the estate. They arrive here as
branches as each becomes releasable; a runtime with no branch yet is not missing, it is not
ready.

| Runtime | Branch | State |
|---|---|---|
| `symoneural-learn` | `symoneural-learn` | releasing — four releases cut |
| adaptive-fabric, api, build, cli, common, crypto, image, live, llm, ravencalc, remix, streamer, web | — | in the estate, not yet on a branch |

## Adding a runtime

1. Push its source to a branch named after it. History comes with it; a runtime that
   arrives with no history arrives with no provenance.
2. Add a row to the table above, on `main`, saying what it is and what state it is in.
3. Cut from it with the machinery on `workflow`. The first release proves the branch, and
   the gate decides whether it ships.

## The other two repositories

This is one of three, and the split is the same on disk as it is here.

| Repository | Holds | Licence of what it ships |
|---|---|---|
| **`SymonSayDistribute`** | the runtimes, one branch each, each cutting its own releases | FSL-1.1-ALv2, and no copyleft |
| `SymonSaySource` | what we build from: pins, licences, provenance — never the source bytes | tracking only; ships nothing |
| `SymonSayOpen` | the copyleft builds | MIT metadata; the outputs stay copyleft |

**Nothing from `SymonSayOpen` may be linked into a release here.** The ship gate fails on any
strong copyleft component, so the rule is enforced rather than trusted — but enforcement is
easier to believe when the two sides were never in the same tree.

## Licence

Every branch here ships under FSL-1.1-ALv2: source-available now, Apache-2.0 two years after
each release. See the `LICENSE` file on any runtime branch. `SymonSayOpen` is deliberately
MIT instead; different licences make the split a statement rather than a directory
convention.

## The licence boundary

These four trees carry **two** licences between them, and that is the point of the split:

| Licence | Where | Why there |
|---|---|---|
| `FSL-1.1-ALv2` | `SymonSayDistribute` | the product: source-available now, Apache-2.0 two years after each release |
| `MIT` | `SymonSayOSS`, `SymonSayOpen`, `SymonSaySource` | work meant to combine freely — with copyleft, with anyone's code, with itself |

Two rules follow, and they are not the same rule:

**A licence deviation inside a tree is a new branch.** If one component in a tree cannot carry
that tree's licence — an upstream obligation, a contributed file with its own terms — it gets
its own branch, and that branch states the licence at the top of its document. A tree stays
readable because every branch in it either carries the tree's licence or says plainly that it
does not.

**A genuinely third licence is a new tree.** If something needs terms that are neither of the
two above — a copyleft obligation on our own code, a third-party commercial licence, an
agreement with its own conditions — it does not go on a branch here. It becomes its own
repository at `/mnt/<repo>`, with its own index, because a tree whose licence you cannot state
in one line is a tree nobody can ship from.

Anything that fits none of the four is raised rather than guessed at, and work continues around
it instead of stopping on it.
