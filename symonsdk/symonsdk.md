# symonsdk

The capability `symonsdk` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `toolchains.py` | `pinned`, `toolchains`, `venvs`, `sdks`, `sources`, `can_build` | What can be built on this machine, with what, and whether it is actual |

## Interfaces

**Configuration read from the environment:**

`SYM_PIN_ROOT`

**Consumed by:** the unit's own `service.py` ([symonsdk.md](../symonsdk.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonsdk.md](../symonsdk.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
