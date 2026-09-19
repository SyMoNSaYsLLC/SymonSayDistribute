# symonskill

The capability `symonskill` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `catalogue.py` | `roots`, `parse_frontmatter`, `skills`, `get`, `relevant`, `validate` | The named procedures this estate knows, made reachable. |

## Interfaces

**Configuration read from the environment:**

`SYM_SKILL_ROOTS`

**Consumed by:** the unit's own `service.py` ([symonskill.md](../symonskill.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonskill.md](../symonskill.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
