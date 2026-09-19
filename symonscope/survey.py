# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Survey the estate from disk: what units exist, what each one is, and their tags.

WHY THIS READS DISK AND NEVER A DOCUMENT
----------------------------------------
Every list of components this estate has held has gone stale, because a list is written once
and the estate changes afterwards. A survey that walks the trees cannot go stale: it is wrong
only if disk is wrong, and then it is reporting a real problem rather than an old opinion.

The one rule this module obeys above all: it does not write. Not a file, not a service, not a
branch. It is safe to run at any moment, including while a build is live.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

# The four trees, and what licence each carries. A tree that is absent is reported absent
# rather than skipped: "not there" and "not looked at" are different answers.
TREES = {
    "SymonSayDistribute": {"root": "/mnt/SymonSayDistribute", "licence": "SymonSaysLLC Proprietary License 1.0"},
    "SymonSaySource":     {"root": "/mnt/SymonSaySource",     "licence": "SymonSaysLLC Proprietary License 1.0"},
    "SymonSayOpen":       {"root": "/mnt/SymonSayOpen",       "licence": "SymonSaysLLC Open Source License 1.0"},
    "SymonSayOSS":        {"root": "/mnt/SymonSayOSS",        "licence": "SymonSaysLLC Open Source License 1.0"},
}

# Directories beside the worktrees that are not units.
SKIP = {".git", "__pycache__", "node_modules", ".pytest_cache", ".next", "dist", "build"}

NOT_A_UNIT = {".bare", ".git", ".pnpm-store", "lost+found", ".trash"}


class SurveyError(Exception):
    """A survey could not be completed, carrying why. Never returned as an empty result."""


def _git(root: str, *args: str, timeout: float = 30.0) -> str:
    bare = Path(root) / ".bare"
    if not bare.is_dir():
        raise SurveyError(f"{root} has no .bare; this is not an estate tree")
    r = subprocess.run(["git", f"--git-dir={bare}", *args],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise SurveyError(f"git {' '.join(args)} in {root} failed rc={r.returncode}: "
                          f"{r.stderr.strip()[:200]}")
    return r.stdout


def trees() -> list[dict[str, Any]]:
    """The four trees, present or not, with how many units each holds."""
    out = []
    for name, meta in TREES.items():
        root = Path(meta["root"])
        present = root.is_dir() and (root / ".bare").is_dir()
        row: dict[str, Any] = {"tree": name, "root": str(root), "licence": meta["licence"],
                               "present": present}
        if present:
            row["units"] = len(_unit_dirs(root))
            try:
                row["tags"] = len([t for t in _git(str(root), "tag", "--list").split() if t])
            except SurveyError as e:
                row["tags"] = None
                row["tags_error"] = str(e)
        else:
            row["why"] = "no directory, or no .bare inside it"
        out.append(row)
    return out


def _unit_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and p.name not in NOT_A_UNIT and not p.name.startswith("."))


def _describe(unit_dir: Path) -> str:
    """The unit's own one-line description, taken from its document rather than invented.

    Every directory carries a document named after it (rules 3.7, 3.8). The first non-heading,
    non-empty line of that document is what the unit says it is. If there is no document, that
    is reported as a finding — a unit with no document is a gap, not a thing to paper over.
    """
    for candidate in (unit_dir / f"{unit_dir.name}.md", unit_dir / "README.md"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(errors="replace").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("!["):
                return s[:200]
    return ""


_ROUTE = re.compile(r'["\'](/api/[a-z0-9_-]+)/')
_PORT = re.compile(r'127\.0\.0\.1:(\d{2,5})')


def _kind_and_surface(unit_dir: Path) -> dict[str, Any]:
    """What kind of thing this unit is, decided by what is in it rather than by its name."""
    pys = list(unit_dir.rglob("*.py"))
    shs = list(unit_dir.rglob("*.sh"))
    mds = list(unit_dir.rglob("*.md"))
    # service.py is not always at the unit root: ravencalc keeps it inside its package, and
    # looking only at the root reported a live service on 8801 as a library. Search for it.
    # Detected by what the code CONSTRUCTS, not by what the file is called. Looking for
    # "service.py" alone reported symoneural-learn — which serves the gateway on 9001 — as a
    # tool, because its application lives in gateway.py.
    services = [q for q in unit_dir.rglob("*.py")
                if not any(d in SKIP for d in q.parts)
                and "test" not in q.name
                and "FastAPI(" in q.read_text(errors="replace")]
    services.sort(key=lambda q: (q.name != "service.py", len(q.parts)))
    prefix, port = None, None
    if services:
        text = services[0].read_text(errors="replace")
        m = _ROUTE.search(text)
        prefix = m.group(1) if m else None
        q = re.search(r'PORT["\']?\s*,\s*["\'](\d{4,5})["\']', text) or _PORT.search(text)
        port = int(q.group(1)) if q else None

    # A package (a directory with __init__.py) is what makes something importable, and that is
    # what "library" means. A unit whose python is top-level scripts is a tool someone runs.
    packages = [q for q in unit_dir.rglob("__init__.py")
                if not any(d in SKIP for d in q.parts) and len(q.relative_to(unit_dir).parts) <= 3]
    if services:
        kind = "service"
    elif packages:
        kind = "library"
    elif pys or shs:
        kind = "tool"
    elif mds:
        kind = "documentation"
    else:
        kind = "unknown"
    return {"kind": kind, "route_prefix": prefix, "port": port,
            "counts": {"py": len(pys), "sh": len(shs), "md": len(mds)}}


def units(tree: str = "SymonSayDistribute") -> list[dict[str, Any]]:
    """Every unit in a tree: what it is, what kind, where it answers, what it has released."""
    if tree not in TREES:
        raise SurveyError(f"{tree!r} is not one of the four trees: {', '.join(TREES)}")
    root = Path(TREES[tree]["root"])
    if not (root / ".bare").is_dir():
        raise SurveyError(f"{tree} is not present at {root}")
    tags_out = _git(str(root), "tag", "--list").split()
    out = []
    for d in _unit_dirs(root):
        tags = sorted(t for t in tags_out if t.startswith(d.name + "/"))
        row = {"unit": d.name, "tree": tree, "path": str(d),
               "describes_itself_as": _describe(d),
               "has_document": (d / f"{d.name}.md").is_file(),
               "releases": tags, "latest": tags[-1] if tags else None}
        row.update(_kind_and_surface(d))
        out.append(row)
    return out


def subcomponents(tree: str = "SymonSayDistribute") -> list[dict[str, Any]]:
    """The components INSIDE a unit, because a branch is not always one thing.

    This exists because of a defect the layering found on its first run. `agents` calls the
    gateway, and the web interface calls `agents`, so at unit granularity there is a cycle
    between `agents` and `symoneural-learn` and nothing can be layered. There is no cycle in
    the actual software: the web interface and the gateway are two different components that
    happen to share a branch, and the real path is web -> agents -> gateway, which is a chain.

    A cycle that disappears when you look closer was never a cycle in the design; it was a
    cycle in the naming. So the survey can look closer.

    A subcomponent is a directory inside a unit that is its own thing: it carries a document
    named after it, or a package, or something that constructs a service.
    """
    out = []
    for u in units(tree):
        d = Path(u["path"])
        children = [c for c in sorted(d.iterdir())
                    if c.is_dir() and c.name not in SKIP and not c.name.startswith(".")] if d.is_dir() else []
        subs = []
        for c in children:
            own_doc = (c / f"{c.name}.md").is_file()
            pkg = (c / "__init__.py").is_file() or any(
                (g / "__init__.py").is_file() for g in c.iterdir() if g.is_dir()) if c.is_dir() else False
            svc = any("FastAPI(" in q.read_text(errors="replace")
                      for q in c.rglob("*.py") if not any(x in SKIP for x in q.parts))
            # A component is not always Python. The web interface is one end of the cycle
            # this function exists to explain, and it has no .py at all.
            js = (c / "package.json").is_file()
            if own_doc or pkg or svc or js:
                info = _kind_and_surface(c)
                kind = "web" if js and info["kind"] in ("unknown", "documentation", "tool") else info["kind"]
                subs.append({"subcomponent": c.name, "path": str(c), "has_document": own_doc,
                             "kind": kind, "port": info["port"],
                             "route_prefix": info["route_prefix"],
                             "describes_itself_as": _describe(c)})
        out.append({"unit": u["unit"], "kind": u["kind"], "count": len(subs),
                    "subcomponents": subs,
                    "is_one_thing": len(subs) <= 1})
    return out
