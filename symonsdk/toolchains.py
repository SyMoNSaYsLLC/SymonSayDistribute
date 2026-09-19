#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What can be built on this machine, with what, and whether it is actually usable.

INSTALLED AND USABLE ARE DIFFERENT, AND ONLY ONE OF THEM BUILDS ANYTHING
A name on PATH proves a directory entry exists. It does not prove the program runs, that its
headers are installed, or that the interpreter a virtualenv points at still exists. Every
answer here is therefore a MEASUREMENT: a resolved path, an argument vector, the exit code it
returned and what it printed. `usable` is derived from that exit code and nothing else.

WHY THE ARGUMENT VECTOR IS PER TOOL
`go --version` exits 2 — the flag does not exist, the correct form is `go version`. A probe
that assumes `--version` reports a working toolchain as broken, which is the precise failure
this module exists to catch, so the argv lives in the registry beside each tool rather than
being assumed. `java -version` is the second case: one dash, and it writes to stderr.

NOTHING HERE WRITES, INSTALLS OR DOWNLOADS
Every probe is a read or a version query. `go` is asked only for `version` and is given
GOTOOLCHAIN=local, because other subcommands fetch. Probes run with cwd `/` so that a project
directory the service happens to be started from cannot change what a toolchain reports or
cause it to resolve a dependency.

FILE CONTENTS ARE NEVER READ OUT OF A VIRTUALENV OR AN SDK TREE
Some of them hold credentials. Distribution counts come from directory names; the interpreter
is proven by running it, not by reading it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Every public callable below carries a route in service.py, so this is empty — declared
# rather than omitted, because `endpoints-current` refuses silence, and an absent dict
# leaves the question unasked rather than answered.
NOT_EXPOSED = {}

PROBE_TIMEOUT_S = 10.0          # a version query that has not answered in ten seconds is hung
SIZE_TIMEOUT_S = 30.0           # a cold walk of a multi-gigabyte tree, bounded
_NEUTRAL_CWD = os.sep           # no build manifest lives at /, so no probe can trigger a fetch

VENV_ROOT_VAR = "SYM_VENV_ROOT"
_DEFAULT_VENV_ROOT = "~/.venvs"

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


class SdkError(RuntimeError):
    """A question this module was asked that it cannot answer from disk."""


# --- the toolchain registry ----------------------------------------------------------------
# name -> (argv tail, what it is, extra absolute paths to try when it is on no PATH entry,
#          environment overrides for the probe)
#
# The argv tail is the whole point of this table. It is read, never guessed.
_TOOLS: dict[str, tuple[tuple[str, ...], str, tuple[str, ...], dict[str, str]]] = {
    "gcc":        (("--version",), "C compiler", (), {}),
    "g++":        (("--version",), "C++ compiler", (), {}),
    "cc":         (("--version",), "C compiler driver", (), {}),
    "make":       (("--version",), "build tool", (), {}),
    "cmake":      (("--version",), "build system generator", (), {}),
    "ninja":      (("--version",), "build tool", (), {}),
    "pkg-config": (("--version",), "build configuration tool", (), {}),
    "git":        (("--version",), "source control", (), {}),
    "rustc":      (("--version",), "Rust compiler", (), {}),
    "cargo":      (("--version",), "Rust build tool", (), {}),
    # `go --version` exits 2: "flag provided but not defined: -version". Measured on this host.
    # GOTOOLCHAIN=local because `auto` lets the go command fetch another toolchain, and nothing
    # in this module is allowed to download.
    "go":         (("version",), "Go toolchain", (), {"GOTOOLCHAIN": "local"}),
    "node":       (("--version",), "JavaScript runtime", (), {}),
    "npm":        (("--version",), "JavaScript package manager", (), {}),
    "python3":    (("--version",), "Python interpreter", (), {}),
    "pip3":       (("--version",), "Python package manager", (), {}),
    # `java -version`: one dash, and it prints to stderr. Both streams are captured.
    "java":       (("-version",), "Java runtime", (), {}),
    "javac":      (("--version",), "Java compiler", (), {}),
    "swift":      (("--version",), "Swift build tool", (), {}),
    "swiftc":     (("--version",), "Swift compiler", (), {}),
    # Not on PATH on this host, but an executable exists in its own tree. That distinction is
    # the difference between "installed" and "usable by name", so it is reported rather than
    # flattened into absent.
    "dotnet":     (("--version",), "dotnet SDK driver", ("~/.dotnet/dotnet",), {}),
    "php":        (("--version",), "PHP interpreter", (), {}),
    "ruby":       (("--version",), "Ruby interpreter", (), {}),
    "perl":       (("--version",), "Perl interpreter", (), {}),
}


def _run(argv: list[str], timeout: float = PROBE_TIMEOUT_S,
         env_extra: dict[str, str] | None = None) -> tuple[int | None, str]:
    """Run an argument vector. Never a shell string: caller text must never reach a shell.

    Returns (exit code, stdout followed by stderr). A code of None means the probe timed out
    or could not be started, and the text says which.
    """
    env = None
    if env_extra:
        env = dict(os.environ)
        env.update(env_extra)
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, cwd=_NEUTRAL_CWD, env=env, check=False)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:g}s"
    except OSError as e:
        return None, f"could not run: {e.strerror or e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _release(text: str) -> str | None:
    m = _VERSION_RE.search(text)
    return m.group(0) if m else None


def _human(n: int | None) -> str | None:
    if n is None:
        return None
    step = 1024.0
    v = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if v < step or unit == "T":
            return f"{v:.0f}{unit}" if unit == "B" else f"{v:.1f}{unit}"
        v /= step
    return f"{v:.1f}T"


def _du_bytes(path: str) -> tuple[int | None, str]:
    """Size on disk, bounded. A tree that will not measure reports null, never a guess."""
    rc, out = _run(["du", "-sb", "--", path], timeout=SIZE_TIMEOUT_S)
    if rc is None:
        return None, f"size not measured: {out}"
    if rc != 0:
        return None, f"size not measured: du exited {rc}"
    head = _first_line(out).split()
    if head and head[0].isdigit():
        return int(head[0]), "du -sb"
    return None, "size not measured: du printed nothing countable"


def _probe_one(name: str) -> dict[str, Any]:
    """One toolchain, measured. `usable` comes from the exit code, never from resolution."""
    argv_tail, kind, fallbacks, env_extra = _TOOLS[name]
    resolved = shutil.which(name)
    on_path = resolved is not None
    fallback_used = None
    if resolved is None:
        for cand in fallbacks:
            c = os.path.expanduser(cand)
            if os.path.isfile(c) and os.access(c, os.X_OK):
                resolved = c
                fallback_used = c
                break

    if resolved is None:
        looked = [name] + [os.path.expanduser(c) for c in fallbacks]
        return {"name": name, "kind": kind, "found": False, "on_path": False, "path": None,
                "real_path": None,
                "argv": [name, *argv_tail], "rc": None, "version": None, "release": None,
                "usable": False,
                "why": f"absent: {name!r} is on no PATH entry" +
                       (f" and at none of {looked[1:]}" if fallbacks else "")}

    # Invoke the path that was RESOLVED, never its realpath. A shim decides which tool it is
    # from argv[0]: realpath turns `rustc` into `rustup`, which then reports rustup's own
    # version, and turns `swift` into a driver that fails outright under the wrong name —
    # a present, working toolchain reported broken, which is the exact failure this module
    # exists to catch. The link target is reported separately, as evidence, not as the target.
    path = resolved
    real = os.path.realpath(resolved)
    argv = [path, *argv_tail]
    rc, out = _run(argv, env_extra=env_extra)
    version = _first_line(out) if rc == 0 else None
    usable = rc == 0 and bool(version)

    if usable:
        why = f"{argv_tail and ' '.join(argv_tail) or 'probe'} exited 0 and named a version"
        if not on_path:
            why = (f"present but NOT on PATH: found at {fallback_used}; "
                   f"anything invoking {name!r} by name will not find it")
    elif rc is None:
        why = f"present at {path} but the version probe failed: {out}"
    else:
        why = (f"present at {path} but `{' '.join([name, *argv_tail])}` exited {rc}: "
               f"{_first_line(out) or 'no output'}")

    return {"name": name, "kind": kind, "found": True, "on_path": on_path, "path": path,
            "real_path": real if real != path else None,
            "argv": argv, "rc": rc, "version": version, "release": _release(version or ""),
            "usable": usable, "why": why}


PIN_ROOT = os.environ.get("SYM_PIN_ROOT", "/mnt/SymonSaySource")

# A toolchain's command name is not always the name the estate pinned it under.
PIN_ALIASES = {"node": "nodejs", "rustc": "rust", "cargo": "rust", "cc": "gcc",
               "g++": "gcc", "swiftc": "swift", "pip3": "python3"}


def _pins() -> dict[str, dict[str, Any]]:
    """Every pin SymonSaySource records, by component name. Read, never assumed (§3.1b-i)."""
    import json
    out: dict[str, dict[str, Any]] = {}
    root = Path(PIN_ROOT)
    if not root.is_dir():
        return out
    for f in root.rglob("*.json"):
        s = str(f)
        if "/.git/" in s or "pin" not in s:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        c = d.get("component")
        if c:
            out[c.lower()] = {**d, "pin_file": s}
    return out


def pinned() -> dict[str, Any]:
    """For every toolchain found here, is its version recorded — and does it agree?

    Rules §3.1b-iii: the estate moves from upstream-dependent toward on-disk, and a program
    invoked without a recorded version is invoked blind. This unit invokes many, so the
    honest answer is per-toolchain and includes the ones with NO pin, because an unrecorded
    build tool is the gap the rule exists to make visible — not something to omit because
    there is nothing to compare.
    """
    pins = _pins()
    found = toolchains().get("tools", [])
    rows, matched, drifted, unrecorded = [], [], [], []
    for tc in found:
        name = tc.get("name")
        if not tc.get("usable"):
            continue
        key = PIN_ALIASES.get(name, name)
        pin = pins.get(key) or pins.get(name)
        observed = tc.get("version")
        if not pin:
            rows.append({"tool": name, "observed": observed, "pinned": None,
                         "state": "UNRECORDED",
                         "why": "no pin in SymonSaySource; this tool can change underneath "
                                "the estate with nothing to notice"})
            unrecorded.append(name)
            continue
        want = str(pin.get("intended_tag_version") or pin.get("intended_revision") or "")
        rel = tc.get("release") or _release(observed or "") or (observed or "")
        agree = bool(want) and want not in ("UNRESOLVED", "?") and rel.startswith(want)
        rows.append({"tool": name, "observed": observed, "release": rel, "pinned": want,
                     "pin_file": pin.get("pin_file"), "component": pin.get("component"),
                     "state": "MATCHES" if agree else
                              ("UNRESOLVED-PIN" if want in ("UNRESOLVED", "?", "") else "DRIFTED"),
                     "why": ("agrees with the recorded pin" if agree else
                             f"pin records {want!r}, this host has {rel!r}")})
        (matched if agree else drifted).append(name)
    return {"pin_root": PIN_ROOT, "pins_available": len(pins),
            "toolchains_checked": len(rows), "toolchains": rows,
            "matched": sorted(matched), "drifted": sorted(drifted),
            "unrecorded": sorted(unrecorded),
            "why": (f"{len(unrecorded)} of {len(rows)} usable toolchains have no pin recorded. "
                    f"Under \u00a73.1b-iii each is a build input that can move without notice.")}


def toolchains() -> dict[str, Any]:
    """Every known toolchain: resolved path, version obtained by running it, and usable or not.

    A tool that is absent is reported by the name that was looked for, so a caller can tell
    "we never checked for it" from "we checked and it is not here".
    """
    tools = [_probe_one(n) for n in sorted(_TOOLS)]
    usable = [t["name"] for t in tools if t["usable"]]
    return {
        "tools": tools,
        "count": len(tools),
        "usable_count": len(usable),
        "usable": usable,
        "absent": [t["name"] for t in tools if not t["found"]],
        "present_but_unusable": [t["name"] for t in tools if t["found"] and not t["usable"]],
        "off_path": [t["name"] for t in tools if t["found"] and not t["on_path"]],
        "searched_path": (os.environ.get("PATH") or "").split(os.pathsep),
        "probe_timeout_s": PROBE_TIMEOUT_S,
    }


# --- virtualenvs ---------------------------------------------------------------------------
def _venv_root() -> Path:
    return Path(os.path.expanduser(os.environ.get(VENV_ROOT_VAR) or _DEFAULT_VENV_ROOT))


def _dist_count(venv: Path) -> int | None:
    """Top-level installed distributions, counted by DIRECTORY NAME.

    Never by reading a METADATA file: a virtualenv may hold credentials and nothing here opens
    anything inside one.
    """
    total = None
    for site in venv.glob("lib*/python*/site-packages"):
        if not site.is_dir():
            continue
        total = total or 0
        try:
            with os.scandir(site) as it:
                total += sum(1 for e in it if e.name.endswith((".dist-info", ".egg-info")))
        except OSError:
            return total
    return total


def _venv_one(d: Path) -> dict[str, Any]:
    cfg = d / "pyvenv.cfg"
    interpreter = None
    for cand in (d / "bin" / "python3", d / "bin" / "python"):
        if os.path.lexists(cand):        # lexists: a DANGLING link is still the declared one
            interpreter = cand
            break

    link_target = None
    if interpreter is not None and os.path.islink(interpreter):
        try:
            link_target = os.readlink(interpreter)
        except OSError:
            link_target = None

    exists = interpreter is not None and os.path.exists(interpreter)
    rc, out, version = None, "", None
    if exists:
        rc, out = _run([str(interpreter), "-c", "import sys; print(sys.version.split()[0])"])
        version = _first_line(out) if rc == 0 else None
    runs = rc == 0 and bool(version)

    if interpreter is None:
        why = f"no interpreter declared: neither bin/python3 nor bin/python exists under {d}"
    elif not exists:
        why = (f"UNUSABLE: the interpreter {interpreter} does not exist" +
               (f" — it is a symlink to {link_target}, which is gone" if link_target else ""))
    elif not runs:
        why = (f"UNUSABLE: {interpreter} exists but did not run "
               f"(exit {rc}): {_first_line(out) or 'no output'}")
    else:
        why = f"interpreter runs and reports {version}"

    return {"name": d.name, "path": str(d), "has_pyvenv_cfg": cfg.is_file(),
            "interpreter": str(interpreter) if interpreter else None,
            "interpreter_link_target": link_target,
            "interpreter_exists": exists, "interpreter_runs": runs,
            "python_version": version, "rc": rc,
            "distributions": _dist_count(d), "usable": bool(exists and runs), "why": why}


def venvs() -> dict[str, Any]:
    """Every python virtualenv under the configured root, and whether each still works.

    The failure this catches: a virtualenv whose interpreter was removed or upgraded out from
    under it. The directory is still there, its packages are still there, and nothing in it
    will run. That is reported explicitly rather than by omission.
    """
    root = _venv_root()
    if not root.is_dir():
        return {"root": str(root), "root_exists": False, "count": 0, "usable_count": 0,
                "unusable": [], "venvs": [],
                "why": f"no such directory: {root} (set {VENV_ROOT_VAR} to point elsewhere)"}

    found = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "pyvenv.cfg").is_file() and not (d / "bin").is_dir():
            continue
        found.append(_venv_one(d))

    bad = [v["name"] for v in found if not v["usable"]]
    return {"root": str(root), "root_exists": True, "count": len(found),
            "usable_count": len(found) - len(bad), "unusable": bad, "venvs": found,
            "why": ("every virtualenv under this root runs" if not bad else
                    f"{len(bad)} of {len(found)} will not run: {', '.join(bad)}")}


# --- SDK trees -----------------------------------------------------------------------------
# name -> (roots, directory whose CHILD NAMES are the versions it offers, what that listing is)
_SDK_TREES: tuple[tuple[str, tuple[str, ...], str | None, str], ...] = (
    ("dotnet", ("~/.dotnet",), "~/.dotnet/sdk", "sdk/ child directory names"),
    ("swift",  ("~/.swiftpm",), "~/.swiftpm/swift-sdks", "swift-sdks/ child directory names"),
    ("rust",   ("~/.cargo", "~/.rustup"), "~/.rustup/toolchains",
     "rustup toolchains/ child directory names"),
    ("go",     ("~/go",), "~/go/pkg/mod/golang.org", "fetched toolchain directory names"),
    ("nuget",  ("~/.nuget",), "~/.nuget/packages", "packages/ child directory names"),
)
_SDK_VERSION_SKIP = {"configuration", "security", "cache", "x"}


def _sdk_one(name: str, roots: tuple[str, ...], vdir: str | None, vfrom: str) -> dict[str, Any]:
    paths = [os.path.expanduser(r) for r in roots]
    present = [p for p in paths if os.path.isdir(p)]
    if not present:
        return {"name": name, "present": False, "root": None, "roots": paths,
                "size_bytes": None, "size_human": None, "size_from": None,
                "versions": [], "versions_from": vfrom,
                "why": f"absent: none of {paths} is a directory"}

    total = 0
    measured = True
    sources = []
    for p in present:
        n, how = _du_bytes(p)
        if n is None:
            measured = False
            sources.append(f"{p}: {how}")
        else:
            total += n
            sources.append(f"{p}: {how}")

    versions: list[str] = []
    vpath = os.path.expanduser(vdir) if vdir else None
    vread = None
    if vpath and os.path.isdir(vpath):
        try:
            with os.scandir(vpath) as it:
                versions = sorted(e.name for e in it
                                  if e.is_dir() and e.name not in _SDK_VERSION_SKIP)
            vread = vpath
        except OSError as e:
            vread = f"{vpath}: unreadable ({e.strerror or e})"

    if versions:
        why = f"{len(versions)} version(s) read from {vread}"
    elif vread:
        why = f"tree is present but {vread} is empty — it offers nothing to build with"
    else:
        why = f"tree is present; {vpath} does not exist, so no versions are readable from disk"

    return {"name": name, "present": True, "root": present[0], "roots": paths,
            "present_roots": present,
            "size_bytes": total if measured else None,
            "size_human": _human(total) if measured else None,
            "size_from": "; ".join(sources),
            "versions": versions, "versions_from": vfrom, "versions_read_at": vread,
            "why": why}


def sdks() -> dict[str, Any]:
    """The non-python SDK trees: present or not, where, how large, and what versions they hold.

    Versions are read off disk as directory names. Where a tree keeps nothing readable, that is
    said rather than filled in from the command's own report — a tree and a command on PATH are
    two different facts and this function answers only the first.
    """
    trees = [_sdk_one(*s) for s in _SDK_TREES]
    total = sum(t["size_bytes"] or 0 for t in trees)
    # A tree whose size timed out contributes nothing to the total. Saying so is the difference
    # between a total and a floor: without the flag an under-report reads as a measurement.
    unmeasured = [t["name"] for t in trees if t["present"] and t["size_bytes"] is None]
    return {"sdks": trees, "count": len(trees),
            "present": [t["name"] for t in trees if t["present"]],
            "absent": [t["name"] for t in trees if not t["present"]],
            "total_bytes": total, "total_human": _human(total),
            "total_measured": not unmeasured, "unmeasured": unmeasured,
            "size_units": "apparent bytes (du -sb), not block usage (du -sh)"}


# --- source trees --------------------------------------------------------------------------
_SOURCE_ROOTS = ("~/src", "~/Desktop")
# A directory is a source tree when it carries a build manifest. A bare git checkout is not:
# every stakeholder folder on this Desktop is a git repository, and reporting those as things
# to build from would bury the trees that actually are.
_MANIFESTS: tuple[tuple[str, str], ...] = (
    ("Cargo.toml", "rust"), ("go.mod", "go"), ("pyproject.toml", "python"),
    ("setup.py", "python"), ("CMakeLists.txt", "cmake"), ("package.json", "node"),
    ("meson.build", "meson"), ("Makefile", "c"), ("pom.xml", "java"),
    ("build.gradle", "java"), ("Package.swift", "swift"),
)


def _source_one(d: Path) -> dict[str, Any] | None:
    manifests = [(m, eco) for m, eco in _MANIFESTS if (d / m).is_file()]
    if not manifests:
        return None
    return {"name": d.name, "path": str(d), "git": (d / ".git").exists(),
            "manifests": [m for m, _ in manifests],
            "builds_with": sorted({eco for _, eco in manifests}),
            "why": f"carries {', '.join(m for m, _ in manifests)}"}


def sources() -> dict[str, Any]:
    """Source trees available to build from, one level under each known root.

    Path and git status per the brief, plus the build manifest that made it count — because
    "this is a source tree" and "this is a source tree I know how to build" are different
    claims and only the second is useful to a caller choosing what to do next.
    """
    roots = [os.path.expanduser(r) for r in _SOURCE_ROOTS]
    found: list[dict[str, Any]] = []
    scanned, missing = [], []
    for r in roots:
        p = Path(r)
        if not p.is_dir():
            missing.append(r)
            continue
        scanned.append(r)
        for d in sorted(p.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            one = _source_one(d)
            if one:
                found.append(one)
    return {"roots": roots, "scanned": scanned, "missing_roots": missing,
            "count": len(found), "git_count": sum(1 for s in found if s["git"]),
            "sources": found,
            "why": (f"{len(found)} source tree(s) under {', '.join(scanned) or 'no root'}"
                    if scanned else "none of the source roots exists")}


# --- can this host build X -------------------------------------------------------------------
# Each precondition is checked and REPORTED SEPARATELY, so a "no" names which part is missing.
#   tool      a toolchain that must run
#   any_tool  one of several is enough
#   on_path   the tool must be reachable BY NAME, not merely present somewhere
#   path      a file or directory that must exist (headers)
#   sdk       an SDK tree that must be present
_ECOSYSTEMS: dict[str, tuple[dict[str, Any], ...]] = {
    "c": ({"kind": "compiler", "tool": "gcc"},
          {"kind": "build tool", "any_tool": ("make", "ninja")},
          {"kind": "headers", "path": "/usr/include/stdio.h"}),
    "c++": ({"kind": "compiler", "tool": "g++"},
            {"kind": "build tool", "any_tool": ("make", "ninja")},
            {"kind": "headers", "path": "/usr/include/c++"}),
    "cmake": ({"kind": "build system generator", "tool": "cmake"},
              {"kind": "generator backend", "any_tool": ("ninja", "make")},
              {"kind": "compiler", "any_tool": ("cc", "gcc")}),
    "rust": ({"kind": "compiler", "tool": "rustc"},
             {"kind": "build tool", "tool": "cargo"},
             {"kind": "linker driver", "any_tool": ("cc", "gcc")}),
    "go": ({"kind": "compiler", "tool": "go"},),
    "python": ({"kind": "interpreter", "tool": "python3"},
               {"kind": "package manager", "tool": "pip3"},
               {"kind": "headers", "glob": "/usr/include/python3*/Python.h",
                "name": "Python.h (needed for native extensions)"}),
    "node": ({"kind": "runtime", "tool": "node"},
             {"kind": "package manager", "tool": "npm"}),
    "java": ({"kind": "compiler", "tool": "javac"},
             {"kind": "runtime", "tool": "java"}),
    "dotnet": ({"kind": "command", "tool": "dotnet", "on_path": True},
               {"kind": "sdk tree", "sdk": "dotnet"}),
    "swift": ({"kind": "compiler", "tool": "swiftc"},
              {"kind": "build tool", "tool": "swift"}),
    "php": ({"kind": "interpreter", "tool": "php"},),
    "ruby": ({"kind": "interpreter", "tool": "ruby"},),
}
_ALIASES = {"cpp": "c++", "cxx": "c++", "golang": "go", "py": "python", "python3": "python",
            "js": "node", "javascript": "node", "nodejs": "node", "typescript": "node",
            "rustlang": "rust", "jvm": "java", "csharp": "dotnet", "net": "dotnet"}


def _check(spec: dict[str, Any]) -> dict[str, Any]:
    kind = spec["kind"]

    if "tool" in spec:
        name = spec["tool"]
        t = _probe_one(name)
        needs_path = bool(spec.get("on_path"))
        met = t["usable"] and (t["on_path"] or not needs_path)
        if met:
            ev = f"{t['version']} at {t['path']}"
        elif needs_path and t["usable"]:
            ev = f"present at {t['path']} but not on PATH, so `{name}` does not resolve"
        else:
            ev = t["why"]
        return {"kind": kind, "name": spec.get("name", name), "met": met, "evidence": ev}

    if "any_tool" in spec:
        names = spec["any_tool"]
        probes = [_probe_one(n) for n in names]
        ok = [p for p in probes if p["usable"]]
        label = spec.get("name", " or ".join(names))
        if ok:
            return {"kind": kind, "name": label, "met": True,
                    "evidence": f"{ok[0]['version']} at {ok[0]['path']}"}
        return {"kind": kind, "name": label, "met": False,
                "evidence": "; ".join(f"{p['name']}: {p['why']}" for p in probes)}

    if "path" in spec:
        p = spec["path"]
        met = os.path.exists(p)
        return {"kind": kind, "name": spec.get("name", p), "met": met,
                "evidence": f"{p} exists" if met else f"absent: {p} does not exist"}

    if "glob" in spec:
        g = spec["glob"]
        hits = sorted(Path("/").glob(g.lstrip("/")))
        return {"kind": kind, "name": spec.get("name", g), "met": bool(hits),
                "evidence": str(hits[0]) if hits else f"absent: nothing matches {g}"}

    if "sdk" in spec:
        want = spec["sdk"]
        tree = next((t for t in sdks()["sdks"] if t["name"] == want), None)
        met = bool(tree and tree["present"] and tree["versions"])
        label = spec.get("name", f"{want} SDK tree")
        if tree is None:
            return {"kind": kind, "name": label, "met": False, "evidence": "unknown SDK tree"}
        return {"kind": kind, "name": label, "met": met,
                "evidence": (f"{tree['root']} offers {', '.join(tree['versions'])}"
                             if met else tree["why"])}

    raise SdkError(f"malformed precondition: {spec!r}")


def can_build(ecosystem: str) -> dict[str, Any]:
    """Can this host build the named language or ecosystem right now.

    Every precondition is named and answered separately, so a "no" says WHICH part is missing —
    a compiler, a build tool, a package manager, headers or an SDK tree — rather than leaving
    the caller to find out by starting a build and watching it fail.
    """
    key = _ALIASES.get((ecosystem or "").strip().lower(), (ecosystem or "").strip().lower())
    if key not in _ECOSYSTEMS:
        raise SdkError(f"unknown ecosystem {ecosystem!r}; known: "
                       f"{', '.join(sorted(_ECOSYSTEMS))}")

    checks = [_check(s) for s in _ECOSYSTEMS[key]]
    missing = [c["name"] for c in checks if not c["met"]]
    ok = not missing
    return {
        "ecosystem": key, "asked": ecosystem, "can_build": ok,
        "preconditions": checks, "missing": missing,
        "known_ecosystems": sorted(_ECOSYSTEMS),
        "why": (f"every precondition is met ({len(checks)} checked)" if ok else
                f"cannot build {key}: missing {', '.join(missing)}"),
    }
