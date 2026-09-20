# symonskill

The named procedures this estate knows, made reachable.

## The gap this closes

Six skills sat on disk — `branch-place`, `copyleft-trace`, `disk-identity`, `estate-verify`,
`placement-triage`, `source-pin`. Each carries a `SKILL.md` with a name, a description and a
licence; most carry scripts. **Nothing in the estate could discover any of them.** The `skills`
branch has no `service.py`: it is a collection, not a component.

That is the same failure this estate has now hit four times in one day — `ravencalc` released
and absent from the board, `symonloop` and `symonscheduler` wired in two places of four, and
these six. Work that exists and cannot be reached was not finished; it was abandoned somewhere
tidy.

## It catalogues; it does not execute

Finding a skill, reading its metadata, checking the contract and handing back the body are one
job. Running a skill's script is another, and it needs the permission to execute.

    symonscheduler   computes WHEN    runs nothing
    symonloop        remembers WHAT   executes nothing
    symonskill       knows HOW        executes nothing
    an adapter       actually RUNS it

A catalogue that also executed could not be asked "what is available?" without risk. A test
reads this module's own source and fails if `subprocess`, `os.system`, `eval`, `exec` or `Popen`
appear in it.

## The contract, and why the description is required

A skill is a directory with a `SKILL.md` whose frontmatter carries at minimum `name` and
`description`.

The description is not decoration. **It is what decides whether a skill is relevant to a task**,
so a skill without one can be listed but never chosen — and the refusal says exactly that,
because "missing description" on its own sounds like a formatting nit rather than a skill that
can never be found.

Frontmatter is read by a narrow parser rather than a YAML dependency. The contract is two
required scalar fields; a parser accepting anchors, aliases and arbitrary nesting would accept
far more than the contract allows, and carrying a dependency in every release to do it is worse
than twelve lines of regex.

Line numbers in parse errors are **file-relative, not block-relative**. Whoever fixes the error
opens an editor and jumps to a line; a block-relative number sends them to the wrong one, which
is a worse error message than none.

## What it refuses, and what it merely reports

**Refuses** (409 over HTTP): an empty skill name; an unknown skill, naming what *is* known; a
relevance query of only short words, because a one-word query ranks everything equally and helps
nobody.

**Reports, never raises**: a malformed skill. `parse_frontmatter` returns `ok: false` with the
reason instead of throwing, because one broken skill must not hide the other five.

**Reports, never repairs**: `validate` lists every contract defect across the collection and
changes nothing. Correcting somebody's procedure on this component's own judgement is not a
catalogue's business, and a test asserts the file is byte-identical after a validation run.

## The defects it is built to catch

    a skill with no SKILL.md                  not a skill; a tree can hold other things
    frontmatter that does not parse           reported with the file line number
    a missing name or description             named, with why the description matters
    a declared name that is not the directory a caller asking by either misses it under the other
    valid frontmatter, no body, no scripts    "nothing to follow"
    a configured root that does not exist     reported, not silently empty

The name-mismatch case is the subtle one: a skill whose `name:` disagrees with its directory is
findable by neither reliably, and nothing else in the estate would notice.

## Relevance is deliberately simple

`relevant(task)` scores each skill's description by word overlap and returns **the words that
matched**, so the ranking can be disagreed with. A catalogue that guessed cleverly and wrongly
would be worse than one whose reasoning a person can check in a glance.

Measured against the real collection:

    task: "decide which licence this component carries and where it belongs"
      6  placement-triage   matched: belongs, carries, decide, licence, where, which
      2  copyleft-trace     matched: component, licence
      2  disk-identity      matched: this, where

No match is an answer, not a failure — and it is better than ranking six irrelevant skills by
noise.

## Routes

    GET /api/symonskill/health          public; answers before any skill is found
    GET /api/symonskill/skills          every skill, invalid ones named rather than dropped
    GET /api/symonskill/skills/{name}   one skill with its body; accepts either name
    GET /api/symonskill/relevant        which skills a task might need, with matched words
    GET /api/symonskill/validate        every contract defect; reports, never repairs
    GET /api/symonskill/frontmatter     read a metadata block and say what is wrong with it

`SYM_SKILL_ROOTS` is a path-separated list, so a test never reads the real collection and a
second collection can be added without moving the first.

Loopback serves open (§3.2a). Bound off-loopback, `SYM_SKILL_TOKEN` is required and an unset one
closes the unit.

One capability carries no route and says so in `NOT_EXPOSED`: `roots` resolves the environment
variable, and its resolved value is reported inside `skills` and `health` — a caller wants the
catalogue, not where this process looked for it.

## Placement

    placement-triage prospect symonskill --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

Written from the specification. The licence survey of 2026-09-19 found no reusable source: Claude
Code is a proprietary ELF with no LICENSE of its own, and `qwen-code` (Apache-2.0),
`opencode-ai` (MIT) and the `openai` SDK (Apache-2.0) are readable but uncopyable under §3.11.
None was needed — reading a fenced block and comparing word sets is not anybody's intellectual
property.

## Testing

35 tests. Most run against a synthetic collection under `tmp_path`, so a malformed skill can be
tested without writing one into the real collection. Three run against the real six and **skip
cleanly** when the `skills` branch is not checked out, because the estate must be testable on a
machine that does not have it.

Coverage includes: eight frontmatter shapes including hostile input that must not raise; an
invalid skill listed rather than hidden; a directory without `SKILL.md` correctly not counted; a
name mismatch flagged; a missing root reported; several roots searched; fetch by either name;
the body returned without its frontmatter; relevance ranked with matched words returned; no-match
as an answer; validation finding a skill with nothing to follow; validation proven not to write;
and the source-level assertion that nothing here executes.

    python3 -m pytest tests/ -q

## Releases

Tagged `symonskill/v<version>`.

## Status

Built and tested. Wired on 8833. Against the real collection: 6 found, 6 valid, 0 invalid,
0 contract defects.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonskill`](symonskill/symonskill.md) | the capability this unit provides — `catalogue.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symonskill`](symonskill/symonskill.md), [`tests`](tests/tests.md).
