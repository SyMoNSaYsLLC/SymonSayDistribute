# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The host kernel, and whether a kernel module can be built for it.

THE FAILURE THIS UNIT EXISTS TO CATCH
-------------------------------------
A kernel upgrade lands. The out-of-tree driver was built against the kernel that is running,
and nothing rebuilt it for the new one. Nothing looks wrong: the old modules are on disk, the
driver is loaded, every probe answers, every service is up. The card comes up with no driver at
the next boot, and that is the first moment anybody finds out.

`coverage()` asks that question before the reboot instead of after it: for every kernel that
has a module tree, is the module actually built and placed for it.

NOTHING HERE CHANGES KERNEL STATE
---------------------------------
This reads. It never builds, installs, loads or unloads anything. `coverage()` reports the
argument vector an operator would run to close a gap, as data — reporting a command and running
one are different acts, and only one of them belongs in a status unit. A test walks every
subprocess call in this file and fails on a state-changing verb.

WHERE THE TOOLS ARE, AND WHY THAT IS NOT A DETAIL
-------------------------------------------------
The module manager is installed at `/usr/sbin`, which is not on an ordinary user's PATH on this
host — `command -v dkms` exits 1 while `/usr/sbin/dkms --version` prints a version. A unit that
asks PATH would report it absent on a host where it is installed and working, and an absent
answer that is really a lookup failure is the most expensive kind of wrong: it reads as
"nothing to report". So the binary is located by looking, and the PATH answer is reported
beside it as its own fact.

The loaded-module table is read from `/proc/modules` rather than by running a formatter over
it. That is the same data by the same kernel, with one less program on a PATH that has already
proved unreliable here.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

MODULES_ROOT = "/lib/modules"
HEADERS_ROOT = "/usr/src"
PROC_MODULES = "/proc/modules"
PROC_VERSION = "/proc/version"

# Where a module manager places what it built, relative to a kernel's module directory. This
# is the subtree the recurring failure lives in: the in-tree modules ship with the kernel and
# are never the thing that goes missing.
OUT_OF_TREE = "updates/dkms"

# Looked at in order, then PATH as the last resort rather than the first.
DKMS_CANDIDATES = ("/usr/sbin/dkms", "/sbin/dkms", "/usr/bin/dkms",
                   "/usr/local/sbin/dkms", "/usr/local/bin/dkms")

MODULE_SUFFIXES = (".ko", ".ko.xz", ".ko.zst", ".ko.gz", ".ko.bz2")

# States a module manager reports for a build that is actually placed under a kernel.
PLACED_STATES = ("installed", "built")


# Every public callable here is either routed in service.py or named below with the reason it
# is not. `endpoints-current` refuses silence: a capability is exposed, or it is deliberately
# not, and not deciding is what shipped a whole release of unreachable arithmetic once.
NOT_EXPOSED = {
    "compilers": "served inside GET /api/symonkernel/buildable. Which compilers exist is not "
                 "an answer on its own — the question is always whether one of them matches "
                 "the kernel about to be built for, and splitting them into two routes invites "
                 "a caller to read 'a compiler is present' and act on it",
}


class KernelError(Exception):
    """A question that could not be answered, carrying why."""


# --- reading names off disk and out of the loaded table ------------------------------------

def _module_name(filename: str) -> str:
    """`nvidia-uvm.ko.xz` -> `nvidia_uvm`.

    THE DIFFERENCE IS ONLY MEANINGFUL AFTER THIS. The loaded table spells a module with
    underscores; the file on disk spells the same module with hyphens. Compare the raw strings
    and every such module lands in BOTH halves of the answer at once — built-but-not-loaded and
    loaded-but-no-file — so the one output this function exists to produce becomes noise, and a
    loosely written test still passes on it.
    """
    name = filename
    for suffix in MODULE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("-", "_")


def _module_files(directory: Path) -> list[Path]:
    return [Path(root) / n
            for root, _dirs, names in os.walk(directory)
            for n in names
            if any(n.endswith(s) for s in MODULE_SUFFIXES)]


def _loaded(proc_modules: str | None = None) -> dict[str, dict[str, Any]]:
    """What is loaded right now, keyed by the normalised module name."""
    p = Path(proc_modules or PROC_MODULES)
    if not p.is_file():
        raise KernelError(f"no {p}: this host does not report which modules are loaded, so "
                          f"'loaded' cannot be answered and is not guessed at")
    out: dict[str, dict[str, Any]] = {}
    for line in p.read_text().splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        out[f[0].replace("-", "_")] = {
            "name": f[0],
            "size_bytes": int(f[1]) if f[1].isdigit() else None,
            "refcount": int(f[2]) if f[2].isdigit() else None,
            "used_by": [d for d in f[3].rstrip(",").split(",") if d and d != "-"],
            "state": f[4],
        }
    return out


# The compiler string the kernel records about itself, e.g.
#   (x86_64-linux-gnu-gcc-15 (Debian 15.3.0-3) 15.3.0, GNU ld ...)
# The leading class excludes '(' deliberately: a bare \S* swallows the opening bracket and the
# name comes back with punctuation on it.
_CC_RE = re.compile(r"([A-Za-z0-9_.+-]*gcc[A-Za-z0-9_.+-]*)\s*\(([^)]*)\)\s*([0-9][0-9.]*)")


def _build_compiler(proc_version: str) -> dict[str, Any] | None:
    m = _CC_RE.search(proc_version or "")
    if not m:
        return None
    return {"compiler": m.group(1), "packaged_as": m.group(2), "version": m.group(3)}


def _build_link(directory: Path) -> dict[str, Any]:
    """The `build` link is what tells a module build where this kernel's headers are."""
    link = directory / "build"
    if not link.exists() and not link.is_symlink():
        return {"path": str(link), "present": False, "symlink": False, "target": None,
                "resolved": None, "resolves": False,
                "why": "no build link: nothing tells a module build where this kernel's "
                       "headers are, so nothing can be compiled against it"}
    target = os.readlink(link) if link.is_symlink() else None
    try:
        resolved: str | None = str(link.resolve(strict=True))
    except OSError:
        resolved = None
    ok = resolved is not None and Path(resolved).is_dir()
    return {"path": str(link), "present": True, "symlink": link.is_symlink(),
            "target": target, "resolved": resolved, "resolves": ok,
            "why": ("the build link resolves to a directory" if ok else
                    f"the build link points at {target!r}, which is not there — a dangling "
                    f"link looks exactly like a working one in a directory listing")}


def _headers(release: str, blink: dict[str, Any]) -> dict[str, Any]:
    """Headers for one kernel, and — the part that matters — whether they are for THAT kernel.

    A build link can resolve to a header tree belonging to a different kernel. The tree states
    its own release in `include/generated/utsrelease.h`, so that is read rather than inferred
    from the directory name.
    """
    conventional = Path(HEADERS_ROOT) / f"linux-headers-{release}"
    path: str | None = None
    via = blink.get("resolved")
    if via and (Path(via) / "Makefile").is_file():
        path = via
    elif (conventional / "Makefile").is_file():
        path = str(conventional)
    uts = None
    if path:
        h = Path(path) / "include/generated/utsrelease.h"
        if h.is_file():
            m = re.search(r'UTS_RELEASE\s+"([^"]+)"', h.read_text())
            uts = m.group(1) if m else None
    return {"present": path is not None, "path": path,
            "conventional_path": str(conventional),
            "conventional_present": conventional.is_dir(),
            "package": f"linux-headers-{release}",
            "utsrelease": uts,
            "matches_release": (uts == release) if uts is not None else None,
            "kbuild_scripts": bool(path and (Path(path) / "scripts").exists()),
            "symbol_table": bool(path and (Path(path) / "Module.symvers").is_file()),
            "why": ("a header tree is present and states its own release" if path and uts else
                    "a header tree is present but does not state its release" if path else
                    f"no header tree for {release}; the package is linux-headers-{release}")}


def _release_key(release: str) -> tuple[int, ...]:
    m = re.match(r"(\d+(?:\.\d+)*)", release)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


# --- the capability -------------------------------------------------------------------------

def running() -> dict[str, Any]:
    """The kernel that is running, and the compiler it was built with.

    The compiler is read out rather than skipped over, because it is half of the question
    `buildable()` has to answer: a module is compiled against a kernel, and the kernel records
    which compiler produced it.
    """
    u = os.uname()
    p = Path(PROC_VERSION)
    raw = p.read_text().strip() if p.is_file() else ""
    return {"release": u.release, "version": u.version, "machine": u.machine,
            "sysname": u.sysname, "node": u.nodename,
            "built_with": _build_compiler(raw),
            "proc_version": raw,
            "modules_dir": str(Path(MODULES_ROOT) / u.release),
            "evidence": {"release_and_version": "os.uname()", "compiler": PROC_VERSION}}


def kernels(root: str | None = None) -> dict[str, Any]:
    """Every kernel with a module directory on this host, and whether each one has headers.

    EVERY DIRECTORY IS REPORTED, INCLUDING THE DEAD ONES. A kernel package that has been
    removed can leave its module directory behind holding only the `modules.*` index files —
    no module tree, no build link, no headers. Filtering those out silently would hide them;
    counting them as kernels that ought to have a driver built would produce three loud gaps on
    a host where nothing is wrong and bury the one real signal. So they are listed, flagged
    `has_module_tree: false`, and `coverage()` buckets them separately.
    """
    base = Path(root or MODULES_ROOT)
    if not base.is_dir():
        raise KernelError(f"no {base}: this host installs no kernel modules")
    run = os.uname().release
    out = []
    for d in sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: _release_key(p.name)):
        files = _module_files(d)
        blink = _build_link(d)
        hdr = _headers(d.name, blink)
        out_of_tree = sorted(f.name for f in files if OUT_OF_TREE in str(f.parent))
        has_tree = bool(files) or (d / "kernel").is_dir()
        out.append({
            "release": d.name, "path": str(d), "running": d.name == run,
            "module_files": len(files),
            "has_module_tree": has_tree,
            "out_of_tree_files": out_of_tree,
            "build_link": blink,
            "headers": hdr,
            "why": ("a live kernel with a module tree" if has_tree else
                    "index files only, no module tree — the kernel this directory belonged to "
                    "is gone, and nothing is expected to build modules for it"),
        })
    live = [k for k in out if k["has_module_tree"]]
    return {"root": str(base), "running": run, "count": len(out),
            "kernels": out,
            "with_module_tree": [k["release"] for k in live],
            "with_headers": [k["release"] for k in live if k["headers"]["present"]],
            "without_headers": [k["release"] for k in live if not k["headers"]["present"]],
            "index_only": [k["release"] for k in out if not k["has_module_tree"]],
            "why": f"{len(live)} of {len(out)} directories under {base} are live kernels with a "
                   f"module tree; the rest hold index files from a kernel that is gone"}


def dkms() -> dict[str, Any]:
    """What the module manager reports it has built, for which kernels.

    AN EMPTY LIST IS NEVER THE WHOLE ANSWER HERE. "No entries" and "the manager is not
    installed" and "the manager failed" are three different facts that produce the same empty
    list, and only one of them means there is nothing to worry about. `state` says which it is
    every time, and `present` is answered by looking at the filesystem rather than at PATH.
    """
    binary = _dkms_binary()
    on_path = shutil.which("dkms")
    if binary is None:
        return {"present": False, "state": "absent", "binary": None, "on_path": False,
                "searched": list(DKMS_CANDIDATES) + ["PATH"],
                "returncode": None, "entries": [], "count": 0, "kernels_covered": [],
                "why": "no module manager found at any of the searched paths or on PATH. This "
                       "is not 'nothing to report': with no manager, no out-of-tree module is "
                       "rebuilt when a kernel lands, and coverage cannot be closed at all"}
    try:
        r = subprocess.run([binary, "status"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return {"present": True, "state": "error", "binary": binary,
                "on_path": on_path is not None, "searched": list(DKMS_CANDIDATES) + ["PATH"],
                "returncode": None, "entries": [], "count": 0, "kernels_covered": [],
                "why": f"{binary} status could not be run: {e}. The empty list below is a "
                       f"failure to ask, not an answer"}
    if r.returncode != 0:
        return {"present": True, "state": "error", "binary": binary,
                "on_path": on_path is not None, "searched": list(DKMS_CANDIDATES) + ["PATH"],
                "returncode": r.returncode, "entries": [], "count": 0, "kernels_covered": [],
                "stderr_tail": (r.stderr or "").strip().splitlines()[-3:],
                "why": f"{binary} status exited {r.returncode}. The empty list below is a "
                       f"failure to ask, not an answer"}
    entries = [e for e in (_parse_dkms_line(l) for l in r.stdout.splitlines()) if e]
    covered = sorted({e["kernel"] for e in entries if e["kernel"]})
    return {"present": True, "state": "ok", "binary": binary,
            "on_path": on_path is not None,
            "searched": list(DKMS_CANDIDATES) + ["PATH"],
            "returncode": 0, "entries": entries, "count": len(entries),
            "kernels_covered": covered,
            "why": (f"{len(entries)} build(s) reported by {binary}, covering "
                    f"{len(covered)} kernel(s)" if entries else
                    f"{binary} answered and reports no builds at all — the manager is installed "
                    f"and knows about nothing, so nothing is being rebuilt for a new kernel")
                   + ("" if on_path else
                      f". {binary} is NOT on PATH; a check that asked PATH would have called "
                      f"this host's working module manager absent")}


def _dkms_binary() -> str | None:
    for c in DKMS_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("dkms")


def _parse_dkms_line(line: str) -> dict[str, Any] | None:
    """One `status` line into fields. Both spellings are handled:

        nvidia/615.71.09, 7.1.13+deb14-amd64, x86_64: installed
        nvidia, 615.71.09, 7.1.13+deb14-amd64, x86_64: installed

    the second being the older form. A line with no kernel — `nvidia/615.71.09: added` — is a
    real state and is kept, with `kernel` left null rather than dropped.
    """
    raw = line.strip()
    if not raw or ":" not in raw:
        return None
    head, _, tail = raw.partition(":")
    parts = [p.strip() for p in head.split(",") if p.strip()]
    if not parts:
        return None
    module, _, version = parts[0].partition("/")
    rest = parts[1:]
    if not version and rest:
        version = rest.pop(0)
    return {"module": module, "version": version or None,
            "kernel": rest[0] if rest else None,
            "arch": rest[1] if len(rest) > 1 else None,
            "state": tail.strip(), "raw": raw}


def modules(release: str | None = None, root: str | None = None) -> dict[str, Any]:
    """Module files on disk for one kernel, against what is loaded — and the difference.

    The difference is the answer. Two halves of it:

      built_not_loaded       an out-of-tree module is placed and nothing is using it
      loaded_without_a_file  something is loaded that has no file under this kernel — it
                             survives only until it is unloaded, and will not come back

    The in-tree modules are counted, not listed. A kernel ships several thousand of them and a
    couple of hundred are ever loaded, so listing the rest as "built but not loaded" would be
    four thousand lines of nothing wrong with one real finding somewhere inside it.

    A kernel that is not the running one gets no difference at all. The loaded table describes
    the running kernel and only the running kernel, so diffing it against another kernel's files
    is a comparison between two kernels reported as a finding about one.
    """
    base = Path(root or MODULES_ROOT)
    run = os.uname().release
    rel = release or run
    d = base / rel
    if not d.is_dir():
        have = sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        raise KernelError(f"no module tree for {rel} under {base}; this host has "
                          f"{', '.join(have) if have else 'none'}")

    files = _module_files(d)
    on_disk: dict[str, list[str]] = {}
    for f in files:
        on_disk.setdefault(_module_name(f.name), []).append(str(f))
    out_of_tree = {n: sorted(p) for n, p in on_disk.items()
                   if any(OUT_OF_TREE in x for x in p)}

    base_answer = {
        "release": rel, "path": str(d), "running_kernel": run,
        "files": {"total": len(files), "out_of_tree": sorted(out_of_tree),
                  "out_of_tree_paths": dict(sorted(out_of_tree.items()))},
    }
    if rel != run:
        return {**base_answer, "compares_running": False, "loaded": None,
                "built_not_loaded": None, "in_tree_built_not_loaded": None,
                "loaded_without_a_file": None,
                "why": f"{rel} is not the running kernel ({run}). Nothing is loaded FROM {rel}, "
                       f"so a difference against the loaded table would compare two kernels and "
                       f"read as a finding about one. The files are listed; the difference is "
                       f"deliberately not invented"}

    loaded = _loaded()
    built_not_loaded = sorted(n for n in out_of_tree if n not in loaded)
    loaded_without_a_file = sorted(n for n in loaded if n not in on_disk)
    in_tree_not_loaded = sum(1 for n in on_disk if n not in loaded and n not in out_of_tree)
    problems = []
    if built_not_loaded:
        problems.append(f"built and not loaded: {', '.join(built_not_loaded)}")
    if loaded_without_a_file:
        problems.append(f"loaded with no file under {rel}: {', '.join(loaded_without_a_file)}")
    return {**base_answer, "compares_running": True,
            "loaded": {"total": len(loaded), "names": sorted(loaded)},
            "built_not_loaded": built_not_loaded,
            "in_tree_built_not_loaded": in_tree_not_loaded,
            "loaded_without_a_file": loaded_without_a_file,
            "why": ("every out-of-tree module placed for this kernel is loaded, and everything "
                    "loaded has a file to come back from"
                    if not problems else "; ".join(problems))}


def compilers() -> dict[str, Any]:
    """Every C compiler on this host, and the one the running kernel was built with.

    THIS IS WHERE THE OBVIOUS ANSWER IS WRONG. `gcc` resolving is not the question. The kernel
    records the compiler that produced it, and on a host where a newer compiler built the
    kernel under a fully qualified name while the unqualified `gcc` is an older release, "a
    compiler is present" and "the compiler the kernel was built with is present" are different
    answers, and only the second one describes the build that is about to happen.

    Every version here is read by running the compiler, not by parsing a package list.
    """
    seen: set[str] = set()
    found: list[dict[str, Any]] = []

    def probe(path: str, on_path_as: str | None = None) -> None:
        if not path or path in seen:
            return
        seen.add(path)
        try:
            r = subprocess.run([path, "-dumpfullversion"], capture_output=True, text=True,
                               timeout=30)
        except (OSError, subprocess.SubprocessError):
            return
        version = (r.stdout or "").strip() if r.returncode == 0 else None
        found.append({"path": path, "version": version or None, "on_path_as": on_path_as})

    for name in ("cc", "gcc"):
        w = shutil.which(name)
        if w:
            probe(w, name)
    for d in ("/usr/bin", "/usr/local/bin"):
        p = Path(d)
        if not p.is_dir():
            continue
        for candidate in sorted(p.glob("*gcc-[0-9]*")):
            if re.fullmatch(r"[A-Za-z0-9_.+-]*gcc-[0-9]+", candidate.name):
                probe(str(candidate))

    default = next((c for c in found if c["on_path_as"]), None)
    kernel_cc = running()["built_with"]
    want = (kernel_cc or {}).get("version")
    matching = [c["path"] for c in found if want and c["version"] == want]
    same = None if not (want and default) else (default["version"] == want)
    return {"found": found, "default": default, "kernel_built_with": kernel_cc,
            "matching_kernel": matching,
            "default_matches_kernel": same,
            "why": ("no compiler on PATH at all" if not default else
                    f"{default['path']} is {default['version']} and the running kernel was "
                    f"built with {want}"
                    + ("" if same else
                       (f"; a compiler at {want} is available as {', '.join(matching)}"
                        if matching else
                        f"; no compiler at {want} is installed anywhere this looked")))}


def coverage(root: str | None = None) -> dict[str, Any]:
    """For every kernel that has a module tree, is the out-of-tree module built FOR IT.

    THIS IS THE POINT OF THE UNIT. A kernel upgrade that lands without a rebuild is invisible
    until the reboot that loses the driver, because everything about the running kernel still
    looks correct. This is the same question asked while it can still be answered cheaply.

    A gap is never reported as a bare "no". Each uncovered kernel carries what is missing and
    what closing it would take — including the exact argument vector, AS DATA. Nothing here
    runs it.

    Index-only directories are bucketed separately and are not gaps. Holding a module manager
    to account for a kernel whose image is gone produces loud findings on a healthy host, and
    a report with three false gaps in it is a report nobody reads the fourth line of.
    """
    ks = kernels(root)
    dk = dkms()
    packages = _dkms_packages(dk)

    entries_by_kernel: dict[str, list[dict[str, Any]]] = {}
    for e in dk["entries"]:
        if e["kernel"]:
            entries_by_kernel.setdefault(e["kernel"], []).append(e)

    per_kernel, covered, uncovered, stale = [], [], [], []
    for k in ks["kernels"]:
        rel = k["release"]
        if not k["has_module_tree"]:
            stale.append({"release": rel, "path": k["path"], "why": k["why"]})
            continue

        dest = Path(k["path"]) / OUT_OF_TREE
        found_here = entries_by_kernel.get(rel, [])
        results, missing_any = [], False
        for pkg in packages:
            entry = next((e for e in found_here
                          if e["module"] == pkg["module"] and e["version"] == pkg["version"]),
                         None)
            present, absent = [], []
            for name in pkg["built_module_names"]:
                if any((dest / f"{name}{s}").is_file() for s in MODULE_SUFFIXES):
                    present.append(name)
                else:
                    absent.append(name)
            placed = bool(entry) and any(entry["state"].startswith(s) for s in PLACED_STATES)
            ok = placed and not absent
            missing_any = missing_any or not ok
            results.append({
                "module": pkg["module"], "version": pkg["version"],
                "reported_state": entry["state"] if entry else None,
                "files_present": present, "files_missing": absent,
                "covered": ok,
                "why": ("built for this kernel and every file is placed" if ok else
                        f"the manager reports no build of {pkg['module']}/{pkg['version']} for "
                        f"{rel}" if not entry else
                        f"the manager reports {entry['state']!r} but "
                        f"{', '.join(absent)} is not under {dest}" if absent else
                        f"the manager reports {entry['state']!r}, which is not a placed build"),
            })

        # No managed package is not automatically clean. With out-of-tree modules already
        # placed here and nothing accounting for them, the next kernel gets none of them and
        # there is no manager to notice — which is the failure in its worst form, not its
        # absence. With no managed package AND nothing out-of-tree placed, there is genuinely
        # nothing to rebuild, and saying otherwise is the false alarm that gets a unit ignored.
        unmanaged = k["out_of_tree_files"] if not packages else []
        if packages:
            is_covered = not missing_any
        else:
            is_covered = not unmanaged
        needed = ([] if is_covered
                  else _would_need(rel, k, dk, [r for r in results if not r["covered"]]))
        per_kernel.append({
            "release": rel, "path": k["path"], "running": k["running"],
            "headers": k["headers"]["present"],
            "modules": results, "covered": is_covered,
            "would_need": needed,
            "why": (("every known out-of-tree module is built and placed for this kernel"
                     if packages else
                     "no managed package and nothing out-of-tree placed here — there is "
                     "nothing to rebuild for this kernel")
                    if is_covered else
                    f"{len(unmanaged)} out-of-tree module file(s) are placed here and no "
                    f"manager accounts for them, so nothing rebuilds them for a new kernel"
                    if not packages else
                    "this kernel would come up without the module(s) it needs: "
                    + "; ".join(r["why"] for r in results if not r["covered"])),
        })
        (covered if is_covered else uncovered).append(rel)

    run = os.uname().release
    newest = max(per_kernel, key=lambda k: _release_key(k["release"]), default=None)
    return {
        "dkms": {"present": dk["present"], "state": dk["state"], "binary": dk["binary"],
                 "on_path": dk["on_path"], "packages": packages},
        "kernels": per_kernel,
        "covered": covered, "uncovered": uncovered,
        "index_only": stale,
        "complete": bool(per_kernel) and not uncovered,
        "running": {"release": run,
                    "covered": run in covered,
                    "why": "the running kernel has its driver, or it would not be serving"
                           if run in covered else
                           "the running kernel is not covered — what is loaded now came from "
                           "somewhere this cannot account for"},
        "newest_installed": None if newest is None else {
            "release": newest["release"], "covered": newest["covered"],
            "caveat": "newest by version number, not read from the bootloader. Which kernel "
                      "boots next is the bootloader's answer and this unit does not ask it",
        },
        "why": ("every kernel with a module tree has its out-of-tree module built and placed"
                if per_kernel and not uncovered else
                "no kernel with a module tree was found" if not per_kernel else
                f"{len(uncovered)} kernel(s) would come up without their module: "
                f"{', '.join(uncovered)}"),
    }


_BUILT_MODULE_RE = re.compile(r'^\s*BUILT_MODULE_NAME\[\d+\]\s*=\s*"?([^"\s]+)"?', re.M)


def _dkms_packages(dk: dict[str, Any]) -> list[dict[str, Any]]:
    """The module names each managed package builds, read from the package's own declaration.

    Derived from what the manager reports rather than written down here. A hardcoded list is a
    list that is right until the day the driver adds a module, and wrong silently after it.
    """
    out, seen = [], set()
    for e in dk["entries"]:
        key = (e["module"], e["version"])
        if key in seen or not e["module"]:
            continue
        seen.add(key)
        conf = Path(HEADERS_ROOT) / f"{e['module']}-{e['version']}" / "dkms.conf"
        names: list[str] = []
        if conf.is_file():
            try:
                names = _BUILT_MODULE_RE.findall(conf.read_text())
            except OSError:
                names = []
        out.append({"module": e["module"], "version": e["version"],
                    "conf": str(conf), "conf_read": bool(names),
                    "built_module_names": names or [e["module"]],
                    "why": "module names read from the package's own declaration" if names else
                           f"no readable declaration at {conf}; falling back to the package "
                           f"name, which under-reports a package that builds several modules"})
    return out


def _would_need(release: str, k: dict[str, Any], dk: dict[str, Any],
                gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What closing a gap would take. Reported, never run."""
    needed: list[dict[str, Any]] = []
    if not dk["present"]:
        needed.append({"what": "a module manager", "argv": None,
                       "why": "none was found at any searched path or on PATH, so no rebuild "
                              "can be arranged at all"})
    elif not dk["entries"]:
        needed.append({"what": "a managed package to rebuild from", "argv": None,
                       "why": f"{dk['binary']} answered and reports no builds at all, so the "
                              f"modules already placed under {release} are unmanaged — nothing "
                              f"will produce them again for the next kernel"})
    if not k["headers"]["present"]:
        needed.append({"what": f"headers for {release}", "argv": None,
                       "why": f"nothing to compile against: the package is "
                              f"{k['headers']['package']} and no header tree is unpacked at "
                              f"{k['headers']['conventional_path']}"})
    elif not k["build_link"]["resolves"]:
        needed.append({"what": f"a build link for {release}", "argv": None,
                       "why": k["build_link"]["why"]})
    for g in gaps:
        if dk["present"] and g["module"] and g["version"]:
            needed.append({
                "what": f"a build of {g['module']}/{g['version']} for {release}",
                "argv": [dk["binary"], "install", f"{g['module']}/{g['version']}",
                         "-k", release],
                "why": "this is the command an operator would run. This unit reports it and "
                       "does not run it: a status unit that changes kernel state is no longer "
                       "a status unit",
            })
    return needed


PIN = os.environ.get(
    "SYM_KERNEL_PIN",
    "/mnt/SymonSaySource/platform/pins/open-gpu-kernel-modules.json")


def pinned() -> dict[str, Any]:
    """Does every DKMS-registered module version match the revision this estate recorded?

    Rules §3.1b-iii. This is a different question from the one symondriver asks: that unit
    compares the module that is LOADED; this compares what DKMS will REBUILD on the next
    kernel. They can disagree — a registration can be bumped while the running module stays
    where it was until reboot — and the disagreement is worth catching before the reboot
    rather than after it.

    A missing pin is reported as missing. Silence is never agreement.
    """
    import json
    f = Path(PIN)
    if not f.is_file():
        return {"pin_file": str(f), "pinned": None, "registered": [], "matches": None,
                "why": f"no pin at {f}; DKMS will rebuild a module this estate has not "
                       f"recorded a revision for"}
    try:
        d = json.loads(f.read_text())
    except Exception as e:
        return {"pin_file": str(f), "pinned": None, "matches": None,
                "why": f"{type(e).__name__} reading the pin: {e}"}
    want = str(d.get("intended_tag_version") or "")
    dk = dkms()
    seen = [{"module": e.get("module"), "version": e.get("version"),
             "kernel": e.get("kernel"), "state": e.get("state"),
             "matches": e.get("version") == want}
            for e in dk.get("entries", [])]
    drifted = [e for e in seen if not e["matches"]]
    return {
        "pin_file": str(f),
        "component": d.get("component"),
        "upstream": d.get("upstream_url"),
        "pinned": want,
        "pinned_revision": d.get("intended_revision"),
        "registered": seen,
        "matches": (bool(want) and bool(seen) and not drifted),
        "drifted": drifted,
        "why": ("every DKMS registration is the revision this estate pinned"
                if want and seen and not drifted else
                ("DKMS has no registrations, so nothing will be rebuilt for a new kernel"
                 if not seen else
                 f"pinned {want!r} but " + ", ".join(
                     f"{e['module']} is {e['version']!r} for kernel {e['kernel']}"
                     for e in drifted) +
                 " — the next kernel will get a module the estate did not record")),
    }


def buildable(release: str | None = None, root: str | None = None) -> dict[str, Any]:
    """Can a module be built for this kernel right now — precondition by precondition.

    A bare "no" is useless, so every precondition is reported with its own answer, its own
    evidence and its own sentence. `blocked_on` names the ones that failed.

    ONE PRECONDITION IS DELIBERATELY NOT A REFUSAL. Whether the available compiler is the one
    the kernel was built with is reported as its own named precondition, with both versions —
    it is the most useful thing on this page and the thing a caller would otherwise never look
    at. It does not flip the verdict, because this unit does not run a build and so cannot
    claim one would fail. What a build system does with a mismatched compiler is a fact about
    that build system; what is on this host is the fact this unit is entitled to report.
    """
    base = Path(root or MODULES_ROOT)
    run = os.uname().release
    rel = release or run
    d = base / rel
    if not d.is_dir():
        have = sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        raise KernelError(f"no module tree for {rel} under {base}; this host has "
                          f"{', '.join(have) if have else 'none'}")

    blink = _build_link(d)
    hdr = _headers(rel, blink)
    cc = compilers()
    dk = dkms()
    make = shutil.which("make")
    kernel_cc = (cc["kernel_built_with"] or {}).get("version")
    default_cc = cc["default"]

    checks: dict[str, dict[str, Any]] = {
        "build_link": {
            "ok": blink["resolves"], "blocking": True,
            "path": blink["path"], "target": blink["target"], "resolved": blink["resolved"],
            "why": blink["why"]},
        "headers": {
            "ok": hdr["present"], "blocking": True,
            "path": hdr["path"], "package": hdr["package"],
            "why": hdr["why"]},
        "headers_are_for_this_kernel": {
            "ok": hdr["matches_release"] is True, "blocking": True,
            "utsrelease": hdr["utsrelease"], "expected": rel,
            "why": ("the header tree states the release being built for"
                    if hdr["matches_release"] else
                    f"the header tree states {hdr['utsrelease']!r} and the build is for "
                    f"{rel!r} — a tree for the wrong kernel compiles and produces a module "
                    f"that will not load" if hdr["utsrelease"] else
                    "the header tree does not state a release, so it cannot be shown to be "
                    "the right one")},
        "kbuild": {
            "ok": hdr["kbuild_scripts"] and hdr["symbol_table"], "blocking": True,
            "scripts": hdr["kbuild_scripts"], "symbol_table": hdr["symbol_table"],
            "why": ("the build scripts and the symbol table are both present"
                    if hdr["kbuild_scripts"] and hdr["symbol_table"] else
                    "the header tree is incomplete: a module needs the build scripts to "
                    "compile and the symbol table to resolve against")},
        "compiler": {
            "ok": default_cc is not None, "blocking": True,
            "path": (default_cc or {}).get("path"),
            "version": (default_cc or {}).get("version"),
            "why": (f"{default_cc['path']} is {default_cc['version']}" if default_cc else
                    "no C compiler on PATH; nothing can be compiled")},
        "compiler_matches_kernel": {
            "ok": cc["default_matches_kernel"] is True, "blocking": False,
            "default": (default_cc or {}).get("version"),
            "kernel_built_with": kernel_cc,
            "available_matching": cc["matching_kernel"],
            "why": cc["why"]},
        "make": {
            "ok": make is not None, "blocking": True, "path": make,
            "why": f"make is at {make}" if make else "no make; nothing drives the build"},
        "module_manager": {
            "ok": dk["present"], "blocking": True,
            "binary": dk["binary"], "on_path": dk["on_path"],
            "why": dk["why"]},
    }

    blocked = sorted(n for n, c in checks.items() if c["blocking"] and not c["ok"])
    warnings = sorted(n for n, c in checks.items() if not c["blocking"] and not c["ok"])
    return {
        "release": rel, "running": rel == run,
        "preconditions": checks,
        "ok": not blocked,
        "blocked_on": blocked,
        "warnings": warnings,
        "why": (("every precondition for building a module for " + rel + " holds"
                 if not blocked else
                 f"a module cannot be built for {rel}: {', '.join(blocked)}")
                + (f". Reported and not blocking: {', '.join(warnings)}" if warnings else "")),
        "note": "nothing here builds anything. These are the preconditions a build needs, each "
                "read from disk.",
    }
