# board

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

The control board. One visible file at `/models/control.board` holds every serving decision,
each with where its value came from, and this reads it, checks it, and applies it.

    symon-board show [section]   the board, with [live] rewritten from the machine
    symon-board sections         every section, its size, and which tree owns it
    symon-board diff             only the lines where configured and live disagree
    symon-board check            every path exists, every port is a port, nothing is stale
    symon-board env              shell exports for a unit launch
    symon-board 3p on|off        the third-party client path

## Why a file and not a dotfile

The settings lived in `~/.config/symoneural/learn.env`: hidden, and inert unless somebody
remembered `set -a; . file; set +a` first. Nothing showed whether a value was measured, derived,
guessed, or stale, and nothing showed whether the thing running bore any relation to it.

A setting you cannot see and cannot check is not a control.

## The two things that make it a board rather than a config file

**Every value carries its source.** `board`, `measured`, `derived`, or `declared`. A value with
no source is a defect, not a default.

**`[live]` is rewritten on every `show`.** It reports what is actually running, beside what is
configured, with `DIFFERS` on any line where they disagree. Configured-versus-actual is visible
without asking. `[live]` is read-only: edits there are discarded, because it reports the machine
rather than requesting anything of it.

## It refuses to emit a board it does not trust

`env` will not produce exports while any value is still marked `STALE`, unless `--allow-stale`
is passed deliberately. The configuration this replaced carried a GPU fraction resting on an
unmeasured assumption, with nothing in the file to say so.

## The third-party client path

`3p` switches it and reports the four things that must hold at once, each of which has failed
here separately: the profile exists; a config-library entry is applied **and its id is a
36-character UUID**, or the client loads nothing while reporting the entry as applied; the
gateway answers; and a credential is reachable through a helper, so it never enters a system
file. The helper is invoked, never read.

## Which surface gets the credential

`symon-board client 3p|webui|both|off` selects it, and reports whether the selected surface is
actually wired.

**The key is not on the board and will not be.** Section 3.2 permits fingerprints and file
locations only. `credential` names the path; the fingerprint is computed at `show` time and
reported in `[live]`, so an operator can confirm which key is live — and that two surfaces hold
the same one — without anyone seeing it.

Neither surface wants the value, which is why this works. The web console reads the key file
server-side through `SYM_GW_KEY_FILE`, never in a browser. The client invokes a helper that
prints the token, so it never enters the client's own configuration. The board only had to
select and verify.

### The check that matters

Not "is a helper configured" but **does what it emits match the key the board names**. A helper
can be present, executable, and handing the client a stale or different credential; every check
short of this one passes while inference fails on a 401.

Both sides are hashed and compared. Neither value is returned, stored, printed or logged — the
comparison is the entire output. A mismatch says so by name.

Verified on this host: the key file, the installed helper's output, and the board all report the
same fingerprint.

If the entry ever reports `STATIC`, the key is sitting in the client's config file on disk. That
is exactly what `helper-script` exists to avoid, and the board says so rather than passing it.

## Nothing it runs is run blind (§3.1b-iii)

The board shells out to five programs it does not own, and every `[live]` line rests on one of
them. `symon-board pinned`, and `GET /api/board/pinned`, run each one and compare what it
reports to the pin in `SymonSaySource`. Measured 2026-09-20:

| Program | Where | Pin | Observed | State |
|---|---|---|---|---|
| `nvidia-smi` | `card()` — the card rows in `[live]` | `platform/pins/open-gpu-kernel-modules.json` → 615.71.09 | 615.71.09 | **MATCHES** |
| `bash` | the `sh("bash","-lc",…)` in `listener()` and both client checks | none | 5.2.37 | **NO-PIN** |
| `ss` | `listener()` — which pid holds a port | none | 6.15.0 (iproute2) | **NO-PIN** |
| `grep` | `listener()` — filters `ss -lntp` | none | 3.11 | **NO-PIN** |
| `curl` | the gateway and web-console health probes | none | 8.14.1 | **NO-PIN** |

**The pin that governs does not nominally name the binary, and that is said rather than
assumed.** `open-gpu-kernel-modules` is the open GPU *kernel module* source; `nvidia-smi` is
driver userspace. They ship on one release train and the strings are identical —
`nvidia-smi --version` reports the same KMD version — which is why this pin governs it. The
reasoning is written down because a reader checking the pin file will not find the word
`nvidia-smi` in it.

**Four gaps, named not omitted.** bash, ss, grep and curl have no pin among the 108. A program
with no pin is still given a row saying so: an omitted program reads as one with nothing to
check, which is the exact impression §3.1b-iii exists to remove. Their *licence* position is
settled — the ship gate already classifies bash and coreutils as `INVOKED_NOT_LINKED` for
`board/v1.3.0` — but a licence classification is not a version record, and this rule is about
the version. `curl` is the furthest from the rule's end state because it reaches the network as
well as the disk; it is closed by a pin, or by replacing the probe with `urllib`, which this
estate already carries.

`ss` deserves its own line: `listener()` parses `pid=` out of its output, so a change to that
format turns every port into `DOWN` with nothing to say why.

## Releases

Tagged `board/v<version>`.

## Over HTTP

Nine routes on `127.0.0.1:8811`, the port `/models/control.board` assigns to `board`. Health
is public; everything else needs `SYM_BOARD_TOKEN`, and the service answers 503 rather than
opening up when that variable is unset — an unconfigured board is closed, not permissive.

    GET  /api/board/health                    public; answers while the board is unconfigured
    GET  /api/board/sections                  the sections, and what each one governs
    GET  /api/board/settings                  every setting with the tree that owns it
    GET  /api/board/live                      the values read back from running things
    GET  /api/board/diff                      where live disagrees with the file on disk
    GET  /api/board/check                     every path exists, every port is a port,
                                              nothing is still marked STALE
    GET  /api/board/pinned                    every external program the board runs, against
                                              the version SymonSaySource records for it
    GET  /api/board/client                    which surface currently holds the credential
    POST /api/board/client/{surface}          move the credential between web and the client

`settings` takes an optional `?section=` and reports the `#@tree:` attribution beside each
value, so a setting is never separated from the tree that is allowed to change it. No route
returns a credential: where a key exists, the board reports its fingerprint and nothing else.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`tests`](tests/tests.md).
