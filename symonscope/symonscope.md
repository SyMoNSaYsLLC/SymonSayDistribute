# symonscope

The capability `symonscope` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `edges.py` | `edges` | Dependency edges between units, found in code and carrying their evide |
| `layers.py` | `layers` | Layers, DERIVED from the dependency graph and never declared. |
| `live.py` | `listening`, `board_ports`, `state` | What is actually running, and whether the estate on disk matches it. |
| `survey.py` | `trees`, `units`, `subcomponents` | Survey the estate from disk: what units exist, what each one is, and t |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonscope.md](../symonscope.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonscope.md](../symonscope.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
