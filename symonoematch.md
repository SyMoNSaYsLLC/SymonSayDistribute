# symonoematch

Naming a prospect's sources and reading their licences, from the local index.

This page describes what is **built and tested**: 74 tests pass against the real corpus,
every gate in the suite returns 0, and every figure quoted below was
read from disk by the code on this branch. It is not yet running as a service — see **Status**
at the end.

## What this is for

§3.1b-i is the hardest placement rule in the estate, and it runs in a fixed order: **name the
sources, then read the licence off them** — "not chosen, not preferred, not assumed: read."
Proprietary is the default. Copyleft is reached only when no other variant of the capability
exists, and that is a claim carrying a burden of proof: it is recorded **with what was
searched**, not merely asserted. Garrett: "this should really never happen with all the
available component source code available on the web and downloaded to the machine."

There was a local index of 479 layers and 39507 recipes on this machine that answered exactly
that question, and nothing used it. This turns the rule from a manual search into a query.

**The worked example the rule describes, in one call.** Step 1 names a source; step 2 reads its
licence:

    GET /api/symonoematch/layers?q=mingw

    name              meta-mingw
    licence           MIT              (class: permissive)
    vcs_url           https://git.yoctoproject.org/meta-mingw
    branch            master
    local_path        /home/google/.cache/oematch/layers/meta-mingw   exists: True

The licence was not chosen. It was read off the named source, and `local_path_exists` was read
off the disk rather than trusted from the row — a layer whose cached checkout has gone is the
difference between "we have this" and "we had it".

**The route that matters is `permissive`.** It asks the §3.1b-i question directly and answers it
with the record the rule demands:

    GET /api/symonoematch/permissive?q=compression

    asked      compression
    searched   "compression"
    found      true
    counts     permissive 101, copyleft 45, unlicensed 4
    complete   true

    permissive  aws-c-compression         0.3.2    Apache-2.0      meta-aws
    permissive  rosbag2-compression-zstd  0.33.1-1 Apache-2.0      meta-ros2-rolling
    copyleft    xdelta3                   3.1.0    GPL-2.0-only    meta-oe

`searched` is the field that makes this worth having. A conclusion without the query that
produced it is the thing §3.1b-i forbids — "recording copyleft without recording what was
looked at and rejected". The string reported is the one actually handed to the index, not a
tidied version of the caller's words.

`find` answers the same corpus with **permissive first and copyleft last**, because the rule
makes permissive the default and copyleft the exception. A result list that puts a GPL recipe on
top because it scored better on a text index is a list arguing for the exception.

## This is a surface over oematch, not a reimplementation

The index, the fingerprinter, the matcher and the layer resolver are **oematch — first-party,
MIT, `Copyright: 2026 SymonSays LLC`, Garrett's own work**. It is a real Debian package with its
own tests and its own reasoning written into it, and this component re-derives none of it. It
resolves the package, reports which copy answered, and calls it.

What this component adds is the part that belongs to the estate rather than to the tool: the
**licence classification**, the **ordering that follows from §3.1b-i**, and an HTTP surface.

**The corpus is rebuildable, and that matters more than its date.** `oematch build` re-pulls
every layer from the layer index and re-indexes it. So the age reported on every answer is a
fact about *this copy*, not a limit on the component. `GET /api/symonoematch/rebuild_plan`
reports the exact command and where it would write, and **never runs it** — it clones every
layer in the index, and a GET that pulls a network is a GET that takes the machine down for
anybody who calls it out of curiosity.

## Two copies of oematch exist here, under one version string

`SYM_OEMATCH_SRC` names the directory containing the `oematch` package. With it unset, the
installed one is used. `GET /api/symonoematch/tool` reports which answered — read by **running
it**, not by importing a constant:

    resolved         installed
    root             /usr/lib/python3/dist-packages
    version          0.1.0          (read by: python3 -m oematch.cli --version)
    digest_sha256    226a58975efb7721b576a8a52a4e082565a694a7eeb44788aa2451ae842f7b56
    modules          __init__, cli, corpus, db, extract, match
    verbs            add, build, match, scan, stats

The digest is there because **the version is not an identification**. Both copies on this host
report `0.1.0` and they are not the same software: the source tree carries `upstream.py` and a
`kind='bb'` filter, and the installed package carries neither. Each copy is loaded under a name
derived from its own root, so resolving both in one process cannot hand back whichever was
imported first — which is how a report ends up describing a copy that did not answer.

## Routes

    GET /api/symonoematch/health         public; answers before the corpus exists
    GET /api/symonoematch/freshness      age, size and row counts of this index
    GET /api/symonoematch/tool           which oematch answered, its version and its verbs
    GET /api/symonoematch/layers         ?q=     layers by name, with each one's licence
    GET /api/symonoematch/find           ?q=     recipes for a capability, permissive first
    GET /api/symonoematch/licence_of     ?pn=    every layer carrying that recipe, and its licence
    GET /api/symonoematch/permissive     ?q=     the §3.1b-i question, with the query that ran
    GET /api/symonoematch/unlicensed             recipes with no licence, and how many
    GET /api/symonoematch/match          ?target= fingerprint an artifact, rank what provides it
    GET /api/symonoematch/upstream       ?url=   which layer carries this upstream project
    GET /api/symonoematch/rebuild_plan           the rebuild command. Reported, never run

Port `SYM_OEMATCH_PORT`, default **8829**. Bind `SYM_OEMATCH_HOST`, default `127.0.0.1`.
Corpus `SYM_OEMATCH_DB`, default `~/.cache/oematch/corpus.db`. Tool `SYM_OEMATCH_SRC`, optional.

Health is public. The **bind address decides the rest** (§3.2a): on loopback there is no token,
because a token there defends only against a caller who already has code execution on this host
and can therefore read the token. Off loopback `SYM_OEMATCH_TOKEN` is required and an unset one
returns 503, so a unit that becomes reachable through a configuration change cannot become
public through that same change.

Two public callables carry no route and say so in `NOT_EXPOSED`: `connect` returns a database
handle, which has no honest HTTP form, and `db_path` is reported inside `freshness` beside what
was found there.

**`match` reads any path this process can read.** On a loopback bind that is the same reach as
the shell of whoever can call it, which is the trust model §3.2a describes; off loopback the
token guard runs before a path is opened. No allowlist was invented for it — §3.2b: security
machinery is proposed, never introduced.

## How a licence expression is read

`AND` and `OR` are different operators and the difference decides the answer:

    Apache-2.0 OR MPL-2.0                 permissive   an arm may be chosen
    Apache-2.0 | GPL-2.0-or-later         permissive   the same, spelled with a pipe
    GPL-2.0-only AND LGPL-2.1-or-later    copyleft     both apply; the strictest term wins
    BSD-3-Clause AND IJG AND Zlib         permissive   every term is permissive

Reading glibc's `AND` as permissive because a permissive term appears in it is how a copyleft
obligation reaches a shipped artifact, so the conjunction is tested in both directions.

Both operators require whitespace on both sides, and the reason is not the one it appears to be.
Measured 2026-09-19 across all 1613 distinct licence strings, one regex at a time:

| Operator | strict vs word-boundary | What differs |
|---|---|---|
| `AND` | **7 strings, 8 recipes** | unexpanded bitbake expressions beginning with a bare `AND `. The loose form reads a licence out of a fragment; the strict form leaves it a question |
| `OR` | **0 strings** | `GPL-2.0-or-later` does shred into `GPL-2.0-` and `-later`, and it changes no answer, because copyleft is matched by containment of `gpl` — the fragment still classifies copyleft |

So the `OR` guard is against something no recipe here exhibits — a hyphenated name whose left
fragment is permissive and whose right is not, `MIT-or-GPL-2.0`. The test that pins it says it
is constructed rather than observed, because a test standing in for evidence it does not have
is worse than no test.

**Three buckets, and anything unread lands in the third.** A blank licence, a string this does
not recognise, a `LicenseRef-*` whose text lives in the recipe rather than on the SPDX list, and
`CLOSED` are all **unlicensed** — a question, never a permissive answer. Over-flagging costs a
manual check; under-flagging is the failure §3.1b-i exists to stop. The precise class stays on
every row, so a reader sees the difference between "nobody said" and "somebody said no".

## Placement

    placement-triage prospect symonoematch --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

This component is built from **python stdlib (`sqlite3`, `subprocess`, `importlib`) at PSF-2.0
and fastapi at MIT**. Both permissive, so §3.1b-i's fourth step is not reached and the
proprietary default stands.

**Indexing GPL-licensed recipe metadata does not make this component GPL.** It reads
`SUMMARY`, `DESCRIPTION`, `HOMEPAGE`, `LICENSE` and `SRC_URI` — descriptions of software, not
the software. Nothing copyleft is compiled, linked or imported here, and nothing copyleft
reaches a shipped artifact through it. §3.1b-i: a component belongs in the open tree when its
**output** is copyleft and would reach a shipped artifact; placing it there for resemblance
rather than consequence is misplacement, and a tree that fills up by resemblance stops meaning
anything. Recording that a recipe is GPL is the opposite of inheriting it.

**Raised, not resolved here: oematch is MIT.** The tool this component wraps carries the MIT
licence and `Copyright: 2026 SymonSays LLC`, while the four trees carry the two SymonSaysLLC
licences between them. §3.1a is explicit that **a licence deviation inside a tree is a new
branch, and that branch states its licence at the top of its document.** Where oematch itself
lands, and under which of the licences, is a placement decision about *his* package rather than
about this one, and it is with Garrett. This component **depends on oematch and does not vendor
it** — no byte of his source is copied into this branch; `SYM_OEMATCH_SRC` points at wherever it
is placed.

## Barriers

**The index is dated 2026-08-21 — 29 days old at the time of writing.** <!-- gate-allow: no-august — an UPSTREAM cache's index date, named in order to refuse reading it as current; not estate material from that month, and removing the date would hide the barrier -->
It is a cache of
*upstream* metadata, not an estate artifact, so the pre-reset material rule does not bar it; but
upstream has moved since, and a recipe that has been relicensed, added or removed in those days
is not in it. Every single response therefore carries the corpus date and age in a `corpus`
field, and `GET /api/symonoematch/freshness` reports it on its own. Nothing here can be read as
current without the reader being told how old it is. The fix is not a barrier, it is a command:
`oematch build`, reported by `rebuild_plan` and run by an operator.

**6786 of 39507 recipes carry no licence at all — 17.2% of the corpus.** Under §3.1b-i every one
of those is "not a prospect yet, it is a question". They can never appear in a `permissive`
answer, they sort between permissive and copyleft in `find`, and `GET
/api/symonoematch/unlicensed` exists so the size of the gap is visible rather than inferred. A
capability whose only candidates are unlicensed has **not** been shown to lack a permissive
variant; it has been shown that the corpus does not know.

**The installed oematch predates the source on disk, and reports the same version.** The
package at `/usr/lib/python3/dist-packages/oematch` (0.1.0) has no `upstream.py`, so
`/api/symonoematch/upstream` refuses with the reason and names `SYM_OEMATCH_SRC`; and its
matcher does not filter `kind='bb'`, so `.bbappend` rows rank as though they provided a recipe
when they only modify one another layer provides. The corpus itself carries the `kind` column
(32659 `bb`, 6848 `bbappend`), which the older indexer never wrote — so the corpus was built by
the newer source, and the installed package is behind both. `GET /api/symonoematch/tool` reports
both gaps as warnings on every call rather than leaving them to be discovered in a result.

**`match` has no timeout, and the parameter that pretended to be one was removed.**
`extract.fingerprint` extracts archives in-process — `dpkg-deb -R` through `subprocess.run` with
no `timeout=`, and `tarfile.extractall` — neither of which can be interrupted from here. A
`timeout_s` argument was written and taken out again: it could only have been checked *after*
the call it was meant to bound, and a check that cannot fail has gated nothing (§3.1d). So a
malformed artifact handed to `/api/symonoematch/match` hangs that request for as long as it
hangs. The response reports `took_s`. Fixing it properly means a timeout inside oematch's
extraction, which is a change to a package this component reads and does not modify.

**Two disclosures are written and untested.** `complete: false` — the flag that says a search
hit its scan bound rather than exhausting the corpus — is never exercised: no query in the
corpus reaches 500 results in `find` or 5000 in `permissive`. The field is correct and unproven,
which is a different thing from correct.

**The test file hardcodes where Garrett's oematch source sits today.** `SRC_CANDIDATES` names two
paths under `~/Downloads`. When that package is placed into a tree, three tests will skip
instead of fail, quietly — the suite still returns 0 and covers less. `SYM_OEMATCH_SRC` overrides
the list, and updating it belongs with the placement, not after it.

**`symonoematch/` and `tests/` carry no document of their own.** §3.7 reads as one Markdown
document per directory; this branch carries one at the root, matching `symonimage`. Recorded as
a question about the convention rather than settled here.

**The read-only claim is stronger than the evidence that prompted it.** oematch's own
`db.connect()` opens read-write and runs DDL. Measured 2026-09-19 against a copy, `oematch --db
<copy> stats` left the file byte-identical, so no write was observed. Every connection here is
still a `file:...?mode=ro` URI and a test asserts an `INSERT` raises, because a read path that
*cannot* write is worth more than one that merely did not.

## Testing

74 tests, `python3 -m pytest tests/ -q`. They are mostly about the classifier, because that is
the part that can be wrong **quietly**: a search returning nothing is obvious, a blank licence
reading as permissive is not, and it would send a component to the wrong tree with a clean
looking record behind it.

Five deliberate defects were introduced one at a time and the suite was re-run against each, to
check the tests can fail: the word-boundary `OR` split, a blank licence bucketing as permissive,
`AND` ignoring a copyleft term, `find` dropping its ordering, and the loopback guard always
returning open. All five were caught — the first only after the test that discriminates it was
added, because the first version of the suite passed with it in place.

One defect was found by running the gates rather than by a test, and is now pinned by one: the
module loader left six `.pyc` files in the tree it had only read. Importing a module writes
bytecode beside it by default, and the tree oematch is resolved from belongs to somebody else.
The loader and the subprocess that reads the version both suppress it now, the six files were
moved to `~/symoneural-quarantine/2026-09-19-symonoematch-pycache/` rather than deleted, and
that tree is byte-identical to its twin again (`diff -rq`, rc=0).

Against the real corpus: `meta-mingw` resolves to MIT at `git.yoctoproject.org`; `sqlite3`
returns four recipes across four layers under three different licence strings (`blessing`, `PD`
and blank) and is reported as disagreeing rather than collapsed; `unlicensed` agrees with
`freshness` on the count from a second code path; and `/bin/ls` is fingerprinted and ranked with
a licence class on every row. The service tests bind off-loopback on purpose, so the token guard
is actually exercised rather than short-circuited.

## Where this sits

    symonoematch/           this document, the service and the tests
      symonoematch/         prospect.py — the corpus queries, the classifier, the tool wrapper
      tests/                test_symonoematch.py

The module is `prospect.py`, not `corpus.py`, and the name was chosen from evidence rather than
taste: oematch already carries `oematch/corpus.py`, that package is being placed into one of the
four trees, and `no-divergent-copy` compares by **basename across every tree**. Two different
files called `corpus.py` would fail that gate the day his source lands.

**The chain ends here.** This component consumes nothing else in the estate and nothing else
consumes it yet: it reads a cache under `~/.cache/oematch`, a package resolved by
`SYM_OEMATCH_SRC`, and paths a caller names. The consumer it is for is `placement-triage` —
the skill that runs §3.1b-i — which does not call it yet, and wiring that is the next thing,
not a claim this page gets to make.

## Releases

Tagged `symonoematch/v<version>`.

## Status

**Built and tested, not running.** 74 tests pass (rc=0, read directly). All 15 gates
return 0 (12 pass, 3 skip). Nothing is registered on `/models/control.board`, nothing is in the
table, and no unit file exists — port 8829 is the number this service would bind, not a port
anything is listening on.

`SYM_OEMATCH_TOKEN` is unprovisioned and deliberately so: on the default loopback bind it is
not needed and not read (§3.2a), and generating a secret is Garrett's alone (§3.2b).
