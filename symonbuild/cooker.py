# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonbuild — the estate's build capability, reported rather than exercised.

The estate is founded on the OpenEmbedded layering system and nothing owned it. Where the task
executor lives, which copy is the one the pins name, what the build configurations declare,
whether the layers they name exist, and whether a build could start at all were four questions
with no answer on disk and four different answers in documents.

THIS NEVER STARTS A COOKER
Reporting and building are different jobs and one of them is destructive. R2 forbids editing a
recipe while a cooker is live, so `cooker_live()` has to be a question anything can ask at any
moment — including a process that is about to edit a recipe. A module that could also launch a
cooker could not be trusted to answer it.

HOW THE PROCESS TABLE IS READ
`cooker_live()` iterates /proc and reads each cmdline, and it matches on the EXECUTABLE — the
basename of argv[0], or of argv[1] behind an interpreter — never on a substring of the joined
command line. Rules section 3.3 forbids the two pattern-matching process utilities outright
because their pattern matches the agent's own shell and has ended sessions here. That failure
is not theoretical for this module in particular: a substring probe written while developing
this file returned exactly one hit, and the hit was the shell running the probe, because the
probe's own text contained the word it was searching for. A test asserts neither utility is
named anywhere in `cooker_live`.

EVERY ANSWER CARRIES ITS EVIDENCE
Each public function returns a dict with an `evidence` key naming the paths read, the commands
run as an argv list, and their exit codes. A claim in this module that cannot name where it
came from is a defect.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Every public callable here is reachable over HTTP. Nothing is deliberately unexposed.
NOT_EXPOSED = {}

# The five sanctioned locations under /mnt. Everything else is the sandbox: Garrett's rule is
# that things graduate OFF the sandbox into /mnt when they enter build -> wire -> commission ->
# ship, so where a copy sits is a statement about how far along it is.
MNT_SANCTIONED = (
    "/mnt/SymonSayDistribute",
    "/mnt/SymonSaySource",
    "/mnt/SymonSayOSS",
    "/mnt/SymonSayOpen",
    "/mnt/models",
)

# Where pins live. A pin is what makes one copy of an upstream tree the canonical one; without
# it "which bitbake" has no answer but a preference.
PIN_TREE = Path("/mnt/SymonSaySource")

# The task executor and its helper processes. A cooker is live if any of these is running.
COOKER_PROGRAMS = frozenset({
    "bitbake",
    "bitbake-server",
    "bitbake-worker",
    "bitbake-hashserv",
    "bitbake-prserv",
    "bitbake-cookerdaemon",
})

# The OE tooling a build needs beyond the executor itself. Absent ones are named, never omitted.
OE_TOOLS = ("devtool", "bitbake-layers", "oe-init-build-env", "recipetool")

# Directories that are never worth descending into: history, caches, build output and vendored
# dependency trees. `downloads` and `sstate-cache` alone hold tens of thousands of entries and
# contain no configuration, no layer and no executor.
#
# `work` IS NOT PRUNED, and that is deliberate. The executor's own work directory is `tmp/work`,
# which `tmp` already covers, so pruning the name buys nothing there — while in this estate
# `work/` is a portal holding first-party recipes. Pruning it hid fifteen layers and a live build
# directory, and the counts this module reported were low without anything looking wrong.
# `work-shared` stays pruned: that one really is build output.
PRUNE = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv", "site-packages",
    "sstate-cache", "downloads", "lost+found", ".cache", ".mypy_cache",
    ".pytest_cache", "tmp", "tmp-glibc", "work-shared", ".Trash-1000",
})

_AUGUST = re.compile(r"2026-?08")
_VERSION = re.compile(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", re.M)
_COLLECTION = re.compile(r"^\s*BBFILE_COLLECTIONS\s*[+:?]*=\s*['\"]([^'\"]*)['\"]", re.M)


class BuildError(Exception):
    """Something this module was asked to read is not there, or is not what it claims."""


# --- roots -----------------------------------------------------------------------------------

def _default_roots() -> list[str]:
    """The places a build stack has ever been put on this host.

    Built from `~` rather than a literal home, and overridable in full, because a component that
    can only look in one operator's home answers a narrower question than the one being asked.
    """
    home = Path(os.path.expanduser("~"))
    return [str(p) for p in (
        *(Path(m) for m in MNT_SANCTIONED),
        home / "SymonSaysLLC" / "Projects",
        home / "symoneural-staging",
        home / "symonsaylearn",
    )]


def _roots() -> list[str]:
    raw = (os.environ.get("SYM_BUILD_ROOTS") or "").strip()
    roots = [r for r in raw.split(os.pathsep) if r.strip()] if raw else _default_roots()
    return [r for r in roots if os.path.isdir(r)]


def _depth() -> int:
    try:
        return max(1, int(os.environ.get("SYM_BUILD_DEPTH", "6")))
    except ValueError:
        return 6


def _walk(root: str, maxdepth: int):
    """os.walk with a depth ceiling and a prune list, because the sandbox is not small.

    An unbounded walk of the sandbox took longer than a test is allowed to take, and a capability
    report nobody waits for is a capability report nobody reads.
    """
    root = os.path.abspath(root)
    base = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=None,
                                                followlinks=False):
        depth = dirpath.rstrip(os.sep).count(os.sep) - base
        if depth >= maxdepth:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d not in PRUNE]
        yield dirpath, dirnames, filenames


# --- disk identity ------------------------------------------------------------------------

_DEVICE_CACHE: dict[str, dict[str, Any]] = {}


def _device(path: str) -> dict[str, Any]:
    """Which block device a path sits on. Read, never recalled — rules section 3.1c.

    argv list, never a shell string, always a timeout. The exit code is recorded beside the
    answer so a reader can tell "sda1" from "we could not find out".
    """
    key = os.path.abspath(path)
    if key in _DEVICE_CACHE:
        return _DEVICE_CACHE[key]
    argv = ["df", "--output=source", key]
    out: dict[str, Any] = {"device": None, "argv": argv, "rc": None}
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
        out["rc"] = p.returncode
        if p.returncode == 0:
            lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
            if len(lines) >= 2:
                out["device"] = lines[-1]
    except (OSError, subprocess.SubprocessError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
    _DEVICE_CACHE[key] = out
    return out


def _placement(path: str) -> str:
    """sanctioned, acquired-upstream or sandbox. Where a thing sits says how far along it is."""
    ap = os.path.abspath(path)
    for m in MNT_SANCTIONED:
        if ap == m or ap.startswith(m + os.sep):
            return "sanctioned-mnt"
    if f"{os.sep}upstream{os.sep}" in ap:
        return "acquired-upstream"
    return "sandbox"


def _git_head(start: str) -> dict[str, Any]:
    """The revision of the tree itself, so a version string can be checked against a pin.

    Two files can carry the same `__version__` and come from different commits; the wrapper is
    byte-identical across two of the copies on this host while their trees are not.

    `git -C <dir> rev-parse HEAD` walks UP to the nearest repository, so a tree vendored inside
    another repository answers with its host's revision. That is somebody else's commit wearing
    this tree's name, and comparing it to a pin would be comparing the wrong thing. The toplevel
    is read first and the revision is reported only when the tree IS the repository.
    """
    out: dict[str, Any] = {"head": None, "toplevel": None, "rc": None,
                           "argv": ["git", "-C", start, "rev-parse", "--show-toplevel", "HEAD"]}
    try:
        p = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel", "HEAD"],
                           capture_output=True, text=True, timeout=20, check=False)
        out["rc"] = p.returncode
        if p.returncode != 0:
            out["why"] = "not inside a git repository"
            return out
        lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
        if len(lines) < 2:
            return out
        top, head = lines[0], lines[1]
        out["toplevel"] = top
        if os.path.realpath(top) == os.path.realpath(start):
            out["head"] = head
        else:
            out["why"] = (f"vendored inside {top}; that repository's HEAD is not this tree's "
                          f"revision, so none is reported")
    except (OSError, subprocess.SubprocessError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# --- pins -------------------------------------------------------------------------------------

def _pins() -> dict[str, dict[str, Any]]:
    """Every acquisition pin in the source tree, keyed by component name.

    A pin is the only thing on this host that can say which copy of an upstream tree is the one
    the estate builds from. Without it, several copies is a fact with no verdict attached.
    """
    found: dict[str, dict[str, Any]] = {}
    if not PIN_TREE.is_dir():
        return found
    for branch in sorted(PIN_TREE.iterdir()):
        d = branch / "pins"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                rec = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            name = str(rec.get("component") or f.stem)
            rec["_pin_path"] = str(f)
            found.setdefault(name, rec)
    return found


# --- the executor -------------------------------------------------------------------------

def bitbakes() -> dict[str, Any]:
    """Every task executor on this host: path, version read from the file, device, placement.

    THE FINDING IS THE SPREAD, NOT THE LIST. Several copies at several versions with nothing
    naming one of them is the same shape as the release gate that existed at four paths with
    three of them stale — each copy individually fine, the set of them unusable. So the version
    spread and the pin comparison are top-level fields here, not something a reader has to
    derive by scanning a table.

    The version is read out of the file. A version that is assumed is a version that is wrong
    the first time somebody moves a tree.
    """
    roots, maxdepth = _roots(), _depth()
    pin = _pins().get("bitbake") or {}
    pinned_rev = str(pin.get("intended_revision") or "")

    seen: dict[str, dict[str, Any]] = {}
    for root in roots:
        for dirpath, _dirs, files in _walk(root, maxdepth):
            if "bitbake" not in files:
                continue
            p = os.path.join(dirpath, "bitbake")
            if not os.path.isfile(p) or os.path.islink(p):
                continue
            try:
                head = Path(p).read_text(errors="replace")[:8192]
            except OSError:
                continue
            m = _VERSION.search(head)
            if not m:
                continue                      # a directory or a namesake, not the executor
            real = os.path.realpath(p)
            if real in seen:
                continue
            tree = os.path.dirname(os.path.dirname(p))      # .../bitbake/bin/bitbake -> .../bitbake
            git = _git_head(tree)
            rev = git.get("head")
            seen[real] = {
                "path": p,
                "version": m.group(1),
                "device": _device(p)["device"],
                "device_evidence": _device(p),
                "on_path": False,
                "placement": _placement(p),
                "tree": tree,
                "revision": rev,
                "revision_evidence": git,
                "matches_pin": bool(pinned_rev) and rev == pinned_rev,
            }

    on_path = shutil.which("bitbake")
    if on_path:
        real = os.path.realpath(on_path)
        if real in seen:
            seen[real]["on_path"] = True
        else:
            seen[real] = {"path": on_path, "version": None, "device": _device(on_path)["device"],
                          "device_evidence": _device(on_path), "on_path": True,
                          "placement": _placement(on_path), "tree": None, "revision": None,
                          "revision_evidence": {}, "matches_pin": False}

    found = sorted(seen.values(), key=lambda r: r["path"])
    versions = sorted({r["version"] for r in found if r["version"]})
    canonical = [r["path"] for r in found if r["matches_pin"]]
    devices = sorted({r["device"] for r in found if r["device"]})

    if not found:
        spread = "no task executor found under any searched root"
    elif len(versions) > 1:
        spread = (f"{len(found)} copies at {len(versions)} versions ({', '.join(versions)}) "
                  f"across {len(devices)} device(s) — no copy is canonical by version alone")
    else:
        spread = f"{len(found)} copies, all at {versions[0] if versions else 'an unread version'}"

    return {
        "found": found,
        "count": len(found),
        "versions": versions,
        "version_spread": spread,
        "diverges": len(versions) > 1,
        "devices": devices,
        "on_path": on_path,
        "pin": {"path": pin.get("_pin_path"), "revision": pinned_rev or None,
                "tag_version": pin.get("intended_tag_version")},
        "canonical": canonical,
        "canonical_note": (
            "the pin resolves the spread: exactly one copy is at the pinned revision"
            if len(canonical) == 1 else
            "no copy is at the pinned revision" if pinned_rev and not canonical else
            f"{len(canonical)} copies are at the pinned revision" if canonical else
            "no pin for the task executor was found, so nothing on disk names a canonical copy"),
        "evidence": {"roots": roots, "maxdepth": maxdepth,
                     "version_read_from": "the __version__ assignment in each file",
                     "which": {"call": "shutil.which('bitbake')", "result": on_path},
                     "pin_read": pin.get("_pin_path")},
    }


# --- the rest of the tooling --------------------------------------------------------------

def devtools() -> dict[str, Any]:
    """The OE tooling beside the executor. An absent tool is named, never dropped from the list.

    A report that lists only what it found cannot be told apart from a report that found
    everything, which is how a missing tool survives three status updates.
    """
    roots, maxdepth = _roots(), _depth()
    hits: dict[str, list[str]] = {t: [] for t in OE_TOOLS}
    wanted = set(OE_TOOLS)
    for root in roots:
        for dirpath, _dirs, files in _walk(root, maxdepth):
            for name in wanted.intersection(files):
                p = os.path.join(dirpath, name)
                if os.path.isfile(p):
                    hits[name].append(p)

    tools = []
    for name in OE_TOOLS:
        paths = sorted(set(hits[name]))
        on_path = shutil.which(name)
        tools.append({
            "tool": name,
            "found": bool(paths) or bool(on_path),
            "paths": paths,
            "count": len(paths),
            "on_path": on_path,
            "placements": sorted({_placement(p) for p in paths}),
        })
    missing = [t["tool"] for t in tools if not t["found"]]
    return {
        "tools": tools,
        "missing": missing,
        "complete": not missing,
        "why": ("every tool in the set was found" if not missing
                else f"absent: {', '.join(missing)}"),
        "evidence": {"roots": roots, "maxdepth": maxdepth, "looked_for": list(OE_TOOLS)},
    }


# --- build configuration -----------------------------------------------------------------

def _bblayers(text: str) -> list[str]:
    """Pull the BBLAYERS entries out of a bblayers.conf without running the parser that owns it.

    Only the literal text is read. An entry holding a variable reference is returned as written
    and reported as unresolved, because expanding it needs the executor and the executor is the
    thing this component is reporting on.
    """
    out: list[str] = []
    for m in re.finditer(r"^\s*BBLAYERS\s*[+:?]*=\s*\"", text, re.M):
        i = m.end()
        j = text.find('"', i)
        if j < 0:
            continue
        body = text[i:j].replace("\\\n", " ")
        out.extend(tok for tok in body.split() if tok and tok != "\\")
    return out


def configs() -> dict[str, Any]:
    """Every build configuration on this host, and for each declared layer whether it is there.

    A CONFIGURATION WHOSE LAYERS ARE MISSING IS THE INTERESTING CASE. It is also the quiet one:
    the directory exists, the file parses, the paths look plausible, and nothing fails until a
    build is started. So `broken` is a top-level list here and a config with a missing layer is
    named in it, rather than being one row among many in a list of paths.

    An entry that still holds a variable reference is reported `exists: null`, not `false`. A
    guess recorded as a measurement is worse than a gap: it puts a real finding and an unread
    one side by side under the same word.
    """
    roots, maxdepth = _roots(), _depth()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for root in roots:
        for dirpath, _dirs, files in _walk(root, maxdepth):
            if "bblayers.conf" not in files or os.path.basename(dirpath) != "conf":
                continue
            real = os.path.realpath(dirpath)
            if real in seen:
                continue
            seen.add(real)
            f = os.path.join(dirpath, "bblayers.conf")
            try:
                text = Path(f).read_text(errors="replace")
            except OSError as e:
                out.append({"conf_dir": dirpath, "bblayers": f, "error": str(e), "layers": []})
                continue

            layers = []
            for entry in _bblayers(text):
                if "${" in entry or "$(" in entry:
                    layers.append({"declared": entry, "exists": None,
                                   "why": "unresolved variable reference; expanding it needs "
                                          "the executor, which is what this reports on"})
                else:
                    layers.append({"declared": entry, "exists": os.path.isdir(entry),
                                   "why": "" if os.path.isdir(entry) else "no such directory"})

            missing = [ly["declared"] for ly in layers if ly["exists"] is False]
            unresolved = [ly["declared"] for ly in layers if ly["exists"] is None]
            local = os.path.join(dirpath, "local.conf")
            august = bool(_AUGUST.search(dirpath))
            out.append({
                "conf_dir": dirpath,
                "bblayers": f,
                "local_conf": local if os.path.isfile(local) else None,
                "device": _device(dirpath)["device"],
                "placement": _placement(dirpath),
                "layers": layers,
                "declared": len(layers),
                "missing": missing,
                "unresolved": unresolved,
                "all_layers_present": bool(layers) and not missing and not unresolved,
                "august_dated": august,
                "why": ("declares no layers at all" if not layers else
                        f"{len(missing)} declared layer(s) do not exist on disk" if missing else
                        f"{len(unresolved)} entr(ies) unresolved without the executor"
                        if unresolved else "every declared layer exists"),
            })

    out.sort(key=lambda c: c["conf_dir"])
    broken = [c for c in out if c.get("missing")]
    usable = [c for c in out if c.get("all_layers_present")]
    return {
        "configs": out,
        "count": len(out),
        "broken": [{"conf_dir": c["conf_dir"], "missing": c["missing"]} for c in broken],
        "usable": [c["conf_dir"] for c in usable],
        "why": ("no build configuration was found" if not out else
                f"{len(usable)} of {len(out)} configuration(s) have every declared layer on disk"),
        "evidence": {"roots": roots, "maxdepth": maxdepth,
                     "read": [c["bblayers"] for c in out]},
    }


# --- layers ------------------------------------------------------------------------------------

def layers() -> dict[str, Any]:
    """OE layers on disk: path, whether it declares itself, the name it declares, and its state.

    ACQUIRED means the source tree it belongs to is tracked in the source tree with a pin, so the
    same bytes can be fetched again and the choice defended. PRESENT means it is merely here —
    staging, a cache, the sandbox — which is not a criticism and is not a provenance either.
    """
    roots, maxdepth = _roots(), _depth()
    pins = _pins()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for root in roots:
        for dirpath, dirs, _files in _walk(root, maxdepth):
            if "conf" not in dirs:
                continue
            lc = os.path.join(dirpath, "conf", "layer.conf")
            if not os.path.isfile(lc):
                continue
            real = os.path.realpath(dirpath)
            if real in seen:
                continue
            seen.add(real)
            try:
                text = Path(lc).read_text(errors="replace")
            except OSError:
                text = ""
            m = _COLLECTION.search(text)

            pin = None
            probe = Path(dirpath)
            for anc in (probe, *probe.parents):
                rec = pins.get(anc.name)
                if rec:
                    pin = rec
                    break
            out.append({
                "path": dirpath,
                "layer_conf": lc,
                "declares_layer_conf": True,
                "name": (m.group(1).strip() or None) if m else None,
                "state": "ACQUIRED" if pin else "PRESENT",
                "pin": (pin or {}).get("_pin_path"),
                "pinned_revision": (pin or {}).get("intended_revision"),
                "placement": _placement(dirpath),
                "august_dated": bool(_AUGUST.search(dirpath)),
            })

    out.sort(key=lambda r: r["path"])
    acquired = [r for r in out if r["state"] == "ACQUIRED"]
    return {
        "layers": out,
        "count": len(out),
        "acquired": len(acquired),
        "present": len(out) - len(acquired),
        "unnamed": [r["path"] for r in out if not r["name"]],
        "why": (f"{len(out)} layer(s) on disk, {len(acquired)} tracked with a pin"
                if out else "no layer declaring conf/layer.conf was found"),
        "evidence": {"roots": roots, "maxdepth": maxdepth, "pin_tree": str(PIN_TREE),
                     "pins_read": len(pins)},
    }


# --- is a cooker live ----------------------------------------------------------------------

def _self_chain() -> set[int]:
    """This process and every ancestor of it, so the probe cannot find itself."""
    chain: set[int] = set()
    pid = os.getpid()
    for _ in range(64):
        if pid <= 0 or pid in chain:
            break
        chain.add(pid)
        try:
            status = Path(f"/proc/{pid}/status").read_text()
        except OSError:
            break
        parent = 0
        for line in status.splitlines():
            if line.startswith("PPid:"):
                parent = int(line.split()[1])
                break
        pid = parent
    return chain


def _program_names(argv: list[str], exe: str | None) -> list[str]:
    """What is actually EXECUTING, not what happens to appear in the command line.

    Three places the name can be: the resolved executable, argv[0], and — behind an
    interpreter — argv[1]. The task executor is a script, so it arrives as the third form as
    often as the second.
    """
    names: list[str] = []
    if exe:
        names.append(os.path.basename(exe))
    if argv:
        names.append(os.path.basename(argv[0]))
        first = os.path.basename(argv[0])
        if (first.startswith("python") or first in ("env", "sh", "bash")) and len(argv) > 1:
            names.append(os.path.basename(argv[1]))
    return [n for n in names if n]


def cooker_live() -> dict[str, Any]:
    """Is a task executor running right now? R2 rests on this being right.

    The process table is read one entry at a time out of /proc, and the match is on the
    executable — the basename of the resolved exe, of argv[0], or of argv[1] behind an
    interpreter. It is never a substring test over the joined command line: such a test matches
    the shell that is running the test, and this session's own shell was the single hit the
    first time one was tried here.

    This process and every ancestor of it are excluded by pid before any matching happens, so a
    caller cannot be reported as the thing it is asking about.
    """
    mine = _self_chain()
    procs: list[dict[str, Any]] = []
    scanned = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in mine:
            continue
        scanned += 1
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            continue
        argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        if not argv:
            continue
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe = None
        names = _program_names(argv, exe)
        hit = [n for n in names if n in COOKER_PROGRAMS]
        if not hit:
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = None
        procs.append({"pid": pid, "program": hit[0], "exe": exe, "cwd": cwd,
                      "argv": argv[:8]})

    procs.sort(key=lambda p: p["pid"])
    return {
        "live": bool(procs),
        "processes": procs,
        "count": len(procs),
        "why": (f"{len(procs)} executor process(es) running: "
                + ", ".join(f"{p['program']} pid {p['pid']}" for p in procs)
                if procs else "no executor process is running"),
        "safe_to_edit_recipes": not procs,
        "evidence": {
            "method": "iterate /proc, read /proc/<pid>/cmdline, match the executable basename",
            "matched_against": sorted(COOKER_PROGRAMS),
            "entries_examined": scanned,
            "excluded_pids": sorted(mine),
        },
    }


# --- could a build run ---------------------------------------------------------------------

def buildable() -> dict[str, Any]:
    """Could a build run right now? Four preconditions, each with its own evidence.

    A false answer here must say what is in the way. `blocked_by` is non-empty whenever
    `buildable` is false, because "no" with nothing named is a mood rather than a finding.
    """
    bb = bitbakes()
    dv = devtools()
    cf = configs()

    build_dirs = [c["conf_dir"] for c in cf["configs"] if c.get("local_conf")]

    pre: list[dict[str, Any]] = [
        {
            "name": "bitbake_on_path_or_resolvable",
            "met": bool(bb["on_path"]) or len(bb["canonical"]) == 1,
            "evidence": {
                "on_path": bb["on_path"],
                "copies": bb["count"],
                "versions": bb["versions"],
                "pin": bb["pin"],
                "canonical": bb["canonical"],
                "note": bb["canonical_note"],
            },
        },
        {
            "name": "config_with_every_layer_present",
            "met": bool(cf["usable"]),
            "evidence": {
                "configs": cf["count"],
                "usable": cf["usable"],
                "broken": cf["broken"],
            },
        },
        {
            "name": "build_directory",
            "met": bool(build_dirs),
            "evidence": {"directories": build_dirs, "count": len(build_dirs),
                         "test": "a conf directory holding both bblayers.conf and local.conf"},
        },
        {
            "name": "oe_tooling",
            "met": dv["complete"],
            "evidence": {"missing": dv["missing"],
                         "found": {t["tool"]: t["count"] for t in dv["tools"]}},
        },
    ]

    blocked_by = [p["name"] for p in pre if not p["met"]]
    ok = not blocked_by
    if not ok and not blocked_by:                       # belt and braces: false must name a cause
        raise BuildError("buildable() returned false with nothing blocking it")
    return {
        "buildable": ok,
        "preconditions": pre,
        "blocked_by": blocked_by,
        "why": ("every precondition is met; a build could be started"
                if ok else "blocked on: " + ", ".join(blocked_by)),
        "evidence": {"roots": _roots(), "maxdepth": _depth(),
                     "note": "this reports capability and never starts a cooker; ask "
                             "cooker_live() whether one is already running"},
    }
