---
name: branch-place
description: Create the branch for a thing in the tree the placement procedure chose, stamp the matching licence, commit by explicit path and push. Use after a placement decision has been made and never to make one — it will not choose a licence, will not guess a repository, and refuses anything it was not told explicitly. Run placement-triage first if the destination is not already settled.
license: SymonSaysLLC Proprietary License 1.0
---

# Branch place

This is the step **after** a decision. Placement triage answers which licence and which tree;
this carries that answer out. Keeping the two apart is deliberate: a tool that both decides and
acts will eventually decide in order to act, and the one thing worse than an unplaced item is a
confidently misplaced one.

## Use it

    scripts/place.sh <name> <proprietary|open-source> <source-dir> [--dry-run]

    scripts/place.sh gates proprietary /home/google/build/gates --dry-run
    scripts/place.sh gates proprietary /home/google/build/gates

`proprietary` places into `/mnt/SymonSayDistribute` and stamps the SymonSaysLLC Proprietary
License. `open-source` places into `/mnt/SymonSayOSS` and stamps the SymonSaysLLC Open Source
License. There is no third option, and the other two trees are not destinations for a new
thing: `SymonSaySource` tracks what we build **from**, and `SymonSayOpen` holds builds whose
output is already somebody else's copyleft.

Always run `--dry-run` first. It prints the tree, the licence, the source and the file count
without creating anything.

## What it refuses

- a branch name containing a slash — `common` and `common/storage` cannot both be refs, and
  that collision has already cost this estate a re-layout
- a branch that already exists — this places new things, it does not update existing ones
- a tree that is not laid out as a bare repository with worktrees
- a missing licence text, rather than committing an unlicensed branch

## Two faults it was born with

Worth stating, because both are the kind that survive a green exit code.

**It used the blanket form of `git add`.** <!-- gate-allow: no-blanket-add — the fault is named here in order to record it --> Section 3.2 forbids that outright, and this estate is exactly why: a
live key, multi-gigabyte weights and whole build trees sit in directories a blanket stage sweeps
up. Every path is now listed explicitly and printed before it is staged.

**Its heredocs ran `$( … )` with nested quotes**, so the file never parsed and had therefore
never run once — while being recorded as a finished skill. Everything is computed into a
variable first now.

A third surfaced on the first real run: clearing the worktree did not stage the removals, so the
first commit still carried `main`'s `README.md` — present in history, absent on disk, and
invisible to anyone reading the exit code instead of the committed tree. It now stages the
deletions by explicit path too.

## Verify, do not assume

The script exiting 0 means it ran, not that the branch is right. After placing, read the
committed tree:

    git -C /mnt/<tree>/<name> ls-tree -r --name-only HEAD
    gate licence-stamped /mnt/<tree>/<name>

Related: `placement-triage` decides, `copyleft-trace` establishes whether copyleft actually
reaches the thing, and `gates` refuses the commit if it carries something it should not.
