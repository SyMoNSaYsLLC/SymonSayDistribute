# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Answering §3.1b-i from disk instead of from memory.

THE RULE THIS SERVES
--------------------
A prospect names its sources first, and its licence is READ off them — "not chosen, not
preferred, not assumed: read." Reaching for a copyleft source is a claim that no permissive
variant of the capability exists, and that claim has to carry a record of what was searched.

That record is what this produces. `permissive()` returns the three buckets and the query it
actually ran, so "no permissive variant exists" stops being an assertion and becomes a query
somebody else can run again.

THIS IS A SURFACE, NOT A REIMPLEMENTATION
-----------------------------------------
The index, the fingerprinter, the matcher and the layer resolver are oematch — first-party,
MIT, `Copyright: 2026 SymonSays LLC`, written by Garrett. This module resolves that package,
reports which copy answered, and calls it. It re-derives none of it. The only logic here that
oematch does not have is the licence CLASSIFICATION and the ordering that follows from it,
because that is the estate's rule rather than the tool's job.

WHY THE CORPUS IS OPENED `mode=ro`
----------------------------------
oematch's own `db.connect()` opens read-write and runs `CREATE TABLE IF NOT EXISTS` plus a
migration pass. Measured 2026-09-19 against a copy: `oematch --db <copy> stats` left the file
byte-identical (sha256 unchanged), so nothing was observed to be written. The handle was still
a writable one. A read path that CANNOT write is worth more than a read path that merely did
not, so every connection here is a `file:...?mode=ro` URI and a test asserts an INSERT raises.

WHAT A BLANK LICENCE MEANS
--------------------------
6786 of 39507 recipes carry no licence string at all. Under §3.1b-i an unlicensed candidate is
"not a prospect yet, it is a question", so a blank licence is classified UNLICENSED and can
never sort or bucket as permissive. The same applies to a licence string this module does not
recognise, and to `LicenseRef-*`, which names a licence text living in the recipe rather than
on the SPDX list — reading it means reading that file, which this does not do. Over-flagging
costs a manual check; under-flagging is the failure the rule exists to stop.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path.home() / ".cache/oematch/corpus.db"

# Every public callable here is routed in service.py or named below with the reason it is not.
# `endpoints-current` refuses silence: a capability is exposed, or it is deliberately not, and
# not deciding is what produced a whole release of unreachable arithmetic once.
NOT_EXPOSED = {
    "connect": "hands back an open sqlite3 connection. There is no honest way to return a "
               "database handle over HTTP, and every route that needs one opens its own. It "
               "is public so the rest of the estate can reuse the read-only opener rather "
               "than writing a second one that forgets the mode=ro",
    "db_path": "resolves SYM_OEMATCH_DB to a path; its result is reported inside GET "
               "/api/symonoematch/freshness, beside the size and age of what was found "
               "there — a caller wants the corpus, not where this process looked for it",
}


class CorpusError(Exception):
    """The corpus could not be read, carrying the path that was tried."""


class ToolError(Exception):
    """oematch could not be resolved or could not answer, carrying what was looked for."""


# ---------------------------------------------------------------- the corpus, read-only

def db_path() -> Path:
    return Path(os.environ.get("SYM_OEMATCH_DB") or DEFAULT_DB).expanduser()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the corpus read-only. A query can never write, by construction rather than care."""
    p = Path(path) if path is not None else db_path()
    if not p.is_file():
        raise CorpusError(
            f"no corpus at {p}. SYM_OEMATCH_DB names it; the default is {DEFAULT_DB}. "
            f"It is rebuilt with `oematch build` (see GET /api/symonoematch/rebuild_plan), "
            f"which fetches from the network and is never run by this service")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@contextlib.contextmanager
def _ro(path: Path | str | None = None):
    """A read-only connection that is always closed.

    `sqlite3.Connection` used as a context manager manages a TRANSACTION and leaves the
    handle open. Every route here opens one to answer and a second to stamp the corpus age,
    so relying on that would leak two descriptors per request.
    """
    con = connect(path)
    try:
        yield con
    finally:
        con.close()


def _has_kind(con: sqlite3.Connection) -> bool:
    """A corpus indexed before the `kind` column existed has no bb/bbappend split.

    A `.bbappend` MODIFIES a recipe another layer provides; it does not provide one. Filtering
    to `kind='bb'` is therefore right for "what provides this capability" — but a corpus built
    by an older index does not carry the column, and a query naming it would raise rather than
    answer. So the filter is applied when the column is there and dropped when it is not.
    """
    return "kind" in {r[1] for r in con.execute("PRAGMA table_info(recipes)")}


def _freshness(con: sqlite3.Connection, p: Path) -> dict[str, Any]:
    st = p.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
    return {
        "path": str(p),
        "bytes": st.st_size,
        "dated": mtime.date().isoformat(),
        "indexed_utc": mtime.isoformat(),
        "age_days": round((time.time() - st.st_mtime) / 86400.0, 2),
        "layers": con.execute("SELECT count(*) FROM layers").fetchone()[0],
        "recipes": con.execute("SELECT count(*) FROM recipes").fetchone()[0],
    }


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    """Every answer carries the corpus's age.

    An index is a photograph of upstream, and a reader who cannot see when it was taken will
    read it as now. The age travels with the answer rather than living on one route nobody
    calls, because the mistake is made at the point of reading a result.
    """
    try:
        p = db_path()
        with _ro(p) as con:
            f = _freshness(con, p)
        payload["corpus"] = {"dated": f["dated"], "age_days": f["age_days"], "path": f["path"]}
    except CorpusError as e:
        payload["corpus"] = {"error": str(e)}
    return payload


# ---------------------------------------------------------------- licence classification

# WITH <exception> does not change a licence's class: `Apache-2.0 WITH LLVM-exception` is
# Apache-2.0 with a carve-out, and `GPL-2.0-only WITH Classpath-exception` is still GPL.
_WITH_RE = re.compile(r"\s+WITH\s+.*$", re.I)
# OR and AND need whitespace on BOTH sides, because the SPDX operators are whitespace-delimited
# and a hyphen is a regex word boundary: `\bOR\b` matches the `or` inside `GPL-2.0-or-later` and
# shreds it into `GPL-2.0-` and `-later`.
#
# MEASURED, 2026-09-19, over all 1613 distinct licence strings in the corpus, one regex at a
# time — because the reason to require the whitespace is not the one it first appears to be:
#
#   AND, strict vs `\bAND\b`:  7 strings, 8 recipes differ. All are unexpanded bitbake
#       expressions beginning with a bare `AND `, which the loose form reads a licence out of
#       and the strict form leaves a question. A fragment is a question.
#   OR,  strict vs `\bOR\b`:   0 strings differ. `GPL-2.0-or-later` DOES shred into `GPL-2.0-`
#       and `-later`, and it changes no answer, because the copyleft rule below matches `gpl`
#       by CONTAINMENT — the fragment still classifies copyleft. That containment is load
#       bearing rather than incidental, and a test pins it.
#
# So the OR case is guarded against something no recipe here exhibits: a hyphenated name whose
# left fragment is permissive and whose right is not, `MIT-or-GPL-2.0`, which the loose form
# calls permissive. Constructed, not observed, and the test that pins it says so.
_ALT_RE = re.compile(r"\s+OR\s+|\s*\|\s*", re.I)
_CONJ_RE = re.compile(r"\s+AND\s+|\s*&\s*|\s*,\s*", re.I)

# Prefix families, matched case-insensitively against a normalised term. A family is used
# rather than an exact list because the corpus carries 1613 distinct licence strings and 861
# distinct terms; an exact list would silently answer "question" for most of them.
_PERMISSIVE = (
    "mit", "bsd", "0bsd", "isc", "apache", "zlib", "libpng", "png", "psf", "python",
    "blessing", "unlicense", "cc0", "bsl", "boost", "ncsa", "x11", "ftl", "ijg",
    "openssl", "curl", "hpnd", "icu", "w3c", "zope", "afl", "wtfpl", "bzip2", "php",
    "sunpro", "miros", "fair", "beerware", "xnet", "libtiff", "mpich2", "postgresql",
    "public-domain", "publicdomain", "sqlite",
)
_PERMISSIVE_EXACT = {"pd", "pddl", "sissl-permissive", "dual-bsd-gpl-permissive-arm"}
# Reciprocal in any degree. GPL is matched by CONTAINMENT so LGPL, AGPL, GPLv2, GPLv2+ and
# LicenseRef-KDE-Accepted-LGPL are all caught by one rule rather than by enumerating spellings.
_COPYLEFT_CONTAINS = ("gpl",)
_COPYLEFT = (
    "mpl", "epl", "cddl", "cpl", "osl", "eupl", "cecill", "qpl", "sissl", "rpl", "apsl",
    "sleepycat", "ipl", "npl", "ms-rl", "artistic", "gfdl", "cc-by-sa", "ccbysa", "erpl",
    "opl", "sspl", "ypl", "rscpl", "nposl", "cpal", "watcom", "vim",
)
# Not free, not copyleft, and certainly not a prospect. Named separately from "unknown" so a
# reader sees the difference between "nobody said" and "somebody said no".
_CLOSED = ("closed", "proprietary", "commercial", "noncommercial", "non-commercial",
           "licenseref-proprietary", "nonfree", "restricted", "evaluation")

PERMISSIVE, COPYLEFT, UNLICENSED = "permissive", "copyleft", "unlicensed"


def _term_class(term: str) -> str:
    t = _WITH_RE.sub("", term).strip().strip("()").strip().rstrip("+").lower()
    if not t:
        return "blank"
    if any(c in t for c in _CLOSED):
        return "closed"
    if any(c in t for c in _COPYLEFT_CONTAINS):
        return COPYLEFT
    if t.startswith(_COPYLEFT):
        return COPYLEFT
    # A LicenseRef- names a licence TEXT carried in the recipe rather than an SPDX identifier.
    # Reading it means reading that file. This does not, so it does not claim to know.
    if t.startswith("licenseref-"):
        return "unknown"
    if t in _PERMISSIVE_EXACT or t.startswith(_PERMISSIVE):
        return PERMISSIVE
    return "unknown"


def _classify(licence: str | None) -> str:
    """The precise class of a licence expression: the value that goes on every row.

    OR and AND are different operators and the difference decides the answer:

        Apache-2.0 OR MPL-2.0                 -> permissive; the permissive arm may be taken
        GPL-2.0-only AND LGPL-2.1-or-later    -> copyleft;   both apply, so the strictest wins
        BSD-3-Clause AND IJG AND Zlib         -> permissive; every term is permissive
    """
    s = (licence or "").replace("(", " ").replace(")", " ").strip()
    if not s:
        return "blank"
    verdicts = set()
    for alt in _ALT_RE.split(s):
        terms = [t for t in (x.strip() for x in _CONJ_RE.split(alt)) if t]
        if not terms:
            continue
        classes = {_term_class(t) for t in terms}
        # Inside one alternative every term applies at once, so one copyleft term makes the
        # whole alternative copyleft. glibc is `GPL-2.0-only AND LGPL-2.1-or-later`, and
        # reading that as permissive because a permissive term appears is how a copyleft
        # obligation gets into a shipped artifact.
        if COPYLEFT in classes:
            verdicts.add(COPYLEFT)
        elif "closed" in classes:
            verdicts.add("closed")
        elif classes == {PERMISSIVE}:
            verdicts.add(PERMISSIVE)
        else:
            verdicts.add("unknown")
    if PERMISSIVE in verdicts:
        return PERMISSIVE
    if COPYLEFT in verdicts:
        return COPYLEFT
    if "closed" in verdicts:
        return "closed"
    return "unknown"


def _bucket(cls: str) -> str:
    """The three buckets §3.1b-i asks for. Anything that is not a read permissive licence and
    not a read copyleft licence is a QUESTION, and questions all sit together."""
    return cls if cls in (PERMISSIVE, COPYLEFT) else UNLICENSED


_ORDER = {PERMISSIVE: 0, UNLICENSED: 1, COPYLEFT: 2}


# ---------------------------------------------------------------- full-text search

# Requires a leading alphanumeric so a fragment of punctuation cannot become an empty FTS
# phrase, which is a syntax error rather than an empty result.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]+")
MAX_TERMS = 16


def _fts_query(text: str) -> str:
    """The query string that is actually handed to FTS5, and the one reported as `searched`.

    §3.1b-i requires the record to say WHAT WAS SEARCHED, not only what was concluded. A
    caller's words and the query that ran are not the same string — terms are quoted, split
    and bounded — so the executed one is what gets reported.
    """
    toks = _TOKEN_RE.findall(text or "")
    if not toks:
        raise ValueError(f"nothing searchable in {text!r}: a term needs two characters "
                         f"starting with a letter or digit")
    return " ".join('"' + t.replace('"', '""') + '"' for t in toks[:MAX_TERMS])


_ROW_SQL = """
SELECT r.pn, r.pv, r.license AS licence, r.summary, r.homepage, r.src_uri, r.filepath,
       l.name AS layer, l.license AS layer_licence, l.vcs_url
FROM recipes_fts f
JOIN recipes r ON r.id = f.rowid
JOIN layers  l ON l.id = r.layer_id
WHERE recipes_fts MATCH ?{kind}
ORDER BY bm25(recipes_fts)
LIMIT ?
"""


def _search(con: sqlite3.Connection, q: str, scan: int) -> list[dict[str, Any]]:
    kind = " AND r.kind = 'bb'" if _has_kind(con) else ""
    rows = con.execute(_ROW_SQL.format(kind=kind), (q, scan)).fetchall()
    out = []
    for r in rows:
        cls = _classify(r["licence"])
        out.append({**{k: r[k] for k in r.keys()}, "licence_class": cls, "bucket": _bucket(cls)})
    return out


# ---------------------------------------------------------------- public: the corpus routes

def freshness() -> dict[str, Any]:
    """How old the index is, how big, and what is in it.

    The corpus is REBUILDABLE — `oematch build` re-pulls every layer from the layer index —
    so its age is a fact about this copy, not a property of the tool. See `rebuild_plan()`.
    """
    p = db_path()
    with _ro(p) as con:
        f = _freshness(con, p)
        f["recipes_indexed"] = con.execute("SELECT count(*) FROM recipes_fts").fetchone()[0]
        f["unlicensed_recipes"] = con.execute(
            "SELECT count(*) FROM recipes WHERE license IS NULL OR trim(license) = ''"
        ).fetchone()[0]
    f["rebuildable"] = True
    f["rebuilt_by"] = "oematch build — fetches from the network; this service never runs it"
    return f


def layers(q: str = "", limit: int = 100) -> dict[str, Any]:
    """Layers whose name contains `q`, with the licence the layer itself declares.

    `local_path_exists` is read from disk every time rather than trusted from the row. A
    layer's cached checkout is what an offline re-index reads, and a row pointing at a
    directory that is no longer there is the difference between "we have this" and "we had it".
    """
    limit = max(1, min(int(limit), 500))
    with _ro() as con:
        rows = con.execute(
            "SELECT name, license AS licence, vcs_url, branch, subdir, description, local_path "
            "FROM layers WHERE name LIKE ? ORDER BY name LIMIT ?",
            (f"%{q}%", limit)).fetchall()
        total = con.execute("SELECT count(*) FROM layers WHERE name LIKE ?", (f"%{q}%",)).fetchone()[0]
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        cls = _classify(d["licence"])
        d["licence_class"] = cls
        d["bucket"] = _bucket(cls)
        d["local_path_exists"] = bool(d["local_path"]) and Path(d["local_path"]).is_dir()
        out.append(d)
    return _stamp({"query": q, "matched": total, "returned": len(out), "layers": out})


def find(q: str, limit: int = 25) -> dict[str, Any]:
    """Recipes providing a capability, PERMISSIVE FIRST and copyleft last.

    The ordering is the rule, not a preference. §3.1b-i makes proprietary-with-permissive-
    sources the default and copyleft the exception that carries a burden of proof, so a result
    list that puts a GPL recipe at the top because it scored better on a text index is a list
    that argues for the exception. Within a class the index's own relevance order is kept.
    """
    limit = max(1, min(int(limit), 200))
    scan = max(limit * 20, 500)
    query = _fts_query(q)
    with _ro() as con:
        hits = _search(con, query, scan)
    hits.sort(key=lambda h: _ORDER[h["bucket"]])          # stable: bm25 order survives inside a class
    return _stamp({
        "asked": q, "searched": query, "scanned": len(hits), "scan_limit": scan,
        "complete": len(hits) < scan, "returned": min(limit, len(hits)),
        "order": "permissive, then unlicensed, then copyleft (§3.1b-i)",
        "results": hits[:limit],
    })


def licence_of(pn: str, limit: int = 100) -> dict[str, Any]:
    """Every recipe named `pn`, in every layer that carries one, with its licence.

    Several layers providing the same recipe under DIFFERENT licence strings is a real and
    important answer, so it is surfaced rather than collapsed to one row. It is how a capability
    that looks copyleft in the first layer searched turns out to be permissive in another —
    `sqlite3` is `blessing` in one layer, `PD` in a second and blank in a third — and collapsing
    it would delete the finding §3.1b-i exists to produce.
    """
    limit = max(1, min(int(limit), 500))
    with _ro() as con:
        kind = ", r.kind" if _has_kind(con) else ""
        rows = con.execute(
            f"SELECT r.pn, r.pv, r.license AS licence, r.homepage, r.src_uri, r.filepath{kind}, "
            f"       l.name AS layer, l.license AS layer_licence, l.vcs_url "
            f"FROM recipes r JOIN layers l ON l.id = r.layer_id "
            f"WHERE r.pn = ? COLLATE NOCASE ORDER BY l.name, r.pv LIMIT ?",
            (pn, limit)).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        cls = _classify(d["licence"])
        d["licence_class"] = cls
        d["bucket"] = _bucket(cls)
        out.append(d)
    strings = sorted({(d["licence"] or "") for d in out})
    buckets = sorted({d["bucket"] for d in out})
    return _stamp({
        "pn": pn, "found": len(out), "recipes": out,
        "distinct_licences": strings, "buckets": buckets,
        "disagrees": len(strings) > 1,
        "why": ("one licence across every layer that carries it" if len(strings) <= 1 else
                f"{len(strings)} different licence strings across {len(out)} recipes — read "
                f"the one belonging to the layer actually being built from"),
    })


def permissive(q: str, limit: int = 25) -> dict[str, Any]:
    """The §3.1b-i question, asked directly: is there a NON-COPYLEFT implementation of this?

    Returns the buckets AND `searched`. The rule requires the record to say what was looked at,
    because "no permissive variant exists" asserted from memory is the step Garrett named as the
    one that gets abused: "this should really never happen with all the available component
    source code available on the web and downloaded to the machine."

    A blank licence and an unrecognised one both land in `unlicensed`. Neither is evidence of
    anything yet — under §3.1b-i they are questions, and a question must never be counted as a
    permissive answer.
    """
    limit = max(1, min(int(limit), 200))
    # Deliberately generous, because a FALSE "no permissive variant" is the expensive error
    # here: it is the finding that sends a component to the open tree. The bound is reported so
    # a truncated search is never mistaken for an exhausted one.
    scan = 5000
    query = _fts_query(q)
    with _ro() as con:
        hits = _search(con, query, scan)
    groups: dict[str, list[dict[str, Any]]] = {PERMISSIVE: [], COPYLEFT: [], UNLICENSED: []}
    for h in hits:
        groups[h["bucket"]].append(h)
    return _stamp({
        "asked": q,
        "searched": query,
        "found": bool(groups[PERMISSIVE]),
        "verdict": ("a permissive implementation exists; the copyleft branch of §3.1b-i is not "
                    "reached" if groups[PERMISSIVE] else
                    "no PERMISSIVE recipe in this corpus matched. That is one search, not a "
                    "proof — widen the terms and search beyond the corpus before claiming no "
                    "non-copyleft variant exists"),
        "counts": {k: len(v) for k, v in groups.items()},
        "scanned": len(hits), "scan_limit": scan, "complete": len(hits) < scan,
        "unlicensed_means": "no licence string, or one this does not recognise (including "
                            "LicenseRef-*, whose text lives in the recipe). A question, never "
                            "a permissive answer",
        PERMISSIVE: groups[PERMISSIVE][:limit],
        COPYLEFT: groups[COPYLEFT][:limit],
        UNLICENSED: groups[UNLICENSED][:limit],
    })


def unlicensed(limit: int = 50) -> dict[str, Any]:
    """Recipes carrying no licence at all, and how many there are.

    The count is the point. 6786 of 39507 is the size of the gap between "the corpus says" and
    "the corpus knows", and a route that returned only rows would let a reader treat the gap as
    a handful of stragglers.
    """
    limit = max(1, min(int(limit), 500))
    with _ro() as con:
        blank = "(r.license IS NULL OR trim(r.license) = '')"
        total = con.execute(f"SELECT count(*) FROM recipes r WHERE {blank}").fetchone()[0]
        recipes = con.execute("SELECT count(*) FROM recipes").fetchone()[0]
        rows = con.execute(
            f"SELECT r.pn, r.pv, r.homepage, r.filepath, l.name AS layer, "
            f"       l.license AS layer_licence FROM recipes r JOIN layers l ON l.id = r.layer_id "
            f"WHERE {blank} ORDER BY l.name, r.pn LIMIT ?", (limit,)).fetchall()
    return _stamp({
        "count": total, "of_recipes": recipes,
        "share": round(total / recipes, 4) if recipes else 0.0,
        "returned": len(rows), "recipes": [{k: r[k] for k in r.keys()} for r in rows],
        "means": "not a prospect yet, a question (§3.1b-i). A blank licence is never permissive",
    })


# ---------------------------------------------------------------- oematch, resolved and run

_PKG_MODULES = ("__init__", "cli", "corpus", "db", "extract", "match", "upstream")
_loaded: dict[str, Any] = {}


def _roots() -> list[tuple[str, Path]]:
    """Where the oematch package may be, most specific first.

    SYM_OEMATCH_SRC names the directory CONTAINING the package, so the same variable works for
    a source checkout and for a placed branch.
    """
    out: list[tuple[str, Path]] = []
    src = os.environ.get("SYM_OEMATCH_SRC")
    if src:
        out.append(("src", Path(src).expanduser()))
    spec = importlib.util.find_spec("oematch")
    if spec and spec.origin:
        out.append(("installed", Path(spec.origin).parent.parent))
    return out


def _resolve() -> tuple[str, Path]:
    tried = []
    for kind, root in _roots():
        tried.append(str(root))
        if (root / "oematch" / "__init__.py").is_file():
            return kind, root
    raise ToolError(
        "oematch is not resolvable. SYM_OEMATCH_SRC names the directory CONTAINING the "
        "`oematch` package; failing that an installed one is used. Tried: "
        + (", ".join(tried) if tried else "nothing — SYM_OEMATCH_SRC unset and no installed "
                                          "package importable"))


@contextlib.contextmanager
def _no_bytecode():
    """Execute somebody else's modules without leaving `__pycache__` in their tree.

    Importing a module writes a `.pyc` beside it by default, and the tree oematch is resolved
    from is READ-ONLY to this component — it is Garrett's package, placed elsewhere and merely
    depended on. Reading it must not modify it. This was found the hard way on 2026-09-19: the
    loader below left six `.pyc` files in his source directory on its first run.
    """
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = prev


def _package(root: Path, modname: str):
    """Import one oematch module from `root` under a name unique to that root.

    Two copies of oematch exist on this host under the same version string, and they answer
    differently. Loading each under its own synthetic package name lets both be resolved in one
    process without `sys.modules` handing back whichever was imported first — which is how a
    report ends up describing a copy that did not answer.
    """
    tag = "oematch_" + hashlib.sha256(str(root).encode()).hexdigest()[:10]
    if tag not in _loaded:
        init = root / "oematch" / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            tag, init, submodule_search_locations=[str(root / "oematch")])
        if spec is None or spec.loader is None:
            raise ToolError(f"oematch at {root} could not be loaded")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[tag] = mod
        with _no_bytecode():
            spec.loader.exec_module(mod)
        _loaded[tag] = mod
    full = f"{tag}.{modname}"
    if full not in sys.modules:
        f = root / "oematch" / f"{modname}.py"
        if not f.is_file():
            raise ToolError(
                f"the resolved oematch at {root} has no `{modname}` module. The copy installed "
                f"as a package predates it; SYM_OEMATCH_SRC pointed at a copy that carries "
                f"{modname}.py answers this")
        spec = importlib.util.spec_from_file_location(full, f)
        if spec is None or spec.loader is None:
            raise ToolError(f"{f} could not be loaded")
        m = importlib.util.module_from_spec(spec)
        sys.modules[full] = m
        with _no_bytecode():
            spec.loader.exec_module(m)
    return sys.modules[full]


def _digest(root: Path) -> tuple[str, list[str]]:
    """A content fingerprint, because the version string does not distinguish the copies.

    Both copies on this host report `0.1.0` and they are not the same software: one carries
    `upstream.py` and a bb/bbappend filter, the other carries neither. A version that cannot
    tell two behaviours apart is not an identification, so the bytes are hashed.
    """
    h = hashlib.sha256()
    present = []
    for name in _PKG_MODULES:
        f = root / "oematch" / f"{name}.py"
        if f.is_file():
            present.append(name)
            h.update(name.encode())
            h.update(f.read_bytes())
    return h.hexdigest(), present


def _run(argv: list[str], root: Path, timeout: float) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    # The child imports the package too, and would write `__pycache__` into a tree this
    # component only reads. Same reason as `_no_bytecode`, one process further out.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(argv, capture_output=True, text=True, errors="replace",
                          timeout=timeout, env=env, check=False)


def tool(timeout_s: float = 30.0) -> dict[str, Any]:
    """Which oematch answered, what it says its version is, and what it can actually do.

    The version is read by RUNNING the resolved copy, not by importing a constant — and then
    reported beside a content digest and the verb list, because the version alone is known to
    be the same string for two copies that behave differently.
    """
    kind, root = _resolve()
    digest, present = _digest(root)
    argv = [sys.executable, "-m", "oematch.cli", "--version"]
    try:
        v = _run(argv, root, timeout_s)
    except subprocess.TimeoutExpired:
        raise ToolError(f"{' '.join(argv)} did not answer within {timeout_s}s from {root}")
    if v.returncode != 0:
        raise ToolError(f"{' '.join(argv)} exited {v.returncode} from {root}: "
                        f"{(v.stderr or v.stdout).strip()[:400]}")
    help_argv = [sys.executable, "-m", "oematch.cli", "--help"]
    h = _run(help_argv, root, timeout_s)
    m = re.search(r"\{([a-z,]+)\}", h.stdout or "")
    verbs = sorted(m.group(1).split(",")) if m else []
    warnings = []
    if "upstream" not in present:
        warnings.append("this copy has no upstream.py, so GET /api/symonoematch/upstream "
                        "refuses. Point SYM_OEMATCH_SRC at a copy that carries it")
    if "match" in present and "kind" not in (root / "oematch" / "match.py").read_text():
        warnings.append("this copy's matcher does not filter kind='bb', so .bbappend rows rank "
                        "as if they provided a recipe. An append modifies a recipe another "
                        "layer provides; it does not provide one")
    return _stamp({
        "resolved": kind, "root": str(root), "package": str(root / "oematch"),
        "version": (v.stdout or v.stderr).strip(),
        "version_read_by": " ".join(argv),
        "digest_sha256": digest, "modules": present, "verbs": verbs,
        "licence": "MIT, Copyright 2026 SymonSays LLC — first-party, wrapped not vendored",
        "warnings": warnings,
    })


def match(target: str, top: int = 25) -> dict[str, Any]:
    """Fingerprint a file or directory on disk and rank the recipes that provide what it uses.

    This is the route that answers §3.1b-i for something that already EXISTS. The other routes
    answer "what could provide this capability"; this one answers "what is this artifact
    actually made of, and what does each of those pieces oblige us to". Every ranked row
    carries its licence class, so a copyleft dependency is visible in the result rather than in
    a second pass nobody runs.

    The ranking is oematch's — its scores, its evidence, untouched. The licence class is added
    beside each row, not folded into the score: reordering somebody else's matcher would make
    its evidence stop explaining its order.

    THE FINGERPRINT PHASE IS UNBOUNDED, AND THERE IS NO TIMEOUT PARAMETER BECAUSE OF IT.
    `extract.fingerprint` extracts archives in-process: `_scan_deb` runs `dpkg-deb -R` through
    `subprocess.run` with no `timeout=`, and `_scan_archive` calls `tarfile.extractall`. Neither
    can be interrupted from here, so a malformed artifact hangs this call for as long as it
    hangs. A `timeout_s` argument was written and then removed: it could only have been checked
    AFTER the call it was supposed to bound, which is a bound that cannot bind — §3.1d, a check
    that cannot fail has gated nothing. The gap is named in the document instead, because it
    belongs to a package this component reads and does not modify.
    """
    top = max(1, min(int(top), 200))
    p = Path(target).expanduser()
    if not p.exists():
        raise ToolError(f"nothing to fingerprint at {p}")
    kind, root = _resolve()
    extract = _package(root, "extract")
    matcher = _package(root, "match")
    started = time.time()
    try:
        sig = extract.fingerprint(str(p))
    except SystemExit as e:                       # his fingerprinter exits on an unknown type
        raise ToolError(f"{p}: {e}")
    with _ro() as con:
        rows = matcher.Matcher(con).run(sig)
    out = []
    for r in rows[:top]:
        cls = _classify(r.get("recipe_license"))
        lcls = _classify(r.get("layer_license"))
        out.append({**r, "licence_class": cls, "bucket": _bucket(cls), "layer_licence_class": lcls})
    counts: dict[str, int] = {PERMISSIVE: 0, COPYLEFT: 0, UNLICENSED: 0}
    for r in out:
        counts[r["bucket"]] += 1
    return _stamp({
        "target": str(p), "kind": sig.kind, "tool": {"resolved": kind, "root": str(root)},
        "signals": {"sonames": sorted(sig.sonames), "deps": sorted(sig.pkg_deps),
                    "tools": sorted(sig.tools), "imports": sorted(sig.imports),
                    "urls": sorted(sig.urls)[:40]},
        "ranked": len(rows), "returned": len(out), "counts": counts,
        "took_s": round(time.time() - started, 2),
        "order": "oematch's score, unchanged — the licence class is reported beside it, "
                 "never folded into it",
        "matches": out,
    })


def upstream(url: str, top: int = 8) -> dict[str, Any]:
    """Which layer carries this upstream project, asked by repository URL.

    §3.1b-i step 1 is "name the sources". This is that step run backwards: given the upstream
    a component would be built from, it says which layer already carries it and under which
    licence — so the licence is READ off a named source instead of chosen.
    """
    top = max(1, min(int(top), 50))
    if not (url or "").strip():
        raise ValueError("a repository URL is required")
    kind, root = _resolve()
    up = _package(root, "upstream")
    with _ro() as con:
        res = up.resolve(con, url, top)
    for r in res.get("matches", []):
        cls = _classify(r.get("recipe_license"))
        r["licence_class"] = cls
        r["bucket"] = _bucket(cls)
    return _stamp({
        "url": url, "tool": {"resolved": kind, "root": str(root)},
        "matches": res.get("matches", []), "appends": res.get("appends", []),
        "why_appends_are_separate": "a .bbappend MODIFIES a recipe another layer provides; it "
                                    "is a different answer, not a weaker one",
        "found": bool(res.get("matches") or res.get("appends")),
    })


def rebuild_plan() -> dict[str, Any]:
    """What rebuilding the corpus WOULD do. It is never done from here.

    The corpus is regenerable — that is the whole reason its age is a fact about this copy
    rather than a limit on the component. But `build` clones every layer in the layer index,
    which is tens of minutes and gigabytes of network, and a GET that does that is a GET that
    takes the machine down for anyone who curls it out of curiosity. So this reports the
    command and the operator runs it.
    """
    try:
        kind, root = _resolve()
        where: dict[str, Any] = {"resolved": kind, "root": str(root)}
    except ToolError as e:
        where = {"error": str(e)}
    layers_root = Path(os.environ.get("OEMATCH_LAYERS") or (Path.home() / ".cache/oematch/layers"))
    return _stamp({
        "runs": False,
        "why_not": "it clones every layer in the layer index. This service never fetches from "
                   "the network on a request; an operator runs the command below",
        "tool": where,
        "full": ["oematch", "--db", str(db_path()), "build"],
        "subset": ["oematch", "--db", str(db_path()), "build", "--only",
                   "openembedded-core", "meta-oe", "meta-python"],
        "offline_reindex": ["oematch", "--db", str(db_path()), "build", "--no-fetch"],
        "adds_local_layers": ["oematch", "--db", str(db_path()), "add", "<layer-dir>", "..."],
        "writes": {"database": str(db_path()), "layer_checkouts": str(layers_root)},
        "network": True,
    })
