# symoneural_agents

The capability `agents` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `agent.py` | `run_agent` | The agent loop — the one thing the estate did not have. |
| `connectors.py` | `board_settings`, `board_status`, `board_check`, `model_budget`, `model_kv_cache`, `list_models` … +24 | Connectors — the tools that reach the rest of the estate. |
| `plugins.py` | `plugin_root`, `discover`, `enabled_names`, `tools_for`, `load` | Plugins — declared capability, never executed code. |
| `registry.py` | — | The run registry — what is running, what ran, and what stopped it. |
| `tools.py` | — | The tool registry — what an agent is permitted to do, declared before  |

## Interfaces

**Configuration read from the environment:**

`SYM_FABRIC_URL`, `SYM_PLUGINS_DIR`, `SYM_PLUGINS_ENABLED`

**Consumed by:** the unit's own `service.py` ([agents.md](../agents.md)), [`tests`](../tests/tests.md)

## Where this leads

Up to [agents.md](../agents.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
