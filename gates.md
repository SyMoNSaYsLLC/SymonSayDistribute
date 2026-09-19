# gates

Licensed under the SymonSaysLLC Proprietary License 1.0.

## What this is

Ten programs that each refuse one thing this estate has already been hurt by, plus the hook
installer that puts them on the commit path and a selftest that proves each one can fail.

## What it does

`gate --list` names them. `gate <name> <path>` runs one: exit 0 it passed, 1 it failed, 2 it was
misused. `gate --all <path>` runs every gate and reports each.

| gate | refuses | the incident behind it |
|---|---|---|
| `no-blanket-add` | `git add .`, `git add -A` | a live key, multi-gigabyte weights and build trees sit in directories a blanket stage sweeps up | <!-- gate-allow: no-blanket-add — naming the form in order to forbid it -->
| `no-secret` | credential-shaped content | reports the file and line, never the value — quoting a leak is still a leak |
| `no-weights` | weights in any format | history keeps a large file after the file is deleted |
| `no-august` | material dated August 2026 <!-- gate-allow: no-august — naming it to forbid it --> | it predates the fresh start and carries decisions that were deliberately dropped |
| `no-upstream-write` | a modified acquired source tree | a dirty upstream makes the recorded SHA a lie |
| `licence-stamped` | a branch with the wrong LICENSE, or none | which tree a thing sits in is the whole answer to what it ships under |
| `exit-code-direct` | `cmd \| tail; rc=$?` | reads `tail`'s status, so a failing build reports success |
| `forbidden-signal` | `pkill --ns`, `pkill -f`, `pgrep -f` | `--ns` hard-crashed this host; `-f` matches the agent's own command line and kills its shell |
| `on-disk` | a path with no filesystem UUID | tmpfs, overlay and FUSE all accept a write and lose it |
| `claim` | a claim that does not hold | section 3.1d, made cheap enough that there is no excuse for skipping it |
| `no-divergent-copy` | the same tool at several paths with different contents | `ship-gate.py` existed four times across two filesystems, three of them stale — the release gate itself, with no agreement about what it was |
| `no-predictable-tmp` | a temporary file at a guessable path | `/tmp/.chk.$$.py` was written and then EXECUTED; $$ reads like uniqueness and is a small, reused, publicly visible number |

## Why it is here and not in the other tree

Placed by the placement procedure: nothing copyleft is linked into it, so the default applied.
Every file is first-party shell. The interpreters and commands it runs — bash, coreutils,
findutils, git — are reached across an exec boundary, which is why the ship gate classes them
`INVOKED_NOT_LINKED` rather than letting GPL-3.0 reach code that merely executes them.

## The selftest is the point

`./selftest.sh` runs every gate twice: once against a fixture built to violate it, once against
one built to satisfy it. A gate is only reported sound if it fails the first and passes the
second.

This is not ceremony. A gate that can only pass looks exactly like a working gate in every
report it appears in, and this estate has already shipped one: a check that read `$?` from a
pipeline instead of from the guard it was checking, and so reported success while the guard it
was verifying was not on disk at all. The selftest exists so that cannot be true of these.

The credential fixture is a synthetic string of the right shape. No real secret is written,
printed or committed by anything in this branch.

## And a gate on the gates

`./mutants.sh` breaks each gate on purpose and requires the selftest to notice. Two mutants per
gate — one that always passes, one that always fails — and each must be **killed**. A mutant
that survives is a gate nothing tests, which looks identical in every report to a gate that
works.

It runs a **control first**: an unmutated copy must pass in exactly the place the mutants will
run. The first version skipped that and worked in `$TMPDIR`, which on this host is tmpfs; the
selftest's own `on-disk` assertion failed there, so all twenty mutants were reported killed
when not one of them had been exercised. A green run that is green for the wrong reason is
worse than a red one, and the control is what makes the difference visible.

## Installing

    ./install.sh --dry-run      # say what would change, touch nothing
    ./install.sh                # pre-commit hook into each of the four trees, `gate` onto PATH
    ./install.sh --uninstall    # remove only hooks this installed

The hook runs against **staged** content, recovered with `git checkout-index` into a temporary
directory — not against the worktree. The worktree may hold anything; only what is staged is
about to become history, and history is the part that cannot be taken back.

An existing hook is never overwritten. It is moved to `pre-commit.before-gates` and the path is
printed. Uninstall moves ours aside too rather than deleting it.

## Releases

This branch cuts its own releases, tagged `gates/v<version>`. A bare version number would be
ambiguous the moment a second thing sits at the same number.
