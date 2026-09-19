#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""third-party-notices — THIRD-PARTY-NOTICES.md from the ship gate's report, never from memory.

    tools/third-party-notices.py --report <stage>/SHIP-GATE-REPORT.json --stage <stage> --out <stage>/THIRD-PARTY-NOTICES.md

For every unit in the report: every component the gate's own census found (wheel metadata,
package manifests, ELF NEEDED, crate closures, image manifests) with its version, licence
expression and class. Then, for every licence text carried inside the stage (licenses/ and
LICENSE.* files beside the binaries), the copyright lines those texts contain — the
attribution the permissive licences oblige us to keep. Components the gate classified as
first-party are listed under their own heading so the boundary is visible.

The result is what the gate's attribution check reads back; a component missing here fails the
release, so this file is generated, not edited.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

POLICY = json.loads((Path(__file__).resolve().parent / "ship-gate-policy.json").read_text())
PRODUCT_LICENCE = POLICY["product_licence"]

ORDER = ["PERMISSIVE", "INVOKED_NOT_LINKED", "WEAK_COPYLEFT_FILE", "WEAK_COPYLEFT_LIB", "NUISANCE_CLAUSE", "PROPRIETARY_THIRD_PARTY", "USE_RESTRICTED", "UNKNOWN", "STRONG_COPYLEFT", "NETWORK_COPYLEFT"]

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True); ap.add_argument("--stage", type=Path, required=True); ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rep = json.loads(a.report.read_text())
    lines = ["# Third-party notices", "",
             f"SyMoNsAyLeaRn is licensed under {PRODUCT_LICENCE} (see LICENSE). A release combines that first-party work with",
             "the third-party components below, each under its own licence. This file is generated from the ship",
             f"gate's census of the staged artifacts (`{a.report.name}`, policy `{rep.get('policy')}`); it lists what the",
             "artifacts actually contain, not what a dependency file declares.", ""]
    total = 0
    for unit, u in sorted(rep["units"].items()):
        comps = u.get("components", [])
        if not comps:
            continue
        third = [c for c in comps if c.get("reason") != "first-party"]
        first = [c for c in comps if c.get("reason") == "first-party"]
        lines += [f"## {unit}", ""]
        if first:
            lines += [f"First-party ({PRODUCT_LICENCE}): " + ", ".join(sorted({c['name'] for c in first})), ""]
        by_class: dict[str, list] = {}
        for c in third:
            by_class.setdefault(c.get("class", "UNKNOWN"), []).append(c)
        for klass in ORDER:
            rows = by_class.get(klass)
            if not rows:
                continue
            lines += [f"### {klass.replace('_', ' ').title()} ({len(rows)})", "", "| component | version | licence | source of the census |", "|---|---|---|---|"]
            seen = set()
            for c in sorted(rows, key=lambda c: (c["name"].lower(), str(c.get("version")))):
                key = (c["name"], c.get("version"))
                if key in seen:
                    continue
                seen.add(key); total += 1
                lines.append(f"| {c['name']} | {c.get('version') or ''} | {c.get('license') or '—'} | {c.get('source') or ''} |")
            lines.append("")
    # copyright lines from every licence text carried in the stage
    lines += ["## Copyright notices carried with the artifacts", "",
              "Each binary unit ships the licence texts of the trees it was built from under `licenses/` or as",
              "`LICENSE.<component>`. The copyright statements those texts contain:", ""]
    found = 0
    for p in sorted(a.stage.rglob("*")):
        if not p.is_file() or "licenses" not in p.parts and not p.name.startswith("LICENSE."):
            continue
        if p.name == "LICENSE" and p.parent.name != "licenses":
            continue  # our own licence copies
        try:
            text = p.read_text(errors="replace")
        except Exception:
            continue
        cps = sorted({l.strip() for l in text.splitlines() if re.match(r"\s*(copyright|\(c\)|©)", l, re.I)})
        if cps:
            found += 1
            lines += [f"- `{p.relative_to(a.stage)}`:"] + [f"    - {c[:160]}" for c in cps[:12]]
    lines += ["", f"{total} third-party components listed; {found} carried licence texts scanned.", ""]
    a.out.write_text("\n".join(lines))
    print(f"wrote {a.out} — {total} components, {found} licence texts")

if __name__ == "__main__":
    main()
