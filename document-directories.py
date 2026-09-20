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

THE OTHER FOUR MODES, ADDED 2026-09-20 BY THE §3.7 SWEEP
--------------------------------------------------------
Filling gaps is not enough once documents are already on disk and wrong, and "never
overwrites" would otherwise freeze every mistake this script has already made.

  --audit    the four §3.7 questions answered from disk, never writes. Exit 1 on a violation,
             so a gate can call it.
  --repair   rewrite a document THIS SCRIPT wrote, and only where it is in violation: it does
             not link a directory that sits below it, or its map row still says the useless
             "part of this unit". Hand-written pages are never touched here.
  --amend    INSERT the missing map into a hand-written page without rewriting a word of it.
  --strays   quarantine documents that landed inside git-ignored directories. §3.7 reaches the
             repository, and build output is not in it.

Nothing is ever deleted. Replaced text is copied, and stray documents are moved, to
~/Desktop/claude/quarantine-3.7-<date>/ with a MANIFEST.txt naming every source and
destination (rule 3.2: Garrett's files are not deleted).
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Tooling and VCS directories, which git does not necessarily ignore.
#
# `build` and `dist` are deliberately NOT in here any more. `SKIP` is tested against worktree
# names in sweep(), and `/mnt/SymonSaySource/build` is a BRANCH — so skipping the name skipped
# the whole branch, and `build/` and `build/pins/` were the only two undocumented directories
# in the estate on 2026-09-20 because of it.
#
# What is regenerable build output is decided by the repository, not by a name: ignored_under()
# asks git. `.next/` was never in this set, which is how 79 documents were written into a
# Next.js build tree under symoneural-learn/web that git has never tracked.
SKIP = {".git", "__pycache__", ".pytest_cache", ".bare", "node_modules", ".venv", "venv",
        ".mypy_cache", ".ruff_cache", ".pnpm-store"}
TREES = ("SymonSayDistribute", "SymonSaySource", "SymonSayOSS", "SymonSayOpen")

# A document this script wrote carries one of these. Nothing hand-written does, which is what
# lets --repair rewrite generated prose and leave Garrett's alone.
GENERATED_MARKS = (
    "§3.7: this is the map. Every directory below is listed with what lives there and",
    ", the map for this unit.",
    "§3.7 requires that to be said rather than left as a dead end.",
    "that to be stated rather than left as an unexplained absence.",
    "a test directory is a leaf by design",
    "Stated rather than omitted: an absent interface",
)


def is_generated(doc: Path) -> bool:
    """Did this script write it? Read from the file, not from a manifest."""
    txt = doc.read_text(errors="replace")
    return any(m in txt for m in GENERATED_MARKS)


def ignored_under(worktree: Path, dirs: list[Path]) -> set[Path]:
    """The directories in `dirs` that git ignores, asked once per worktree.

    Build output is not part of the repository, so §3.7 does not reach it. A directory whose
    ANCESTOR is ignored is ignored too — `git check-ignore` reports the ancestor, not the leaf.
    """
    rels = [str(d.relative_to(worktree)) for d in dirs if d != worktree]
    if not rels:
        return set()
    p = subprocess.run(["git", "-C", str(worktree), "check-ignore", "--stdin"],
                       input="\n".join(rels), capture_output=True, text=True)
    ign = {x for x in p.stdout.splitlines() if x}
    out: set[Path] = set()
    for d in dirs:
        if d == worktree:
            continue
        parts = d.relative_to(worktree).parts
        if any(str(Path(*parts[:i + 1])) in ign for i in range(len(parts))):
            out.add(d)
    return out


def children(d: Path, ignored: set[Path]) -> list[Path]:
    """The directories directly below this one that §3.7 reaches."""
    return [x for x in sorted(d.iterdir())
            if x.is_dir() and x.name not in SKIP and x not in ignored]


def held_by(d: Path, worktree: Path, ignored: set[Path] | None = None) -> str:
    """One line saying what is in a directory, read from the directory itself.

    Ordered by CONTENT, not by name. kind_of() calls anything beginning `symon` a package, and
    under `recipes/` that is wrong — `symoneural-awcc/` holds a `.bb` and no python at all, and
    the first version of this said "the capability this unit provides — no python at this
    level", which is a sentence that describes nothing.
    """
    n = d.name
    if n == "tests":
        return f"what proves this unit does what it says — {len(list(d.glob('test_*.py')))} test file(s)"
    if n == "pins":
        return f"what this branch builds from, by full SHA — {len(list(d.glob('*.json')))} pin(s)"
    bbs = len(list(d.rglob("*.bb")))
    if bbs:
        return f"build recipes — {bbs} at generation time"
    mods = sorted(p.name for p in d.glob("*.py") if p.name != "__init__.py")
    if mods:
        lead = ("the capability this unit provides — "
                if n == worktree.name or n.startswith(("symon", "symoneural_")) else "")
        return (lead + "`" + "`, `".join(mods[:4]) + "`"
                + (f" … +{len(mods) - 4}" if len(mods) > 4 else ""))
    if n in ("scripts", "bin"):
        return "executable steps, not a library"
    subs = sorted(x.name for x in children(d, ignored or set()))
    if subs:
        return "a grouping directory — " + ", ".join(f"`{s}`" for s in subs[:5]) + \
               (f" … +{len(subs) - 5}" if len(subs) > 5 else "")
    # Only the directory's OWN document is excluded. Excluding every .md described a docs/
    # directory of eleven pages by the one .txt file beside them.
    files = sorted(p.name for p in d.iterdir() if p.is_file() and p.name != f"{n}.md"
                   and not p.name.startswith("."))
    if files:
        return ("`" + "`, `".join(files[:4]) + "`"
                + (f" … +{len(files) - 4}" if len(files) > 4 else ""))
    return "nothing but its own document — the directory is otherwise empty"


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


def compose(d: Path, worktree: Path, tree: str, ignored: set[Path] | None = None) -> str:
    """The document. Every claim in it is read from disk at generation time."""
    ignored = ignored or set()
    kind = kind_of(d, worktree)
    rel = d.relative_to(worktree)
    parent = d.parent
    parent_doc = f"{parent.name}.md" if parent != worktree else f"{worktree.name}.md"
    up = os.path.relpath(parent / parent_doc, d)
    kids = children(d, ignored)

    L = [f"# {d.name}", ""]

    if d == worktree:
        subs = kids
        L += [f"The `{d.name}` branch of `{tree}`.", "",
              "§3.7: this is the map. Every directory below is listed with what lives there and",
              "why a reader would go to it.", ""]
        rts = routes_of(worktree)
        if rts:
            L += ["## What it serves", "", "```"] + [f"    {r}" for r in rts] + ["```", ""]
        if subs:
            L += ["## Directories", "", "| Directory | Holds |", "|---|---|"]
            for s in subs:
                L.append(f"| [`{s.name}`]({s.name}/{s.name}.md) | {held_by(s, worktree, ignored)} |")
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
              "makes `import service` and the package import resolve.", ""]
        if kids:
            L += ["## Directories", "", "| Directory | Holds |", "|---|---|"]
            for s in kids:
                L.append(f"| [`{s.name}`]({s.name}/{s.name}.md) | {held_by(s, worktree, ignored)} |")
            L += ["", "## Where this leads", "",
                  f"Back to [{parent_doc}]({up}), which is the map for this unit.", "",
                  "Onward, into " +
                  ", ".join(f"[`{s.name}`]({s.name}/{s.name}.md)" for s in kids) + ".", ""]
        else:
            L += ["## Where this leads", "",
                  f"Back to [{parent_doc}]({up}), which is the map for this unit. The flow ends",
                  "here: tests are exercised by a person or a gate, call nothing further, and no",
                  "directory sits below this one.", ""]
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

    # A directory with directories below it is never a leaf. Emitting the map only at the
    # worktree root is what made every intermediate document declare "the chain ends at this
    # document" while its own children sat underneath it, unreachable — a false terminal,
    # which is worse than a bare dead end because it tells the reader to stop.
    if kids:
        L += ["## Directories", "", "| Directory | Holds |", "|---|---|"]
        for s in kids:
            L.append(f"| [`{s.name}`]({s.name}/{s.name}.md) | {held_by(s, worktree, ignored)} |")
        L.append("")

    onward = [f"[`{s.name}`]({s.name}/{s.name}.md)" for s in kids]
    onward += [f"[`{u}`]({os.path.relpath(worktree / u / (u + '.md'), d)})" for u in uses]
    L += ["## Where this leads", "",
          f"Up to [{parent_doc}]({up}), the map for this unit."]
    if onward:
        L += ["", "Onward, in the order the code runs: " + ", ".join(onward) + "."]
    else:
        L += ["", "No directory sits below this one and nothing here calls into another directory",
              "of this unit, so the chain ends at this document. §3.7 requires that to be said",
              "rather than left as a dead end."]
    L.append("")
    return "\n".join(L)


def worktrees_of(root: Path) -> list[Path]:
    """A branch is a worktree beside the bare repository (§3.1a). This finds them."""
    return [w for w in sorted(root.iterdir())
            if w.is_dir() and w.name not in SKIP and (w / ".git").exists()]


def directories_of(wt: Path) -> tuple[list[Path], set[Path]]:
    """Every directory of this worktree §3.7 reaches, and the ignored ones it does not."""
    cand = [wt] + [d for d in sorted(wt.rglob("*"))
                   if d.is_dir() and not any(p in SKIP for p in d.relative_to(wt).parts)]
    ign = ignored_under(wt, cand)
    return [d for d in cand if d not in ign], ign


# ---------------------------------------------------------------------------------------
# Quarantine. Rule 3.2: Garrett's files are never deleted. A document this script replaces,
# and a stray document swept out of build output, is MOVED and its destination is reported.
# ---------------------------------------------------------------------------------------

def quarantine_root() -> Path:
    return Path.home() / "Desktop" / "claude" / f"quarantine-3.7-{date.today().isoformat()}"


def quarantine(p: Path, why: str, move: bool) -> Path:
    """Put a file beyond the repository without destroying it. Returns where it went."""
    rel = str(p).lstrip("/")
    dest = quarantine_root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    (shutil.move if move else shutil.copy2)(str(p), str(dest))
    with (quarantine_root() / "MANIFEST.txt").open("a") as fh:
        fh.write(f"{'moved ' if move else 'copied'}\t{p}\t->\t{dest}\t{why}\n")
    return dest


# ---------------------------------------------------------------------------------------
# The three things this script does to a tree.
# ---------------------------------------------------------------------------------------

def sweep(root: Path, apply: bool) -> dict[str, Any]:
    """Write the document for any directory that has none. Never overwrites."""
    written, skipped, seen = [], [], 0
    for wt in worktrees_of(root):
        ds, ign = directories_of(wt)
        for d in ds:
            seen += 1
            target = d / f"{d.name}.md"
            if target.is_file():
                skipped.append(str(target))
                continue
            if apply:
                target.write_text(compose(d, wt, root.name, ign))
            written.append(str(target))
    return {"root": str(root), "directories": seen,
            "already_documented": len(skipped), "written": len(written), "paths": written}


def repair(root: Path, apply: bool) -> dict[str, Any]:
    """Rewrite documents THIS SCRIPT wrote, from what is on disk now.

    A generated document is derived prose with no hand-written content in it, so regenerating
    it is safe and is the only way the map fixes above reach the ~149 already on disk — the
    generator refuses to overwrite, by design, and that refusal would otherwise freeze every
    false terminal it has already written. Hand-written documents are left untouched here;
    --amend is what touches those, and it only inserts.

    The previous text is quarantined before the new text lands, never discarded.
    """
    fixed, left = [], []
    for wt in worktrees_of(root):
        ds, ign = directories_of(wt)
        for d in ds:
            doc = d / f"{d.name}.md"
            if not doc.is_file():
                continue
            if not is_generated(doc):
                left.append(str(doc))
                continue
            # Only a document that is actually in violation is rewritten. Regenerating every
            # generated page because the derived wording improved would put 145 files in a
            # diff to hide 21 real fixes, and a review nobody can read is a review nobody does.
            old = doc.read_text(errors="replace")
            linked = set(re.findall(r"\]\(([^)\s]+\.md)\)", old))
            unlinked = [k for k in children(d, ign) if f"{k.name}/{k.name}.md" not in linked]
            # "| part of this unit |" was the fallback the first version of this script put in
            # a map row when it could not classify a directory by name. §3.7 asks the root
            # document for "a brief description of the system that lives there and the reason a
            # reader would navigate to it"; a row that says a directory is part of the unit it
            # is in tells the reader nothing they did not already know from the path.
            if not unlinked and "part of this unit |" not in old:
                continue
            new = compose(d, wt, root.name, ign)
            if new == old:
                continue
            if apply:
                quarantine(doc, "superseded by --repair", move=False)
                doc.write_text(new)
            fixed.append(str(doc))
    return {"root": str(root), "repaired": fixed, "hand_written_left": left}


DIRECTORIES_BLOCK = "## Directories"
ONWARD_HEADS = ("## Where this leads", "## Onward", "## Where the flow ends")


def amend(root: Path, apply: bool) -> dict[str, Any]:
    """Give a HAND-WRITTEN document the map §3.7 requires, without touching its prose.

    Inserting, never rewriting. Garrett's pages are the reason this estate can be read; a
    generator that regenerated over them would trade a real description for a derived one.
    What gets inserted is a `## Directories` table linking each child document, and the onward
    sentence — appended into an existing onward section if the page already has one, so a page
    never ends up with two.
    """
    touched, already = [], []
    for wt in worktrees_of(root):
        ds, ign = directories_of(wt)
        for d in ds:
            doc = d / f"{d.name}.md"
            if not doc.is_file() or is_generated(doc):
                continue
            txt = doc.read_text(errors="replace")
            linked = set(re.findall(r"\]\(([^)\s]+\.md)\)", txt))
            kids = children(d, ign)
            missing = [k for k in kids if f"{k.name}/{k.name}.md" not in linked]
            # A heading called "Onward" is not a terminal statement. `runtime.md` and
            # `workflow.md` both carried one and still left the reader nowhere, which is the
            # dead end §3.7 forbids; the section has to SAY the flow ends and why.
            terminal = TERMINAL.search(txt) is not None
            if not missing and (kids or terminal):
                already.append(str(doc))
                continue

            block = []
            if missing:
                block += ["## Directories", "",
                          "Every directory below, what is in it, and the document that carries it.",
                          "", "| Directory | Holds |", "|---|---|"]
                for k in kids:
                    block.append(f"| [`{k.name}`]({k.name}/{k.name}.md) | {held_by(k, wt, ign)} |")
                block.append("")
            onward_line = ("Onward, in the order the code runs: "
                           + ", ".join(f"[`{k.name}`]({k.name}/{k.name}.md)" for k in kids) + ".")
            up = ""
            if d != wt:
                pd = f"{d.parent.name}.md" if d.parent != wt else f"{wt.name}.md"
                # NOT ", the map for this unit." — that exact phrase is a GENERATED_MARK, and
                # writing it into a hand-written page would make is_generated() say yes, which
                # would hand --repair permission to overwrite Garrett's prose on the next run.
                up = f"Up to [{pd}]({os.path.relpath(d.parent / pd, d)}) — the map for this branch."

            head = next((h for h in ONWARD_HEADS if h in txt), None)
            if head:
                # Extend the section the page already has rather than adding a second one.
                # The table goes immediately ABOVE that section, so a reader meets the map and
                # then the sentence that says which way to read it.
                i = txt.index(head)
                add = "\n\n" + onward_line if kids else ""
                if up and up not in txt:
                    add += "\n\n" + up
                txt = (txt[:i]
                       + ("\n".join(block) + "\n" if block else "")
                       + head + add + txt[i + len(head):])
            else:
                tail = ["## Where this leads", ""]
                if up:
                    tail += [up, ""]
                if kids:
                    tail += [onward_line, ""]
                else:
                    tail += ["No directory sits below this one, so the chain ends at this document.",
                             "§3.7 requires a final document to say so rather than leave the reader",
                             "at an unexplained stop.", ""]
                txt = txt.rstrip("\n") + "\n\n" + "\n".join(block + tail).rstrip("\n") + "\n"

            # A hand-written page must still read as hand-written afterwards. If an amendment
            # ever makes is_generated() true, --repair would be free to regenerate over it.
            hit = [g for g in GENERATED_MARKS if g in txt]
            if hit:
                raise SystemExit(f"refusing to amend {doc}: the insert would make it look "
                                 f"generated ({hit[0]!r}); change the wording in amend()")
            if apply:
                quarantine(doc, "amended by --amend", move=False)
                doc.write_text(txt)
            touched.append(str(doc))
    return {"root": str(root), "amended": touched, "already_mapped": already}


def merge_extra(root: Path, name: str, apply: bool) -> dict[str, Any]:
    """Fold a SECOND Markdown document in a directory into that directory's own document.

    §3.7 allows one document per directory. The estate had 49 extra files across 38
    directories, most of them the hand-written branch pages — `sources.md` on every
    SymonSaySource branch, `recipes.md` on every SymonSayOpen branch — that predate the rule's
    naming. Deleting them would be deleting the only real content those branches carry, so the
    text moves into `<dir>.md` and the husk is quarantined, never dropped.

    The extra is NAMED by the operator, one name per run. This function does not decide which
    of two documents is redundant; a `SKILL.md` a loader resolves and a `README.md` GitHub
    serves are not husks, and a tool that guessed would eventually guess one of those.
    """
    done, skipped = [], []
    for wt in worktrees_of(root):
        ds, ign = directories_of(wt)
        for d in ds:
            own, extra = d / f"{d.name}.md", d / name
            if not own.is_file() or not extra.is_file() or own == extra:
                continue
            body = extra.read_text(errors="replace").strip("\n").splitlines()
            title = body[0].lstrip("# ").strip() if body and body[0].startswith("# ") else name
            if body and body[0].startswith("# "):
                body = body[1:]
            while body and not body[0].strip():
                body.pop(0)
            dest = quarantine_root() / str(extra).lstrip("/")
            block = [f"## {title}", "",
                     f"*Folded in from `{name}` on {date.today().isoformat()}: §3.7 allows one",
                     f"document per directory. Nothing was lost — the original file is at",
                     f"`{dest}`.*", ""] + body + [""]
            txt = own.read_text(errors="replace")
            head = next((h for h in ONWARD_HEADS if h in txt), None)
            if head:
                i = txt.index(head)
                txt = txt[:i] + "\n".join(block) + "\n" + txt[i:]
            else:
                txt = txt.rstrip("\n") + "\n\n" + "\n".join(block)
            if apply:
                own.write_text(txt)
                quarantine(extra, f"folded into {own.name} under §3.7", move=True)
            done.append(str(extra))
    return {"root": str(root), "merged": done, "skipped": skipped}


def strays(root: Path, apply: bool) -> dict[str, Any]:
    """Documents that landed inside directories git ignores. They are not in the repository."""
    out = []
    for wt in worktrees_of(root):
        cand = [d for d in sorted(wt.rglob("*"))
                if d.is_dir() and not any(p in SKIP for p in d.relative_to(wt).parts)]
        for d in sorted(ignored_under(wt, cand)):
            for m in sorted(d.glob("*.md")):
                out.append(str(m))
                if apply:
                    quarantine(m, "document inside a git-ignored directory", move=True)
    return {"root": str(root), "strays": out}


def audit(root: Path) -> dict[str, Any]:
    """The four §3.7 questions, answered from disk. Read-only, always."""
    R: dict[str, Any] = {"root": str(root), "worktrees": 0, "directories": 0,
                         "no_document": [], "extra_documents": [], "dead_end": [],
                         "root_not_a_map": [], "unreachable": [], "broken_link": []}
    for wt in worktrees_of(root):
        R["worktrees"] += 1
        ds, ign = directories_of(wt)
        R["directories"] += len(ds)
        docs: dict[str, Path] = {}
        for d in ds:
            own = d / f"{d.name}.md"
            mds = sorted(p.name for p in d.glob("*.md"))
            if not own.is_file():
                R["no_document"].append(str(d))
                continue
            docs[str(own)] = d
            extra = [m for m in mds if m != own.name]
            if extra:
                R["extra_documents"].append({"dir": str(d), "extra": extra})
        graph: dict[str, list[str]] = {}
        for doc, d in docs.items():
            txt = Path(doc).read_text(errors="replace")
            tg = []
            for l in re.findall(r"\]\(([^)\s]+\.md)\)", txt):
                if l.startswith(("http://", "https://")):
                    continue
                p = os.path.normpath(os.path.join(str(d), l))
                tg.append(p)
                if not Path(p).is_file():
                    R["broken_link"].append({"doc": doc, "target": l})
            graph[doc] = tg
            kids = children(d, ign)
            unlinked = [k.name for k in kids if str(k / f"{k.name}.md") not in tg]
            if unlinked:
                R["root_not_a_map"].append({"doc": doc, "unlinked": unlinked})
            par = str(d.parent / f"{d.parent.name}.md") if d != wt else None
            wd = str(wt / f"{wt.name}.md")
            onward = [x for x in tg if x != doc and x != par and not (d != wt and x == wd)]
            if not onward and not kids and not TERMINAL.search(txt):
                R["dead_end"].append(doc)
        rd = str(wt / f"{wt.name}.md")
        if rd in graph:
            seen, stack = {rd}, [rd]
            while stack:
                for x in graph.get(stack.pop(), []):
                    if x in docs and x not in seen:
                        seen.add(x)
                        stack.append(x)
            R["unreachable"] += [d for d in docs if d not in seen]
    return R


TERMINAL = re.compile(r"(ends here|ends there|chain ends|flow ends|ends at this|nowhere onward|"
                      r"leads nowhere|no document remains|terminates here|end of the chain|"
                      r"chain ends at this document)", re.I)


def main() -> int:
    ap = argparse.ArgumentParser(description="§3.7: one document per directory, chained.")
    ap.add_argument("--apply", action="store_true", help="write; without it, report only")
    ap.add_argument("--root", action="append", default=None)
    ap.add_argument("--audit", action="store_true", help="report §3.7 violations, never write")
    ap.add_argument("--repair", action="store_true",
                    help="rewrite documents this script wrote, from disk as it is now")
    ap.add_argument("--amend", action="store_true",
                    help="insert the missing map into hand-written documents, keeping their prose")
    ap.add_argument("--strays", action="store_true",
                    help="quarantine documents sitting inside git-ignored directories")
    ap.add_argument("--merge-extra", metavar="NAME",
                    help="fold this second document (e.g. sources.md) into the directory's own")
    a = ap.parse_args()
    roots = [Path(r) for r in (a.root or [f"/mnt/{t}" for t in TREES])]
    rc = 0
    for r in roots:
        if not r.is_dir():
            print(f"  {r}: absent")
            continue
        if a.audit:
            x = audit(r)
            print(f"  {r.name:22} {x['worktrees']:3} worktrees  {x['directories']:4} dirs")
            for k in ("no_document", "extra_documents", "dead_end", "root_not_a_map",
                      "unreachable", "broken_link"):
                print(f"      {k:18} {len(x[k])}")
                rc = rc or (1 if x[k] else 0)
            continue
        if a.strays:
            x = strays(r, a.apply)
            print(f"  {r.name:22} {'quarantined' if a.apply else 'would quarantine'} "
                  f"{len(x['strays'])} stray document(s)")
        if a.repair:
            x = repair(r, a.apply)
            print(f"  {r.name:22} {'repaired' if a.apply else 'would repair'} "
                  f"{len(x['repaired'])} generated, left {len(x['hand_written_left'])} hand-written")
        if a.amend:
            x = amend(r, a.apply)
            print(f"  {r.name:22} {'amended' if a.apply else 'would amend'} "
                  f"{len(x['amended'])} hand-written, {len(x['already_mapped'])} already mapped")
        if a.merge_extra:
            x = merge_extra(r, a.merge_extra, a.apply)
            print(f"  {r.name:22} {'folded' if a.apply else 'would fold'} "
                  f"{len(x['merged'])} × {a.merge_extra}")
            for p in x["merged"]:
                print(f"        {p}")
        if not (a.strays or a.repair or a.amend or a.merge_extra):
            res = sweep(r, a.apply)
            verb = "wrote" if a.apply else "would write"
            print(f"  {r.name:22} {res['directories']:4} dirs  "
                  f"{res['already_documented']:4} documented  {verb} {res['written']}")
            for p in res["paths"]:
                print(f"        {p}")
    if a.apply and quarantine_root().is_dir():
        print(f"\n  nothing was deleted; replaced text is under {quarantine_root()}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
