# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The GPU driver's userspace surface, and whether it is CONSISTENT with the kernel module.

THE FAILURE THIS UNIT EXISTS TO CATCH
-------------------------------------
A partial package upgrade leaves the userspace libraries at one version and the loaded kernel
module at another. Nothing announces it. The first symptom is a compute call into the driver
failing with an error that names neither version, so the cause is invisible from the message
and the operator goes looking in the wrong place.

So this reads every source that holds a version and puts them side by side:

    the loaded module   /proc/driver/nvidia/version, cross-checked against
                        /sys/module/nvidia/version — two independent files, not one read twice
    userspace           by RUNNING the query tool. A file describing what userspace would say
                        is not userspace saying it
    the libraries       the version carried in each filename, in EVERY architecture installed
    the packages        dpkg-query

`consistent()` is the point of the unit. Agreement is one line; DISAGREEMENT IS THE FINDING,
and it names every source and what each one said.

TWO VERSION SERIES SHARE THIS FILENAME SPACE, AND CONFLATING THEM MAKES THE UNIT USELESS
The driver's own series is three dotted components with a three-digit major. Several files and
packages matching the same name patterns come from unrelated source packages that have never
tracked the driver and never will — they sit on their own series entirely. Counting those as
disagreement would report every host as permanently inconsistent, which is the same as
reporting nothing.

They are separated by `_DRIVER_SERIES`, and they are still RETURNED, each carrying the reason
it is not compared. A filter nobody can see is indistinguishable from a bug.

NOTHING HERE WRITES, LOADS OR INSTALLS ANYTHING
Every path is opened read-only. Exactly one program is ever executed — the query tool, in
`userspace()`, and `dpkg-query` in `packages()` — both as argument vectors, never through a
shell. `binaries()` LOCATES the known programs and runs none of them: one of them writes a
large archive as its whole purpose, and an inspector that does that as a side effect of being
asked what exists is not an inspector.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import struct
import subprocess
from pathlib import Path
from typing import Any, Mapping

# --- where the facts live -------------------------------------------------------------------
# Paths and program names are technical identifiers required to run software: they are what
# must be typed to reach the thing, so they are reproduced byte-exact and used as opaque names.
_PROC_VERSION = "/proc/driver/nvidia/version"
_SYS_VERSION = "/sys/module/nvidia/version"

_LIB_DIRS = ("/usr/lib/x86_64-linux-gnu", "/usr/lib/i386-linux-gnu")
_LIB_GLOBS = ("libnvidia*", "libcuda*")

_QUERY_TOOL = "nvidia-smi"
_QUERY_ARGS = ["--query-gpu=driver_version", "--format=csv,noheader"]

_PACKAGE_TOOL = "dpkg-query"
_PACKAGE_FORMAT = ("${binary:Package}\\t${Architecture}\\t${Version}\\t"
                   "${source:Package}\\t${source:Version}\\t${db:Status-Abbrev}\\n")

_KNOWN_BINARIES = (
    "nvidia-smi",
    "nvidia-settings",
    "nvidia-modprobe",
    "nvidia-persistenced",
    "nvidia-debugdump",
    "nvidia-cuda-mps-control",
    "nvidia-bug-report.sh",
)

# Programs this unit locates but must never execute, with the reason, so that the restriction
# travels with the list rather than living in somebody's memory.
_NEVER_RUN = {
    "nvidia-bug-report.sh": "writes a large archive to disk as its entire purpose; asking what "
                            "exists must not produce a file",
}

_FAMILY = re.compile(r"nvidia|cuda", re.I)

# The driver's version series: a three-digit major and two further components. This is read off
# the estate's own data rather than invented — it admits the running 615.71.09 and the stale
# 550.163.01 that this host actually carries, and rejects the toolkit and the unrelated
# libraries, which sit at one- and two-digit majors. It is reported in every result that uses
# it so a reader can see what was compared and what was not.
_DRIVER_SERIES = re.compile(r"^\d{3}\.\d+\.\d+$")

# The version a versioned filename ends with: `libcuda.so.615.71.09` -> `615.71.09`,
# `libcuda.so.1` -> `1`. Absent on an unversioned name, which is reported as absent, not zero.
_FILE_VERSION = re.compile(r"\.so\.(\d+(?:\.\d+)*)$")

_NVRM_VERSION = re.compile(r"\b(\d{2,}\.\d+\.\d+)\b")
_BUILD_STAMP = re.compile(r"\(([^)\s]+@[^)\s]+)\)\s*(.*)$")
_COMPILER = re.compile(r"gcc version (\S+)")


# Declared as a bare assignment, not an annotated one. `endpoints-current` reads this with
# `ast.Assign`, and `NOT_EXPOSED: dict[str, str] = {...}` parses as `ast.AnnAssign`, which that
# check never sees — the declaration would be silently ignored and a deliberately withheld
# capability would be reported as unreachable.
NOT_EXPOSED = {
    # Empty on purpose, and empty is a DECISION rather than silence: every public callable in
    # this module is reachable over HTTP, one route each. `endpoints-current` refuses a
    # capability nobody can ask for, and the answer here is that nobody is withheld.
    #
    # The helpers that are genuinely internal — version normalisation, the ELF reader, the
    # filename parser — are underscore-prefixed, which is the honest way to say "not a
    # capability" rather than listing them here as capabilities that were declined.
}


class DriverError(Exception):
    """A driver fact that could not be read, carrying why rather than an empty result."""


# --- internals ------------------------------------------------------------------------------

def _upstream(version: str) -> str:
    """The upstream part of a package version: `1:1.0.6-1` -> `1.0.6`, `615.71.09-2` -> `615.71.09`.

    The kernel module says `615.71.09` and the package manager says `615.71.09-2`. Comparing
    those as strings reports every host on earth as inconsistent, which turns the one finding
    that matters into noise nobody reads.
    """
    v = version.split(":", 1)[-1]
    return v.rsplit("-", 1)[0] if "-" in v else v


def _is_driver_series(version: str | None) -> bool:
    return bool(version and _DRIVER_SERIES.match(version))


def _file_version(name: str) -> str | None:
    m = _FILE_VERSION.search(name)
    return m.group(1) if m else None


def _read_lines(path: str) -> list[str] | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return [ln.rstrip("\n") for ln in fh.read().splitlines()]
    except OSError:
        return None


def _soname(path: Path) -> str | None:
    """The SONAME recorded in the file's own dynamic section — read, not inferred from the name.

    A filename is a convention; DT_SONAME is what the dynamic loader actually goes by, and the
    two disagreeing is itself worth seeing. Both 32- and 64-bit objects are installed here, so
    the class byte decides the struct layout: assuming 64-bit would silently misparse a third
    of the libraries on this host and report a plausible wrong answer, which is worse than
    reporting none.

    Only the ELF and section headers are read, not the file body — these objects run to tens of
    megabytes each and reading all of them to answer one HTTP request is not a thing to do.
    """
    try:
        with path.open("rb") as fh:
            ident = fh.read(16)
            if len(ident) < 16 or ident[:4] != b"\x7fELF":
                return None
            end = "<" if ident[5] == 1 else ">"
            if ident[4] == 1:                                    # ELFCLASS32
                fh.seek(32); shoff = struct.unpack(end + "I", fh.read(4))[0]
                fh.seek(46); shentsize, shnum = struct.unpack(end + "HH", fh.read(4))
                sh_fmt, dyn_fmt = end + "IIIIIIIIII", end + "iI"
            elif ident[4] == 2:                                  # ELFCLASS64
                fh.seek(40); shoff = struct.unpack(end + "Q", fh.read(8))[0]
                fh.seek(58); shentsize, shnum = struct.unpack(end + "HH", fh.read(4))
                sh_fmt, dyn_fmt = end + "IIQQQQIIQQ", end + "qQ"
            else:
                return None
            if not shoff or not shnum or shentsize < struct.calcsize(sh_fmt):
                return None

            secs = []
            for i in range(shnum):
                fh.seek(shoff + i * shentsize)
                buf = fh.read(struct.calcsize(sh_fmt))
                if len(buf) < struct.calcsize(sh_fmt):
                    return None
                secs.append(struct.unpack(sh_fmt, buf))

            for s in secs:
                if s[1] != 6:                                    # SHT_DYNAMIC
                    continue
                link = s[6]
                if link >= len(secs):
                    return None
                str_off, str_size = secs[link][4], secs[link][5]
                step = struct.calcsize(dyn_fmt)
                fh.seek(s[4])
                dyn = fh.read(s[5])
                for off in range(0, len(dyn) - step + 1, step):
                    tag, val = struct.unpack_from(dyn_fmt, dyn, off)
                    if tag == 0:                                 # DT_NULL
                        break
                    if tag == 14:                                # DT_SONAME
                        if val >= str_size:
                            return None
                        fh.seek(str_off + val)
                        raw = fh.read(min(512, str_size - val))
                        cut = raw.find(b"\0")
                        return raw[:cut if cut >= 0 else None].decode("ascii", "replace")
    except (OSError, struct.error):
        return None
    return None


def _run(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Every program this unit runs goes through here, as an argument vector.

    There is no code path that builds a command line by concatenation, and the shell is never
    invoked anywhere in this module — a test asserts that against the module source, because
    the day an inspector's input reaches a shell is the day an inspector becomes an execution
    surface.
    """
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


# --- capabilities ---------------------------------------------------------------------------

def kernel_module() -> dict[str, Any]:
    """What the LOADED kernel module says about itself, parsed from the file it publishes.

    An absent file is not an empty answer. It means the module is not loaded, and saying so is
    the whole finding: until it is loaded, nothing userspace does reaches the device, and every
    other version on this host is describing something that is not running.
    """
    lines = _read_lines(_PROC_VERSION)
    sys_lines = _read_lines(_SYS_VERSION)
    sysfs_version = sys_lines[0].strip() if sys_lines and sys_lines[0].strip() else None

    if not lines:
        return {
            "loaded": False,
            "source": _PROC_VERSION,
            "raw": [],
            "version": None,
            "open_module": None,
            "sysfs": {"source": _SYS_VERSION, "version": sysfs_version,
                      "agrees": None, "present": sysfs_version is not None},
            "why": f"{_PROC_VERSION} is not readable, so no kernel module is loaded. Nothing in "
                   f"userspace reaches the device until one is, and every other version on this "
                   f"host describes something that is not currently running.",
        }

    head = lines[0]
    rest = " ".join(lines[1:])

    m = _NVRM_VERSION.search(head)
    version = m.group(1) if m else None

    lower = head.lower()
    open_module = "open kernel module" in lower
    variant = "open" if open_module else "proprietary"

    build_user = build_host = built = None
    b = _BUILD_STAMP.search(head)
    if b:
        stamp = b.group(1)
        build_user, _, build_host = stamp.partition("@")
        built = b.group(2).strip() or None

    c = _COMPILER.search(rest)
    compiler = c.group(1) if c else None

    build_type = "Release Build" if "release build" in lower else (
        "Debug Build" if "debug build" in lower else None)

    here = socket.gethostname()
    built_here = (build_host == here) if build_host else None

    return {
        "loaded": True,
        "source": _PROC_VERSION,
        "raw": lines,
        "version": version,
        "open_module": open_module,
        "variant": variant,
        "build_type": build_type,
        "build_user": build_user,
        "build_host": build_host,
        "built": built,
        "built_here": built_here,
        "this_host": here,
        "compiler": compiler,
        "compiler_raw": (lines[1].strip() if len(lines) > 1 else None),
        "sysfs": {
            "source": _SYS_VERSION,
            "version": sysfs_version,
            "present": sysfs_version is not None,
            # A second, independent file. If the two ever disagree the module publishing them
            # is not the module answering, and that is worth a line of its own.
            "agrees": (sysfs_version == version) if (sysfs_version and version) else None,
        },
        "why": (f"the loaded module is the {variant} variant at {version}"
                + (f", built on {build_host}" if build_host else "")
                + (" — which is this host, so it was compiled here from source rather than "
                   "installed as a binary" if built_here else "")
                + (f", with compiler {compiler}" if compiler else "")),
    }


def userspace() -> dict[str, Any]:
    """The version USERSPACE reports, obtained by running the query tool.

    Running it is the point. A package version records what was installed; this records what
    the userspace library stack answers when something asks it, which is the number a caller
    actually gets.
    """
    tool = shutil.which(_QUERY_TOOL)
    if not tool:
        raise DriverError(f"{_QUERY_TOOL} is not on PATH; userspace cannot be asked what "
                          f"version it is, only what version was installed")
    argv = [tool, *_QUERY_ARGS]
    try:
        r = _run(argv, timeout=30)
    except subprocess.TimeoutExpired:
        raise DriverError(f"{_QUERY_TOOL} did not answer within 30s; the driver is loaded but "
                          f"not responding, which is a different fault from a version mismatch")
    if r.returncode != 0:
        raise DriverError(f"{_QUERY_TOOL} rc={r.returncode}: "
                          f"{(r.stderr or r.stdout).strip()[:200]}")

    rows = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    versions = sorted(set(rows))
    return {
        "tool": tool,
        "argv": argv,
        "returncode": r.returncode,
        "stdout": (r.stdout or "").strip(),
        "devices": len(rows),
        "version": versions[0] if len(versions) == 1 else None,
        "versions": versions,
        "why": (f"userspace answers {versions[0]} across {len(rows)} device(s)"
                if len(versions) == 1 else
                f"userspace answered {len(versions)} different versions across {len(rows)} "
                f"device(s): {', '.join(versions) or 'none'} — one stack cannot be two versions"),
    }


def libraries() -> dict[str, Any]:
    """Every driver library on disk, grouped by architecture, with its soname and version.

    BOTH architectures are read, not just the native one. A 32-bit stack left behind by a
    partial upgrade is exactly as able to break a process as the 64-bit one, and it is the half
    nobody looks at.
    """
    by_arch: dict[str, Any] = {}
    missing: list[str] = []
    driver_versions: set[str] = set()
    other_series: list[dict[str, Any]] = []
    total = 0

    for root in _LIB_DIRS:
        d = Path(root)
        arch = d.name                      # the multiarch tuple, as it exists on disk
        if not d.is_dir():
            missing.append(root)
            continue
        found: list[dict[str, Any]] = []
        names: set[str] = set()
        for pat in _LIB_GLOBS:
            names |= {p.name for p in d.glob(pat)}
        for name in sorted(names):
            p = d / name
            link = p.is_symlink()
            real = Path(os.path.realpath(p))
            fv = _file_version(name)
            rv = _file_version(real.name)

            # A name like `libcuda.so.1` carries the ABI number, not the driver version, and
            # calling that "another version series" would be false — it is the driver, reached
            # through its soname. So the link is followed, and where the resolved file carries
            # the driver version the entry is credited with it, saying which name it came from.
            if _is_driver_series(fv):
                driver_version, version_from = fv, "filename"
            elif _is_driver_series(rv):
                driver_version, version_from = rv, "resolved link target"
            else:
                driver_version, version_from = None, None

            if driver_version:
                driver_versions.add(driver_version)

            entry = {
                "file": name,
                "path": str(p),
                "symlink": link,
                "target": (os.readlink(p) if link else None),
                "real": str(real),
                "resolves": real.is_file(),
                "soname": _soname(real),
                "filename_version": fv,
                "driver_version": driver_version,
                "version_from": version_from,
                "series": "driver" if driver_version else "other",
                "bytes": (real.stat().st_size if real.is_file() else None),
            }
            if not driver_version:
                entry["why_not_compared"] = (
                    "not compared because " + (
                        f"neither {name} nor the file it resolves to ({real.name}) carries a "
                        f"version in its name, so it reports no version to compare"
                        if fv is None else
                        f"{fv} is not the driver's version series {_DRIVER_SERIES.pattern} and "
                        f"it resolves to {real.name}, which carries no driver version either — "
                        f"this file comes from a source package that versions independently of "
                        f"the driver, so comparing it would report a mismatch that is not one"))
                other_series.append({"arch": arch, "file": name, "version": fv,
                                     "real": str(real), "why": entry["why_not_compared"]})
            found.append(entry)
        total += len(found)
        by_arch[arch] = {"dir": root, "count": len(found), "libraries": found}

    return {
        "roots": list(_LIB_DIRS),
        "patterns": list(_LIB_GLOBS),
        "driver_series": _DRIVER_SERIES.pattern,
        "architectures": sorted(by_arch),
        "by_arch": by_arch,
        "count": total,
        "driver_versions": sorted(driver_versions),
        "other_series": other_series,
        "missing_dirs": missing,
        "why": (f"{total} driver libraries across {len(by_arch)} architecture(s); "
                + (f"all at {sorted(driver_versions)[0]}" if len(driver_versions) == 1 else
                   f"versions present: {', '.join(sorted(driver_versions)) or 'none'}")
                + (f"; {len(other_series)} file(s) sit on another series and are listed with "
                   f"the reason they are not compared" if other_series else "")),
    }


def binaries() -> dict[str, Any]:
    """Which of the known driver programs exist, and their real paths. None of them is run.

    Locating is not invoking. One of these writes a large archive as its whole purpose, so an
    inspector that executed what it found would produce a file every time somebody asked it a
    question. The one program this unit ever runs is the query tool, in `userspace()`.
    """
    present: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in _KNOWN_BINARIES:
        found = shutil.which(name)
        if not found:
            missing.append(name)
            continue
        p = Path(found)
        entry = {
            "name": name,
            "path": found,
            "real": os.path.realpath(found),
            "symlink": p.is_symlink(),
            "executable": os.access(found, os.X_OK),
            "bytes": (p.stat().st_size if p.exists() else None),
        }
        if name in _NEVER_RUN:
            entry["never_run_here"] = _NEVER_RUN[name]
        present.append(entry)

    return {
        "known": list(_KNOWN_BINARIES),
        "present": present,
        "missing": missing,
        "count": len(present),
        "executed": [_QUERY_TOOL],
        "why": (f"{len(present)} of {len(_KNOWN_BINARIES)} known driver programs are on PATH"
                + (f"; absent: {', '.join(missing)}" if missing else "; none absent")
                + f". This route located them and ran none of them."),
    }


def packages() -> dict[str, Any]:
    """The installed package family and their versions, read with an argument vector.

    The family is split by version series, and BOTH halves are returned. The driver half is
    what `consistent()` compares; the other half is every package whose name matched the same
    pattern but which sits on an unrelated series, each carrying the reason it was set aside.
    Hiding them would be tidier and would make the result unverifiable.
    """
    tool = shutil.which(_PACKAGE_TOOL)
    if not tool:
        raise DriverError(f"{_PACKAGE_TOOL} is not on PATH; the installed package set cannot "
                          f"be read on this host")
    argv = [tool, "-W", f"-f={_PACKAGE_FORMAT}".replace("\\t", "\t").replace("\\n", "\n")]
    try:
        r = _run(argv, timeout=60)
    except subprocess.TimeoutExpired:
        raise DriverError(f"{_PACKAGE_TOOL} did not answer within 60s")
    if r.returncode != 0:
        raise DriverError(f"{_PACKAGE_TOOL} rc={r.returncode}: "
                          f"{(r.stderr or '').strip()[:200]}")

    driver_family: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    by_source: dict[str, Any] = {}
    matched = 0

    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name, arch, version, src, src_version, status = (p.strip() for p in parts[:6])
        if not _FAMILY.search(name):
            continue
        matched += 1
        up = _upstream(version)
        is_driver = _is_driver_series(up)
        entry = {
            "package": name,
            "architecture": arch,
            "version": version,
            "upstream": up,
            "source": src,
            "source_version": src_version,
            "status": status,
            "series": "driver" if is_driver else "other",
        }
        if is_driver:
            driver_family.append(entry)
        else:
            entry["why_not_compared"] = (
                f"{up} is not the driver's version series {_DRIVER_SERIES.pattern}; source "
                f"package {src} versions independently of the driver, so comparing it would "
                f"report a mismatch that is not one")
            other.append(entry)
        slot = by_source.setdefault(src, {"source": src, "source_version": src_version,
                                          "upstream": _upstream(src_version),
                                          "series": "driver" if is_driver else "other",
                                          "binaries": []})
        slot["binaries"].append(name if not arch else f"{name}:{arch}")

    versions = sorted({e["upstream"] for e in driver_family})
    at: dict[str, list[str]] = {}
    for e in driver_family:
        at.setdefault(e["upstream"], []).append(e["package"])

    return {
        "tool": tool,
        "argv": argv,
        "pattern": _FAMILY.pattern,
        "driver_series": _DRIVER_SERIES.pattern,
        "matched": matched,
        "driver_family": sorted(driver_family, key=lambda e: (e["package"], e["architecture"])),
        "driver_family_count": len(driver_family),
        "other": sorted(other, key=lambda e: (e["package"], e["architecture"])),
        "other_count": len(other),
        "by_source": by_source,
        "versions": versions,
        "packages_at": {v: sorted(set(ns)) for v, ns in at.items()},
        "why": (f"{matched} installed packages match {_FAMILY.pattern}; {len(driver_family)} "
                f"sit on the driver's version series and are compared, {len(other)} do not and "
                f"are listed with the reason. "
                + (f"All compared packages are at {versions[0]}." if len(versions) == 1 else
                   f"The compared packages carry {len(versions)} different versions: "
                   f"{', '.join(versions)} — a partial upgrade looks exactly like this.")),
    }


PIN = os.environ.get(
    "SYM_DRIVER_PIN",
    "/mnt/SymonSaySource/platform/pins/open-gpu-kernel-modules.json")


def pinned() -> dict[str, Any]:
    """Does the loaded kernel module match the revision this estate recorded?

    Rules §3.1b-iii: a component that invokes or inspects something it does not own must
    assert that thing's version against a recorded pin. Invoking blind is how an upgrade
    underneath a component gets discovered by a user instead of by a test.

    The pin is the authority and it is READ, never assumed — §3.1b-i. A missing pin is
    reported as a missing pin, never as agreement.
    """
    import json
    f = Path(PIN)
    if not f.is_file():
        return {"pin_file": str(f), "pinned": None, "observed": None, "matches": None,
                "why": f"no pin at {f}; the driver is being inspected with nothing recorded "
                       f"to compare it against, which is the gap §3.1b-iii names"}
    try:
        d = json.loads(f.read_text())
    except Exception as e:
        return {"pin_file": str(f), "pinned": None, "matches": None,
                "why": f"{type(e).__name__} reading the pin: {e}"}
    want = str(d.get("intended_tag_version") or "")
    km = kernel_module()
    got = km.get("version")
    return {
        "pin_file": str(f),
        "component": d.get("component"),
        "upstream": d.get("upstream_url"),
        "pinned": want,
        "pinned_revision": d.get("intended_revision"),
        "observed": got,
        "source_of_observed": km.get("source"),
        "matches": (bool(want) and got == want),
        "why": ("the loaded module is the revision this estate pinned"
                if want and got == want else
                f"pinned {want!r} but the loaded module reports {got!r} — one of them moved, "
                f"and until this is reconciled nothing here can be trusted to describe the "
                f"driver the estate actually builds against"),
    }


def consistent(*, extra_sources: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Do the kernel module, userspace, the libraries and the packages agree on one version?

    THIS IS THE POINT OF THE UNIT. Every other function here exists to feed this one.

    The answer is not a boolean with a shrug attached. It is the SET of versions seen and,
    for each, every source that reported it and where that source was read — because when they
    disagree the useful information is which one is the odd one out, and a result that says
    only "inconsistent" sends an operator to look at all four.

    A source that cannot be read is named in `unavailable` rather than dropped. Dropping it
    would let the remaining sources agree with each other and report a consistency that was
    never established.

    `extra_sources` injects additional named versions — `{"where it came from": "version"}`.
    It exists so the disagreement path can be exercised against a real host that happens to
    agree with itself: a mismatch detector only ever tested on matching input has been tested
    for nothing.
    """
    seen: dict[str, list[dict[str, str]]] = {}
    by_source: dict[str, Any] = {}
    unavailable: list[dict[str, str]] = []
    running: list[str] = []

    def record(source: str, where: str, version: str | None, detail: str = "",
               *, running_stack: bool = False) -> None:
        if not version:
            return
        seen.setdefault(version, []).append(
            {"source": source, "where": where, "detail": detail})
        prev = by_source.get(source)
        if prev is None:
            by_source[source] = version
        elif isinstance(prev, list):
            if version not in prev:
                prev.append(version)
        elif prev != version:
            by_source[source] = [prev, version]
        if running_stack:
            running.append(version)

    # 1. the loaded kernel module, and the second file it publishes
    try:
        km = kernel_module()
        if km.get("loaded"):
            record("kernel module", km.get("source", _PROC_VERSION), km.get("version"),
                   f"the loaded {km.get('variant') or 'kernel'} module", running_stack=True)
            sysfs = km.get("sysfs") or {}
            record("kernel module (sysfs)", sysfs.get("source", _SYS_VERSION),
                   sysfs.get("version"), "a second file published by the same module",
                   running_stack=True)
        else:
            unavailable.append({"source": "kernel module",
                                "where": km.get("source", _PROC_VERSION),
                                "why": km.get("why", "no kernel module is loaded")})
    except Exception as e:                       # a source that fails is named, never dropped
        unavailable.append({"source": "kernel module", "where": _PROC_VERSION, "why": str(e)})

    # 2. userspace, by running the query tool
    try:
        us = userspace()
        for v in us.get("versions") or []:
            record("userspace", " ".join(us.get("argv") or [_QUERY_TOOL]), v,
                   "what the userspace stack answers when asked", running_stack=True)
    except Exception as e:
        unavailable.append({"source": "userspace", "where": _QUERY_TOOL, "why": str(e)})

    # 3. the libraries on disk, per architecture
    try:
        libs = libraries()
        for arch, group in (libs.get("by_arch") or {}).items():
            vs: dict[str, int] = {}
            for lib in group.get("libraries") or []:
                if lib.get("driver_version"):
                    vs[lib["driver_version"]] = vs.get(lib["driver_version"], 0) + 1
            for v, n in sorted(vs.items()):
                record(f"libraries ({arch})", group.get("dir", arch), v,
                       f"{n} versioned file(s) under {group.get('dir', arch)}",
                       running_stack=True)
    except Exception as e:
        unavailable.append({"source": "libraries", "where": ", ".join(_LIB_DIRS), "why": str(e)})

    # 4. the installed packages
    try:
        pkgs = packages()
        for v, names in sorted((pkgs.get("packages_at") or {}).items()):
            shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
            # The tool, not the whole argv: the query format carries tabs and a newline, and a
            # provenance line that breaks across three lines is a provenance line nobody reads.
            # The full argv is in `packages()`.
            record("packages", pkgs.get("tool") or _PACKAGE_TOOL, v,
                   f"{len(names)} package(s): {shown}")
    except Exception as e:
        unavailable.append({"source": "packages", "where": _PACKAGE_TOOL, "why": str(e)})

    # 5. anything the caller injected
    for where, v in (extra_sources or {}).items():
        record("injected", where, v, "supplied by the caller, not read from this host")

    versions = sorted(seen)
    agreed = len(versions) == 1 and not unavailable
    running_versions = sorted(set(running))
    odd: list[dict[str, Any]] = []
    if len(versions) > 1:
        majority = max(versions, key=lambda v: len(seen[v]))
        for v in versions:
            if v == majority:
                continue
            for s in seen[v]:
                odd.append({**s, "version": v, "against": majority})
    else:
        majority = versions[0] if versions else None

    if agreed:
        why = (f"every source agrees on {versions[0]}: "
               + "; ".join(f"{s} ({v})" for s, v in sorted(
                   (k, vv if isinstance(vv, str) else ", ".join(vv))
                   for k, vv in by_source.items())))
    elif not versions:
        why = ("no source reported a version at all. "
               + "; ".join(f"{u['source']}: {u['why']}" for u in unavailable))
    elif len(versions) > 1:
        why = (f"{len(versions)} different versions are installed on this host: "
               f"{', '.join(versions)}. "
               + "; ".join(f"{d['source']} at {d['where']} says {d['version']}"
                           + (f" — {d['detail']}" if d.get("detail") else "")
                           + f", against {d['against']}" for d in odd)
               + (f". The running stack — loaded module, userspace and the libraries — is "
                  f"itself coherent at {running_versions[0]}, so what disagrees is installed "
                  f"rather than loaded" if len(running_versions) == 1 else ""))
    else:
        why = (f"every source that could be read agrees on {versions[0]}, but "
               f"{len(unavailable)} source(s) could not be read, so agreement was not "
               f"established")

    # An unreadable source is named in `why` whatever else `why` had to say. Agreement among
    # the sources that answered is not agreement; it is a smaller question than the one asked.
    if unavailable:
        why += (". Sources that could not be read: "
                + "; ".join(f"{u['source']} ({u['where']}): {u['why']}" for u in unavailable))

    return {
        "consistent": agreed,
        "versions": versions,
        "sources": seen,
        "by_source": by_source,
        "disagreements": odd,
        "unavailable": unavailable,
        "majority": majority,
        "running_stack": {
            "members": ["kernel module", "kernel module (sysfs)", "userspace", "libraries"],
            "versions": running_versions,
            "consistent": len(running_versions) == 1,
        },
        "driver_series": _DRIVER_SERIES.pattern,
        "why": why,
    }
