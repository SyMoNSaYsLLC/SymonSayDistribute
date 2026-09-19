# symoneural_ravencalc

The capability `ravencalc` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `compute.py` | `simplify`, `solve`, `precise`, `matrix_solve`, `integrate`, `backends` | RavenCalc compute core — symbolic and numeric evaluation. |
| `model.py` | `read_tensors`, `kv_cache`, `expert_residency`, `transfer_ms`, `budget`, `gpu_fraction` | RavenCalc model arithmetic — what a checkpoint costs, derived from the |
| `service.py` | `require_unit_token`, `health`, `backends`, `do_simplify`, `do_solve`, `do_precise` … +9 | RavenCalc HTTP surface — Phase 11's gate. |

## Interfaces

**Configuration read from the environment:**

`SYM_LOG_LEVEL`, `SYM_RAVENCALC_HOST`, `SYM_RAVENCALC_PORT`, `SYM_RAVENCALC_TOKEN`

**Consumed by:** [`tests`](../tests/tests.md)

## Where this leads

Up to [ravencalc.md](../ravencalc.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
