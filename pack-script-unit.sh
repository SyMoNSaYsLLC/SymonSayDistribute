#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
#
#   workflow/pack-script-unit.sh <unit> <version> <source-dir> <stage-dir>
#   workflow/pack-script-unit.sh gates 1.0.0 /mnt/SymonSayDistribute/gates ~/symoneural-release/gates/v1.0.0
#
# Stage a unit whose artifact is scripts rather than a wheel, a node tree or an ELF. The three
# existing packers all assume a compiled or packaged artifact, so a branch made of shell and
# Python had no way to reach a release at all — which is why the gates and the skills, both
# finished and both tested, had nothing to cut.
#
# The layout is the one every other unit uses: <stage>/<unit>/<arch>/<artifact>, with a
# BUILD-RECORD.md beside it. The archive is reproducible: mtimes, ownership and order are all
# pinned, and the clock is taken from the source commit rather than from now, so packing the
# same commit twice gives the same bytes.
set -o pipefail
UNIT=${1:?unit name}
VERSION=${2:?version without a leading v}
SRC=${3:?source directory}
STAGE=${4:?stage directory}
VERSION=${VERSION#v}

[ -d "$SRC" ] || { echo "no such source: $SRC" >&2; exit 2; }
OUT="$STAGE/$UNIT/noarch"
mkdir -p "$OUT" || exit 2

# The clock comes from the commit, never from now. Anchoring it to anything the gate rewrites
# makes the archive differ on every run, which has already happened here once.
EPOCH=$(git -C "$SRC" log -1 --format=%ct 2>/dev/null)
COMMIT=$(git -C "$SRC" rev-parse HEAD 2>/dev/null)
BRANCH=$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null)
[ -n "$EPOCH" ] || { echo "$SRC is not a git checkout — refusing to pack an unpinned tree" >&2; exit 2; }
# What ships is `git archive HEAD`, so UNTRACKED files are irrelevant to the artifact — a
# __pycache__ beside the scripts changes nothing about what is packed. Only tracked changes
# matter, because those are edits that exist on disk and not in the commit being shipped.
# Untracked paths are named rather than ignored, in case one of them was meant to be committed.
DIRTY=$(git -C "$SRC" status --porcelain --untracked-files=no)
[ -z "$DIRTY" ] || { echo "$SRC has uncommitted changes to tracked files — commit first" >&2; echo "$DIRTY" | sed 's/^/    /' >&2; exit 2; }
UNTRACKED=$(git -C "$SRC" ls-files --others --exclude-standard)
[ -z "$UNTRACKED" ] || { echo "  note: not packed, untracked in $SRC:"; echo "$UNTRACKED" | sed 's/^/          /'; }

TAR="$OUT/$UNIT-$VERSION.tar.gz"
# git archive takes the content from the COMMIT, so what ships is what is in history, not what
# happens to be sitting in the worktree.
git -C "$SRC" archive --format=tar --prefix="$UNIT-$VERSION/" HEAD \
  | gzip -n -9 > "$TAR" || exit 3
touch -d "@$EPOCH" "$TAR"

NFILES=$(git -C "$SRC" ls-tree -r --name-only HEAD | wc -l)
cat > "$STAGE/$UNIT/BUILD-RECORD.md" <<REC
# $UNIT $VERSION — build record

| | |
|---|---|
| unit | \`$UNIT\` |
| version | \`$VERSION\` |
| branch | \`$BRANCH\` |
| commit | \`$COMMIT\` |
| files | $NFILES |
| artifact | \`$UNIT-$VERSION.tar.gz\` |
| sha256 | \`$(sha256sum "$TAR" | cut -d' ' -f1)\` |
| bytes | $(stat -c%s "$TAR") |
| source epoch | \`$EPOCH\` (the commit's own time) |

Built by \`workflow/pack-script-unit.sh\` with \`git archive\` from the commit above, gzipped
with \`-n\` so no timestamp enters the stream. Packing the same commit again produces the same
bytes; that is the only claim of reproducibility made here, and it is checkable with
\`sha256sum\`.
REC
touch -d "@$EPOCH" "$STAGE/$UNIT/BUILD-RECORD.md"
echo "  $UNIT $VERSION -> $TAR ($(stat -c%s "$TAR") bytes, $NFILES files from $COMMIT)"
