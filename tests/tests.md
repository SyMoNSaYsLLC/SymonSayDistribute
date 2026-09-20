# tests — the release machinery's own exercises

## Why this directory exists at all

On 2026-09-20 two defects were found in this branch, and neither was caught by a test, because
this branch had none. The machinery that gates every release was the only thing in the estate
shipping unexercised. `symonpayload` carries 175 tests; the code that decides whether
`symonpayload` may ship carried zero.

## What is guarded

`test_workflow.py`, 9 tests.

**The notes must never disagree with the report they came from.** Five parametrised shapes plus
the exact shape `symoneural-learn/v1.6.0` shipped — one `REVIEW` unit beside one `PASS` unit,
published as *"Overall FAIL — 1 failing unit(s), 0 needing review"* while its own uploaded
`SHIP-GATE-REPORT.json` said `REVIEW`.

**The ordering that caused it.** `stage-and-cut.sh` ran the gate, then wrote
`THIRD-PARTY-NOTICES.md`, then generated the notes from that first report — but
`check_attribution()` FAILs every permissive unit when that file is absent
(`ship-gate.py:405`), and the line that writes it had not run yet. Measured on the v1.0.0
stage, notices parked and restored:

    without THIRD-PARTY-NOTICES.md   10 FAIL,  0 REVIEW, 0 PASS
    with it                           2 FAIL,  6 REVIEW, 2 PASS

The guard asserts a gate run sits between the notices and the notes. It discriminates: against
the pre-fix script it finds 0 such runs and fails; against the current one it finds 1.

**The checksums must cover the final notes.** `SHA256SUMS` is written after `release-notes.py`,
or it signs a file that then changes.

**The premise the ordering rests on.** A source-level assertion that a missing
`THIRD-PARTY-NOTICES.md` is still a `FAIL` rather than a `REVIEW`. If that ever changes, the
ordering guard is guarding nothing and should be revisited rather than silently kept — a test
that cannot fail has gated nothing.

## The sweep tools, and the five defects they shipped

`drive-sweep.sh` drives `secret-sweep.py` over a cloud remote. Every assertion below exists
because the script reported success while doing the opposite:

    --files-from with --max-size      rclone refuses to load any filter and fetches NOTHING,
                                      exit 0. Measured: 0 of 5196 files, reported as clean.
    a fetch of zero files             counted as a clean chunk and written as a checkpoint,
                                      so the false clean would have been permanent.
    a short fetch                     317 of 400 arrived, rclone exit 0, checkpoint banked.
                                      All 12 sampled absentees were still on the remote.
    the checkpoint key                keyed on the part alone, so two different lists both
                                      produce part-0000 and the second skips the first's work.
    the chunk directory               one fixed directory cleared on entry — passing it a list
                                      that lived there deleted the input, then reported success.

And one in the scanner itself: `redact()` replaced only the match that produced the finding, so
a line carrying both an access token and a refresh token printed whichever one it had not
matched. That reached a terminal and a 0664 log. It now sweeps the line with every pattern it
knows, and a test asserts neither value survives.

## Interfaces

Reads `../release-notes.py`, `../stage-and-cut.sh` and `../ship-gate.py` — the first by running
it against a synthetic stage under `tmp_path`, the other two by reading their source. Nothing
here writes into a real stage, publishes anything, or reaches the network.

    python3 -m pytest tests/ -q

## Where this leads

**The chain ends here, and §3.7 asks why.** This directory has no directories below it, and the
onward step from `workflow` is not a directory at all: it is another *branch*, checked out as
its own worktree beside this one, with its own root document. `main` holds the index of those.
A branch boundary is where the filesystem chain stops, because a worktree's documents are laid
out per branch (§3.1a) and nothing under `/mnt/SymonSayDistribute/workflow` can name a path
inside `/mnt/SymonSayDistribute/main` that survives the layout being recreated on another host.
