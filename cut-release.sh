#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
#
# cut-release — publish one runtime's release, but only if the ship gate passes.
#
#   Run from a runtime checkout, with this branch as a worktree beside it:
#     git worktree add workflow workflow
#     workflow/cut-release.sh <runtime> <version> <stage> [--dry-run] [--prerelease]
#     workflow/cut-release.sh symoneural-learn 1.4.0 ~/symoneural-release/v1.4.0
#
# WHY A RUNTIME NAME AND NOT JUST A TAG
# -------------------------------------
# In this distribution a runtime owns a branch and cuts its own releases, so a bare `v1.4.0`
# is ambiguous the moment a second runtime exists: two of them can sit at the same version
# and mean entirely different things. The tag is `<runtime>/v<version>`, and the runtime name
# is also what the cutter checks the checked-out branch against — publishing one runtime's
# release from another runtime's branch is the mistake this argument exists to prevent.
#
# What it enforces, in order, each with its own exit code check:
#   1. the checked-out branch IS the runtime, the tree is clean, and the tag is free
#   2. the stage carries SHA256SUMS, RELEASE-NOTES.md, THIRD-PARTY-NOTICES.md, all verifying
#   3. workflow/ship-gate.py --stage <stage> exits 0
#   4. every asset has a distinct basename — a collision is refused here, not discovered by
#      GitHub after the tag has been pushed
#   5. gh release create <runtime>/v<version> with every asset attached
#
# No `set -e`: every step checks its own exit code and exits with a documented number
# (3 branch/tree/tag, 4 stage, 5 gate, 6 layout, 7 exists, 8 gh).
set -o pipefail

RUNTIME=${1:?runtime name, e.g. symoneural-learn}
VERSION=${2:?version without a leading v, e.g. 1.4.0}
STAGE=${3:?stage directory}
shift 3
DRY=0; PRE=""
for a in "$@"; do case "$a" in --dry-run) DRY=1;; --prerelease) PRE="--prerelease";; *) echo "unknown arg $a" >&2; exit 2;; esac; done

VERSION=${VERSION#v}
TAG="$RUNTIME/v$VERSION"
# The machinery lives on its own branch and is usually checked out as a worktree inside the
# runtime it is releasing, so its own location says nothing about which runtime is being cut.
# The runtime is the directory this was RUN from; the scripts are beside this one.
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "   not inside a git checkout"; exit 3; }
cd "$REPO_DIR" || exit 3

echo "== 1. branch ↔ runtime"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "$RUNTIME" ]; then
  echo "   on branch '$BRANCH' but asked to release '$RUNTIME' — check out that branch first"; exit 3
fi
HEAD=$(git rev-parse HEAD)
[ -z "$(git status --porcelain)" ] || { echo "   working tree not clean — commit or stash first"; git status --porcelain | head; exit 3; }
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  TAGGED=$(git rev-parse "$TAG^{commit}")
  [ "$TAGGED" = "$HEAD" ] || { echo "   tag $TAG points at $TAGGED but HEAD is $HEAD — refusing"; exit 3; }
  echo "   tag $TAG exists and matches HEAD $HEAD"
else
  echo "   tag $TAG will be created at HEAD $HEAD on branch $BRANCH"
fi

echo "== 2. stage integrity"
for f in SHA256SUMS RELEASE-NOTES.md THIRD-PARTY-NOTICES.md; do
  [ -s "$STAGE/$f" ] || { echo "   missing $STAGE/$f"; exit 4; }
done
( cd "$STAGE" && sha256sum -c --quiet SHA256SUMS ); rc=$?
[ $rc -eq 0 ] || { echo "   SHA256SUMS verification failed rc=$rc"; exit 4; }
echo "   $(wc -l < "$STAGE/SHA256SUMS") sums verified"

echo "== 3. ship gate"
python3 -I "$HERE/ship-gate.py" --stage "$STAGE" --repo . --json "$STAGE/SHIP-GATE-REPORT.json"; rc=$?
[ $rc -eq 0 ] || { echo "   SHIP GATE FAILED rc=$rc — nothing is published"; exit 5; }

echo "== 4. assets"
ASSETS=()
while IFS= read -r f; do
  base=$(basename "$f")
  case "$base" in SHA256SUMS|RELEASE-NOTES.md|THIRD-PARTY-NOTICES.md|SHIP-GATE-REPORT.json|BUILD-RECORD.md|cargo-metadata.json) continue;; esac
  ASSETS+=("$f")
done < <(find "$STAGE" -mindepth 2 -type f | sort)
for extra in SHA256SUMS THIRD-PARTY-NOTICES.md SHIP-GATE-REPORT.json; do ASSETS+=("$STAGE/$extra"); done
# An asset is published under its own basename: `gh release create file#text` sets the asset's
# LABEL, not its name. A rename attempted there is silently ignored, which once published
# three assets under names the installer did not match — after the tag was already immutable.
dupes=$(printf '%s\n' "${ASSETS[@]##*/}" | sort | uniq -d)
[ -z "$dupes" ] || { echo "   duplicate asset basenames — pack the trees first:"; printf '     %s\n' $dupes; exit 6; }
printf '   %s\n' "${ASSETS[@]##*/}"

echo "== 5. publish"
if gh release view "$TAG" >/dev/null 2>&1; then echo "   release $TAG already exists — releases are immutable here; bump the version"; exit 7; fi
CMD=(gh release create "$TAG" --title "$RUNTIME $VERSION" --notes-file "$STAGE/RELEASE-NOTES.md" --target "$HEAD" $PRE "${ASSETS[@]}")
if [ $DRY -eq 1 ]; then echo "   DRY RUN — would run:"; printf '   %q ' "${CMD[@]}"; echo; exit 0; fi
if ! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  git tag -a "$TAG" -m "$RUNTIME $VERSION"; rc=$?; [ $rc -eq 0 ] || { echo "   git tag rc=$rc"; exit 8; }
  git push origin "refs/tags/$TAG"; rc=$?;   [ $rc -eq 0 ] || { echo "   tag push rc=$rc"; exit 8; }
  echo "   tag $TAG created at $HEAD and pushed"
fi
"${CMD[@]}"; rc=$?
[ $rc -eq 0 ] || { echo "   gh release create rc=$rc"; exit 8; }
gh release view "$TAG" --json tagName,isDraft,isPrerelease,url,assets \
  --jq '{tag:.tagName, draft:.isDraft, prerelease:.isPrerelease, url:.url,
         assets:(.assets|length), pending:[.assets[]|select(.state!="uploaded")|.name]}'; rc=$?
[ $rc -eq 0 ] || echo "   release created; the confirmation query failed rc=$rc — check the URL above"
exit 0
