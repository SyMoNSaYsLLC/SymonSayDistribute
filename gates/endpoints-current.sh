#!/usr/bin/env bash
# one-line: refuses a capability that no endpoint reaches
# target: content — a capability added without a route is added in the staged bytes
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# A runtime that can do something the network cannot ask for has a capability the estate cannot
# use. It looks finished in every report — the module is there, the tests pass — and the only
# way to reach it is for somebody to remember it exists and import it.
#
# That happened: ravencalc shipped v1.0.0 with the whole model arithmetic — KV cache sizing,
# expert residency, the fit budget, the GPU fraction — and not one route touching it. Every
# serving figure it produced was unreachable over HTTP for a full release.
#
# WHAT IT CHECKS
# --------------
# For a branch carrying a service, every PUBLIC callable in each capability module it imports
# must either be named somewhere in the service, or be listed in that module's `NOT_EXPOSED`
# with a reason. Silence is the failure. A capability is exposed or it is deliberately not,
# and either is fine — not deciding is not.
#
#     NOT_EXPOSED = {"helper": "internal; every caller goes through budget()"}
set -o pipefail
T=${1:?path to check}
[ -d "$T" ] || { echo "no such directory: $T" >&2; exit 2; }

mapfile -t SERVICES < <(find "$T" -name 'service.py' -not -path '*/.git/*' -not -path '*__pycache__*' 2>/dev/null)
[ "${#SERVICES[@]}" -gt 0 ] || { echo "no service.py here — nothing to keep current" >&2; exit 2; }

rc=0
for svc in "${SERVICES[@]}"; do
  pkg=$(dirname "$svc")
  python3 - "$svc" "$pkg" <<'PY'
import ast, sys, pathlib
svc, pkg = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
text = svc.read_text()
tree = ast.parse(text)

# The capability modules this service imports. BOTH forms count:
#
#   from . import model        a package layout
#   import board as B          a flat layout, a sibling module in the same directory
#
# Only the first was checked, so a flat service passed having examined nothing — the gate
# reporting PASS because it had found no modules to look at. A check that cannot fail is not
# a check, and that is the one rule this whole suite is built on.
# THREE import forms, all of which this estate actually uses. Each was found by a service
# passing vacuously:
#
#   from . import model                   a package-relative sibling
#   import board as B                     a flat module beside the service
#   from symoneural_agents import tools   an absolute package beside the service
#
# caps holds (directory, module) so a capability can live one level down.
caps: set[tuple] = set()
for n in ast.walk(tree):
    if isinstance(n, ast.ImportFrom) and n.level == 1:
        caps |= {(pkg, a.name) for a in n.names}
    elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
        head = n.module.split(".")[0]
        d = pkg / head
        if d.is_dir():
            caps |= {(d, a.name) for a in n.names}
    elif isinstance(n, ast.Import):
        for a in n.names:
            head = a.name.split(".")[0]
            if (pkg / f"{head}.py").is_file() and head != svc.stem:
                caps.add((pkg, head))

if not caps:
    print(f"  no capability module found beside {svc.name} — nothing was checked")
    sys.exit(2)

bad = 0
for d, cap in sorted(caps, key=lambda c: (str(c[0]), c[1])):
    f = d / f"{cap}.py"
    if not f.is_file():
        continue
    m = ast.parse(f.read_text())
    declared = {}
    # BOTH assignment forms. `NOT_EXPOSED = {...}` is an ast.Assign; the annotated
    # `NOT_EXPOSED: dict[str, str] = {...}` is an ast.AnnAssign and was invisible here.
    # The gate then saw an empty dict and refused a component whose declarations were
    # correct — it failed CLOSED, which is the safe direction, but it rejected valid code
    # and the author had no way to see why. Found 2026-09-19 while building symondriver.
    for node in m.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "NOT_EXPOSED":
                try:
                    declared = ast.literal_eval(node.value)
                except Exception:
                    declared = {}
    public = [node.name for node in m.body
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and not node.name.startswith("_")]
    for name in public:
        if name in declared:
            continue
        if f"{cap}.{name}" in text or f"{name}(" in text:
            continue
        print(f"  unreachable: {cap}.{name}() has no route and no NOT_EXPOSED entry")
        bad += 1
sys.exit(1 if bad else 0)
PY
  [ $? -eq 0 ] || rc=1
done

if [ $rc -ne 0 ]; then
  echo "  A capability with no endpoint cannot be used by anything but an import."
  echo "  Add a route, or record why not:  NOT_EXPOSED = {\"name\": \"reason\"}"
fi
exit $rc
