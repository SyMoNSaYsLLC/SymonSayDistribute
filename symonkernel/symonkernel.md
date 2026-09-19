# symonkernel

The capability `symonkernel` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `kernel.py` | `running`, `kernels`, `dkms`, `modules`, `compilers`, `coverage` … +2 | The host kernel, and whether a kernel module can be built for it. |

## Interfaces

**Configuration read from the environment:**

`SYM_KERNEL_PIN`

**Consumed by:** the unit's own `service.py` ([symonkernel.md](../symonkernel.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [symonkernel.md](../symonkernel.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
