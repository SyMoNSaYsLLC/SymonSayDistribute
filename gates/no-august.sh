#!/usr/bin/env bash
# one-line: refuses material dated August 2026
# staged: yes — scans content and mtimes
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# gate-allow-file: no-august — this file is the detector; it names the date to refuse it.
# August 2026 predates the fresh start. Anything carrying that date
# belongs to the estate that was abandoned, and reintroducing it reintroduces decisions that
# were deliberately dropped. This file names the date in order to refuse it, which is why the
# marker above exempts it from itself.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }

DATE_RX='2026-08-[0-3][0-9]|August 2026'   # gate-allow: no-august — this IS the detector

# Two exemptions, both explicit and both greppable, so `gate --exemptions` can list every one:
#   gate-allow:      on a line   — that line declares the pattern rather than using it
#   gate-allow-file: in a file   — the whole file is a detector or a fixture for this gate
# A gate that exempted itself silently would be free to hide a real violation in its own source.
EXEMPT_FILES=$(grep -rlI "gate""-allow-file: no-august" --exclude-dir=.git "$T" 2>/dev/null)
hits=$(grep -rnI -E "$DATE_RX" --exclude-dir=.git "$T" 2>/dev/null \
       | grep -v 'gate''-allow' \
       | cut -d: -f1,2)
if [ -n "$EXEMPT_FILES" ]; then
  while IFS= read -r ef; do
    [ -n "$ef" ] && hits=$(printf '%s\n' "$hits" | grep -v -F "$ef:")
  done <<< "$EXEMPT_FILES"
fi
mtimes=$(find "$T" -type f -newermt '2026-08-01' ! -newermt '2026-09-01' -not -path '*/.git/*' 2>/dev/null)

rc=0
if [ -n "$hits" ]; then
  echo "August 2026 referenced:"; echo "$hits" | sort -u | sed 's/^/  /'; rc=1
fi
if [ -n "$mtimes" ]; then
  echo "files last modified in August 2026:"; echo "$mtimes" | sed 's/^/  /'; rc=1
fi
exit $rc
