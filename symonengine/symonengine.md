# symonengine

The capability `symonengine` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `capability.py` | `surface`, `serves` | What a serving build can actually do, asked of the build. |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonengine.md](../symonengine.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonengine.md](../symonengine.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
