#!/usr/bin/env bash
# one-line: refuses pkill --ns, pkill -f and pgrep -f
# target: content — the staged bytes are what becomes history
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# `pkill --ns` signals every process in the root namespace and hard-crashed this host on
# 2026-09-18. `pgrep -f` and `pkill -f` match the pattern against the agent's own command line,
# so the agent kills its own shell — which has also happened here, exit 144.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }
hits=$(grep -rnE '\bpkill[[:space:]]+(--ns\b|-[a-zA-Z]*f)|\bpgrep[[:space:]]+-[a-zA-Z]*f' \
        --include='*.sh' --include='*.bash' --include='*.py' --exclude-dir=.git "$T" 2>/dev/null \
        | grep -vE ':[0-9]+:[[:space:]]*#' | grep -v 'gate''-allow')
if [ -n "$hits" ]; then
  echo "forbidden process-signalling found:"; echo "$hits" | sed 's/^/  /'
  echo "  stop a process by PID, with SIGCONT before SIGTERM."
  exit 1
fi
exit 0
