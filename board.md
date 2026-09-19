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

## Releases

Tagged `board/v<version>`.
