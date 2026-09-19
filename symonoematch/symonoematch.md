# symonoematch

The capability `symonoematch` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `prospect.py` | `db_path`, `connect`, `freshness`, `layers`, `find`, `licence_of` … +6 | Answering §3.1b-i from disk instead of from memory. |

## Interfaces

**Configuration read from the environment:**

`SYM_OEMATCH_DB`, `SYM_OEMATCH_SRC`

**Consumed by:** the unit's own `service.py` ([symonoematch.md](../symonoematch.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonoematch.md](../symonoematch.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
