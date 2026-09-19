# symoneural_gateway

The capability `symoneural-learn` provides. Its HTTP surface is `service.py` at the
worktree root; this directory is what that surface calls.

## What is here

| Module | Public callables | Summary |
|---|---|---|
| `dialect.py` | `error_body`, `error`, `list_models`, `retrieve_model`, `create_message`, `count_tokens` | The /v1 dialect — the Messages dialect's shapes, served under SyMoNeuR |
| `gateway.py` | `key_fingerprint`, `identify_and_authenticate`, `health`, `ready`, `version`, `main` | The gateway process — one loopback port, the /v1 dialect, and the cred |
| `models.py` | `register`, `model`, `cards`, `for_surface`, `worker_models` | The model catalogue — what this estate offers, under its own name. |
| `worker.py` | `client`, `aclose`, `health`, `served_models`, `post_json`, `post_stream` | The chat worker client — the gateway's one way to reach an inference e |

## Interfaces

**Configuration read from the environment:**

`SYM_CHAT_TOKEN`, `SYM_CHAT_URL`, `SYM_CHAT_WORKER_MODEL`, `SYM_GW_CONNECT_TIMEOUT`, `SYM_GW_HOST`, `SYM_GW_KEY_FILE`, `SYM_GW_PORT`, `SYM_GW_READ_TIMEOUT`, `SYM_IDENTITY`, `SYM_LOG_LEVEL`

## Where this leads

Up to [gateway.md](../gateway.md), the map for this unit.

Nothing here calls into another directory of this unit, so the chain ends at this
document. §3.7 requires that to be said rather than left as a dead end.
