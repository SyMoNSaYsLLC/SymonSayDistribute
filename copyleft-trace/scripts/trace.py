#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""copyleft-trace — does a copyleft obligation actually reach this artifact?

    scripts/trace.py <elf-or-directory> [...] [--json]

THE ONLY QUESTION THAT MATTERS
------------------------------
A copyleft component used to BUILD something does not make the output copyleft. A copyleft
component LINKED INTO the shipped artifact does. Everything else in a licence discussion is
downstream of that distinction, and getting it backwards is expensive in both directions: it
either drags a product into the open source tree, or hides a real obligation inside a
proprietary release.

So this walks what a binary actually links — the NEEDED graph, transitively — and reports the
licence of each library it truly depends on at run time. A recipe's DEPENDS line is not
evidence of linkage; a NEEDED entry is.

THE EXCEPTIONS THAT DEFEAT AN OBLIGATION
----------------------------------------
Two matter constantly and are easy to miss:

  * The GCC runtime (libgcc, libstdc++, libgomp) is GPL-3.0-or-later WITH GCC-exception-3.1.
    The exception exists precisely so that compiling with GCC does not make your work GPL.
  * LGPL linked DYNAMICALLY does not force the combined work open. Linked STATICALLY it does.
    The difference is visible: a dynamic dependency appears in NEEDED, a static one does not
    appear at all because it is already inside the binary.

The second is why "no copyleft in NEEDED" is necessary but not sufficient, and this says so
rather than implying it checked something it cannot see.
"""
from __future__ import annotations
import argparse, json, re, subprocess, shutil
from pathlib import Path

# Obligation by soname stem. Read from the system where possible, and fall back to this table
# for the handful that decide almost every case.
KNOWN = {
    "libc": ("LGPL-2.1-or-later", "weak", "glibc, linked dynamically — does not force the work open"),
    "libm": ("LGPL-2.1-or-later", "weak", "glibc"),
    "libpthread": ("LGPL-2.1-or-later", "weak", "glibc"),
    "libdl": ("LGPL-2.1-or-later", "weak", "glibc"),
    "librt": ("LGPL-2.1-or-later", "weak", "glibc"),
    "ld-linux-x86-64": ("LGPL-2.1-or-later", "weak", "glibc — the dynamic loader itself"),
    "ld-linux-aarch64": ("LGPL-2.1-or-later", "weak", "glibc — the dynamic loader itself"),
    "libgcc_s": ("GPL-3.0-or-later WITH GCC-exception-3.1", "exempt", "the runtime exception is the whole point of it"),
    "libstdc++": ("GPL-3.0-or-later WITH GCC-exception-3.1", "exempt", "the runtime exception is the whole point of it"),
    "libgomp": ("GPL-3.0-or-later WITH GCC-exception-3.1", "exempt", "the runtime exception is the whole point of it"),
    "libgfortran": ("GPL-3.0-or-later WITH GCC-exception-3.1", "exempt", "the runtime exception is the whole point of it"),
    "libcudart": ("proprietary-third-party", "vendor", "the operator's CUDA runtime, not redistributed by us"),
    "libcublas": ("proprietary-third-party", "vendor", "the operator's CUDA runtime"),
    "libcublasLt": ("proprietary-third-party", "vendor", "the operator's CUDA runtime"),
    "libcuda": ("proprietary-third-party", "vendor", "the operator's driver"),
    "libnvidia-ml": ("proprietary-third-party", "vendor", "the operator's driver"),
}
STRONG = re.compile(r"\b(A?GPL-[123])", re.I)
WEAK = re.compile(r"\b(LGPL|MPL|EPL|CDDL)", re.I)


def is_elf(p: Path) -> bool:
    try:
        return p.is_file() and p.stat().st_size > 64 and p.open("rb").read(4) == b"\x7fELF"
    except Exception:
        return False


def needed(p: Path) -> list[str]:
    if not shutil.which("readelf"):
        return []
    r = subprocess.run(["readelf", "-d", str(p)], capture_output=True, text=True)
    return re.findall(r"NEEDED.*\[([^\]]+)\]", r.stdout)


def stem(soname: str) -> str:
    return soname.split(".so")[0]


def resolve(soname: str, near: Path | None = None) -> str:
    """Where the loader would find it.

    A sibling wins over a system library, because that is what the loader does when RUNPATH
    points at the binary's own directory — and it is where our own libraries live. Looking
    only at the system cache reported our own work as having an unrecorded licence, which is
    the difference between "we built this under a permissive licence" and "route to a human"."""
    if near is not None:
        for d in (near.parent, near.parent / "..", near.parent / "ggml"):
            cand = (d / soname).resolve()
            if cand.exists():
                return str(cand)
    r = subprocess.run(["bash", "-c", f"/sbin/ldconfig -p 2>/dev/null | grep -m1 ' {soname} '"],
                       capture_output=True, text=True)
    m = re.search(r"=>\s*(\S+)", r.stdout)
    return m.group(1) if m else ""


def owner(path: str) -> str:
    if not path or not shutil.which("dpkg"):
        return ""
    real = subprocess.run(["readlink", "-f", path], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["dpkg", "-S", real or path], capture_output=True, text=True)
    return r.stdout.split(":")[0].strip() if r.returncode == 0 else ""


def local_licence(path: str) -> str:
    """A licence file beside a library we built and ship."""
    if not path:
        return ""
    d = Path(path).parent
    for up in (d, d.parent, d.parent.parent):
        for name in ("LICENSE", "LICENCE", "COPYING"):
            f = up / name
            if f.exists():
                try:
                    head = f.read_text(errors="replace")[:300]
                except Exception:
                    continue
                for ident in ("MIT", "Apache", "BSD", "ISC", "SymonSaysLLC"):
                    if ident.lower() in head.lower():
                        return f"{ident} (from {f})"
        for f in sorted(up.glob("licenses/*")) [:12]:
            try:
                if "MIT" in f.read_text(errors="replace")[:300]:
                    return f"MIT (from {f})"
            except Exception:
                continue
    return ""


def obligation(soname: str, near: Path | None = None) -> tuple[str, str, str]:
    s = stem(soname)
    if s in KNOWN:
        return KNOWN[s]
    p = resolve(soname, near)
    loc = local_licence(p)
    if loc:
        cls = "strong" if STRONG.search(loc) else ("weak" if WEAK.search(loc) else "permissive")
        return (loc.split(" (from")[0], cls, f"carried beside the binary: {p}")
    pkg = owner(p)
    lic = ""
    if pkg:
        cp = Path(f"/usr/share/doc/{pkg}/copyright")
        if cp.exists():
            try:
                head = cp.read_text(errors="replace")[:4000]
                m = re.search(r"^License:\s*(.+)$", head, re.M)
                lic = m.group(1).strip() if m else ""
            except Exception:
                pass
    if lic:
        if "exception" in lic.lower():
            return (lic, "exempt", f"from {pkg}")
        if STRONG.search(lic):
            return (lic, "strong", f"from {pkg}")
        if WEAK.search(lic):
            return (lic, "weak", f"from {pkg}")
        return (lic, "permissive", f"from {pkg}")
    return ("unrecorded", "unknown", f"package {pkg or 'unidentified'}; no licence line found")


def walk_needed(root: Path, depth: int = 3) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    frontier = [(s, 1) for s in needed(root)]
    while frontier:
        so, d = frontier.pop(0)
        if so in seen:
            continue
        lic, cls, note = obligation(so, root)
        seen[so] = {"licence": lic, "class": cls, "note": note, "depth": d}
        if d < depth:
            p = resolve(so, root)
            if p and is_elf(Path(p)):
                frontier += [(x, d + 1) for x in needed(Path(p))]
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    binaries: list[Path] = []
    for t in a.targets:
        if t.is_dir():
            binaries += [p for p in sorted(t.rglob("*")) if is_elf(p)]
        elif is_elf(t):
            binaries.append(t)

    report = {}
    for b in binaries:
        report[str(b)] = walk_needed(b)

    if a.json:
        print(json.dumps(report, indent=2)); return 0

    if not binaries:
        print("no ELF binaries found — nothing links anything, so nothing is forced")
        return 0

    verdict_strong: list = []
    unresolved: list = []
    for b, deps in report.items():
        print(f"\n{b}")
        for so, d in sorted(deps.items()):
            mark = {"strong": "FORCES", "weak": "weak  ", "exempt": "exempt", "vendor": "vendor",
                    "permissive": "ok    ", "unknown": "UNKNOWN"}[d["class"]]
            print(f"  {mark}  {so:28s} {d['licence'][:44]}")
            if d["class"] == "strong":
                verdict_strong.append((b, so, d["licence"]))
            if d["class"] == "unknown":
                unresolved.append((b, so))

    print()
    if verdict_strong:
        print("Copyleft reaches a shipped artifact:")
        for b, so, lic in verdict_strong:
            print(f"  {Path(b).name} links {so} ({lic})")
        print("\nThis is the open source case. It is forced, not chosen.")
    elif unresolved:
        print("No strong copyleft found, but some dependencies could not be identified:")
        for b, so in unresolved:
            print(f"  {Path(b).name} links {so} — licence unrecorded")
        print("\nUnknown is not the same as clean. This routes to a human, not to a default.")
    else:
        print("No strong copyleft in any dynamic dependency. The default applies: proprietary.")
    print("\nNot visible here: a STATICALLY linked library is already inside the binary and")
    print("never appears in NEEDED. If a build statically links LGPL or GPL, this cannot see it —")
    print("check the build flags before treating this as a complete answer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
