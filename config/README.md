# config

What the product needs to be told, and nothing else.

## The rule

`config/` holds **declarations the product reads**. It does not hold application state
exported from some program's profile, it does not hold anything host-specific by
accident, and it never holds a secret or a weight. Two years after each release this
repository becomes Apache-2.0; assume everything here will be public and write it that way.

## Layout

| Path | What it is | Who reads it |
|---|---|---|
| `symoneural-learn.env.example` | **the configuration contract** — every `SYM_*` variable the gateway, the web UI and the chat-unit scripts read, with the default the code uses | operators; `set -a; . learn.env; set +a` before starting units |

Precedence, everywhere: process environment > the env file you sourced > the default in
code. If a `SYM_*` name exists in code and not in `symoneural-learn.env.example`, that is
a defect to fix in the same change that introduced the variable.

## What is deliberately not here

- **The gateway credential.** It lives only in the file named by `SYM_GW_KEY_FILE`
  (0600, operator-created). Every document here names *where* it is and never *what* it is.
- **Weights.** `SYM_MODELS_DIR` points outside the repository. Nothing under `config/`
  or anywhere else in this tree carries a checkpoint.
- **Client configuration.** The product exposes a public wire dialect (see `docs/ARCHITECTURE.md`); how any particular client is pointed at `SYM_GW_URL` is that client's business and is kept out of this repository. Reference notes for clients used during development live in the build estate, not here.
- **Model cards.** `symon-chat`, `symon-coder`, `symon-work` are code today
  (`gateway/symoneural_gateway/models.py`). Moving them to data under `config/models/`
  is the natural next step once the engine behind `/v1` is the estate's own — recorded
  here so the direction is visible, not built until asked.

