#!/usr/bin/env bash
# one-line: refuses `git add .` and `git add -A` anywhere in the tree
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# Section 3.2 forbids a blanket stage outright. This estate holds a live API key, multi-gigabyte
# weights and whole build trees in directories a blanket stage would sweep up, and a secret that
# reaches a remote cannot be recalled. The rule is only worth having if something enforces it.
#
# A line that documents the prohibition is not a violation, so a comment is not counted.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }
hits=$(grep -rnE '(^|[;&|`]|\$\()[[:space:]]*git[[:space:]]+add[[:space:]]+(-A\b|--all\b|\.[[:space:]]*$)' \
         --include='*.sh' --include='*.bash' --include='*.py' --include='*.md' \
         --exclude-dir=.git "$T" 2>/dev/null | grep -vE ':[[:space:]]*#' | grep -vE '^[^:]+:[0-9]+:[[:space:]]*(#|//)' | grep -v 'gate''-allow')
if [ -n "$hits" ]; then
  echo "blanket stage found — section 3.2 forbids it:"; echo "$hits" | sed 's/^/  /'; exit 1
fi
exit 0
