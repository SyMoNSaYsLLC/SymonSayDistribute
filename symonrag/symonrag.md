# symonrag

The capability `symonrag` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `chunk.py` | `chunk_text`, `chunk_file` | Turning documents into passages that can be cited. |
| `index.py` | `tokenize` | The index, and why it is lexical. |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonrag.md](../symonrag.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonrag.md](../symonrag.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
