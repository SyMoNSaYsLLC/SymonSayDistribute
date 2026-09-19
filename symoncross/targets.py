#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What this build host can target — measured on the host, never recalled.

THIS COMPONENT CROSS-COMPILES NOTHING.

It answers one question and only that question: **can the estate build for target X right now,
with what, and what is missing.** No estate component is compiled here, no layer is fetched, no
build directory is created, nothing outside this worktree is written to.

That distinction is the whole point. A component that claimed to "build for Windows" while
nothing on this host can emit a PE binary would be a phantom completion: the report exists, the
artifact does not. So every answer here carries the evidence it was derived from — the path that
was read, the argument vector that was run, and the exit code that came back — and a capability
that was not measured is not claimed.

WHAT `buildable` MEANS, EXACTLY
    buildable = the toolchain on this host can emit an artifact for that target, proven by
                emitting one.
    buildable != the estate has source that wants building for that target.

Those are different questions and conflating them produces nonsense in both directions. This
host has gcc 14.2.0 and glibc, so `linux-native` is buildable — even though the estate's
components are Python and none of them needs a C compiler. The second question is answered
separately by `portability()`, and for these components it is the one that actually matters:
what stops them running elsewhere is not a missing cross-compiler, it is the Linux-only paths
and Linux-only programs written into them.

HOW A TARGET IS DECIDED
Each target carries a list of preconditions. `blocked_by` is derived from that list, and
`buildable` is derived from `blocked_by`:

    blocked_by = [p["name"] for p in preconditions if not p["met"]]
    buildable  = not blocked_by

so a false `buildable` structurally cannot arrive without the reason it is false. A bare boolean
verdict is never returned, because a verdict nobody can check is a rumour.

THE PROBE COMPILES
Three of the four targets are settled by compiling a few lines into a temporary directory and
reading what came out — ELF for the native target, class bytecode for the JVM, a Mach-O for
darwin. This is a measurement of the toolchain, not a build of anything the estate ships. It is
here because the alternative is inference, and inference is how "the SDK is on disk" becomes
"we can build for it" without anyone checking. On this host that inference would have been
wrong, and the probe is what caught it.
"""
from __future__ import annotations

import ast
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

# ---------------------------------------------------------------------------------------------
# Where things are. Every one of these is read, never written.
# ---------------------------------------------------------------------------------------------

DIST_ROOT = Path(os.environ.get("SYM_CROSS_DIST_ROOT", "/mnt/SymonSayDistribute"))
SOURCE_ROOT = Path(os.environ.get("SYM_CROSS_SOURCE_ROOT", "/mnt/SymonSaySource"))

# (path, kind, depth). `kind` decides whether a layer found there could ever be ACQUIRED:
# a cache is a download area, not a tree the estate owns, so nothing in one is acquired however
# complete it looks.
LAYER_ROOTS: tuple[tuple[str, str, int], ...] = (
    ("/home/google/.cache/oematch/layers", "cache", 3),
    ("/home/google/symoneural-staging/yocto", "staging", 4),
    ("/home/google/SymonSaysLLC/Projects/yocto", "sandbox", 4),
    ("/yocto", "mount", 4),
)

# Enumerating every layer in a 300-entry download cache buries the one distinction this function
# exists to draw. Layers outside a cache are always listed individually; from a cache only the
# ones a cross-target question is about. The root summary still carries the true total, so the
# rest is summarised, not hidden — pass `names=[...]` to pull any of them out by name.
CROSS_TARGET_LAYERS: tuple[str, ...] = ("meta-mingw", "meta-darwin", "meta-java", "meta-swift")

# Copies found by searching; none of these is on PATH, which is the point of reporting them.
BITBAKE_PATHS: tuple[str, ...] = (
    "/home/google/SymonSaysLLC/Projects/yocto/bitbake/bin/bitbake",
    "/home/google/SymonSaysLLC/Projects/symoneural-bootstrap-master/bitbake/bin/bitbake",
    "/home/google/SymonSaysLLC/Projects/symoneural-devtool-bootstrap/bitbake/bin/bitbake",
    "/home/google/symonsaylearn/upstream/build/bitbake",
)

OE_BUILD_DIR = Path("/yocto")

DARWIN_BUNDLE = Path(
    os.environ.get("SYM_CROSS_DARWIN_BUNDLE",
                   "/home/google/.swiftpm/swift-sdks/darwin.artifactbundle"))

# Toolkit command names as they must be typed to be found on PATH.
MINGW_COMPILERS: tuple[str, ...] = (
    "x86_64-w64-mingw32-gcc",
    "x86_64-w64-mingw32-g++",
    "i686-w64-mingw32-gcc",
)

# Version arguments differ per tool; a wrong one reports a working tool as absent.
BUILDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cmake", ("--version",)),
    ("ninja", ("--version",)),
    ("make", ("--version",)),
    ("cargo", ("--version",)),
    ("go", ("version",)),
    ("swiftc", ("--version",)),
    ("javac", ("-version",)),
)

TARGET_NAMES: tuple[str, ...] = ("windows", "darwin", "jvm", "linux-native")

# A target key names a PLATFORM FAMILY; the toolchain that would serve it is metadata beside
# it, not baked into the public identifier. Garrett, 2026-09-19: "the canonical SyMoNeuRaL
# target key should describe the platform rather than bake a particular toolchain
# implementation into the public identifier."
#
# The distinction matters because a platform can be served by more than one toolchain, and a
# key that says otherwise has to be renamed the day a second one appears. Upstream identifiers
# — meta-mingw, x86_64-w64-mingw32 — keep their exact spelling wherever they are technically
# required; only OUR key changed.
TARGET_TOOLCHAIN: dict[str, str] = {
    "windows": "mingw",
    "darwin": "swift-sdk",
    "jvm": "javac",
    "linux-native": "native",
}

# Accepted on input, never returned. A caller using the old key still works; the answer always
# comes back under the canonical one, so two names cannot both become canonical by habit.
DEPRECATED_TARGET_ALIASES: dict[str, str] = {"windows-mingw": "windows"}

# The triple is a technical identifier and is typed exactly as the toolchain expects it.
DARWIN_TRIPLE = "x86_64-apple-macosx13.0"

# ---------------------------------------------------------------------------------------------
# portability(): what actually stops these components running somewhere else.
# ---------------------------------------------------------------------------------------------

# Programs that exist only on this platform. A component that shells out to one of these does not
# run elsewhere, whatever the build system can emit.
LINUX_ONLY_PROGRAMS: frozenset[str] = frozenset({
    "lsmod", "dpkg", "dpkg-query", "ss", "dkms", "nvidia-smi", "uname",
    "modprobe", "systemctl", "journalctl", "ldconfig", "insmod", "rmmod",
})

# Paths that exist only on this platform.
LINUX_ONLY_PATH_PREFIXES: tuple[str, ...] = (
    "/proc", "/sys/", "/lib/modules", "/usr/lib/x86_64-linux-gnu",
)

SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "site-packages",
})

# Build output, not layers. Walking these costs minutes and finds nothing: a sstate directory
# holds hundreds of thousands of files and never a conf/layer.conf. The list is a constant so
# that a root's reported count can be reproduced by anyone reading it.
NOT_A_LAYER_DIR: frozenset[str] = frozenset({
    "sstate-cache", "downloads", "tmp", "tmp-glibc", "deploy", "build", "build-symoneural",
    "build-audit", "cache", "lost+found", "sources", "matrix-run", "Archives", "metrics",
    "controlboard",
})

# A detector that reads its own detector list finds itself. Excluding it silently would be a
# hole nobody can enumerate, so the exclusion is returned in the record instead.
#
# These are resolved ABSOLUTE paths, compared as paths. They were once relative tails matched
# with endswith, which worked from the estate root and silently stopped working for any root at
# or below this component — the one case where the scanner is certain to be in range. A scan of
# this directory then reported seventeen findings in the detector and an empty `excluded`.
def _self_excluded() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    return (here, here.parent.parent / "tests" / "test_symoncross.py")

# A string only counts as a command line when it BOTH pipes/redirects/chains AND carries an
# option. Either alone is ordinary prose: "no nvidia-smi on this host; ..." has a semicolon and
# is a message, and a message reported as a call site is how a report stops being believed.
_SHELL_METACHARACTERS: tuple[str, ...] = ("|", "$(", "&&", ";", "`", ">", "<")

# Where an executable lives. A path whose basename matches a program but whose directory is not
# one of these is not that program: /api/symonkernel/dkms is a route, not a package manager.
_BIN_DIRS: frozenset[str] = frozenset({
    "/bin", "/usr/bin", "/sbin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin",
})

NOT_EXPOSED: dict[str, str] = {}
"""Every public callable in this module carries a route in service.py.

The name is declared rather than omitted: an empty mapping is a decision on record that nothing
here is deliberately unreachable, which is a different statement from not having considered it.
"""


# ---------------------------------------------------------------------------------------------
# Evidence. Nothing below returns a fact without one of these attached.
# ---------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run(argv: Iterable[str], timeout: float = 20.0) -> dict[str, Any]:
    """Run an argument vector and return what happened, including the exit code.

    Always a list, never a shell string: a value that reaches a shell is a value that can become
    a command. Always bounded: an unbounded probe on a capability report hangs the route that
    asked, and a capability report that hangs is worse than one that says it timed out.
    """
    argv = [str(a) for a in argv]
    started = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"command": argv, "rc": None, "error": "not found on this host",
                "stdout": "", "stderr": "", "seconds": 0.0}
    except OSError as e:                                  # not executable, bad interpreter, ...
        return {"command": argv, "rc": None, "error": f"{type(e).__name__}: {e}",
                "stdout": "", "stderr": "", "seconds": 0.0}
    except subprocess.TimeoutExpired:
        return {"command": argv, "rc": None, "error": f"timed out after {timeout}s",
                "stdout": "", "stderr": "", "seconds": round(time.monotonic() - started, 2)}
    return {"command": argv, "rc": p.returncode,
            "stdout": (p.stdout or "").strip(), "stderr": (p.stderr or "").strip(),
            "seconds": round(time.monotonic() - started, 2)}


def _first_line(ev: dict[str, Any]) -> str:
    for stream in ("stdout", "stderr"):
        text = (ev.get(stream) or "").strip()
        if text:
            return text.splitlines()[0]
    return ev.get("error") or ""


def _which(name: str) -> dict[str, Any]:
    p = shutil.which(name)
    return {"command": name, "path": p, "found": p is not None,
            "evidence": {"call": f"shutil.which({name!r})", "result": p}}


def _path_fact(p: Path) -> dict[str, Any]:
    """What the filesystem says about a path. The read itself is the evidence."""
    fact: dict[str, Any] = {"path": str(p), "exists": False}
    try:
        st = p.lstat()
    except OSError as e:
        fact["error"] = f"{type(e).__name__}: {e}"
        return fact
    fact["exists"] = True
    fact["is_dir"] = p.is_dir()
    fact["is_symlink"] = p.is_symlink()
    fact["bytes"] = st.st_size
    fact["modified"] = datetime.fromtimestamp(st.st_mtime, timezone.utc).date().isoformat()
    if fact["is_symlink"]:
        try:
            fact["resolves_to"] = str(p.resolve())
        except OSError:
            fact["resolves_to"] = None
    return fact


def _pins() -> dict[str, Any]:
    """Every acquisition pin the estate holds, read from disk on each call.

    A pin is what makes an upstream tree ACQUIRED rather than merely sitting on the disk: it
    records the commit, so the same bytes can be fetched again and the choice defended later.
    """
    glob = "*/pins/*.json"
    entries: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    for p in sorted(SOURCE_ROOT.glob(glob)):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            unreadable.append({"path": str(p), "error": f"{type(e).__name__}: {e}"})
            continue
        entries.append({"component": d.get("component"),
                        "acquisition_state": d.get("acquisition_state"),
                        "revision": d.get("intended_revision"),
                        "path": str(p)})
    return {"root": str(SOURCE_ROOT), "root_exists": SOURCE_ROOT.is_dir(),
            "glob": glob, "count": len(entries), "entries": entries,
            "unreadable": unreadable}


# ---------------------------------------------------------------------------------------------
# hosts()
# ---------------------------------------------------------------------------------------------

def hosts() -> dict[str, Any]:
    """The build host itself: os, arch, libc, and the native compiler with its version.

    Everything here is read or run at call time. The host is the one thing a capability report
    must never take from a note, because a note is exactly as old as the last time somebody
    changed the machine.
    """
    libc_name, libc_version = platform.libc_ver()
    ldd = _run(["ldd", "--version"], timeout=10.0)

    cc = _which("cc")
    cc_version = _run([cc["path"], "--version"], timeout=10.0) if cc["found"] else {
        "command": ["cc", "--version"], "rc": None, "error": "no cc on PATH",
        "stdout": "", "stderr": "", "seconds": 0.0}

    uname = _run(["uname", "-srm"], timeout=10.0)

    return {
        "os": {"value": platform.system(),
               "evidence": {"call": "platform.system()", "result": platform.system()}},
        "kernel": {"value": platform.release(),
                   "evidence": {"call": "platform.release()", "command": uname["command"],
                                "rc": uname["rc"], "result": _first_line(uname)}},
        "arch": {"value": platform.machine(),
                 "evidence": {"call": "platform.machine()", "result": platform.machine()}},
        "libc": {"value": f"{libc_name} {libc_version}".strip() or None,
                 "evidence": {"call": "platform.libc_ver()",
                              "command": ldd["command"], "rc": ldd["rc"],
                              "result": _first_line(ldd)}},
        "compiler": {"name": "cc", "path": cc["path"], "found": cc["found"],
                     "version": _first_line(cc_version) or None,
                     "evidence": {"which": cc["evidence"], "command": cc_version["command"],
                                  "rc": cc_version["rc"]}},
        "python": {"value": platform.python_version(), "executable": sys.executable,
                   "evidence": {"call": "platform.python_version()"}},
        "measured_at": _now(),
    }


# ---------------------------------------------------------------------------------------------
# layers()
# ---------------------------------------------------------------------------------------------

def _repo_root(d: Path) -> Path | None:
    """The nearest ancestor holding a .git — a sublayer is acquired through its repository."""
    for candidate in (d, *d.parents):
        if (candidate / ".git").exists():
            return candidate
        if candidate == candidate.parent:
            break
    return None


def _find_layers(root: Path, depth: int) -> list[Path]:
    """Directories holding conf/layer.conf, to a stated depth.

    The depth is recorded with the answer because it changes the answer: at depth 2 this root
    reported nothing and at depth 3 it reported three hundred layers, and a search whose reach
    is not stated is a number nobody can reproduce.
    """
    found: list[Path] = []

    def walk(d: Path, level: int) -> None:
        if level > depth:
            return
        try:
            children = sorted(d.iterdir())
        except OSError:
            return
        for c in children:
            if not c.is_dir() or c.is_symlink():
                continue
            if c.name in SKIP_DIRS or c.name in NOT_A_LAYER_DIR:
                continue
            if (c / "conf" / "layer.conf").is_file():
                found.append(c)
            walk(c, level + 1)

    if (root / "conf" / "layer.conf").is_file():
        found.append(root)
    walk(root, 2)
    return found


_HEAD_CACHE: dict[str, dict[str, Any]] = {}


def _git_head(repo: Path) -> dict[str, Any]:
    """The commit a checkout is actually at. Read, because a pin records intent, not fact.

    A pin says which commit the estate meant to build from. Repeating that number beside a
    directory implies the directory is at it, and nobody had checked. On this host neither
    pinned checkout was: both had moved, and the record said otherwise.
    """
    key = str(repo)
    if key in _HEAD_CACHE:
        return dict(_HEAD_CACHE[key])
    ev = _run(["git", "-C", key, "rev-parse", "HEAD"], timeout=20.0)
    out = {"revision": ev["stdout"] if ev["rc"] == 0 else None,
           "evidence": {"command": ev["command"], "rc": ev["rc"],
                        "error": ev.get("error") or (ev["stderr"][:160] or None)}}
    _HEAD_CACHE[key] = out
    return dict(out)


def _acquisition(layer: Path, kind: str, pins: dict[str, Any]) -> dict[str, Any]:
    """ACQUIRED, or merely PRESENT. This distinction is the point of the function.

    ACQUIRED means the estate tracks this upstream under SymonSaySource with a pin naming its
    commit. PRESENT means the bytes are on the disk and nothing records what they are — a
    download cache, a staging copy, a checkout in the sandbox. The two look identical in a
    directory listing and are not remotely the same thing to a build.

    An ACQUIRED record also says whether the checkout is at the commit its pin names. Tracked
    and at-the-pinned-commit are different facts, and reporting the first as though it were the
    second is how a build reproduces something nobody pinned.
    """
    repo = _repo_root(layer)
    names = {layer.name} | ({repo.name} if repo else set())
    match = next((e for e in pins["entries"] if e["component"] in names), None)

    if kind == "cache":
        return {
            "acquisition": "PRESENT", "acquired": False,
            "why": ("a download cache is not a tree the estate owns: nothing is built from one "
                    "and no pin records what these bytes are"),
            "pin": match, "checkout": None,
            "evidence": {"root_kind": kind, "names_searched": sorted(names),
                         "pins_searched": pins["count"], "pin_root": pins["root"]},
        }
    if match and match.get("acquisition_state") == "ACQUIRED":
        head = _git_head(repo) if repo else {"revision": None,
                                             "evidence": {"error": "no git repository above it"}}
        matches = bool(head["revision"]) and head["revision"] == match["revision"]
        checkout = {"repo_root": str(repo) if repo else None,
                    "head": head["revision"], "pin": match["revision"],
                    "matches_pin": matches, "evidence": head["evidence"]}
        why = (f"pinned as {match['component']} at {match['revision']}, and the checkout is at "
               f"that commit" if matches else
               f"pinned as {match['component']} at {match['revision']}, but the checkout is at "
               f"{head['revision']} — the tree on disk is NOT the pinned bytes"
               if head["revision"] else
               f"pinned as {match['component']} at {match['revision']}; the checkout's commit "
               f"could not be read")
        return {
            "acquisition": "ACQUIRED", "acquired": True, "why": why,
            "pin": match, "checkout": checkout,
            "evidence": {"root_kind": kind, "names_searched": sorted(names),
                         "pin_path": match["path"], "pins_searched": pins["count"],
                         "head": head["evidence"]},
        }
    return {
        "acquisition": "PRESENT", "acquired": False,
        "why": (f"no pin under {pins['root']} names any of {sorted(names)}"
                if match is None else
                f"pin {match['path']} records state {match.get('acquisition_state')!r}"),
        "pin": match, "checkout": None,
        "evidence": {"root_kind": kind, "names_searched": sorted(names),
                     "pins_searched": pins["count"], "pin_root": pins["root"]},
    }


def layers(names: Iterable[str] | None = None) -> dict[str, Any]:
    """Every OE layer this host can see, and whether the estate actually owns it.

    `names` selects layers by directory name from every root. Left out, the selection is every
    layer outside a download cache plus the cross-target layers a question about targets is
    about; the root summaries still carry the full counts.
    """
    pins = _pins()
    wanted = set(names) if names is not None else None

    roots: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    for raw, kind, depth in LAYER_ROOTS:
        root = Path(raw)
        summary: dict[str, Any] = {"path": str(root), "kind": kind, "search_depth": depth,
                                   "exists": root.is_dir()}
        if not summary["exists"]:
            summary["layer_count"] = 0
            summary["evidence"] = {"read": f"{root}/*/conf/layer.conf", "result": "root absent"}
            roots.append(summary)
            continue

        found = _find_layers(root, depth)
        summary["layer_count"] = len(found)
        summary["evidence"] = {"read": f"{root} to depth {depth} for */conf/layer.conf",
                               "result": f"{len(found)} layer(s)",
                               "not_descended_into": sorted(NOT_A_LAYER_DIR)}
        roots.append(summary)

        for d in found:
            if wanted is not None:
                if d.name not in wanted:
                    continue
            elif kind == "cache" and d.name not in CROSS_TARGET_LAYERS:
                continue

            conf = d / "conf" / "layer.conf"
            repo = _repo_root(d)
            acq = _acquisition(d, kind, pins)
            records.append({
                "name": d.name,
                "path": str(d),
                "root": str(root),
                "root_kind": kind,
                "layer_conf": _path_fact(conf),
                "repo_root": str(repo) if repo else None,
                **acq,
                "directory": _path_fact(d),
            })

    records.sort(key=lambda r: (r["root_kind"], r["name"]))
    acquired = [r["name"] for r in records if r["acquired"]]
    present = [r["name"] for r in records if not r["acquired"]]
    drifted = [r["name"] for r in records
               if r["acquired"] and r["checkout"] and not r["checkout"]["matches_pin"]]
    return {
        "roots": roots,
        "selection": ("named" if wanted is not None else
                      "every layer outside a cache, plus the cross-target layers"),
        "selected_names": sorted(wanted) if wanted is not None else list(CROSS_TARGET_LAYERS),
        "layers": records,
        "totals": {"reported": len(records),
                   "acquired": len(acquired), "present": len(present),
                   "acquired_but_drifted": len(drifted),
                   "seen_across_roots": sum(r["layer_count"] for r in roots)},
        "acquired_names": sorted(set(acquired)),
        "present_names": sorted(set(present)),
        "drifted_names": sorted(set(drifted)),
        "pins": {"root": pins["root"], "root_exists": pins["root_exists"],
                 "count": pins["count"], "glob": pins["glob"],
                 "unreadable": pins["unreadable"]},
        "measured_at": _now(),
    }


# ---------------------------------------------------------------------------------------------
# builders()
# ---------------------------------------------------------------------------------------------

def builders() -> dict[str, Any]:
    """The build systems on this host, each with how it was found and what it answered.

    The build-and-integration tool is reported by searching for copies and is never executed:
    starting one is a build, and this component does not build. Its copies are described from
    the filesystem — path, mode, size, date — and from the pin that says what it is supposed
    to be.
    """
    pins = _pins()
    bb_pin = next((e for e in pins["entries"] if e["component"] == "bitbake"), None)

    on_path = _which("bitbake")
    copies = []
    for raw in BITBAKE_PATHS:
        p = Path(raw)
        fact = _path_fact(p)
        fact["executable"] = os.access(p, os.X_OK) if fact["exists"] else False
        copies.append(fact)

    found_copies = [c for c in copies if c["exists"]]
    tools: dict[str, Any] = {
        "bitbake": {
            "on_path": on_path["found"],
            "path": on_path["path"],
            "copies_found": len(found_copies),
            "copies": copies,
            "pin": bb_pin,
            "version": None,
            "not_run": ("a build-and-integration tool is not executed by a capability report; "
                        "starting one is a build"),
            "evidence": {"which": on_path["evidence"],
                         "searched": list(BITBAKE_PATHS),
                         "pin_root": pins["root"]},
        }
    }

    for name, args in BUILDERS:
        w = _which(name)
        ev = _run([w["path"], *args], timeout=20.0) if w["found"] else {
            "command": [name, *args], "rc": None, "error": "not found on this host",
            "stdout": "", "stderr": "", "seconds": 0.0}
        tools[name] = {
            "on_path": w["found"],
            "path": w["path"],
            "version": _first_line(ev) or None,
            "evidence": {"which": w["evidence"], "command": ev["command"], "rc": ev["rc"],
                         "seconds": ev.get("seconds")},
        }

    return {
        "tools": tools,
        "on_path": sorted(n for n, t in tools.items() if t["on_path"]),
        "absent": sorted(n for n, t in tools.items() if not t["on_path"]),
        "measured_at": _now(),
    }


# ---------------------------------------------------------------------------------------------
# targets()
# ---------------------------------------------------------------------------------------------

_PROBE_CACHE: dict[str, dict[str, Any]] = {}


def _probe(key: str, fn) -> dict[str, Any]:
    """Run a compile probe once per process and stamp it with when it actually ran.

    Cached because the darwin probe costs about nineteen seconds. The stamp is what keeps the
    cache honest: a repeated call says when the measurement was taken rather than implying it
    was taken now.
    """
    if key not in _PROBE_CACHE:
        result = fn()
        result["measured_at"] = _now()
        result["cached"] = False
        _PROBE_CACHE[key] = result
        return dict(result)
    out = dict(_PROBE_CACHE[key])
    out["cached"] = True
    return out


def _probe_native() -> dict[str, Any]:
    """Compile and run a native program. Emitting one is the proof; `which cc` is not."""
    cc = shutil.which("cc")
    if cc is None:
        return {"ok": False, "why": "no cc on PATH", "run": None, "artifact": None}
    d = Path(tempfile.mkdtemp(prefix="symoncross-"))
    try:
        src, out = d / "probe.c", d / "probe.bin"
        src.write_text('#include <stdio.h>\nint main(void){puts("symoncross");return 0;}\n')
        ev = _run([cc, str(src), "-o", str(out)], timeout=60.0)
        artifact = _path_fact(out)
        if ev["rc"] == 0 and out.is_file():
            artifact["magic"] = out.read_bytes()[:4].hex()
            ran = _run([str(out)], timeout=20.0)
            ok = ran["rc"] == 0 and ran["stdout"] == "symoncross"
            return {"ok": ok, "why": ("compiled and ran" if ok else "compiled but did not run"),
                    "run": ev, "executed": {"rc": ran["rc"], "stdout": ran["stdout"]},
                    "artifact": artifact}
        return {"ok": False, "why": f"compiler exited {ev['rc']}", "run": ev,
                "artifact": artifact, "first_error": _first_line(ev)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _probe_jvm() -> dict[str, Any]:
    """Compile to class bytecode and check the magic. Bytecode is the artifact, not a binary."""
    javac = shutil.which("javac")
    if javac is None:
        return {"ok": False, "why": "no javac on PATH", "run": None, "artifact": None}
    d = Path(tempfile.mkdtemp(prefix="symoncross-"))
    try:
        src = d / "Probe.java"
        src.write_text("public class Probe { public static void main(String[] a) {} }\n")
        ev = _run([javac, "-d", str(d), str(src)], timeout=120.0)
        cls = d / "Probe.class"
        artifact = _path_fact(cls)
        if ev["rc"] == 0 and cls.is_file():
            magic = cls.read_bytes()[:4].hex()
            artifact["magic"] = magic
            ok = magic == "cafebabe"
            return {"ok": ok,
                    "why": ("class bytecode emitted" if ok else f"unexpected magic {magic}"),
                    "run": ev, "artifact": artifact}
        return {"ok": False, "why": f"compiler exited {ev['rc']}", "run": ev,
                "artifact": artifact, "first_error": _first_line(ev)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _darwin_sdk() -> dict[str, Any]:
    """Read the SDK bundle: its manifest, its target triples, and whether its root resolves."""
    manifest = DARWIN_BUNDLE / "swift-sdk.json"
    fact = {"bundle": _path_fact(DARWIN_BUNDLE), "manifest": _path_fact(manifest),
            "toolset": _path_fact(DARWIN_BUNDLE / "toolset.json"),
            "sdk_version_file": _path_fact(DARWIN_BUNDLE / "darwin-sdk-version.txt"),
            "triples": [], "sdk_root": None, "complete": False}
    if not manifest.is_file():
        fact["why"] = f"no manifest at {manifest}"
        return fact
    try:
        d = json.loads(manifest.read_text())
    except (OSError, ValueError) as e:
        fact["why"] = f"manifest unreadable: {type(e).__name__}: {e}"
        return fact
    triples = d.get("targetTriples") or {}
    fact["triples"] = sorted(triples)
    entry = next((triples[t] for t in triples if t.startswith("x86_64-apple-macosx")), None)
    if entry is None:
        fact["why"] = "the manifest declares no x86_64 macosx triple"
        return fact
    root = DARWIN_BUNDLE / entry["sdkRootPath"]
    fact["sdk_root"] = _path_fact(root)
    fact["complete"] = root.exists()
    fact["why"] = ("sdk root resolves" if fact["complete"]
                   else f"sdk root {root} does not resolve")
    return fact


def _probe_darwin() -> dict[str, Any]:
    """Compile one line for the darwin triple and look at what came out.

    This is the probe that matters. The bundle is 3.2 GB, its manifest parses, its sdk root
    resolves through a symlink to a real 868 MB tree — and the compile still fails, because the
    host compiler cannot parse the SDK's own standard library interface. Every structural check
    passes and the target is not buildable. That gap is exactly why a capability report compiles
    instead of inspecting.
    """
    swiftc = shutil.which("swiftc")
    sdk = _darwin_sdk()
    if swiftc is None:
        return {"ok": False, "why": "no swiftc on PATH", "run": None, "artifact": None,
                "sdk": sdk}
    if not sdk["complete"]:
        return {"ok": False, "why": sdk.get("why", "sdk incomplete"), "run": None,
                "artifact": None, "sdk": sdk}
    d = Path(tempfile.mkdtemp(prefix="symoncross-"))
    try:
        src, out = d / "probe.swift", d / "probe.bin"
        src.write_text('print("symoncross")\n')
        ev = _run([swiftc, "-sdk", sdk["sdk_root"]["path"], "-target", DARWIN_TRIPLE,
                   "-o", str(out), str(src)], timeout=300.0)
        artifact = _path_fact(out)
        if ev["rc"] == 0 and out.is_file():
            magic = out.read_bytes()[:4].hex()
            artifact["magic"] = magic
            ok = magic in ("cffaedfe", "cefaedfe", "feedfacf", "feedface")
            return {"ok": ok,
                    "why": ("mach-o emitted" if ok else f"unexpected magic {magic}"),
                    "run": ev, "artifact": artifact, "sdk": sdk}
        errors = [ln for ln in (ev.get("stderr") or "").splitlines() if "error:" in ln]
        return {"ok": False,
                "why": (f"compiler exited {ev['rc']} with {len(errors)} error(s); the host "
                        f"compiler and this SDK are not a matched pair"),
                "run": {k: ev[k] for k in ("command", "rc", "seconds")},
                "first_errors": errors[:3], "error_count": len(errors),
                "artifact": artifact, "sdk": sdk}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _language_census() -> dict[str, Any]:
    """What source the estate actually holds, by extension. Counted, not remembered."""
    counts: dict[str, int] = {}
    files = 0
    if DIST_ROOT.is_dir():
        for p in DIST_ROOT.rglob("*"):
            if not p.is_file() or p.is_symlink():
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            ext = p.suffix.lower()
            if ext in (".c", ".cpp", ".cc", ".h", ".hpp", ".rs", ".go", ".swift", ".java",
                       ".kt", ".py", ".m", ".mm"):
                counts[ext] = counts.get(ext, 0) + 1
                files += 1
    return {"root": str(DIST_ROOT), "root_exists": DIST_ROOT.is_dir(),
            "by_extension": dict(sorted(counts.items())), "counted": files,
            "evidence": {"read": f"{DIST_ROOT} recursively, skipping {sorted(SKIP_DIRS)}"}}


def _precondition(name: str, met: bool, evidence: Any) -> dict[str, Any]:
    return {"name": name, "met": bool(met), "evidence": evidence}


def _record(target: str, preconditions: list[dict[str, Any]], estate_source: dict[str, Any],
            note: str) -> dict[str, Any]:
    """Derive the verdict from the preconditions, never the other way round.

    `blocked_by` comes from the list and `buildable` comes from `blocked_by`, so a false verdict
    structurally cannot arrive without its reasons. There is no branch here that can set one
    without the other.
    """
    blocked_by = [p["name"] for p in preconditions if not p["met"]]
    return {
        "target": target,
        "buildable": not blocked_by,
        "preconditions": preconditions,
        "blocked_by": blocked_by,
        "means": ("the toolchain on this host can emit an artifact for this target; NOT that "
                  "the estate has source wanting to be built for it"),
        "estate_source": estate_source,
        "note": note,
        "measured_at": _now(),
    }


def _target_windows(census: dict[str, Any], lay: dict[str, Any],
                          build: dict[str, Any]) -> dict[str, Any]:
    found = [c for c in (_which(n) for n in MINGW_COMPILERS) if c["found"]]
    pkg = _run(["dpkg-query", "-W", "-f=${Package} ${Version}\n", "mingw-w64*"], timeout=20.0)

    mingw_layers = [r for r in lay["layers"] if r["name"] == "meta-mingw"]
    acquired_layer = [r for r in mingw_layers if r["acquired"]]

    bb = build["tools"]["bitbake"]
    try:
        entries = sorted(p.name for p in OE_BUILD_DIR.iterdir())
    except OSError as e:
        entries = None
        build_dir_ev: dict[str, Any] = {"path": str(OE_BUILD_DIR),
                                        "error": f"{type(e).__name__}: {e}"}
    else:
        build_dir_ev = {"path": str(OE_BUILD_DIR), "entries": len(entries),
                        "sample": entries[:10], **_path_fact(OE_BUILD_DIR)}

    pre = [
        _precondition(
            "mingw cross compiler on PATH", bool(found),
            {"searched": list(MINGW_COMPILERS),
             "found": [c["path"] for c in found],
             "package_query": {"command": pkg["command"], "rc": pkg["rc"],
                               "stdout": pkg["stdout"][:200],
                               "stderr": pkg["stderr"][:200]}}),
        _precondition(
            "meta-mingw layer acquired", bool(acquired_layer),
            {"copies_seen": [{"path": r["path"], "acquisition": r["acquisition"],
                              "why": r["why"]} for r in mingw_layers],
             "acquired": [r["path"] for r in acquired_layer]}),
        _precondition(
            "build-and-integration tool on PATH", bb["on_path"],
            {"on_path": bb["on_path"], "copies_found": bb["copies_found"],
             "copies": [c["path"] for c in bb["copies"] if c["exists"]],
             "which": bb["evidence"]["which"]}),
        _precondition(
            "an OE build directory exists", bool(entries), build_dir_ev),
    ]
    native = sum(census["by_extension"].get(e, 0) for e in (".c", ".cpp", ".cc", ".rs", ".go"))
    return _record(
        "windows", pre,
        {"native_source_files": native, "by_extension": census["by_extension"],
         "evidence": census["evidence"]},
        ("Nothing on this host can emit a PE binary today by any route. There is also nothing "
         "here that would need one: the estate's components are Python."))


def _target_darwin(census: dict[str, Any]) -> dict[str, Any]:
    swiftc = _which("swiftc")
    version = _run([swiftc["path"], "--version"], timeout=20.0) if swiftc["found"] else {
        "command": ["swiftc", "--version"], "rc": None, "error": "not found",
        "stdout": "", "stderr": "", "seconds": 0.0}
    probe = _probe("darwin", _probe_darwin)
    sdk = probe.get("sdk") or _darwin_sdk()

    pre = [
        _precondition("swift compiler on PATH", swiftc["found"],
                      {"which": swiftc["evidence"], "command": version["command"],
                       "rc": version["rc"], "version": _first_line(version)}),
        _precondition("darwin SDK bundle complete on disk", bool(sdk["complete"]),
                      {"bundle": sdk["bundle"], "manifest": sdk["manifest"],
                       "triples": sdk["triples"], "sdk_root": sdk["sdk_root"],
                       "why": sdk.get("why")}),
        _precondition(f"compile probe for {DARWIN_TRIPLE}", bool(probe["ok"]),
                      {k: probe[k] for k in
                       ("why", "run", "first_errors", "error_count", "artifact",
                        "measured_at", "cached") if k in probe}),
    ]
    return _record(
        "darwin", pre,
        {"swift_source_files": census["by_extension"].get(".swift", 0),
         "objc_source_files": (census["by_extension"].get(".m", 0)
                               + census["by_extension"].get(".mm", 0)),
         "evidence": census["evidence"]},
        ("The SDK bundle is complete and the compiler is present, and the pair still does not "
         "compile. Structural checks said yes; the probe said no, and the probe is what counts."))


def _target_jvm(census: dict[str, Any]) -> dict[str, Any]:
    javac, java = _which("javac"), _which("java")
    jc = _run([javac["path"], "-version"], timeout=20.0) if javac["found"] else {
        "command": ["javac", "-version"], "rc": None, "error": "not found",
        "stdout": "", "stderr": "", "seconds": 0.0}
    jr = _run([java["path"], "-version"], timeout=20.0) if java["found"] else {
        "command": ["java", "-version"], "rc": None, "error": "not found",
        "stdout": "", "stderr": "", "seconds": 0.0}
    probe = _probe("jvm", _probe_jvm)

    pre = [
        _precondition("java compiler on PATH", javac["found"],
                      {"which": javac["evidence"], "command": jc["command"], "rc": jc["rc"],
                       "version": _first_line(jc)}),
        _precondition("java runtime on PATH", java["found"],
                      {"which": java["evidence"], "command": jr["command"], "rc": jr["rc"],
                       "version": _first_line(jr)}),
        _precondition("compile probe emits class bytecode", bool(probe["ok"]),
                      {k: probe[k] for k in
                       ("why", "run", "artifact", "first_error", "measured_at", "cached")
                       if k in probe}),
    ]
    return _record(
        "jvm", pre,
        {"java_source_files": census["by_extension"].get(".java", 0),
         "kotlin_source_files": census["by_extension"].get(".kt", 0),
         "evidence": census["evidence"]},
        ("Class bytecode is not host-specific, so this target needs no cross-toolchain. The "
         "estate holds no source for it."))


def _target_linux_native(census: dict[str, Any]) -> dict[str, Any]:
    is_linux = platform.system() == "Linux"
    cc = _which("cc")
    probe = _probe("native", _probe_native)

    pre = [
        _precondition("host is linux", is_linux,
                      {"call": "platform.system()", "result": platform.system()}),
        _precondition("native C compiler on PATH", cc["found"], cc["evidence"]),
        _precondition("compile probe emits and runs a native executable", bool(probe["ok"]),
                      {k: probe[k] for k in
                       ("why", "run", "executed", "artifact", "first_error", "measured_at",
                        "cached") if k in probe}),
    ]
    native = sum(census["by_extension"].get(e, 0) for e in (".c", ".cpp", ".cc"))
    return _record(
        "linux-native", pre,
        {"native_source_files": native, "python_source_files":
            census["by_extension"].get(".py", 0), "evidence": census["evidence"]},
        ("Buildable, and nothing here asks for it: the components are Python. What stops them "
         "running elsewhere is in portability(), not in a missing compiler."))


def targets(name: str | None = None) -> dict[str, Any]:
    """Can this host build for each target right now — and if not, what is in the way.

    `name` narrows the answer to one target. Every record carries its preconditions and a
    `blocked_by` derived from them; a bare boolean is never returned, because a verdict without
    its reasons cannot be acted on or checked.
    """
    if name is not None:
        name = DEPRECATED_TARGET_ALIASES.get(name, name)
    if name is not None and name not in TARGET_NAMES:
        raise KeyError(f"no such target: {name!r}; known targets are {list(TARGET_NAMES)}")

    census = _language_census()
    wanted = (name,) if name else TARGET_NAMES

    records: dict[str, Any] = {}
    if "windows" in wanted:
        records["windows"] = _target_windows(
            census, layers(names=["meta-mingw"]), builders())
    if "darwin" in wanted:
        records["darwin"] = _target_darwin(census)
    if "jvm" in wanted:
        records["jvm"] = _target_jvm(census)
    if "linux-native" in wanted:
        records["linux-native"] = _target_linux_native(census)

    return {
        "targets": records,
        "buildable": sorted(t for t, r in records.items() if r["buildable"]),
        "blocked": {t: r["blocked_by"] for t, r in records.items() if not r["buildable"]},
        "means": ("the toolchain on this host can emit an artifact for the target; NOT that "
                  "the estate has source wanting to be built for it"),
        "cross_compiles_nothing": True,
        "measured_at": _now(),
    }


# ---------------------------------------------------------------------------------------------
# portability()
# ---------------------------------------------------------------------------------------------

def _literal_text(node: ast.AST) -> str | None:
    """The literal text of a string, including the fixed parts of an f-string.

    An f-string's interpolations are replaced with a placeholder so that the prefix of
    f"/proc/{pid}/cmdline" is still recognisable as a path on this platform.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("\x00")
        return "".join(parts)
    return None


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Docstrings are prose, not calls. A file:line pointing at prose discredits the report."""
    ids: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(n, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _program_of(token: str) -> str | None:
    """The platform-locked program a token names, or None.

    A bare name, or an absolute path into a directory executables actually live in. Nothing
    else: a route `/api/symonkernel/dkms` and a module directory `updates/dkms` both end in a
    program name and neither is a call to one.
    """
    token = token.strip("\"'")
    if not token or token.startswith("-"):
        return None
    if token in LINUX_ONLY_PROGRAMS:
        return token
    if token.startswith("/"):
        p = PurePosixPath(token)
        if p.name in LINUX_ONLY_PROGRAMS and str(p.parent) in _BIN_DIRS:
            return p.name
    return None


def _looks_like_a_command(s: str) -> bool:
    return (any(m in s for m in _SHELL_METACHARACTERS)
            and any(t.startswith("-") for t in s.split()))


def _command_tokens(s: str) -> list[str]:
    """Split a shell string into candidate argv-zero positions.

    Shell punctuation is turned into whitespace first, so the program after a pipe or inside a
    command substitution is reached: `p=$(/sbin/ldconfig -p | awk …) && dpkg -S …` names two.
    """
    for ch in ("|", "&", ";", "(", ")", "$", "`", "<", ">", "="):
        s = s.replace(ch, " ")
    return s.split()


def _scan_source(text: str, rel: str) -> list[dict[str, Any]]:
    """Find the platform-locked call sites in one file, from its syntax tree.

    The tree, not a regex over the bytes: a regex matches the word in a comment and in a
    sentence, and a finding that points at a comment is the reason a whole report stops being
    believed. Comments are not in the tree at all, and docstrings are skipped explicitly.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [{"line": e.lineno or 0, "kind": "unparseable", "name": "SyntaxError",
                 "text": str(e)[:160], "site": f"{rel}:{e.lineno or 0}"}]

    skip = _docstring_nodes(tree)
    hits: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()

    def add(line: int, kind: str, name: str, text_: str) -> None:
        key = (line, kind, name)
        if key in seen:
            return
        seen.add(key)
        hits.append({"line": line, "kind": kind, "name": name,
                     "text": text_[:160], "site": f"{rel}:{line}"})

    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        s = _literal_text(node)
        if s is None:
            continue
        line = getattr(node, "lineno", 0)

        for prefix in LINUX_ONLY_PATH_PREFIXES:
            if s == prefix.rstrip("/") or s.startswith(prefix):
                add(line, "linux_path", prefix, s)
                break

        stripped = s.strip()
        if not stripped:
            continue
        if not any(c.isspace() for c in stripped):
            prog = _program_of(stripped)
            if prog:
                add(line, "linux_program", prog, s)
            continue
        if _looks_like_a_command(stripped):
            for t in _command_tokens(stripped):
                prog = _program_of(t)
                if prog:
                    add(line, "linux_program", prog, s)
    return hits


def portability(root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Which of the estate's own Python components are locked to this platform, and where.

    This is the honest answer to "make these components run on another platform". No
    cross-compiler is involved: there is no native code here to cross-compile. What stops them
    is written into the Python — absolute paths that exist only here, and programs that ship
    only here — and every one of those is returned with the file and the line it is on.
    """
    base = Path(root) if root is not None else DIST_ROOT
    mine = {p.resolve() for p in _self_excluded()}
    findings: dict[str, list[dict[str, Any]]] = {}
    excluded: list[dict[str, str]] = []
    scanned = 0
    scanned_bytes = 0
    unreadable: list[dict[str, str]] = []

    if not base.is_dir():
        return {"root": str(base), "root_exists": False,
                "scanned": {"files": 0, "bytes": 0, "skipped_dirs": sorted(SKIP_DIRS)},
                "excluded": excluded, "findings": {}, "unreadable": unreadable,
                "totals": {"sites": 0, "components": 0, "by_kind": {}, "files_with_findings": 0},
                "evidence": {"read": f"{base} — absent"}, "measured_at": _now()}

    for p in sorted(base.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            rel = str(p.relative_to(base))
        except ValueError:
            rel = str(p)
        if p.resolve() in mine:
            excluded.append({"path": str(p),
                             "reason": ("this scanner and its tests name the programs they "
                                        "detect, so scanning them reports the detector as the "
                                        "defect")})
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            unreadable.append({"path": str(p), "error": f"{type(e).__name__}: {e}"})
            continue
        scanned += 1
        scanned_bytes += len(text)
        hits = _scan_source(text, rel)
        if not hits:
            continue
        component = rel.split(os.sep)[0]
        for h in hits:
            h["file"] = str(p)
            h["rel"] = rel
        findings.setdefault(component, []).extend(hits)

    by_kind: dict[str, int] = {}
    files_with: set[str] = set()
    sites = 0
    for rows in findings.values():
        for h in rows:
            by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1
            files_with.add(h["rel"])
            sites += 1

    for rows in findings.values():
        rows.sort(key=lambda h: (h["rel"], h["line"]))

    return {
        "root": str(base),
        "root_exists": True,
        "scanned": {"files": scanned, "bytes": scanned_bytes,
                    "skipped_dirs": sorted(SKIP_DIRS)},
        "excluded": excluded,
        "unreadable": unreadable,
        "detectors": {
            "linux_program": sorted(LINUX_ONLY_PROGRAMS),
            "linux_path": list(LINUX_ONLY_PATH_PREFIXES),
            "method": ("python syntax tree; comments are not in the tree and docstrings are "
                       "skipped, so no finding can point at prose"),
            "known_gap": ("a program reached only through a variable holding a computed name "
                          "is not detected; a literal name is, wherever it appears"),
        },
        "findings": dict(sorted(findings.items())),
        "totals": {"sites": sites, "components": len(findings),
                   "files_with_findings": len(files_with), "by_kind": dict(sorted(by_kind.items()))},
        "evidence": {"read": f"{base} recursively for *.py, skipping {sorted(SKIP_DIRS)}",
                     "files_scanned": scanned},
        "measured_at": _now(),
    }
