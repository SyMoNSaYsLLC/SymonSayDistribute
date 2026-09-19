# symonscheduler

The capability `symonscheduler` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `cadence.py` | `interval_seconds`, `to_cron`, `field_values`, `parse`, `next_fire`, `upcoming` … +1 | When work should next happen, computed rather than waited for. |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonscheduler.md](../symonscheduler.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonscheduler.md](../symonscheduler.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
