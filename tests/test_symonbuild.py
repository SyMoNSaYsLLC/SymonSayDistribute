# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonbuild tests.

Most of these are about what this host actually holds, because the component's whole job is to
report that rather than to repeat what a document says about it. A test here that would pass on
a clean machine with one tidy build stack would not be testing this component at all.
"""
import ast
import importlib
import inspect
import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from symonbuild import cooker as C

TOKEN = uuid.uuid4().hex
_VERSION = re.compile(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", re.M)


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard. On a loopback
    # bind the guard returns before comparing anything, which would make every authenticated
    # test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_BUILD_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_BUILD_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- the divergence is real, and a test asserting one canonical copy would be false ---------

def test_bitbakes_reports_more_than_one_version_on_this_host():
    """Several copies at several versions IS the finding.

    A test asserting a single canonical executor would be a test that says the estate is tidy,
    which is not what is on disk. It would also have to fail before the mess was cleaned up and
    pass afterwards — the wrong way round for a report.
    """
    b = C.bitbakes()
    assert b["count"] > 1, "only one executor found; the spread this unit reports is not here"
    assert len(b["versions"]) > 1, \
        f"one version across {b['count']} copies: {b['versions']} — the divergence is not real"
    assert b["diverges"] is True
    assert str(len(b["versions"])) in b["version_spread"]


def test_every_reported_version_was_read_out_of_its_own_file():
    """The version is READ, not assumed — so re-reading each file independently must agree.

    This is the test that would catch a version inferred from a directory name, from a pin, or
    from the last thing somebody wrote down.
    """
    b = C.bitbakes()
    assert b["found"], "nothing to check"
    for row in b["found"]:
        if not row["version"]:
            continue
        with open(row["path"], encoding="utf-8", errors="replace") as fh:
            m = _VERSION.search(fh.read(8192))
        assert m, f"no version in {row['path']} but one was reported"
        assert row["version"] == m.group(1), \
            f"{row['path']}: reported {row['version']}, file says {m.group(1)}"


def test_a_copy_that_is_not_on_path_is_not_reported_as_on_path():
    b = C.bitbakes()
    for row in b["found"]:
        if row["on_path"]:
            assert b["on_path"], "a copy claims PATH while nothing resolved on PATH"
    assert all(row["device"] for row in b["found"]), "a copy was reported with no device"


def test_the_pin_is_what_resolves_the_spread_or_it_is_recorded_that_nothing_does():
    """Canonicity comes from the recorded pin, never from preference or recency."""
    b = C.bitbakes()
    if b["pin"]["revision"]:
        for row in b["found"]:
            assert row["matches_pin"] == (row["revision"] == b["pin"]["revision"])
        assert len(b["canonical"]) == len([r for r in b["found"] if r["matches_pin"]])
    assert b["canonical_note"]


# --- an absent tool is named -------------------------------------------------------------------

def test_every_tool_in_the_set_appears_in_the_report_found_or_not():
    """A report listing only what it found reads identically to one that found everything."""
    d = C.devtools()
    named = {t["tool"] for t in d["tools"]}
    assert named == set(C.OE_TOOLS), f"tools dropped from the report: {set(C.OE_TOOLS) - named}"
    for t in d["tools"]:
        assert t["found"] == (bool(t["paths"]) or bool(t["on_path"]))
    assert d["complete"] == (not d["missing"])


def test_a_tool_that_is_not_there_is_reported_absent(monkeypatch, tmp_path):
    """The negative control: point the search at an empty root and every tool must go missing.

    Without this, `complete: True` could mean "the check does not work".
    """
    monkeypatch.setenv("SYM_BUILD_ROOTS", str(tmp_path))
    monkeypatch.setattr(C.shutil, "which", lambda _n: None)
    d = C.devtools()
    assert d["complete"] is False
    assert set(d["missing"]) == set(C.OE_TOOLS)
    for name in C.OE_TOOLS:
        assert name in d["why"]


# --- a configuration whose layers are missing is the interesting case -------------------------

def _write_conf(root, layers_text):
    conf = root / "build" / "conf"
    conf.mkdir(parents=True)
    (conf / "local.conf").write_text('MACHINE ?= "qemux86-64"\n')
    (conf / "bblayers.conf").write_text(
        'LCONF_VERSION = "7"\nBBPATH = "${TOPDIR}"\nBBFILES ?= ""\n\n'
        f'BBLAYERS ?= " \\\n{layers_text}  "\n')
    return str(conf)


def test_configs_flags_a_declared_layer_whose_path_does_not_exist(monkeypatch, tmp_path):
    """Built against a fixture, never the real configurations — those are read-only to this."""
    missing = tmp_path / "nowhere" / "meta"
    present = tmp_path / "meta-real"
    (present / "conf").mkdir(parents=True)
    (present / "conf" / "layer.conf").write_text('BBFILE_COLLECTIONS += "meta-real"\n')
    conf = _write_conf(tmp_path, f"  {missing}  \\\n  {present}  \\\n")

    monkeypatch.setenv("SYM_BUILD_ROOTS", str(tmp_path))
    out = C.configs()
    rows = [c for c in out["configs"] if c["conf_dir"] == conf]
    assert len(rows) == 1, f"the fixture config was not found: {[c['conf_dir'] for c in out['configs']]}"
    row = rows[0]

    assert row["declared"] == 2
    assert row["missing"] == [str(missing)], row["layers"]
    assert row["all_layers_present"] is False
    assert {"conf_dir": conf, "missing": [str(missing)]} in out["broken"]
    assert conf not in out["usable"]
    assert str(present) not in row["missing"], "an existing layer was reported missing"


def test_a_config_whose_layers_all_exist_is_reported_usable(monkeypatch, tmp_path):
    """The other half: without this, `all_layers_present` could be hardwired false."""
    present = tmp_path / "meta-real"
    (present / "conf").mkdir(parents=True)
    (present / "conf" / "layer.conf").write_text('BBFILE_COLLECTIONS += "meta-real"\n')
    conf = _write_conf(tmp_path, f"  {present}  \\\n")

    monkeypatch.setenv("SYM_BUILD_ROOTS", str(tmp_path))
    out = C.configs()
    row = next(c for c in out["configs"] if c["conf_dir"] == conf)
    assert row["missing"] == []
    assert row["all_layers_present"] is True
    assert conf in out["usable"]


def test_an_unexpanded_entry_is_null_rather_than_missing(monkeypatch, tmp_path):
    """`${TOPDIR}/sources/meta-oe` was not measured, so it is not reported as measured.

    Calling it missing would put a read finding and an unread one under the same word, which is
    exactly how the one config that really is broken stops standing out.
    """
    conf = _write_conf(tmp_path, "  ${TOPDIR}/sources/meta-oe  \\\n")
    monkeypatch.setenv("SYM_BUILD_ROOTS", str(tmp_path))
    out = C.configs()
    row = next(c for c in out["configs"] if c["conf_dir"] == conf)
    assert row["layers"][0]["exists"] is None
    assert row["missing"] == []
    assert row["unresolved"] == ["${TOPDIR}/sources/meta-oe"]
    assert row["all_layers_present"] is False


# --- layers ---------------------------------------------------------------------------------------

def test_a_layer_is_acquired_only_when_a_pin_tracks_it(monkeypatch, tmp_path):
    lay = tmp_path / "meta-invented"
    (lay / "conf").mkdir(parents=True)
    (lay / "conf" / "layer.conf").write_text('BBFILE_COLLECTIONS += "meta-invented"\n')
    monkeypatch.setenv("SYM_BUILD_ROOTS", str(tmp_path))
    out = C.layers()
    row = next(r for r in out["layers"] if r["path"] == str(lay))
    assert row["name"] == "meta-invented"
    assert row["state"] == "PRESENT", "a layer with no pin was called acquired"
    assert row["pin"] is None
    assert out["acquired"] == 0


def test_layers_on_this_host_declare_their_names():
    out = C.layers()
    assert out["count"] > 0, "no layer found on a host whose estate is built on layers"
    assert out["acquired"] + out["present"] == out["count"]


# --- is a cooker live: R2 rests on this ------------------------------------------------------

def test_cooker_live_names_neither_forbidden_process_utility():
    """Rules section 3.3 forbids both outright: the pattern matches the agent's own shell and
    has ended sessions on this host. Asserted against the source, the way the image unit asserts
    `shell=True` never appears in its generate path."""
    src = inspect.getsource(C.cooker_live)
    assert "pgrep" not in src
    assert "pkill" not in src
    assert "/proc" in src, "the process table has to be read from somewhere"
    whole = inspect.getsource(C)
    assert "pgrep" not in whole and "pkill" not in whole, \
        "forbidden elsewhere in the module; cooker_live is clean but the module is not"


def test_the_match_is_on_the_executable_not_the_command_line():
    """The negative case is the one that matters: a process whose COMMAND LINE contains the
    executor's name, but which is not the executor. That is the shape that has killed sessions
    here, and a probe written while developing this module hit it immediately — its single
    result was the shell running the probe."""
    decoy = ["bash", "-c", "marker=bitbake-worker; sleep 25; echo $marker"]
    assert not set(C._program_names(decoy, "/usr/bin/bash")) & C.COOKER_PROGRAMS

    grep_shaped = ["python3", "-c", "print('bitbake bitbake-server')"]
    assert not set(C._program_names(grep_shaped, "/usr/bin/python3.13")) & C.COOKER_PROGRAMS

    # and the positive branch, without starting anything: both real invocation shapes.
    direct = ["/x/bitbake/bin/bitbake", "-c", "build", "core-image-minimal"]
    assert "bitbake" in C._program_names(direct, None)
    behind_interpreter = ["python3", "/x/bitbake/bin/bitbake-worker"]
    assert "bitbake-worker" in C._program_names(behind_interpreter, "/usr/bin/python3.13")


def test_cooker_live_never_reports_the_process_asking():
    k = C.cooker_live()
    pids = {p["pid"] for p in k["processes"]}
    assert os.getpid() not in pids
    assert os.getppid() not in pids
    assert os.getpid() in k["evidence"]["excluded_pids"]
    assert k["evidence"]["entries_examined"] > 1, "the process table was not actually read"
    assert k["safe_to_edit_recipes"] is (not k["live"])
    assert k["live"] == bool(k["processes"])


# --- could a build run --------------------------------------------------------------------------

def test_buildable_is_false_here_and_says_what_is_in_the_way():
    b = C.buildable()
    assert b["buildable"] is False, \
        f"a build is reported runnable on this host; preconditions: {b['preconditions']}"
    assert b["blocked_by"], "false with nothing named as blocking"
    names = {p["name"] for p in b["preconditions"]}
    assert set(b["blocked_by"]) <= names
    for p in b["preconditions"]:
        assert p["met"] == (p["name"] not in b["blocked_by"])
        assert p["evidence"], f"{p['name']} carries no evidence"


def test_a_false_precondition_always_carries_a_blocker(monkeypatch, tmp_path):
    """Negative control on the whole answer: an empty root must block on everything."""
    monkeypatch.setenv("SYM_BUILD_ROOTS", str(tmp_path))
    monkeypatch.setattr(C.shutil, "which", lambda _n: None)
    b = C.buildable()
    assert b["buildable"] is False
    assert set(b["blocked_by"]) == {p["name"] for p in b["preconditions"]}


def test_this_unit_never_starts_a_build():
    """Not a style point. R2's answer has to come from something that cannot be the cause of a
    cooker existing, so no capability here may invoke the executor or source its environment.

    The check is on the argument vectors, not on whether the names appear: this module has to
    LOOK for `oe-init-build-env` in order to report it, and a substring ban would forbid the
    reporting along with the running.
    """
    src = inspect.getsource(C)
    tree = ast.parse(src)

    allowed = {"df", "git"}
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            head = node.elts[0]
            if isinstance(head, ast.Constant) and isinstance(head.value, str):
                assert head.value in allowed, \
                    f"an argument vector this module could run starts with {head.value!r}"

    runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "run"]
    assert runs, "no subprocess call found — this test would then be checking nothing"
    for call in runs:
        kw = {k.arg for k in call.keywords}
        assert "timeout" in kw, "a subprocess with no timeout"
        assert "shell" not in kw, "a subprocess through a shell"

    for banned in ("subprocess.Popen", "os.system", "os.exec", "shell=True", "eval("):
        assert banned not in src, f"this module reaches for {banned!r}"


# --- over http --------------------------------------------------------------------------------------

def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    """Off-loopback the bind is reachable, so the token is required and an unset one closes the
    unit: becoming reachable through a config change must not make it public through that same
    change. The host is set before the reload so the guard is in its off-loopback mode."""
    monkeypatch.setenv("SYM_BUILD_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_BUILD_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonbuild/health").status_code == 200
    assert c.get("/api/symonbuild/cooker-live").status_code == 503
    assert c.get("/api/symonbuild/buildable").status_code == 503


def test_loopback_needs_no_token(monkeypatch):
    """The other half of the contract: on the loopback default no token is asked for, because a
    token on a 127.0.0.1 bind defends only against a caller who could already read the token."""
    monkeypatch.delenv("SYM_BUILD_HOST", raising=False)
    monkeypatch.delenv("SYM_BUILD_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonbuild/health").status_code == 200
    assert c.get("/api/symonbuild/cooker-live").status_code == 200, \
        "a loopback bind must not refuse a caller over a token it cannot justify asking for"


def test_off_loopback_a_wrong_token_is_refused(monkeypatch):
    monkeypatch.setenv("SYM_BUILD_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_BUILD_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonbuild/cooker-live",
                 headers={"Authorization": "Bearer " + uuid.uuid4().hex}).status_code == 401


def test_every_capability_has_a_route(client):
    """The gate checks this statically; this checks it by calling."""
    for path in ("bitbakes", "devtools", "configs", "layers", "cooker-live", "buildable"):
        r = client.get(f"/api/symonbuild/{path}", headers=auth())
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        assert "evidence" in r.json(), f"{path} answered without its evidence"


def test_the_buildable_route_carries_its_blockers(client):
    b = client.get("/api/symonbuild/buildable", headers=auth()).json()
    assert b["buildable"] is False
    assert b["blocked_by"]
    assert b["why"].startswith("blocked on:")
