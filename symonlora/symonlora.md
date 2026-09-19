# symonlora

The capability `symonlora` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `dataset.py` | `load`, `validate`, `deduplicate` | The training set, and refusing to train on one that will not teach any |
| `plan.py` | `read_config`, `module_shapes`, `adapter_params`, `memory`, `plan` | Planning a LoRA run against the checkpoint that will actually be train |
| `prereq.py` | `check` | What is missing before a run can start, named rather than discovered a |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonlora.md](../symonlora.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonlora.md](../symonlora.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
