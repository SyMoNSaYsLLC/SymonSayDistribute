#!/usr/bin/env bash
# one-line: refuses anything that looks like a live credential
# target: content — the staged bytes are what becomes history
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# Section 3.2: never print, generate or commit a secret. The gate names the file and the line,
# never the value — reporting a leak by quoting it is still a leak.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }
PATTERNS='sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-[A-Za-z0-9-]{10,}'
found=$(grep -rnIE "$PATTERNS" --exclude-dir=.git "$T" 2>/dev/null | grep -v 'gate''-allow' | cut -d: -f1,2)
if [ -n "$found" ]; then
  echo "credential-shaped content found (locations only, values withheld):"
  echo "$found" | sort -u | sed 's/^/  /'
  exit 1
fi
exit 0
