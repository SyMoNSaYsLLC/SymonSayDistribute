# symoneural_fabric

The capability `adaptive-fabric` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `route.py` | `call`, `reachable` | Making the call — the fabric holds the credentials so its callers do n |
| `wiring.py` | `board_text`, `ports`, `components`, `not_routable`, `unknown_on_board`, `resolve` | The wiring table — one place that knows where every component answers. |

## Interfaces

**Configuration read from the environment:**

`SYM_BOARD_FILE`

**Consumed by:** the unit's own `service.py` ([adaptive-fabric.md](../adaptive-fabric.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [adaptive-fabric.md](../adaptive-fabric.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
