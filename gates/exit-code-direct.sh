#!/usr/bin/env bash
# one-line: refuses an exit code read through a pipeline
# staged: yes — scans shell content
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# Section 3.1: exit codes are checked directly, never through a pipeline. `cmd | tail; rc=$?`
# reads tail's status, not the command's, so a failing build reports success. This estate has
# already shipped one: a check that read $? from a pipeline "confirmed" a guard script that was
# not on disk at all.
#
# WHAT THE FIRST VERSION GOT WRONG
# --------------------------------
# It matched a bare `|` and so fired on every `||` in the estate — `[ $? -eq 0 ] || FAILS=…`
# was reported as a pipeline when it is the opposite, an exit code being checked directly and
# then acted on. A gate that cries wolf is a gate that gets ignored, so `||` and `&&` are
# excluded here, quoted pipes are excluded too, and only a real shell pipe on the same line
# as the `$?` counts. A previous-line check was tried and dropped: it fired on every function
# whose body happened to end in a pipe, which is indirect enough to be noise.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }

hits=$(find "$T" -type f \( -name '*.sh' -o -name '*.bash' \) -not -path '*/.git/*' -print0 2>/dev/null \
  | xargs -0 -r awk '
      # A pipe only matters when it is SHELL syntax reaching the command whose status is read.
      # Four things look like one and are not, each found by a real false positive in this
      # estate and each dropped here:
      #   ||  and  &&                     logical operators, the opposite of a pipeline
      #   a | inside quotes               a jq program, an awk -F, a regex alternation
      #   a | inside a quote spanning      cut-release.sh holds a jq program across five lines
      #     several lines
      #   a | in a DIFFERENT command       `pat=$(echo x | awk ...); fetch "$p"; rc=$?`
      #     on the same line               reads fetch, which is not piped at all
      function unquote(s,   out, i, c, inq) {
        out = ""; inq = ""
        for (i = 1; i <= length(s); i++) {
          c = substr(s, i, 1)
          if (inq == "") { if (c == "\047" || c == "\"") { inq = c; continue } out = out c }
          else if (c == inq) { inq = "" }
        }
        return out
      }
      function has_pipe(s) { gsub(/\|\|/, "", s); gsub(/&&/, "", s); return s ~ /\|/ }
      {
        line = $0
        # carry the quote state across lines: an odd number of quotes opens a run that the
        # next line continues, which is how a multi-line jq program is recognised as a string.
        if (inrun) {
          n = gsub(/\047/, "\047", line)
          if (n % 2 == 1) inrun = 0
          next
        }
        probe = line
        n = gsub(/\047/, "\047", probe)
        if (n % 2 == 1) { inrun = 1 }

        code = line
        sub(/^[ \t]*#.*/, "", code)
        if (code ~ /gate-allow/ || code ~ /PIPESTATUS/ || code !~ /\$\?/) next
        bare = unquote(code)
        # split into commands and look only at the one holding $? and the one before it
        nseg = split(bare, seg, /;/)
        for (i = 1; i <= nseg; i++) {
          if (seg[i] ~ /\$\?/) {
            if (has_pipe(seg[i]) || (i > 1 && has_pipe(seg[i-1]))) {
              printf "%s:%d:%s\n", FILENAME, FNR, $0
              break
            }
          }
        }
      }' 2>/dev/null)

if [ -n "$hits" ]; then
  echo "exit code read after a pipeline (use PIPESTATUS, or do not pipe):"
  echo "$hits" | sed 's/^/  /'
  exit 1
fi
exit 0
