# symonpayload

The capability `symonpayload` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `admit.py` | — | Admission — everything that happens before a request is allowed to cos |
| `dispatch.py` | — | Dispatch — deciding what runs next, sending it, and getting the answer |
| `flow.py` | — | Flow control — what stops the estate accepting work it cannot serve. |
| `form.py` | — | Batch formation — turning admitted requests into one call the engine c |
| `residency.py` | — | Residency and buffers — what is held, where, and for how long. |
| `sweep.py` | `grid` | Running the same thing many ways on purpose, and recording what happen |

## Interfaces

**Consumed by:** the unit's own `service.py` ([symonpayload.md](../symonpayload.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonpayload.md](../symonpayload.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
