# symondriver

The capability `symondriver` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `driver.py` | `kernel_module`, `userspace`, `libraries`, `binaries`, `packages`, `pinned` … +1 | The GPU driver's userspace surface, and whether it is CONSISTENT with  |

## Interfaces

**Configuration read from the environment:**

`SYM_DRIVER_PIN`

**Consumed by:** the unit's own `service.py` ([symondriver.md](../symondriver.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symondriver.md](../symondriver.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
