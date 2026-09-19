# symonprobe

The capability `symonprobe` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `device.py` | `devices`, `build`, `fit` | The card, and whether a build can actually run on it. |
| `runtime.py` | `venvs`, `packages`, `parsers`, `suggest` | What a serving runtime actually offers, asked of the runtime rather th |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonprobe.md](../symonprobe.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonprobe.md](../symonprobe.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
