# symonbuild

The capability `symonbuild` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `cooker.py` | `bitbakes`, `devtools`, `configs`, `layers`, `cooker_live`, `buildable` | symonbuild — the estate's build capability, reported rather than exerc |

## Interfaces

**Configuration read from the environment:**

`SYM_BUILD_DEPTH`, `SYM_BUILD_ROOTS`

**Consumed by:** the unit's own `service.py` ([symonbuild.md](../symonbuild.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonbuild.md](../symonbuild.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
