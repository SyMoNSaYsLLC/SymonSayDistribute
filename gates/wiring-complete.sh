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

def _dict_items(src: str, name: str) -> dict | None:
    """Read a dict ANYWHERE in the file, including inside a function.

    _dict_keys walks only the module body. `by_tool` is built inside the function that
    assembles the registry, so a module-body walk cannot see it — which is why the first
    version of this gate fell back to a regex over the whole file and passed on a gap it
    exists to catch. An ast.walk sees it.
    """
    for node in ast.walk(ast.parse(src)):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) and getattr(node, "value", None) else [])
        for t in targets:
            if isinstance(t, ast.Name) and t.id == name:
                try:
                    return dict(ast.literal_eval(node.value))
                except Exception:
                    return {}
    # None means "the name is not there at all", which is different from "it is there and
    # empty". An empty tool map is a legitimate state; an absent one means this gate cannot
    # see the mapping and must not report a pass. Conflating them made the gate exit 2 on a
    # fixture built to make it FAIL — found by gates/selftest.sh on 2026-09-20.
    return None


# A reason that defers the decision is not a decision. On 2026-09-19 `symondevice` sat in
# NO_TOOL_REASON as "PENDING — must become a tool or a real reason before it is released" and
# this gate returned rc=0, because a key was present and the old reachability test matched any
# quoted occurrence of the name anywhere in the file. Both holes are closed below.
_DEFERRAL = re.compile(r"\b(PENDING|TODO|TBD|FIXME|XXX|placeholder|for now|later)\b", re.I)

known = _dict_keys(w, "KNOWN")
not_routable_items = _dict_items(w, "NOT_ROUTABLE") or {}
not_routable = set(not_routable_items) or _dict_keys(w, "NOT_ROUTABLE")

# --- the connectors: a tool actually maps to it, or NO_TOOL_REASON says why not ---------------
c = conn_p.read_text(errors="replace")
by_tool = _dict_items(c, "by_tool")
if by_tool is None:
    # A check that cannot fail has gated nothing. Say so rather than quietly regressing.
    print("  cannot read the tool->component map (`by_tool`) from the connectors; "
          "this gate cannot verify reachability and is not reporting a pass")
    sys.exit(2)
reached = set(by_tool.values())
no_tool_reason_items = _dict_items(c, "NO_TOOL_REASON") or {}
no_tool_reason = set(no_tool_reason_items) or _dict_keys(c, "NO_TOOL_REASON")

bad = []
for n, why in list(not_routable_items.items()) + list(no_tool_reason_items.items()):
    if isinstance(why, str) and _DEFERRAL.search(why):
        bad.append((n, f"its recorded reason defers the decision: {why.strip()[:70]!r}",
                    "replace it with a real reason, or wire the component"))

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
