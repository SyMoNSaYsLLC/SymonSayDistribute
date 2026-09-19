#!/usr/bin/env bash
# one-line: refuses a component on the board that nothing can reach
# target: estate — the board, the fabric and the connectors live in different worktrees
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# Wiring a component is four places. Miss one and it is built, released, running, and
# unreachable by the thing that needs it.
#
# This happened FIVE times on 2026-09-19 alone:
#
#   ravencalc        released and running, absent from the board entirely
#   symonloop        board + fabric, no agent tool
#   symonscheduler   board + fabric, no agent tool
#   symonskill       board + fabric, no agent tool — and reported as "all four places"
#   symonimage       released before its port was on the board
#
# Each was found by accident, days or hours later. A rule broken five times in one day is not
# a discipline problem, it is a missing check — so here is the check.
#
# WHAT IT REQUIRES
# For every name in /mnt/models/control.board [ports]:
#   1. the fabric's KNOWN table routes it, or it is listed in NOT_ROUTABLE with a reason;
#   2. the agents connectors reach it, or it is listed in NO_TOOL_REASON with a reason.
#
# Silence is the failure. A component deliberately without a tool is fine and normal — the
# board serves the board, the gateway owns its own dialect — but not deciding is not.
set -o pipefail
[ $# -ge 1 ] || { echo "usage: wiring-complete.sh <tree> [more trees]" >&2; exit 2; }

BOARD=${SYM_BOARD_FILE:-/mnt/models/control.board}
DIST=""
for p in "$@"; do
  case "$p" in *SymonSayDistribute*) DIST="$p" ;; esac
done
[ -n "$DIST" ] || DIST=/mnt/SymonSayDistribute

WIRING="$DIST/adaptive-fabric/symoneural_fabric/wiring.py"
CONN="$DIST/agents/symoneural_agents/connectors.py"

# Nothing to check if the pieces are not all present — a partial checkout is not a violation.
[ -r "$BOARD" ] || { echo "no board at $BOARD" >&2; exit 2; }
[ -r "$WIRING" ] || { echo "no fabric wiring table at $WIRING" >&2; exit 2; }
[ -r "$CONN" ] || { echo "no connectors at $CONN" >&2; exit 2; }

python3 - "$BOARD" "$WIRING" "$CONN" <<'PY'
import ast, re, sys, pathlib

board_p, wiring_p, conn_p = (pathlib.Path(a) for a in sys.argv[1:4])

# --- the board's [ports] section, as written -------------------------------------------------
text = board_p.read_text(errors="replace")
start = text.find("[ports]")
if start < 0:
    print(f"  {board_p} has no [ports] section"); sys.exit(1)
block = text[start + len("[ports]"):]
end = block.find("\n[")
block = block[:end] if end > 0 else block
named = [m.group(1) for m in re.finditer(r'^\s*([a-z_][a-z0-9_]*)\s*=\s*\d{2,5}', block, re.M)]

# --- the fabric: KNOWN routes it, or NOT_ROUTABLE says why not -------------------------------
w = wiring_p.read_text(errors="replace")
def _dict_keys(src: str, name: str) -> set:
    for node in ast.parse(src).body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) and node.value else [])
        for t in targets:
            if isinstance(t, ast.Name) and t.id == name:
                try:
                    return set(ast.literal_eval(node.value))
                except Exception:
                    return {k.value for k in node.value.keys
                            if isinstance(k, ast.Constant)} if hasattr(node.value, "keys") else set()
    return set()

known = _dict_keys(w, "KNOWN")
not_routable = _dict_keys(w, "NOT_ROUTABLE")

# --- the connectors: a tool names it, or NO_TOOL_REASON says why not --------------------------
c = conn_p.read_text(errors="replace")
reached = {n for n in named if re.search(rf'["\']{re.escape(n)}["\']', c)}
no_tool_reason = _dict_keys(c, "NO_TOOL_REASON")

bad = []
for n in named:
    if n not in known and n not in not_routable:
        bad.append((n, "the fabric neither routes it nor records why not",
                    "add it to KNOWN, or to NOT_ROUTABLE with the reason"))
    if n not in reached and n not in no_tool_reason and n not in not_routable:
        bad.append((n, "no agent tool reaches it and no reason is recorded",
                    "add a tool in connectors.py, or a NO_TOOL_REASON entry"))

if bad:
    print(f"  {len(bad)} wiring gap(s) across {len(named)} component(s) on the board:")
    for n, why, fix in bad:
        print(f"    {n:16} {why}")
        print(f"    {'':16} -> {fix}")
    print("  A component the estate cannot reach is not finished; it is abandoned somewhere tidy.")
    sys.exit(1)
print(f"  {len(named)} component(s) on the board, all routed and all reachable or explained")
PY
