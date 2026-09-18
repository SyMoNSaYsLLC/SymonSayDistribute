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
| `clients/claude-desktop/` | the **reference third-party client**: the tracked third-party-inference declaration (`symonAI.json`, no credential), the installer that refuses while the app runs, and the settings and SSH-surface documents with their measured reasons | anyone pointing Claude Desktop at the gateway |

Precedence, everywhere: process environment > the env file you sourced > the default in
code. If a `SYM_*` name exists in code and not in `symoneural-learn.env.example`, that is
a defect to fix in the same change that introduced the variable.

## What is deliberately not here

- **The gateway credential.** It lives only in the file named by `SYM_GW_KEY_FILE`
  (0600, operator-created). Every document here names *where* it is and never *what* it is.
- **Weights.** `SYM_MODELS_DIR` points outside the repository. Nothing under `config/`
  or anywhere else in this tree carries a checkpoint.
- **Client application state.** Exports of Claude Desktop's own profile
  (`claude_desktop_config.json`, `extensions-blocklist.json`, `mcp-user-tool-toggles.json`,
  `os-entry-points.json`, `symonAI.live-export.json`) were removed on 2026-09-18. They
  carried the operator's Anthropic account and organisation identifiers, home-directory
  paths, a per-account permissions map and an MCP server path pointing at a dead mount;
  nothing installed them and none of it configures the product. The estate keeps those
  exports as dated evidence under `work/config/claude-desktop/`.
- **Model cards.** `symon-chat`, `symon-coder`, `symon-work` are code today
  (`gateway/symoneural_gateway/models.py`). Moving them to data under `config/models/`
  is the natural next step once the engine behind `/v1` is the estate's own — recorded
  here so the direction is visible, not built until asked.

## Adding a client

Make a directory under `clients/` named for the client. It holds the client's declaration
pointing at `SYM_GW_URL`, an installer if the client needs one, and a README stating what
the client requires of the gateway (for Claude Desktop that is the `anthropic_family_tier`
field on every `/v1/models` row — the one fact that makes a Symon-branded model selectable
at all). A client directory never contains a credential, an account identifier or an
absolute path into someone's home directory.
