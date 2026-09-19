# store

`store` inside the `model-store` unit.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `inspect.py` | `store_root`, `sha256`, `where`, `models`, `manifest`, `provenance` … +2 | Reading the weight store — what is in it, and whether it still is what |
| `place.py` | `sha256`, `fs_facts`, `main` | place — put an acquired checkpoint into the estate's model store, unde |
| `verify.py` | `main` | model-store verify — re-hash every tracked file and compare it to the  |

## Interfaces

**Configuration read from the environment:**

`SYM_MODELS_DIR`, `SYM_MODEL_STORE`

**Consumed by:** the unit's own `service.py` ([model-store.md](../model-store.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [model-store.md](../model-store.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
