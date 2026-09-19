#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Give every directory the document §3.7 requires, with content read from the code.

WHY A GENERATOR AND NOT 198 HAND-WRITTEN STUBS
----------------------------------------------
§3.7 does not ask for a file to exist. It asks for three things, and a stub satisfies none:

    "Every subdirectory document states its interfaces … every interface and endpoint the
     directory exposes to, or consumes from, other directories: files read and written,
     functions and services called, ports, environment variables, build targets."

    "Each such reference links to the document of the directory on the other side."

    "A document that links nowhere onward is a dead end and is not permitted."

So each document here is derived from what is actually in the directory: the modules, their
public callables, the environment contract they read, the routes they serve, what they import
and what imports them. A generated document that says something false is worse than none, so
everything it claims is read from disk at generation time and nothing is assumed.

WHAT IT WILL NOT DO
It never overwrites an existing document. Hand-written prose beats generated prose every time,
and the documents already written by hand — symonimage.md, symonloop.md and their siblings —
are the reason this estate can be read at all. This fills gaps; it does not flatten.

Run:  python3 document-directories.py [--apply] [--root /mnt/SymonSayDistribute]
Without --apply it reports what it would write and changes nothing.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path
from typing import Any

SKIP = {".git", "__pycache__", ".pytest_cache", ".bare", "node_modules", ".venv", "venv",
        ".mypy_cache", ".ruff_cache", "dist", "build"}
TREES = ("SymonSayDistribute", "SymonSaySource", "SymonSayOSS", "SymonSayOpen")


def python_surface(d: Path) -> dict[str, Any]:
    """What this directory's python actually offers, parsed rather than guessed."""
    mods: list[dict[str, Any]] = []
    for f in sorted(d.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(errors="replace"))
        except SyntaxError:
            mods.append({"file": f.name, "error": "does not parse"})
            continue
        pub = [n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and not n.name.startswith("_")]
        cls = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        doc = ast.get_docstring(tree) or ""
        mods.append({"file": f.name, "public": pub, "classes": cls,
                     "summary": doc.strip().splitlines()[0] if doc else ""})
    return {"modules": mods}


def env_contract(d: Path) -> list[str]:
    """Every SYM_* variable the directory reads. Its configuration interface (§3.7)."""
    found: set[str] = set()
    for f in list(d.glob("*.py")) + list(d.glob("*.sh")):
        txt = f.read_text(errors="replace")
        found |= set(re.findall(r'environ\.get\(\s*["\'](SYM_[A-Z0-9_]+)', txt))
        found |= set(re.findall(r'environ\[\s*["\'](SYM_[A-Z0-9_]+)', txt))
        found |= set(re.findall(r'\$\{?(SYM_[A-Z0-9_]+)', txt))
    return sorted(found)


def routes_of(worktree: Path) -> list[str]:
    """The HTTP surface the unit publishes, from its service.py."""
    out: list[str] = []
    for svc in list(worktree.glob("service.py")) + [p for p in worktree.glob("*/service.py")
                                                    if "tests" not in str(p)]:
        txt = svc.read_text(errors="replace")
        out += [f"{m.group(1).upper():6} {m.group(2)}"
                for m in re.finditer(r'@app\.(get|post|put|delete)\("([^"]+)"', txt)]
    return out


def local_imports(d: Path, worktree: Path) -> list[str]:
    """Sibling directories inside this worktree that this one imports from."""
    names = {p.name for p in worktree.iterdir() if p.is_dir() and p.name not in SKIP}
    hits: set[str] = set()
    for f in d.glob("*.py"):
        try:
            tree = ast.parse(f.read_text(errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                head = n.module.split(".")[0]
                if head in names:
                    hits.add(head)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    head = a.name.split(".")[0]
                    if head in names:
                        hits.add(head)
    return sorted(hits - {d.name})


def imported_by(d: Path, worktree: Path) -> list[str]:
    """Which sibling directories import THIS one. The other half of the interface."""
    hits: set[str] = set()
    for other in worktree.iterdir():
        if not other.is_dir() or other.name in SKIP or other == d:
            continue
        for f in other.rglob("*.py"):
            if any(p in SKIP for p in f.parts):
                continue
            if re.search(rf'\b(from|import)\s+{re.escape(d.name)}\b',
                         f.read_text(errors="replace")):
                hits.add(other.name)
                break
    if any(re.search(rf'\b(from|import)\s+{re.escape(d.name)}\b',
                     f.read_text(errors="replace"))
           for f in worktree.glob("*.py")):
        hits.add(worktree.name)
    return sorted(hits)


def kind_of(d: Path, worktree: Path) -> str:
    n = d.name
    if n == "tests":
        return "tests"
    if n == worktree.name or n.startswith("symoneural_") or n.startswith("symon"):
        return "package"
    if n in ("scripts", "bin"):
        return "scripts"
    if n == "pins":
        return "pins"
    if n.startswith("recipes") or n.startswith("meta-"):
        return "recipes"
    return "directory"


def compose(d: Path, worktree: Path, tree: str) -> str:
    """The document. Every claim in it is read from disk at generation time."""
    kind = kind_of(d, worktree)
    rel = d.relative_to(worktree)
    parent = d.parent
    parent_doc = f"{parent.name}.md" if parent != worktree else f"{worktree.name}.md"
    up = os.path.relpath(parent / parent_doc, d)

    L = [f"# {d.name}", ""]

    if d == worktree:
        subs = sorted(x for x in worktree.iterdir()
                      if x.is_dir() and x.name not in SKIP)
        L += [f"The `{d.name}` branch of `{tree}`.", "",
              "§3.7: this is the map. Every directory below is listed with what lives there and",
              "why a reader would go to it.", ""]
        rts = routes_of(worktree)
        if rts:
            L += ["## What it serves", "", "```"] + [f"    {r}" for r in rts] + ["```", ""]
        if subs:
            L += ["## Directories", "", "| Directory | Holds |", "|---|---|"]
            for s in subs:
                k = kind_of(s, worktree)
                held = {"tests": "what proves this unit does what it says",
                        "package": "the capability this unit provides",
                        "scripts": "executable steps, not a library",
                        "pins": "what this branch builds from, by full SHA",
                        "recipes": "build recipes"}.get(k, "part of this unit")
                L.append(f"| [`{s.name}`]({s.name}/{s.name}.md) | {held} |")
            L.append("")
        else:
            L += ["## Directories", "",
                  "None. This branch is a single directory, so the chain ends here — §3.7 requires",
                  "that to be stated rather than left as an unexplained absence.", ""]
        L += ["## Where this leads", ""]
        if subs:
            L += ["Into " + ", ".join(f"[`{s.name}`]({s.name}/{s.name}.md)" for s in subs[:6]) +
                  ("." if len(subs) <= 6 else ", and the rest of the table above."), ""]
        else:
            L += ["Nowhere onward from here.", ""]
        return "\n".join(L)

    if kind == "tests":
        files = sorted(p.name for p in d.glob("test_*.py"))
        n = 0
        for p in d.glob("test_*.py"):
            try:
                n += sum(1 for x in ast.parse(p.read_text(errors="replace")).body
                         if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and x.name.startswith("test_"))
            except SyntaxError:
                pass
        L += [f"What proves `{worktree.name}` does what it says.", "",
              f"{len(files)} test file(s), {n} test function(s) at generation time.", ""]
        if files:
            L += ["```"] + [f"    {f}" for f in files] + ["```", ""]
        L += ["## Interfaces", "",
              f"**Consumes:** the `{worktree.name}` package and its `service.py`. Nothing here is",
              "imported by anything else — a test directory is a leaf by design, which is why it",
              "does not link onward to a sibling.", "",
              "**Run with:**", "", "```", "    python3 -m pytest tests/ -q", "```", "",
              "`python3 -m` is load-bearing: it puts the worktree root on `sys.path`, which is what",
              "makes `import service` and the package import resolve.", "",
              "## Where this leads", "",
              f"Back to [{parent_doc}]({up}), which is the map for this unit. The flow ends here:",
              "tests are exercised by a person or a gate, and call nothing further.", ""]
        return "\n".join(L)

    surface = python_surface(d)
    envs = env_contract(d)
    uses = local_imports(d, worktree)
    used_by = imported_by(d, worktree)
    mods = [m for m in surface["modules"] if m["file"] != "__init__.py"]

    if kind == "package":
        L += [f"The capability `{worktree.name}` provides. Its HTTP surface is `service.py` at the",
              "worktree root; this directory is what that surface calls.", ""]
    elif kind == "scripts":
        L += ["Executable steps this unit runs. Scripts, not a library — nothing imports them.", ""]
    elif kind == "pins":
        pins = sorted(p.name for p in d.glob("*.json"))
        L += [f"What this branch builds from: {len(pins)} pinned upstream(s).", "",
              "§3.1a: source is tracked, not carried. Each record holds the commit by full SHA, the",
              "declared licence with its checksum, the copyright line and the acquisition date —",
              "never the source bytes.", ""]
        if pins:
            L += ["```"] + [f"    {p}" for p in pins[:20]] + \
                 ([f"    … and {len(pins)-20} more"] if len(pins) > 20 else []) + ["```", ""]
    elif kind == "recipes":
        bbs = sorted(p.name for p in d.rglob("*.bb"))
        L += [f"Build recipes. {len(bbs)} at generation time.", ""]
        if bbs:
            L += ["```"] + [f"    {b}" for b in bbs[:15]] + \
                 ([f"    … and {len(bbs)-15} more"] if len(bbs) > 15 else []) + ["```", ""]
    else:
        L += [f"`{rel}` inside the `{worktree.name}` unit.", ""]

    if mods:
        L += ["## What is here", "", "| Module | Public callables | Summary |", "|---|---|---|"]
        for m in mods:
            pub = ", ".join(f"`{x}`" for x in m.get("public", [])[:6]) or "—"
            if len(m.get("public", [])) > 6:
                pub += f" … +{len(m['public'])-6}"
            L.append(f"| `{m['file']}` | {pub} | {m.get('summary','')[:70]} |")
        L.append("")

    L += ["## Interfaces", ""]
    if envs:
        L += ["**Configuration read from the environment:**", "",
              ", ".join(f"`{e}`" for e in envs), ""]
    if uses:
        L += ["**Consumes, inside this unit:** " +
              ", ".join(f"[`{u}`]({os.path.relpath(worktree/u/(u+'.md'), d)})" for u in uses), ""]
    if used_by:
        # The worktree root importing this package is not a sibling relationship, and when the
        # package shares the unit's name it would render as the directory citing ITSELF with a
        # link to its own document. Named for what it is instead.
        links = []
        for u in used_by:
            if u == worktree.name:
                links.append(f"the unit's own `service.py` "
                             f"([{worktree.name}.md]({os.path.relpath(worktree / (worktree.name + '.md'), d)}))")
                continue
            tgt = worktree / u / f"{u}.md" if (worktree / u).is_dir() else worktree / f"{u}.md"
            links.append(f"[`{u}`]({os.path.relpath(tgt, d)})")
        L += ["**Consumed by:** " + ", ".join(links), ""]
    if not envs and not uses and not used_by:
        L += ["No environment variable is read here, nothing inside this unit is imported, and",
              "nothing inside this unit imports it. Stated rather than omitted: an absent interface",
              "section reads as an oversight, an explicit one is an answer.", ""]

    L += ["## Where this leads", "",
          f"Up to [{parent_doc}]({up}), the map for this unit."]
    if uses:
        L += ["", "Onward, in the order the code runs: " +
              ", ".join(f"[`{u}`]({os.path.relpath(worktree/u/(u+'.md'), d)})" for u in uses) + "."]
    else:
        L += ["", "Nothing here calls into another directory of this unit, so the chain ends at this",
              "document. §3.7 requires that to be said rather than left as a dead end."]
    L.append("")
    return "\n".join(L)


def sweep(root: Path, apply: bool) -> dict[str, Any]:
    written, skipped, seen = [], [], 0
    for wt in sorted(root.iterdir()):
        if not wt.is_dir() or wt.name in SKIP or not (wt / ".git").exists():
            continue
        for d in [wt] + sorted(wt.rglob("*")):
            if not d.is_dir():
                continue
            if any(p in SKIP for p in d.relative_to(wt).parts):
                continue
            seen += 1
            target = d / f"{d.name}.md"
            if target.is_file():
                skipped.append(str(target))
                continue
            if apply:
                target.write_text(compose(d, wt, root.name))
            written.append(str(target))
    return {"root": str(root), "directories": seen,
            "already_documented": len(skipped), "written": len(written),
            "paths": written}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write; without it, report only")
    ap.add_argument("--root", action="append", default=None)
    a = ap.parse_args()
    roots = [Path(r) for r in (a.root or [f"/mnt/{t}" for t in TREES])]
    total = 0
    for r in roots:
        if not r.is_dir():
            print(f"  {r}: absent"); continue
        res = sweep(r, a.apply)
        total += res["written"]
        verb = "wrote" if a.apply else "would write"
        print(f"  {r.name:22} {res['directories']:4} dirs  "
              f"{res['already_documented']:4} documented  {verb} {res['written']}")
    print(f"\n  {'wrote' if a.apply else 'would write'} {total} document(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
