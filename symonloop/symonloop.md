# symonloop

The capability `symonloop` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `ledger.py` | `root`, `path_for`, `add`, `get`, `jobs`, `due` … +3 | Recurring work that survives the process that created it. |

## Interfaces

**Configuration read from the environment:**

`SYM_LOOP_DIR`

**Consumed by:** the unit's own `service.py` ([symonloop.md](../symonloop.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonloop.md](../symonloop.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
