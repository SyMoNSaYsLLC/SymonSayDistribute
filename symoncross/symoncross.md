# symoncross

The capability `symoncross` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `targets.py` | `hosts`, `layers`, `builders`, `targets`, `portability` | What this build host can target — measured on the host, never recalled |

## Interfaces

**Configuration read from the environment:**

`SYM_CROSS_DARWIN_BUNDLE`, `SYM_CROSS_DIST_ROOT`, `SYM_CROSS_SOURCE_ROOT`

**Consumed by:** the unit's own `service.py` ([symoncross.md](../symoncross.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symoncross.md](../symoncross.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
