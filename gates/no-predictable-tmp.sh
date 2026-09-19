#!/usr/bin/env bash
# one-line: refuses a temporary file at a guessable path
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# A temporary file must be created with mktemp. Writing to a path a script composes itself —
# /tmp/.m.$$, /tmp/build.log, /tmp/$USER-out — is guessable, and /tmp is world-writable.
# Anything that can create that path first, as a symlink, redirects the write somewhere else.
# The sticky bit stops another user DELETING the file; it does not stop them creating it before
# the script does.
#
# $$ is the worst of them because it reads like uniqueness and is not: pids are small, they are
# reused, and they are visible to anyone who can run ps.
#
# Found in this estate on 2026-09-18: verify-3p-path.sh wrote the gateway's authenticated
# /v1/models response to /tmp/.m.$$ with no trap, so a failure between the write and the rm left
# it behind as well.
#
# mktemp is not flagged: it creates the file atomically with the right mode and fails rather
# than following a symlink.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }

hits=$(grep -rnE '(^|[^A-Za-z0-9_$/])/tmp/[A-Za-z0-9._$-]+' \
        --include='*.sh' --include='*.bash' --include='*.py' --exclude-dir=.git "$T" 2>/dev/null \
      | grep -v 'mktemp' \
      | grep -vE ':[0-9]+:[[:space:]]*(#|//)' \
      | grep -v 'gate''-allow')

if [ -n "$hits" ]; then
  echo "temporary file at a guessable path — use mktemp:"
  echo "$hits" | sed 's/^/  /'
  exit 1
fi
exit 0
