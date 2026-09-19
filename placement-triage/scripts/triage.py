#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""placement-triage — decide where a thing belongs, from what is on disk.

    scripts/triage.py <path> [<path> ...] [--json] [--name NAME]

WHAT IT DECIDES
---------------
Two questions, in this order, and the second only matters because of the first:

  1. Does building or running this REQUIRE a copyleft component?
  2. If so, is that component LINKED INTO what ships, or only used to build it?

A build-time tool under GPL does not make its output copyleft. A library linked into the
artifact does. Getting that backwards is the single mistake that puts a thing in the wrong
repository, so the two are reported separately and never merged into one verdict.

THE FLOW IT APPLIES
-------------------
Proprietary is the DEFAULT. Open source is what copyleft FORCES, never what usefulness
suggests. Where the evidence does not settle it, the verdict is PRESENT_TO_GARRETT, because a
guess here is worse than a question.

WHAT IT WILL NOT DO
-------------------
It does not move anything, write anything, or decide anything it cannot evidence. Every line
of its verdict names the file that produced it.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
TABLE = json.loads((HERE / "licences.json").read_text())
CLASSES = {k: v for k, v in TABLE.items() if not k.startswith("_")}

SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+_ ()]+)")
BB_LICENSE_RE = re.compile(r'^LICENSE\s*=\s*"([^"]+)"', re.M)
BB_DEPENDS_RE = re.compile(r'^(R?DEPENDS)(?::\S+)?\s*[+:]?=\s*"([^"]*)"', re.M)
SOURCE_EXT = {".py", ".sh", ".ts", ".tsx", ".js", ".mjs", ".c", ".h", ".cc", ".cpp", ".rs",
              ".go", ".css", ".bb", ".bbappend", ".inc"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", "dist", "build", "target",
             ".venv", "venv", ".bare"}

# Things that BUILD software and are never linked into it. A GPL compiler does not make its
# output GPL, and treating one as if it did is how a build tool ends up dragging a product
# into the wrong repository. The list is deliberately explicit: a heuristic that guessed
# "sounds like a tool" would be wrong exactly when it mattered.
BUILD_TOOLS = {
    "bitbake", "openembedded-core", "autoconf", "automake", "libtool", "m4", "make",
    "cmake", "meson", "ninja", "pkgconfig", "pkg-config", "gcc", "binutils", "flex",
    "bison", "gettext", "texinfo", "patch", "quilt", "gperf", "help2man", "debian-kernel-inputs",
}


def is_build_tool(name: str) -> bool:
    n = name.lower().removeprefix("symoneural-").removesuffix("-native")
    return n in BUILD_TOOLS or name.endswith("-native")


def classify(expr: str) -> tuple[str, str]:
    """A licence expression -> (class, the identifier that decided it).

    An expression may be a compound like "GPL-2.0-only AND MIT". The STRONGEST obligation in
    it governs, because a combined work carries every obligation of its parts."""
    if not expr:
        return "unknown", ""
    tokens = re.split(r"[\s|&()]+|\bAND\b|\bOR\b|\bWITH\b", expr)
    order = ["strong_copyleft", "weak_copyleft", "proprietary_ours", "permissive"]
    found: dict[str, str] = {}
    for tok in filter(None, tokens):
        t = tok.strip().rstrip("+").lower()
        if not t:
            continue
        for cls in order:
            for known in CLASSES[cls]:
                k = known.lower()
                if t == k or t.startswith(k):
                    found.setdefault(cls, tok)
    for cls in order:
        if cls in found:
            return cls, found[cls]
    return "unknown", expr.strip()[:60]


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            yield Path(dirpath) / f


class Evidence:
    def __init__(self) -> None:
        self.declared: list[tuple[str, str, str]] = []   # (class, id, where)
        self.linked: list[tuple[str, str, str]] = []     # copyleft reached at run time
        self.buildtime: list[tuple[str, str, str]] = []  # copyleft needed only to build
        self.notes: list[str] = []

    def add(self, cls, ident, where, *, kind="declared"):
        getattr(self, kind).append((cls, ident, where))


def scan_path(root: Path, ev: Evidence) -> None:
    if not root.exists():
        ev.notes.append(f"{root} does not exist")
        return

    for f in walk(root):
        rel = str(f.relative_to(root)) if root.is_dir() else f.name
        name = f.name

        # 1. a LICENSE file states what THIS thing is licensed as
        if name in ("LICENSE", "LICENCE", "COPYING", "LICENSE.txt", "LICENSE.md"):
            try:
                head = f.read_text(errors="replace")[:400]
            except Exception:
                continue
            for cls, ids in CLASSES.items():
                if cls == "not_a_licence":
                    continue      # placeholders, not findings
                for ident in ids:
                    if ident.lower().replace("-", " ") in head.lower().replace("-", " "):
                        ev.add(cls, ident, rel)
                        break
            m = SPDX_RE.search(head)
            if m:
                c, i = classify(m.group(1))
                ev.add(c, i, rel)

        # 2. SPDX headers in our own source
        elif f.suffix in SOURCE_EXT:
            try:
                head = f.read_text(errors="replace")[:600]
            except Exception:
                continue
            m = SPDX_RE.search(head)
            if m:
                c, i = classify(m.group(1))
                ev.add(c, i, rel)

            # 3. a BitBake recipe declares what it BUILDS and what it needs
            if f.suffix in (".bb", ".bbappend", ".inc"):
                try:
                    body = f.read_text(errors="replace")
                except Exception:
                    body = ""
                ml = BB_LICENSE_RE.search(body)
                if ml:
                    c, i = classify(ml.group(1))
                    if c in ("strong_copyleft", "weak_copyleft"):
                        stem = f.name.split("_")[0]
                        if is_build_tool(stem):
                            # Its output builds software; it is never linked into any. The
                            # licence is real and does not travel.
                            ev.add(c, i, f"{rel}: builds {ml.group(1)} — BUILD TOOL", kind="buildtime")
                        else:
                            ev.add(c, i, f"{rel}: builds {ml.group(1)}")
                for kind, dep in BB_DEPENDS_RE.findall(body):
                    bucket = "buildtime" if kind == "DEPENDS" else "linked"
                    for d in dep.split():
                        if d.endswith("-native"):
                            bucket = "buildtime"
                        ev.add("dependency", d, f"{rel}: {kind}", kind=bucket)

        # 4. what a python package actually imports at run time
        if f.suffix == ".py":
            try:
                body = f.read_text(errors="replace")
            except Exception:
                continue
            for mod in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", body, re.M):
                top = mod.split(".")[0]
                if top not in sys.stdlib_module_names and top not in ("symoneural_api", "symoneural_llm", "symoneural_gateway"):
                    ev.add("dependency", top, f"{rel}: import", kind="linked")

    # 5. what a binary actually links
    for f in (walk(root) if root.is_dir() else [root]):
        try:
            if f.is_file() and f.stat().st_size > 64 and f.open("rb").read(4) == b"\x7fELF":
                r = subprocess.run(["readelf", "-d", str(f)], capture_output=True, text=True)
                for so in re.findall(r"NEEDED.*\[([^\]]+)\]", r.stdout):
                    ev.add("dependency", so, f"{f.name}: NEEDED", kind="linked")
        except Exception:
            continue


def already_placed(paths) -> str | None:
    """Source and Open are not destinations. A thing already inside one of them is not being
    placed and must not be proposed for a move; asking 'where does this go' about a branch
    that already has a home is how a correct layout gets churned."""
    for p in paths:
        s = str(Path(p).resolve())
        for tree, what in (("/mnt/SymonSaySource", "SymonSaySource — this records what we build from"),
                           ("/mnt/SymonSayOpen", "SymonSayOpen — this holds builds whose output is copyleft")):
            if s == tree or s.startswith(tree + "/"):
                return what
    return None


def prospect(name: str, sources: list[str], alternatives_searched: str) -> dict:
    """Triage a thing that does not exist yet.

    Rules 3.1b-i: a prospect with no licence classification is not a prospect, it is a question.
    A component's SOURCES define its licence, so nothing can be classified until what it will
    be built from is named. The order does not reverse: name the sources, read the licence off
    them, default proprietary, and reach copyleft only when no other variant exists.

    This refuses rather than guesses. "Probably proprietary" is not a classification; it is a
    guess wearing one, and a guess recorded as a verdict is how a tree stops meaning anything.
    """
    if not sources:
        return {"licence": "undecided", "repository": "NOT YET A PROSPECT",
                "why": ("no sources named. A component's licence comes from what it is built "
                        "from, so this cannot be classified until that is known — name the "
                        "upstream and the pin, then triage again"),
                "evidence": [], "confidence": "incomplete"}

    classes = []
    for s in sources:
        lic = s.split("@")[-1] if "@" in s else ""
        c, why = classify(lic) if lic else ("unknown", "no licence given with the source")
        classes.append((c, s, why))

    unknown = [c for c in classes if c[0] == "unknown"]
    if unknown:
        return {"licence": "undecided", "repository": "NOT YET A PROSPECT",
                "why": ("a source was named without its licence. Write it as "
                        "<source>@<SPDX-id> so the classification is read rather than assumed"),
                "evidence": [f"{s}: {w}" for _, s, w in unknown], "confidence": "incomplete"}

    copyleft = [c for c in classes if c[0] in ("strong_copyleft", "weak_copyleft")]
    if not copyleft:
        return {"licence": "SymonSaysLLC Proprietary License",
                "repository": "SymonSayDistribute",
                "why": "every named source is non-copyleft, so the default applies",
                "evidence": [f"{s} -> {c}" for c, s, _ in classes],
                "confidence": "from declared sources"}

    # Reaching here is a CLAIM that no non-copyleft variant of this component exists. Garrett,
    # 2026-09-19: "this should really never happen with all the available component source code
    # available on the web and downloaded to the machine." So the claim carries its proof.
    if not alternatives_searched.strip():
        return {"licence": "undecided", "repository": "NOT YET A PROSPECT",
                "why": ("a copyleft source was named, which is a claim that NO non-copyleft "
                        "variant of this component exists. That claim is recorded with what was "
                        "searched, not asserted — pass --alternatives with what was looked at "
                        "and why each was rejected"),
                "evidence": [f"{s} -> {c}" for c, s, _ in copyleft],
                "confidence": "unproven claim"}

    return {"licence": "SymonSaysLLC Open Source License",
            "repository": "SymonSayOSS",
            "why": "a copyleft source is the only available form of this component",
            "evidence": [f"{s} -> {c}" for c, s, _ in copyleft] +
                        [f"alternatives searched: {alternatives_searched}"],
            "confidence": "forced, with the search recorded"}


def verdict(ev: Evidence) -> dict:
    """Apply the flow. Proprietary by default; open source only when copyleft is LINKED."""
    linked_copyleft = [e for e in ev.linked if e[0] in ("strong_copyleft", "weak_copyleft")]
    declared_copyleft = [e for e in ev.declared if e[0] in ("strong_copyleft", "weak_copyleft")]
    build_only = [e for e in ev.buildtime if e[0] in ("strong_copyleft", "weak_copyleft")]

    if linked_copyleft:
        return {"licence": "SymonSaysLLC Open Source License",
                "repository": "SymonSayOSS",
                "why": "a copyleft component is linked into what ships",
                "evidence": [f"{c}: {i} ({w})" for c, i, w in linked_copyleft[:6]],
                "confidence": "forced"}

    if declared_copyleft and not linked_copyleft:
        return {"licence": "undecided",
                "repository": "PRESENT_TO_GARRETT",
                "why": "something here declares a copyleft licence, but nothing shows it reaching a shipped artifact — that is a question, not a default",
                "evidence": [f"{c}: {i} ({w})" for c, i, w in declared_copyleft[:6]],
                "confidence": "needs a human"}

    if not ev.declared and not ev.linked and not ev.buildtime:
        return {"licence": "undecided",
                "repository": "PRESENT_TO_GARRETT",
                "why": "no licence evidence of any kind was found; absence is not permission",
                "evidence": ev.notes or ["nothing scanned"],
                "confidence": "no evidence"}

    return {"licence": "SymonSaysLLC Proprietary License",
            "repository": "SymonSayDistribute",
            "why": "nothing copyleft is linked in, so the default applies",
            "evidence": ([f"build-time only: {i} ({w})" for _, i, w in build_only[:4]]
                         or [f"{c}: {i} ({w})" for c, i, w in ev.declared[:4]]),
            "confidence": "default"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Decide where a thing belongs, from what is on disk.")
    ap.add_argument("paths", nargs="*", type=Path,
                    help="what to scan; omit when triaging a prospect from --sources")
    ap.add_argument("--sources", nargs="*", default=None, metavar="SOURCE@SPDX",
                    help="for a PROSPECT that does not exist yet: what it will be built from, "
                         "each with its licence, e.g. github.com/x/y@MIT")
    ap.add_argument("--alternatives", default="",
                    help="when a source is copyleft: what non-copyleft variants were searched "
                         "and why each was rejected. Required, because reaching the copyleft "
                         "branch is a claim that none exists")
    ap.add_argument("--name", default=None, help="what to call this thing in the report")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.sources is not None or not a.paths:
        v = prospect(a.name or 'prospect', a.sources or [], a.alternatives)
        if a.json:
            print(json.dumps(v, indent=1)); return 0 if v['repository'] != 'NOT YET A PROSPECT' else 2
        print(f"prospect  {a.name or '(unnamed)'}")
        print(f"  verdict   {v['repository']}")
        print(f"  licence   {v['licence']}")
        print(f"  why       {v['why']}")
        for e in v['evidence']:
            print(f"            {e}")
        return 0 if v['repository'] != 'NOT YET A PROSPECT' else 2


    name = a.name or a.paths[0].name
    home = already_placed(a.paths)
    if home:
        v = {"licence": "as that tree carries", "repository": "ALREADY PLACED",
             "why": f"this already lives in {home}", "evidence": [], "confidence": "not a placement question"}
        if a.json:
            print(json.dumps({"name": name, "verdict": v}, indent=2)); return 0
        print(f"{name}\n  {v['why']}.\n  Nothing to decide; the flow places NEW things.")
        return 0

    ev = Evidence()
    for p in a.paths:
        scan_path(p, ev)
    v = verdict(ev)

    if a.json:
        print(json.dumps({"name": name, "verdict": v,
                          "declared": ev.declared, "linked": ev.linked[:40],
                          "buildtime": ev.buildtime[:40], "notes": ev.notes}, indent=2))
        return 0

    print(f"{name}")
    print(f"  licence      {v['licence']}")
    print(f"  repository   {v['repository']}")
    print(f"  because      {v['why']}")
    print(f"  confidence   {v['confidence']}")
    for e in v["evidence"]:
        print(f"    - {e}")
    if v["repository"] == "PRESENT_TO_GARRETT":
        print("\n  This one is a question, not a placement. Raise it and keep working on the rest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
