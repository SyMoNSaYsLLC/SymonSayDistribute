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

# the capability modules this service imports from its own package
caps = set()
for n in ast.walk(tree):
    if isinstance(n, ast.ImportFrom) and n.level == 1:
        caps |= {a.name for a in n.names}

bad = 0
for cap in sorted(caps):
    f = pkg / f"{cap}.py"
    if not f.is_file():
        continue
    m = ast.parse(f.read_text())
    declared = {}
    for node in m.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
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
