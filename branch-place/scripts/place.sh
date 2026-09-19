#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
#
# place — give a thing its branch in the tree the placement procedure chose.
#
#   scripts/place.sh <name> <proprietary|open-source> <source-dir> [--dry-run]
#   scripts/place.sh gates proprietary /home/google/build/gates --dry-run
#
# This is the step AFTER a decision, never the decision itself. It will not choose a licence,
# will not guess a repository, and refuses anything it was not told explicitly — because the
# one thing worse than an unplaced item is a confidently misplaced one.
#
# What it does: creates the branch off that tree's main, copies the source in, stamps the
# matching LICENSE, writes a stub document naming what the thing is, stages BY EXPLICIT PATH,
# commits and pushes.
#
# TWO FAULTS THIS FILE WAS BORN WITH, BOTH FIXED HERE
# ---------------------------------------------------
# 1. It used `git add -A`, which section 3.2 forbids outright. A live key, multi-gigabyte
#    weights and whole build trees sit in this estate; a blanket stage is how one of them
#    reaches a remote. Every path is now listed explicitly and printed before it is staged.
# 2. Its document and commit message ran `$( ... )` inside heredocs, which never parsed — the
#    file failed `bash -n` and had therefore never run once. Everything is computed into a
#    variable first, and the heredocs interpolate plain variables only.
set -o pipefail

NAME=${1:?the branch name, which is also the thing name}
KIND=${2:?proprietary | open-source}
SRC=${3:?directory holding what to place}
DRY=0; [ "${4:-}" = "--dry-run" ] && DRY=1

case "$KIND" in
  proprietary)
    TREE=/mnt/SymonSayDistribute
    LIC=/home/google/symonsay-licences/SymonSaysLLC-Proprietary-1.0.txt
    LABEL="SymonSaysLLC Proprietary License 1.0"
    WHY="nothing copyleft is linked into it, so the default applied"
    WHY_C="Nothing copyleft is linked in, so the default applied." ;;
  open-source)
    TREE=/mnt/SymonSayOSS
    LIC=/home/google/symonsay-licences/SymonSaysLLC-OpenSource-1.0.txt
    LABEL="SymonSaysLLC Open Source License 1.0"
    WHY="a copyleft source is linked into it, which forced the open source licence"
    WHY_C="A copyleft source is linked in, which forced the open source licence." ;;
  *)
    echo "kind must be 'proprietary' or 'open-source'." >&2
    echo "Source and Open are not destinations for a NEW thing: Source tracks what we build" >&2
    echo "from, and Open holds builds whose output is already somebody else's copyleft." >&2
    exit 2 ;;
esac

case "$NAME" in
  */*) echo "branch names carry no slash: 'common' and 'common/storage' cannot both be refs" >&2; exit 2 ;;
esac

[ -d "$SRC" ]        || { echo "no such source directory: $SRC" >&2; exit 2; }
[ -d "$TREE/.bare" ] || { echo "$TREE is not laid out as a bare repository with worktrees" >&2; exit 2; }
[ -r "$LIC" ]        || { echo "licence text missing: $LIC" >&2; exit 2; }

if git -C "$TREE/main" show-ref --verify --quiet "refs/heads/$NAME"; then
  echo "branch '$NAME' already exists in $(basename "$TREE") — this places NEW things" >&2; exit 3
fi

echo "place   $NAME"
echo "  tree    $TREE"
echo "  licence $LABEL"
echo "  from    $SRC"
echo "  files   $(find "$SRC" -type f -not -path '*/.git/*' | wc -l)"
[ $DRY -eq 1 ] && { echo "  DRY RUN — nothing created"; exit 0; }

git -C "$TREE" worktree add -q "$NAME" -b "$NAME" main || exit 4
WT="$TREE/$NAME"
case "$WT" in "$TREE"/*) : ;; *) echo "refusing to clear $WT — outside $TREE" >&2; exit 4 ;; esac

# The worktree starts as a copy of main. Clear it so the branch holds this thing and not
# main's index. Everything removed here is a committed file on main, recoverable from git.
find "$WT" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} + 2>/dev/null
cp -a "$SRC"/. "$WT"/ || exit 4
find "$WT" -mindepth 2 -maxdepth 3 -name '.git' -exec rm -rf {} + 2>/dev/null
cp "$LIC" "$WT/LICENSE" || exit 4

# Only if the source did not already bring one. The stub is a starting point for a thing that
# has no document yet; writing it unconditionally CLOBBERS a real one, which is what happened to
# a 65-line gates.md on the first two branches this placed — replaced by a template, committed,
# and pushed, with the exit code reporting success throughout.
if [ -s "$WT/$NAME.md" ]; then
  echo "  keeping the $NAME.md the source already carries ($(wc -l < "$WT/$NAME.md") lines)"
else
cat > "$WT/$NAME.md" <<DOC
# $NAME

Licensed under the $LABEL.

## What this is

(state what it is, in one sentence a stranger could act on)

## What it does

(state what it does, not how it is built)

## Why it is here and not in the other tree

Placed by the placement procedure: $WHY.

## Releases

This branch cuts its own releases, tagged \`$NAME/v<version>\`. A bare version number would be
ambiguous the moment a second thing sits at the same number.
DOC
fi

cd "$WT" || exit 4

# Explicit paths only. Section 3.2: never `git add .`, never `git add -A`.
#
# `.git` is EXCLUDED by name, not just `.git/`: inside a worktree `.git` is a regular FILE
# holding a gitdir pointer, so a plain `-type f` sweep offers it to git. Git refuses it, but a
# staging list that names it is a staging list nobody should trust.
mapfile -t FILES < <(cd "$WT" && find . -type f -not -path './.git/*' -not -name '.git' -printf '%P\n' | sort)
[ "${#FILES[@]}" -gt 0 ] || { echo "  nothing to stage" >&2; exit 4; }
echo "  staging ${#FILES[@]} files by explicit path:"
printf '            %s\n' "${FILES[@]}" | head -20
[ "${#FILES[@]}" -gt 20 ] && echo "            … and $(( ${#FILES[@]} - 20 )) more"
git add -- "${FILES[@]}" || exit 4

# The branch starts as a copy of main, and clearing the WORKTREE does not stage the removals.
# Without this the first commit still carried main's README.md — present in history, absent on
# disk, and invisible unless someone reads the committed tree rather than the exit code.
mapfile -t GONE < <(git diff --cached --name-only --diff-filter=D)
mapfile -t INHEAD < <(git ls-tree -r --name-only HEAD)
STALE=()
for f in "${INHEAD[@]}"; do [ -e "$WT/$f" ] || STALE+=("$f"); done
if [ "${#STALE[@]}" -gt 0 ]; then
  echo "  removing ${#STALE[@]} file(s) inherited from main and not part of this thing:"
  printf '            %s\n' "${STALE[@]}"
  git rm -q --cached -- "${STALE[@]}" || exit 4
fi

MSG="$NAME: placed under the $LABEL

Placed by the placement procedure rather than by habit. $WHY_C

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015ASXrr8kFxkrx58fFVHmcB"

git commit -q -m "$MSG" || exit 4
git push -q -u origin "$NAME" || { echo "  committed locally; push failed" >&2; exit 5; }
echo "  branch  $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD), pushed"
echo "  next    fill in $NAME.md, then cut $NAME/v0.1.0 when it is worth releasing"
