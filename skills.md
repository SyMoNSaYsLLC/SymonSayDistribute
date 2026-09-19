# skills

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

Six skills, each one a decision this estate keeps having to make, with the code that makes it
from what is on disk rather than from what someone remembers.

| skill | answers | refuses to |
|---|---|---|
| `placement-triage` | which licence, which repository | answer when the evidence does not support one |
| `branch-place` | carries a placement decision out | make the decision itself |
| `copyleft-trace` | does a copyleft obligation actually reach this artifact | conflate "built with" and "links against" |
| `source-pin` | what exactly is this acquired tree | accept a tag where a commit is meant |
| `disk-identity` | which machine, which filesystem UUID | state a UUID from memory |
| `estate-verify` | what is running right now | present a status board it did not just produce |

## Why they exist as code and not as habits

Every one of them encodes something that has already gone wrong here and cost a rebuild or a
crash. A habit degrades quietly between sessions; a script does not. The rule they share is the
one that made them worth writing: a claim about disk is tested against disk, at the time, or it
is not a claim.

Each was run against the real estate as it was written, and each found a fault in itself when
it was:

- `placement-triage` treated a build-time tool as a linked dependency
- `copyleft-trace` reported our own libraries as UNKNOWN because it resolved siblings last, and
  separately conflated "could not establish" with "is copyleft" — opposite verdicts
- `disk-identity` carried a hardcoded home path, which is precisely the remembered fact it
  exists to refuse
- `branch-place` used a blanket `git add`, never parsed at all, and left `main`'s README in the
  first branch it produced

## Why it is here and not in the other tree

Placed by the placement procedure: nothing copyleft is linked into it, so the default applied.
These are first-party shell and Python. The interpreters and commands they run are reached
across an exec boundary, which is a different thing from linking and does not carry copyleft
into the caller.

## Releases

This branch cuts its own releases, tagged `skills/v<version>`.
