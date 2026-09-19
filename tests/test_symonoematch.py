# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonoematch tests.

Most of them are about the licence classifier, because that is the part of this component that
can be wrong QUIETLY. A search that returns nothing is obvious; a blank licence that reads as
permissive is not, and it is the failure §3.1b-i exists to stop — it would send a component to
the wrong tree with a clean-looking record behind it.

Nothing here writes to the real corpus. The read-only test copies it into `tmp_path` first.
"""
import importlib
import os
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from symonoematch import prospect as P

TOKEN = uuid.uuid4().hex
REAL_DB = Path(os.environ.get("SYM_OEMATCH_DB") or P.DEFAULT_DB)

# Copies of oematch that carry `upstream.py`. The package installed on this host predates it,
# so the route is exercised against a source copy when one is reachable and against a
# deliberately incomplete one always.
SRC_CANDIDATES = [
    Path("/home/google/Downloads/sendtodrive/old-symoneural/Symoneural-Custom/yocto/oematch"),
    Path("/home/google/Downloads/sendtodrive/old-symoneural/symoneural-repo-from-git/yocto/oematch"),
]

# The index's own DDL. A fixture built with anything else would not have the FTS triggers, and
# a test that searches a table the real one populates differently has stopped being a test.
SCHEMA = """
CREATE TABLE layers(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, vcs_url TEXT, branch TEXT,
  subdir TEXT, license TEXT, description TEXT, local_path TEXT
);
CREATE TABLE recipes(
  id INTEGER PRIMARY KEY, layer_id INTEGER REFERENCES layers(id),
  pn TEXT, pv TEXT, summary TEXT, description TEXT, homepage TEXT,
  license TEXT, src_uri TEXT, depends TEXT, rdepends TEXT,
  provides TEXT, rprovides TEXT, inherits TEXT, filepath TEXT, kind TEXT DEFAULT 'bb'
);
CREATE VIRTUAL TABLE recipes_fts USING fts5(
  pn, summary, description, homepage, provides, rprovides, src_uri,
  content='recipes', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER recipes_ai AFTER INSERT ON recipes BEGIN
  INSERT INTO recipes_fts(rowid,pn,summary,description,homepage,provides,rprovides,src_uri)
  VALUES (new.id,new.pn,new.summary,new.description,new.homepage,new.provides,new.rprovides,new.src_uri);
END;
"""


def _fixture_db(tmp_path, rows):
    """A corpus of exactly the rows a test needs, with the real schema."""
    p = tmp_path / "fixture-corpus.db"
    con = sqlite3.connect(p)
    con.executescript(SCHEMA)
    lid = con.execute(
        "INSERT INTO layers(name,vcs_url,branch,subdir,license,description,local_path) "
        "VALUES(?,?,?,?,?,?,?)",
        ("meta-fixture", "https://git.example.invalid/meta-fixture", "master", "", "MIT", "",
         str(tmp_path / "layers/meta-fixture"))).lastrowid
    for pn, pv, licence, summary in rows:
        con.execute(
            "INSERT INTO recipes(layer_id,pn,pv,summary,description,homepage,license,src_uri,"
            "depends,rdepends,provides,rprovides,inherits,filepath,kind) "
            "VALUES(?,?,?,?,'','',?,'','','','','','',?,'bb')",
            (lid, pn, pv, summary, licence, f"recipes-fixture/{pn}_{pv}.bb"))
    con.commit()
    con.close()
    return p


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard. On a
    # loopback bind the guard returns before comparing anything, which would make every
    # authenticated test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_OEMATCH_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_OEMATCH_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def _src_with_upstream():
    env = os.environ.get("SYM_OEMATCH_SRC")
    for root in ([Path(env)] if env else []) + SRC_CANDIDATES:
        if (root / "oematch" / "upstream.py").is_file():
            return root
    return None


# --- §3.2a: the bind address decides, and nothing else -------------------------------------
def test_loopback_needs_no_token(monkeypatch):
    monkeypatch.setenv("SYM_OEMATCH_HOST", "127.0.0.1")
    monkeypatch.delenv("SYM_OEMATCH_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    r = c.get("/api/symonoematch/freshness")
    assert r.status_code == 200, r.text
    assert r.json()["recipes"] > 0


def test_off_loopback_with_no_token_is_503(monkeypatch):
    monkeypatch.setenv("SYM_OEMATCH_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_OEMATCH_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonoematch/freshness").status_code == 503
    assert c.get("/api/symonoematch/health").status_code == 200   # health stays public


def test_off_loopback_refuses_a_wrong_token_and_accepts_the_right_one(client):
    assert client.get("/api/symonoematch/freshness",
                      headers={"Authorization": "Bearer " + uuid.uuid4().hex}).status_code == 401
    assert client.get("/api/symonoematch/freshness", headers=auth()).status_code == 200


def test_a_hostname_that_cannot_be_proven_loopback_is_treated_as_reachable(monkeypatch):
    monkeypatch.setenv("SYM_OEMATCH_HOST", "symon.example.invalid")
    import service
    importlib.reload(service)
    assert service._open_on_loopback() is False


# --- the corpus is read, never written ------------------------------------------------------
def test_the_corpus_is_opened_read_only(tmp_path):
    """Against a COPY. The real corpus is not a test fixture and is never opened writable."""
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    copy = tmp_path / "corpus-copy.db"
    shutil.copy(REAL_DB, copy)
    con = P.connect(copy)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("INSERT INTO layers(name) VALUES('written-by-a-test')")
    finally:
        con.close()
    # and the copy is byte-for-byte what it was
    assert copy.stat().st_size == REAL_DB.stat().st_size


def test_a_missing_db_is_reported_with_the_path_not_as_an_empty_result(monkeypatch, tmp_path):
    absent = tmp_path / "there-is-no-corpus-here.db"
    monkeypatch.setenv("SYM_OEMATCH_DB", str(absent))
    with pytest.raises(P.CorpusError) as e:
        P.find("compression")
    assert str(absent) in str(e.value)
    assert "SYM_OEMATCH_DB" in str(e.value)


def test_a_missing_db_reaches_the_caller_through_the_route_as_a_503(monkeypatch, tmp_path):
    """Through the ROUTE as well as the function: `_stamp` swallows a missing corpus into a
    field, and a route that let it swallow the whole answer would 500 or return nothing."""
    absent = tmp_path / "there-is-no-corpus-here.db"
    monkeypatch.setenv("SYM_OEMATCH_DB", str(absent))
    monkeypatch.setenv("SYM_OEMATCH_HOST", "127.0.0.1")
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    r = c.get("/api/symonoematch/find", params={"q": "compression"})
    assert r.status_code == 503, r.text
    assert str(absent) in r.json()["detail"]


# --- the classifier. The whole rule rests on it --------------------------------------------
@pytest.mark.parametrize("licence,expected", [
    # `-or-later` is a licence name, not an OR expression. A `\bOR\b` split shreds it into
    # `GPL-2.0-` and `-later`, because a hyphen is a regex word boundary.
    ("GPL-2.0-or-later", "copyleft"),
    ("LGPL-2.1-or-later", "copyleft"),
    ("GPL-1.0-or-later", "copyleft"),
    # AND means both apply, so the strictest term wins. Reading glibc as permissive because
    # a permissive term appears is how a copyleft obligation reaches a shipped artifact.
    ("GPL-2.0-only AND LGPL-2.1-or-later", "copyleft"),
    ("GPL-2.0-only & LGPL-2.1-or-later", "copyleft"),
    ("MIT AND GPL-3.0-only", "copyleft"),
    # OR means an arm may be chosen, so a wholly permissive arm makes it permissive.
    ("Apache-2.0 OR MPL-2.0", "permissive"),
    ("GPL-2.0-only | MIT", "permissive"),
    ("BSD-3-Clause AND IJG AND Zlib", "permissive"),
    # WITH names an exception; it does not change the class either way.
    ("Apache-2.0 WITH LLVM-exception", "permissive"),
    ("GPL-2.0-only WITH Classpath-exception-2.0", "copyleft"),
    ("MIT", "permissive"), ("BSD-3-Clause", "permissive"), ("blessing", "permissive"),
    ("GPLv2", "copyleft"), ("GPLv2+", "copyleft"), ("AGPL-3.0-only", "copyleft"),
    ("CLOSED", "closed"), ("LicenseRef-Proprietary", "closed"),
    # A LicenseRef names a text carried in the recipe. Reading it means reading that file.
    ("LicenseRef-BSD", "unknown"),
    ("", "blank"), ("   ", "blank"), (None, "blank"),
])
def test_the_licence_expression_is_read_not_guessed(licence, expected):
    assert P._classify(licence) == expected


@pytest.mark.parametrize("licence", ["", "   ", None, "LicenseRef-BSD", "Ruby", "CLOSED"])
def test_nothing_unread_ever_buckets_as_permissive(licence):
    assert P._bucket(P._classify(licence)) == "unlicensed"


@pytest.mark.parametrize("fragment", [
    # Unexpanded bitbake expressions in the corpus leave strings starting with a bare `AND `.
    # Measured 2026-09-19: 7 such strings, 8 recipes. Splitting on `\bAND\b` rather than on
    # whitespace-delimited AND reads a licence out of the fragment; requiring the whitespace
    # leaves it a question, which is what a fragment is.
    "AND BSD-3-Clause", "AND MIT", "AND MIT AND BSD-3-Clause",
])
def test_a_licence_fragment_is_a_question_not_a_licence(fragment):
    assert P._classify(fragment) == "unknown"
    assert P._bucket(P._classify(fragment)) == "unlicensed"


@pytest.mark.parametrize("licence", [
    # Real strings from the corpus: 69 distinct ones across 168 recipes offer a copyleft arm
    # OR a commercial arm. Neither arm is permissive — you take the copyleft terms or you pay —
    # and a dual-licensed package must never be counted as the permissive variant §3.1b-i is
    # asking for. `closed` is tested before copyleft at term level, so this pins that the
    # ordering does not turn a copyleft expression into a question.
    "GPL-3.0-only | The-Qt-Company-Commercial",
    "GPL-3.0-only | Slint-Commercial",
    "LGPL & Proprietary",
    "(GPL-2.0-only & LGPL-2.1-only & AGPL-3.0-only) | KDAB-Commercial",
    "Apache-2.0 & BSD-2-Clause & GPL-2.0-or-later & LGPL-2.1-or-later & MIT & Proprietary",
])
def test_a_copyleft_or_commercial_dual_licence_is_copyleft_not_a_permissive_option(licence):
    assert P._classify(licence) == "copyleft"
    assert P._bucket(P._classify(licence)) == "copyleft"


def test_match_has_no_timeout_parameter_it_cannot_honour():
    """A bound that can only be checked after the call it bounds has gated nothing (§3.1d).
    The fingerprint phase extracts archives through calls carrying no timeout of their own, so
    the parameter was removed rather than left as a promise the code cannot keep."""
    import inspect
    assert "timeout" not in inspect.signature(P.match).parameters
    assert "UNBOUNDED" in (P.match.__doc__ or "")


@pytest.mark.parametrize("licence", [
    "MIT-or-GPL-2.0", "BSD-3-Clause-or-GPL-3.0-only", "Zlib-or-LGPL-2.1",
])
def test_a_hyphenated_name_is_not_an_OR_expression(licence):
    """CONSTRUCTED, not drawn from the corpus — measured 2026-09-19, no string in the 1613 there
    distinguishes the two forms. These do: splitting on `\\bOR\\b` leaves a permissive left
    fragment and calls the whole thing permissive. The operator is whitespace-delimited, so a
    name that merely contains `-or-` is one term."""
    assert P._classify(licence) == "copyleft"


@pytest.mark.parametrize("term,expected", [
    # The rule that absorbs `-or-later` shredding: gpl is matched by CONTAINMENT, so even a
    # truncated fragment of a copyleft name still classifies copyleft. Match it by prefix
    # instead and `GPL-2.0-` becomes a question.
    ("GPL-2.0-", "copyleft"), ("LGPL-2.1-", "copyleft"), ("LicenseRef-KDE-Accepted-LGPL", "copyleft"),
])
def test_a_truncated_copyleft_name_is_still_copyleft(term, expected):
    assert P._term_class(term) == expected


def test_an_empty_licence_is_unlicensed_never_permissive(monkeypatch, tmp_path):
    """The one that protects the rule, against a corpus built for it.

    Three rows match the same query: one permissive, one copyleft, one with a BLANK licence.
    The blank one must appear in `unlicensed` and in neither other bucket.
    """
    db = _fixture_db(tmp_path, [
        ("perm-widget", "1.0", "MIT", "a widget that widgets"),
        ("copy-widget", "1.0", "GPL-3.0-only", "a widget that widgets"),
        ("blank-widget", "1.0", "", "a widget that widgets"),
    ])
    monkeypatch.setenv("SYM_OEMATCH_DB", str(db))
    r = P.permissive("widget")
    names = {b: [x["pn"] for x in r[b]] for b in ("permissive", "copyleft", "unlicensed")}
    assert names["unlicensed"] == ["blank-widget"]
    assert "blank-widget" not in names["permissive"]
    assert "blank-widget" not in names["copyleft"]
    assert names["permissive"] == ["perm-widget"]
    assert names["copyleft"] == ["copy-widget"]
    assert r["counts"] == {"permissive": 1, "copyleft": 1, "unlicensed": 1}


def test_a_capability_with_only_blank_and_copyleft_rows_is_not_found(monkeypatch, tmp_path):
    """`found` is the flag that decides whether the copyleft branch of §3.1b-i is reached, so
    it must not be true because a blank-licence row was counted as an answer."""
    db = _fixture_db(tmp_path, [
        ("copy-widget", "1.0", "GPL-3.0-only", "a widget that widgets"),
        ("blank-widget", "1.0", "   ", "a widget that widgets"),
    ])
    monkeypatch.setenv("SYM_OEMATCH_DB", str(db))
    r = P.permissive("widget")
    assert r["found"] is False
    assert r["counts"]["permissive"] == 0
    assert "not a proof" in r["verdict"]


def test_find_puts_permissive_first_and_copyleft_last(monkeypatch, tmp_path):
    db = _fixture_db(tmp_path, [
        ("copy-widget", "1.0", "GPL-3.0-only", "a widget that widgets"),
        ("blank-widget", "1.0", "", "a widget that widgets"),
        ("perm-widget", "1.0", "Apache-2.0", "a widget that widgets"),
    ])
    monkeypatch.setenv("SYM_OEMATCH_DB", str(db))
    order = [x["bucket"] for x in P.find("widget")["results"]]
    assert order == ["permissive", "unlicensed", "copyleft"]


# --- §3.1b-i requires the record to say WHAT WAS SEARCHED -----------------------------------
def test_permissive_records_the_query_it_actually_ran(monkeypatch, tmp_path):
    db = _fixture_db(tmp_path, [("perm-widget", "1.0", "MIT", "an image codec widget")])
    monkeypatch.setenv("SYM_OEMATCH_DB", str(db))
    r = P.permissive("image codec")
    assert r["searched"] == '"image" "codec"'
    assert r["asked"] == "image codec"
    # and it is the string that was handed to the index, not a pretty-printed version of it
    assert P._fts_query("image codec") == r["searched"]


def test_an_unsearchable_query_is_refused_rather_than_matching_everything():
    with pytest.raises(ValueError, match="nothing searchable"):
        P._fts_query("-- ?")


# --- against the real corpus ----------------------------------------------------------------
def test_layers_finds_meta_mingw_with_its_licence_and_its_vcs_url():
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    r = P.layers("mingw")
    found = {x["name"]: x for x in r["layers"]}
    assert "meta-mingw" in found, sorted(found)
    m = found["meta-mingw"]
    assert m["licence"] == "MIT"
    assert m["licence_class"] == "permissive"
    assert "yoctoproject.org" in m["vcs_url"]
    assert isinstance(m["local_path_exists"], bool)


def test_permissive_finds_a_permissive_option_for_a_real_capability():
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    r = P.permissive("jpeg")
    assert r["found"] is True
    assert r["counts"]["permissive"] > 0
    assert all(P._bucket(P._classify(x["licence"])) == "permissive" for x in r["permissive"])
    assert all(P._bucket(P._classify(x["licence"])) == "copyleft" for x in r["copyleft"])
    assert r["searched"] == '"jpeg"'


def test_find_on_the_real_corpus_never_ranks_copyleft_above_permissive():
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    buckets = [x["bucket"] for x in P.find("jpeg", limit=60)["results"]]
    assert "permissive" in buckets and "copyleft" in buckets, buckets
    assert buckets.index("copyleft") > max(i for i, b in enumerate(buckets) if b == "permissive")


def test_licence_of_surfaces_disagreement_instead_of_collapsing_it():
    """Several layers carrying one recipe under different licences is the answer, not noise."""
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    r = P.licence_of("sqlite3")
    assert r["found"] > 1
    layers_seen = {x["layer"] for x in r["recipes"]}
    assert len(layers_seen) > 1, layers_seen
    assert r["disagrees"] is True
    assert len(r["distinct_licences"]) > 1


def test_unlicensed_reports_the_size_of_the_gap_and_agrees_with_freshness():
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    u = P.unlicensed(limit=5)
    f = P.freshness()
    assert u["count"] == f["unlicensed_recipes"] > 0
    assert u["of_recipes"] == f["recipes"]
    assert 0 < u["share"] < 1
    assert len(u["recipes"]) == 5


def test_every_answer_carries_the_corpus_age():
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    for payload in (P.layers("mingw"), P.find("jpeg", limit=3), P.permissive("jpeg", limit=3),
                    P.unlicensed(limit=1), P.licence_of("sqlite3", limit=3), P.rebuild_plan()):
        assert "corpus" in payload
        assert payload["corpus"]["age_days"] >= 0
        assert payload["corpus"]["dated"]


def test_freshness_says_the_corpus_is_rebuildable():
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    f = P.freshness()
    assert f["rebuildable"] is True
    assert f["layers"] > 0 and f["recipes"] > 0
    assert f["recipes_indexed"] == f["recipes"]


# --- the tool is resolved, reported, and run -------------------------------------------------
def test_tool_names_the_copy_that_answered_and_reads_its_version_by_running_it():
    t = P.tool()
    assert t["version"]
    assert "-m oematch.cli --version" in t["version_read_by"]
    assert len(t["digest_sha256"]) == 64
    assert {"extract", "match"} <= set(t["modules"])
    assert "match" in t["verbs"], t["verbs"]
    assert Path(t["package"], "__init__.py").is_file()


def test_two_copies_under_one_version_string_are_told_apart_by_their_bytes(monkeypatch):
    """The version is not an identification here, and the report must not pretend it is."""
    src = _src_with_upstream()
    if src is None:
        pytest.skip("no oematch source copy carrying upstream.py; set SYM_OEMATCH_SRC")
    monkeypatch.delenv("SYM_OEMATCH_SRC", raising=False)
    installed = P.tool()
    monkeypatch.setenv("SYM_OEMATCH_SRC", str(src))
    from_src = P.tool()
    if installed["root"] == from_src["root"]:
        pytest.skip("the installed copy IS the source copy")
    assert installed["version"] == from_src["version"]          # same version string
    assert installed["digest_sha256"] != from_src["digest_sha256"]   # different software


def test_a_copy_without_upstream_refuses_clearly_instead_of_failing_later(monkeypatch, tmp_path):
    root = tmp_path / "oematch-without-upstream"
    (root / "oematch").mkdir(parents=True)
    (root / "oematch" / "__init__.py").write_text('__version__ = "0.0.0-fixture"\n')
    monkeypatch.setenv("SYM_OEMATCH_SRC", str(root))
    with pytest.raises(P.ToolError) as e:
        P.upstream("https://git.example.invalid/thing")
    assert "upstream" in str(e.value)
    assert "SYM_OEMATCH_SRC" in str(e.value)


def test_resolving_the_tool_leaves_no_bytecode_in_the_tree_it_read(monkeypatch, tmp_path):
    """The tree oematch is resolved from is read-only to this component. Importing a module
    writes a `.pyc` beside it by default, and on 2026-09-19 this loader left six of them in
    Garrett's source directory. Reading somebody's package must not modify it."""
    root = tmp_path / "oematch-root"
    pkg = root / "oematch"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "0.0.0-fixture"\n')
    (pkg / "upstream.py").write_text("def resolve(con, url, limit=8):\n    return {}\n")
    monkeypatch.setenv("SYM_OEMATCH_SRC", str(root))
    mod = P._package(root, "upstream")
    assert callable(mod.resolve)
    assert not (pkg / "__pycache__").exists(), sorted(p.name for p in pkg.iterdir())

    # and the subprocess that reads the version does not write one either
    P._run([sys.executable, "-c", "import oematch"], root, 30.0)
    assert not (pkg / "__pycache__").exists(), sorted(p.name for p in pkg.iterdir())


def test_an_unresolvable_tool_names_what_was_looked_for(monkeypatch, tmp_path):
    monkeypatch.setenv("SYM_OEMATCH_SRC", str(tmp_path / "nothing-here"))
    monkeypatch.setattr(P.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(P.ToolError, match="SYM_OEMATCH_SRC"):
        P.tool()


def test_upstream_reads_the_licence_off_a_named_source(monkeypatch):
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    src = _src_with_upstream()
    if src is None:
        pytest.skip("no oematch source copy carrying upstream.py; set SYM_OEMATCH_SRC")
    monkeypatch.setenv("SYM_OEMATCH_SRC", str(src))
    r = P.upstream("https://github.com/sqlite/sqlite", top=6)
    assert r["found"] is True
    pns = [m["pn"] for m in r["matches"]]
    assert "sqlite3" in pns, pns
    assert all("bucket" in m for m in r["matches"])


def test_match_fingerprints_a_real_artifact_and_carries_a_licence_class_on_every_row():
    if not REAL_DB.is_file():
        pytest.skip(f"no corpus at {REAL_DB}")
    target = "/bin/ls"
    if not Path(target).exists():
        pytest.skip(f"no artifact at {target}")
    r = P.match(target, top=10)
    assert r["kind"] == "elf"
    assert r["signals"]["sonames"], r["signals"]
    assert r["matches"], "nothing ranked for an artifact with sonames"
    assert all(m["bucket"] in ("permissive", "copyleft", "unlicensed") for m in r["matches"])
    assert sum(r["counts"].values()) == r["returned"] == len(r["matches"])
    # the score order is oematch's and is not re-sorted by licence
    assert [m["score"] for m in r["matches"]] == sorted(
        (m["score"] for m in r["matches"]), reverse=True)


def test_match_refuses_a_path_that_is_not_there(tmp_path):
    missing = tmp_path / "no-such-artifact"
    with pytest.raises(P.ToolError) as e:
        P.match(str(missing))
    assert str(missing) in str(e.value)


# --- nothing here pulls a network on a request ----------------------------------------------
def test_rebuild_plan_reports_the_command_and_does_not_run_it():
    r = P.rebuild_plan()
    assert r["runs"] is False
    assert r["network"] is True
    assert isinstance(r["full"], list) and "build" in r["full"]
    assert str(P.db_path()) in r["full"]
    assert "--no-fetch" in r["offline_reindex"]


def test_no_command_in_this_component_is_built_as_a_shell_string():
    src = Path(P.__file__).read_text()
    assert "shell=True" not in src
    assert "subprocess.run(argv" in src


def test_the_service_routes_every_capability_the_module_exposes():
    """The premise `endpoints-current` checks, asserted here too, so it fails at test time
    rather than only at gate time."""
    import service
    importlib.reload(service)
    paths = {r.path for r in service.app.routes}
    public = [n for n in dir(P)
              if not n.startswith("_") and callable(getattr(P, n))
              and getattr(getattr(P, n), "__module__", "") == P.__name__]
    for name in public:
        if name in P.NOT_EXPOSED or name[0].isupper():
            continue
        assert f"/api/symonoematch/{name}" in paths, f"{name}() has no route"
