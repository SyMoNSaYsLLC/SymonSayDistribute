# symonimage

The capability `symonimage` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `imager.py` | `binary`, `store`, `version`, `weights`, `card`, `room` … +1 | Serving symon-imager — a CLI wrapped honestly, on a card it has to sha |

## Interfaces

**Configuration read from the environment:**

`SYM_IMAGE_BIN`, `SYM_IMAGE_STORE`

**Consumed by:** the unit's own `service.py` ([symonimage.md](../symonimage.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonimage.md](../symonimage.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
