# symongithub

Licensed under the SymonSaysLLC Proprietary License 1.0.

GitHub reached from the coder through one pinned, credential-owning launcher.

## What this is

The estate's placement of the official GitHub MCP server (`github/github-mcp-server`, MIT,
a DEPENDENCY) behind a first-party launcher, so that Claude Code, and any other MCP client on
this host, gets repository, issue, pull-request, workflow, release, security, code-search and
organisation tools without a credential ever being written into a configuration file, an
argument list, a log or a prompt.

Nothing here is the product. It is a tool the product is built with (§3.5).

## Directories and files

| Path | What lives there | Why a reader goes there |
|---|---|---|
| `symoneural-github-mcp` | the launcher the MCP client executes | to see exactly what the model can and cannot reach, and how the credential is handled |
| `acquire.sh` | fetch, verify and install the pinned release asset read-only; `--check` verifies only | when the binary is missing, or to prove it is still the pinned bytes |
| `pin.json` | the record: upstream commit, tag, licence checksum, copyright, release asset and binary sha256, container digest, build-from-source state | before trusting any statement about "which version" |
| [`tests/`](tests/tests.md) | what proves the above | before registering the launcher with a client |

## Interfaces

| Direction | What |
|---|---|
| Executed by | Claude Code, user scope (`~/.claude.json` → `mcpServers.symoneural-github`, stdio); the Codex configuration names the same command |
| Reads | `pin.json`; the installed binary at `~/.local/share/symoneural/github-mcp-server/<tag>/`; the gh credential for `SYM_GITHUB_ACCOUNT` via `gh auth token --user` (OS keyring) |
| Writes | nothing on disk; the server speaks MCP over stdio to its parent and HTTPS to `api.github.com` (or `SYM_GITHUB_HOST`) |
| Ports | none; no listener, no router rule, no loopback socket |
| Environment | `SYM_GITHUB_ACCOUNT`, `SYM_GITHUB_READ_ONLY`, `SYM_GITHUB_TOOLSETS`, `SYM_GITHUB_EXCLUDE`, `SYM_GITHUB_HOST`, `SYM_GITHUB_INSTALL`, `SYM_GITHUB_PIN` — none carries a secret |
| Refuses | to start when the binary is missing (127), when its sha256 or reported commit is not the pin's (70), or when gh holds no credential for the named account (78) |

## The credential boundary

The model asks for a tool; the client executes this launcher; the launcher asks gh for the
token and hands it to the server as an environment variable of that one child process. The
token is never an argument (`/proc/<pid>/cmdline` is world-readable; `environ` is not), never
in `~/.claude.json`, never in this repository, never on the model bus. Only accounts logged in
to gh work, on purpose: gh keeps them in the OS keyring, and a plaintext store is not consulted
even when one exists.

Identity in use on 2026-09-20: `SyMoNSaYsLLC`, gh OAuth (`gho_`), scopes
`admin:public_key gist read:org repo`. That is an **interim** credential: a fine-grained token
or a GitHub App installation is the durable form, and moving to one changes nothing here but
how gh is logged in.

## Default tool surface

Toolsets: `context repos issues pull_requests actions code_security secret_protection
dependabot security_advisories orgs users git labels governance code_quality discussions`.
Off until the operator names them (`SYM_GITHUB_EXCLUDE`): `delete_file push_files
merge_pull_request create_repository fork_repository create_repository_ruleset
custom_properties_write actions_run_trigger projects_write label_write
discussion_comment_write assign_copilot_to_issue assign_copilot_to_issue_with_intent
request_copilot_review star_repository unstar_repository create_gist update_gist`.

`SYM_GITHUB_READ_ONLY=1` removes every write.

## Direction of travel (§3.1b-iii)

| State | Where this is |
|---|---|
| network-dependent | no: the asset, tarball and licence are on disk and `acquire.sh --check` needs no network |
| upstream-bound | no: the launcher asserts sha256 and commit against `pin.json` on every start |
| on-disk and pinned | **yes for the binary**; building it from the pinned commit is NOT done, because `go.mod` wants Go 1.25.12 and the host has 1.24.4. That build is the next step, after a Go toolchain is pinned in `SymonSaySource`. |

## Placement

Proprietary, `SymonSayDistribute`, branch `symongithub`; the pin is mirrored into
`SymonSaySource` `cli/pins/github-mcp-server.json`. The upstream is MIT and is invoked as a
separate process, never linked, so nothing copyleft or third-party enters this branch.

The flow continues at [`tests/`](tests/tests.md).
